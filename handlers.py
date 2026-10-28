import os
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from keyboards import main_panel, back_button
from decorators import admin_only
from pyrogram import Client

# Importamos la librería de toDus
from todus import ToDusClient2

# ---------- Comandos ----------

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hola {user.first_name}, bienvenido a *TotalDown*.\n\n"
        "Envíame un archivo (video, foto, audio o documento) de cualquier tamaño y te devolveré el enlace S3 de toDus.",
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
            "✅ *¡Ya no hay límite de 20MB!* Puedes enviar archivos grandes.",
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

# ---------- Funciones de descarga y subida ----------

async def download_large_file(chat_id: int, message_id: int, local_path: str):
    """Descarga archivos mayores a 20MB usando Pyrogram"""
    api_id = int(os.getenv("API_ID", "0"))
    api_hash = os.getenv("API_HASH", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    # Iniciamos el cliente de Pyrogram temporalmente para descargar
    async with Client("totaldown_session", api_id=api_id, api_hash=api_hash, bot_token=bot_token) as app:
        await app.download_media(
            message=message_id, 
            file_name=local_path
        )

def upload_to_todus_sync(local_path: str, phone: str) -> str:
    """Función síncrona para subir el archivo a toDus usando solo el teléfono"""
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

    status_msg = await msg.reply_text("⏳ Analizando archivo...")
    local_path = f"tmp_{file_obj.file_unique_id}"
    
    try:
        # Verificamos el tamaño del archivo (límite estándar de Telegram bots: 20MB)
        if file_obj.file_size and file_obj.file_size > 20 * 1024 * 1024:
            await status_msg.edit_text("⏳ Archivo grande detectado. Descargando con Pyrogram...")
            
            # Descargamos usando Pyrogram
            await download_large_file(msg.chat_id, msg.message_id, local_path)
        else:
            await status_msg.edit_text("⏳ Descargando archivo...")
            
            # Descargamos usando python-telegram-bot (más rápido para archivos pequeños)
            tg_file = await file_obj.get_file()
            await tg_file.download_to_drive(local_path)

        await status_msg.edit_text("☁️ Subiendo a los servidores de toDus...")

        # Subimos a toDus en un hilo aparte para no bloquear el bot
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
        await status_msg.edit_text(f"❌ Error:\n`{e}`", parse_mode="Markdown")
    finally:
        # Limpiar el archivo temporal para no llenar el disco de Kerit Cloud (2GB)
        if os.path.exists(local_path):
            os.remove(local_path)
