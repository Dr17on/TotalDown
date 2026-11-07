import os
import asyncio
import glob
import shutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from keyboards import main_panel, back_button
from decorators import admin_only
from pyrogram import Client
from todus import ToDusClient2

UPLOAD_STATES = {}

# ---------- Funciones de Soporte ----------

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar subida", callback_data="cancel_upload")]])

async def monitor_progress(chat_id: int, status_msg):
    try:
        while True:
            state = UPLOAD_STATES.get(chat_id)
            if not state: break
            
            curr, tot = state["current"], state["total"]
            pct = int((curr / tot) * 100) if tot > 0 else 0
            pct = min(100, pct)
            bar = "■" * (pct // 10) + "□" * (10 - (pct // 10))
            
            status_text = "⏳ Descargando de Telegram..." if state["status"] == "downloading" else "☁️ Subiendo a toDus..."
            
            text = f"{status_text}\n\n{bar} {pct}%\n📦 {round(curr/(1024*1024),1)} MB / {round(tot/(1024*1024),1)} MB"
            try: 
                await status_msg.edit_text(text, reply_markup=cancel_keyboard())
            except Exception: 
                pass
            await asyncio.sleep(3)
    except asyncio.CancelledError:
        pass

class ProgressFileWrapper:
    def __init__(self, file_path, chat_id):
        self.file = open(file_path, "rb")
        self.chat_id = chat_id
        self.file.seek(0, 2)
        self.total_size = self.file.tell()
        self.file.seek(0)
    def read(self, size=-1):
        state = UPLOAD_STATES.get(self.chat_id)
        if state and state.get("cancelled", False): 
            raise Exception("Subida cancelada.")
        chunk = self.file.read(size)
        if chunk and state: 
            state["current"] += len(chunk)
        return chunk
    def __len__(self): return self.total_size
    def __getattr__(self, attr): return getattr(self.file, attr)
    def close(self): self.file.close()

# ---------- Funciones de Subida ----------

def upload_to_todus_sync(file_path: str, phone: str, chat_id: int) -> str:
    try:
        client = ToDusClient2(phone)
        client.login_with_phone_only()
        wrapper = ProgressFileWrapper(file_path, chat_id)
        result = client.upload_file(wrapper)
        wrapper.close()
        return getattr(result, 'file_url', str(result))
    except Exception as e:
        raise Exception(f"Error de toDus: {str(e)}")

# ---------- Comandos ----------

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bienvenido a *TotalDown*.\n\n"
        "Envíame un archivo de cualquier tamaño y te devolveré el enlace S3 de toDus.\n\n"
        "Comandos:\n"
        "• `/limpiar` - Borrar archivos temporales",
        reply_markup=main_panel(), parse_mode="Markdown"
    )

@admin_only
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎛️ *Panel de control*", reply_markup=main_panel(), parse_mode="Markdown")

@admin_only
async def clean_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🧹 Iniciando limpieza...")
    freed_space, deleted_files, files_deleted_list = 0, 0, []
    
    search_paths = ["tmp_*", "*.temp", "temp_uploads/*"]
    for pattern in search_paths:
        for file_path in glob.glob(pattern):
            try:
                if os.path.isfile(file_path):
                    freed_space += os.path.getsize(file_path)
                    os.remove(file_path)
                    deleted_files += 1
                    files_deleted_list.append(os.path.basename(file_path))
            except Exception: pass

    if os.path.exists("__pycache__"):
        try: shutil.rmtree("__pycache__")
        except Exception: pass

    mb_freed = round(freed_space / (1024 * 1024), 2)
    
    text = f"✅ *Limpieza completada*\n\n• Archivos eliminados: `{deleted_files}`\n• Espacio liberado: `{mb_freed} MB`\n\n"
    if deleted_files > 0 and deleted_files <= 10:
        for f in files_deleted_list: text += f"🗑️ `{f}`\n"
    await status_msg.edit_text(text, parse_mode="Markdown")

@admin_only
async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id

    if data == "cancel_upload":
        if chat_id in UPLOAD_STATES:
            UPLOAD_STATES[chat_id]["cancelled"] = True
        await query.edit_message_text("🛑 *Cancelando...*", parse_mode="Markdown")
        return

    if data == "main":
        await query.edit_message_text("🎛️ *Panel de control*", parse_mode="Markdown", reply_markup=main_panel())
    elif data == "info_upload":
        await query.edit_message_text(
            "📤 *Cómo subir un archivo*\n\n"
            "Solo envíame un archivo de cualquier tipo (video, audio, doc) y lo subiré a toDus.",
            parse_mode="Markdown", reply_markup=back_button()
        )
    elif data == "help":
        await query.edit_message_text(
            "❓ *Ayuda*\n\n"
            "• `/start` - Inicio\n"
            "• `/limpiar` - Borrar archivos temporales",
            parse_mode="Markdown", reply_markup=back_button()
        )

