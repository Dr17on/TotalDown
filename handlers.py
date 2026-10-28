import os
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from keyboards import main_panel, back_button
from decorators import admin_only

# Importamos la librería de toDus
from todus import ToDusClient2

# ---------- Comandos ----------

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hola {user.first_name}, bienvenido a *TotalDown*.\n\n"
        "Envíame un archivo (video, foto, audio o documento) y te devolveré el enlace S3 de toDus.",
        reply_markup=main_panel(),
        parse_mode="Markdown"
    )

@admin_only
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎛️ *Panel de control*",
        reply_markup=main_panel(),
        parse_mode="Markdown"
    )

# ---------- Callback del panel ----------

@admin_only
async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main":
        await query.edit_message_text(
            "🎛️ *Panel de control*", parse_mode="Markdown",
            reply_markup=main_panel()
        )
    elif data == "info_upload":
        await query.edit_message_text(
            "📤 *Cómo subir un archivo en TotalDown*\n\n"
            "Solo envíame uno de estos tipos y te devolveré el enlace S3:\n"
            "• 🎬 Video\n• 🖼️ Foto\n• 🎵 Audio\n• 📄 Documento (ZIP, PDF, etc)\n\n"
            "⚠️ *Límite:* Telegram permite hasta 20MB para bots.",
            parse_mode="Markdown", reply_markup=back_button()
        )
    elif data == "help":
        await query.edit_message_text(
            "❓ *Ayuda*\n\n"
            "• `/start` - Panel principal\n"
            "• `/panel` - Abrir panel\n"
            "• Envía archivos para obtener enlaces S3 de toDus",
            parse_mode="Markdown", reply_markup=back_button()
        )

# ---------- Upload de archivos ----------

def upload_to_todus_sync(local_path: str, phone: str) -> str:
    """Función síncrona para conectar con toDus usando solo el teléfono"""
    try:
        client = ToDusClient2(phone)
        client.login_with_phone_only()
        
        with open(local_path, "rb") as f:
            file_data = f.read()
            
        result = client.upload_file(file_data)
        
        return getattr(result, 'file_url', str(result))
    except Exception as e:
        raise Exception(f"Error de toDus: {str(e)}")

@admin_only
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = (
        msg.document or msg.video or msg.audio or
        (msg.photo[-1] if msg.photo else None) or msg.voice
    )
    if not file_obj:
        return
    
    # Verificamos el límite de Telegram (20MB para bots)
    if file_obj.file_size and file_obj.file_size > 20 * 1024 * 1024:
        await msg.reply_text("❌ El archivo supera los 20MB permitidos por Telegram para bots.")
        return

    status_msg = await msg.reply_text("⏳ Descargando de Telegram...")

    tg_file = await file_obj.get_file()
    local_path = f"tmp_{file_obj.file_unique_id}"
    
    try:
        await tg_file.download_to_drive(local_path)
        await status_msg.edit_text("☁️ Subiendo a los servidores de toDus...")

        s3_url = await asyncio.to_thread(
            upload_to_todus_sync, 
            local_path, 
            os.getenv("TODUS_PHONE")
        )
        
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
