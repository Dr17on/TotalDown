import os
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from database import (
    create_key, validate_and_assign_key, list_keys,
    increment_uploads, get_user_stats, is_authorized
)
from decorators import require_auth, require_admin
from keyboards import main_panel, back_button, keys_panel

# Importamos toDus SDK (asegúrate de que el nombre de la clase sea el correcto)
from todus_sdk import ToDusClientWithQueue

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ---------- Comandos ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_authorized(user.id):
        await update.message.reply_text(
            f"👋 Hola {user.first_name}, bienvenido a *TotalDown*.\n\n"
            "🔒 Este bot requiere una key de acceso.\n"
            "Envíala así: `/key TD-XXXXXXXXXX`",
            parse_mode="Markdown"
        )
        return
    await update.message.reply_text(
        "👋 *TotalDown*\nEnvía un archivo o usa el panel:",
        reply_markup=main_panel(user.id),
        parse_mode="Markdown"
    )

@require_auth
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎛️ *Panel de control*",
        reply_markup=main_panel(update.effective_user.id),
        parse_mode="Markdown"
    )

async def key_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_authorized(user.id):
        await update.message.reply_text("✅ Ya estás autorizado.")
        return
    if not context.args:
        await update.message.reply_text("Uso: `/key TD-XXXXXXXXXX`", parse_mode="Markdown")
        return
    key = context.args[0].strip()
    if validate_and_assign_key(key, user.id, user.username or user.first_name):
        await update.message.reply_text(
            "✅ *¡Autorizado!* Ya puedes enviar archivos.",
            parse_mode="Markdown",
            reply_markup=main_panel(user.id)
        )
    else:
        await update.message.reply_text("❌ Key inválida, expirada o ya usada.")

# ---------- Callback del panel ----------

async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    data = query.data

    if data == "main":
        await query.edit_message_text(
            "🎛️ *Panel de control*", parse_mode="Markdown",
            reply_markup=main_panel(user.id)
        )
    elif data == "info_upload":
        await query.edit_message_text(
            "📤 *Cómo subir un archivo en TotalDown*\n\n"
            "Solo envíame uno de estos tipos y te devolveré el enlace S3:\n"
            "• 🎬 Video\n• 🖼️ Foto\n• 🎵 Audio\n• 📄 Documento (ZIP, PDF, etc)",
            parse_mode="Markdown", reply_markup=back_button()
        )
    elif data == "my_stats":
        stats = get_user_stats(user.id)
        if stats:
            count, since = stats
            await query.edit_message_text(
                f"📊 *Tus estadísticas*\n\n"
                f"• Archivos subidos: `{count}`\n"
                f"• Autorizado desde: `{since}`",
                parse_mode="Markdown", reply_markup=back_button()
            )
    elif data == "help":
        await query.edit_message_text(
            "❓ *Ayuda*\n\n"
            "• `/start` — Panel principal\n"
            "• `/panel` — Abrir panel\n"
            "• Envía archivos para obtener enlaces S3 de toDus",
            parse_mode="Markdown", reply_markup=back_button()
        )
    # --- Admin ---
    elif data == "admin_keys":
        if user.id != ADMIN_ID:
            await query.answer("⛔ Solo admin", show_alert=True); return
        await query.edit_message_text("🔑 *Gestión de Keys*", parse_mode="Markdown",
                                       reply_markup=keys_panel())
    elif data == "admin_gen_key":
        if user.id != ADMIN_ID: return
        new_key = create_key(user.id)
        await query.edit_message_text(
            f"✅ Key generada:\n\n`{new_key}`\n\nEnvíasela al usuario.",
            parse_mode="Markdown", reply_markup=keys_panel()
        )
    elif data == "admin_list_keys":
        if user.id != ADMIN_ID: return
        rows = list_keys()
        if not rows:
            text = "No hay keys creadas."
        else:
            lines = ["📋 *Keys:*\n"]
            for k, used_by, active in rows[:20]:
                status = "🟢 libre" if used_by is None and active else "🔴 usada" if used_by else "⚪ inactiva"
                lines.append(f"`{k}` — {status}")
            text = "\n".join(lines)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keys_panel())

# ---------- Upload de archivos ----------

def upload_to_todus_sync(local_path: str, phone: str, password: str) -> str:
    """Función síncrona que se ejecutará en un hilo aparte"""
    client = ToDusClientWithQueue(phone, password)
    client.login()
    result = client.upload_file(local_path)
    # Dependiendo de la versión del SDK, puede ser result.file_url o result['url']
    return getattr(result, 'file_url', str(result))

@require_auth
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = (
        msg.document or msg.video or msg.audio or
        (msg.photo[-1] if msg.photo else None) or msg.voice
    )
    if not file_obj:
        return
    
    # Telegram limita las descargas de bots a 20MB (a menos que uses un servidor local)
    if file_obj.file_size and file_obj.file_size > 20 * 1024 * 1024:
        await msg.reply_text("❌ El archivo supera los 20MB permitidos por Telegram para bots.")
        return

    status_msg = await msg.reply_text("⏳ Descargando de Telegram...")

    tg_file = await file_obj.get_file()
    local_path = f"tmp_{file_obj.file_unique_id}"
    await tg_file.download_to_drive(local_path)

    await status_msg.edit_text("☁️ Subiendo a los servidores de toDus...")

    try:
        # Ejecutamos la subida en un hilo aparte para no bloquear el bot
        s3_url = await asyncio.to_thread(
            upload_to_todus_sync, 
            local_path, 
            os.getenv("TODUS_PHONE"), 
            os.getenv("TODUS_PASSWORD")
        )
        
        increment_uploads(update.effective_user.id)
        await status_msg.edit_text(
            f"✅ *¡Enlace Generado!*\n\n"
            f"🔗 [Haz clic aquí para descargar]({s3_url})\n\n"
            f"`{s3_url}`", 
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ Error al subir a toDus:\n`{e}`", parse_mode="Markdown")
    finally:
        # Limpiar archivo temporal SIEMPRE
        if os.path.exists(local_path):
            os.remove(local_path)