# ---------- Manejo de Archivos ----------

async def download_progress(current, total, chat_id):
    state = UPLOAD_STATES.get(chat_id)
    if state:
        if state.get("cancelled", False): raise Exception("Descarga cancelada.")
        state["current"] = current
        state["total"] = total

async def download_with_pyrogram(file_id: str, local_path: str, chat_id: int) -> str:
    """Descarga usando el file_id para evitar errores con get_messages"""
    api_id = int(os.getenv("API_ID", "0"))
    api_hash = os.getenv("API_HASH", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    async with Client("totaldown_session", api_id=api_id, api_hash=api_hash, bot_token=bot_token) as app:
        # Pasamos el file_id directamente
        downloaded_file_path = await app.download_media(
            message=file_id, 
            file_name=local_path,
            progress=download_progress,
            progress_args=(chat_id,)
        )
        if not downloaded_file_path:
            raise Exception("Pyrogram no pudo descargar el archivo.")
        return downloaded_file_path

@admin_only
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = msg.document or msg.video or msg.audio or (msg.photo[-1] if msg.photo else None) or msg.voice
    if not file_obj: return

    file_size = file_obj.file_size or 0
    UPLOAD_STATES[msg.chat_id] = {"current": 0, "total": file_size, "status": "downloading", "cancelled": False}
    
    status_msg = await msg.reply_text("⏳ *Iniciando descarga...*", parse_mode="Markdown", reply_markup=cancel_keyboard())
    monitor_task = asyncio.create_task(monitor_progress(msg.chat_id, status_msg))
    
    local_path = f"tmp_{file_obj.file_unique_id}"
    actual_path = None
    
    try:
        # Descargamos usando Pyrogram pasando el file_id
        actual_path = await download_with_pyrogram(file_obj.file_id, local_path, msg.chat_id)
        
        if UPLOAD_STATES[msg.chat_id]["cancelled"]:
            raise Exception("Operación cancelada.")

        # Lógica del nombre original (manteniendo la extensión)
        orig_name = getattr(file_obj, 'file_name', None)
        if orig_name:
            safe_name = "".join(c for c in orig_name if c.isalnum() or c in "._- ").strip()
        else:
            if msg.photo: safe_name = f"{file_obj.file_unique_id}.jpg"
            elif msg.video: safe_name = f"{file_obj.file_unique_id}.mp4"
            elif msg.audio: safe_name = f"{file_obj.file_unique_id}.mp3"
            else: safe_name = f"{file_obj.file_unique_id}.bin"

        os.makedirs("temp_uploads", exist_ok=True)
        upload_path = os.path.join("temp_uploads", safe_name)
        if os.path.exists(upload_path): os.remove(upload_path)
        os.rename(actual_path, upload_path)
        actual_path = upload_path

        # Cambiamos el estado a subiendo
        UPLOAD_STATES[msg.chat_id]["status"] = "uploading"
        UPLOAD_STATES[msg.chat_id]["current"] = 0
        
        # Subimos a toDus
        s3_url = await asyncio.to_thread(
            upload_to_todus_sync, 
            upload_path, 
            os.getenv("TODUS_PHONE"),
            msg.chat_id
        )
        
        await status_msg.edit_text(
            f"✅ *¡Enlace Generado!*\n\n"
            f"📄 *Nombre:* `{safe_name}`\n"
            f"🔗 [Haz clic aquí para descargar]({s3_url})\n\n"
            f"`{s3_url}`", 
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        
    except Exception as e:
        error_msg = str(e)
        if "cancelada" in error_msg.lower() or "cancelado" in error_msg.lower():
            await status_msg.edit_text("🛑 *Operación cancelada por el usuario.*", parse_mode="Markdown")
        else:
            await status_msg.edit_text(f"❌ Error:\n`{error_msg}`", parse_mode="Markdown")
            
    finally:
        if msg.chat_id in UPLOAD_STATES: del UPLOAD_STATES[msg.chat_id]
        monitor_task.cancel()
        
        if actual_path and os.path.exists(actual_path): os.remove(actual_path)
        if local_path and os.path.exists(local_path): os.remove(local_path)
