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

async def monitor_progress(chat_id: int, status_msg, custom_text=None):
    try:
        while True:
            state = UPLOAD_STATES.get(chat_id)
            if not state: break
            
            if custom_text:
                text = custom_text
            else:
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

def split_file(file_path, chunk_size_mb=100):
    chunk_size = chunk_size_mb * 1024 * 1024
    parts = []
    base_name = os.path.basename(file_path)
    with open(file_path, 'rb') as f_in:
        part_num = 1
        while True:
            chunk = f_in.read(chunk_size)
            if not chunk: break
            part_name = f"{base_name}.part{part_num:03d}"
            with open(part_name, 'wb') as f_out:
                f_out.write(chunk)
            parts.append(part_name)
            part_num += 1
    return parts

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
        "Envíame un archivo. Si supera los 100MB, lo dividiré para que toDus no falle.\n\n"
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
    
    search_paths = ["tmp_*", "*.temp", "temp_uploads/*", "*.part*"]
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
            "Envíame un archivo. Si es mayor a 100MB, lo dividiré y te daré los enlaces.",
            parse_mode="Markdown", reply_markup=back_button()
        )
    elif data == "help":
        await query.edit_message_text(
            "❓ *Ayuda*\n\n• `/start` - Inicio\n• `/limpiar` - Borrar archivos temporales",
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
    api_id = int(os.getenv("API_ID", "0"))
    api_hash = os.getenv("API_HASH", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    async with Client("totaldown_session", api_id=api_id, api_hash=api_hash, bot_token=bot_token) as app:
        try:
            downloaded_file_path = await app.download_media(
                message=file_id, 
                file_name=local_path,
                progress=download_progress,
                progress_args=(chat_id,)
            )
            if not downloaded_file_path:
                raise Exception("El archivo descargado está vacío o no se pudo escribir en el disco.")
            return downloaded_file_path
        except Exception as e:
            raise Exception(f"Fallo en Pyrogram: {str(e)}")

@admin_only
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = msg.document or msg.video or msg.audio or (msg.photo[-1] if msg.photo else None) or msg.voice
    if not file_obj: return

    file_size = file_obj.file_size or 0
    file_size_mb = round(file_size / (1024 * 1024), 2)
    
    # Verificación de espacio en disco ANTES de descargar
    try:
        total, used, free = shutil.disk_usage("/")
        free_mb = round(free / (1024 * 1024), 2)
        
        # Necesitamos espacio para el archivo original + un 10% extra (por si se divide)
        needed_space = file_size * 1.1 
        if free < needed_space:
            await msg.reply_text(
                f"❌ *Espacio insuficiente en el servidor*\n\n"
                f"El archivo pesa: `{file_size_mb} MB`\n"
                f"Espacio libre: `{free_mb} MB`\n\n"
                f"Usa el comando `/limpiar` para borrar archivos temporales viejos y vuelve a intentarlo.",
                parse_mode="Markdown"
            )
            return
    except Exception:
        pass # Si falla la lectura del disco, continuamos e intentamos descargar.

    UPLOAD_STATES[msg.chat_id] = {"current": 0, "total": file_size, "status": "downloading", "cancelled": False}
    status_msg = await msg.reply_text("⏳ *Iniciando descarga...*", parse_mode="Markdown", reply_markup=cancel_keyboard())
    monitor_task = asyncio.create_task(monitor_progress(msg.chat_id, status_msg))
    
    local_path = f"tmp_{file_obj.file_unique_id}"
    actual_path = None
    original_name = getattr(file_obj, 'file_name', f"{file_obj.file_unique_id}.mp4")
    safe_name = "".join(c for c in original_name if c.isalnum() or c in "._- ").strip()
    
    try:
        actual_path = await download_with_pyrogram(file_obj.file_id, local_path, msg.chat_id)
        
        if UPLOAD_STATES[msg.chat_id]["cancelled"]:
            raise Exception("Operación cancelada.")

        os.makedirs("temp_uploads", exist_ok=True)
        upload_path = os.path.join("temp_uploads", safe_name)
        if os.path.exists(upload_path): os.remove(upload_path)
        os.rename(actual_path, upload_path)
        actual_path = upload_path

        links_text = ""
        
        # Si el archivo pesa más de 100MB, se divide
        if file_size > 100 * 1024 * 1024:
            await status_msg.edit_text(f"✂️ *Archivo grande ({file_size_mb} MB). Dividiendo en partes de 100MB...*", parse_mode="Markdown")
            parts = split_file(upload_path, 100)
            os.remove(upload_path) # Borramos el original inmediatamente para liberar espacio
            
            links_text = f"✅ *¡Enlaces Generados!*\n\n📄 *Nombre:* `{safe_name}`\n🧩 *Partes:* {len(parts)}\n\n"
            links_text += "⚠️ *Para unir:* Descarga todas las partes y usa ZArchiver (Android) en la parte 1.\n\n"
            
            for i, part in enumerate(parts):
                if UPLOAD_STATES[msg.chat_id]["cancelled"]:
                    raise Exception("Operación cancelada durante la división.")
                
                part_size_mb = round(os.path.getsize(part) / (1024*1024), 1)
                custom_msg = f"☁️ Subiendo parte {i+1} de {len(parts)} ({part_size_mb} MB)..."
                
                monitor_task.cancel()
                monitor_task = asyncio.create_task(monitor_progress(msg.chat_id, status_msg, custom_text=custom_msg))
                
                UPLOAD_STATES[msg.chat_id]["current"] = 0
                UPLOAD_STATES[msg.chat_id]["total"] = os.path.getsize(part)
                UPLOAD_STATES[msg.chat_id]["status"] = "uploading"
                
                part_url = await asyncio.to_thread(upload_to_todus_sync, part, os.getenv("TODUS_PHONE"), msg.chat_id)
                links_text += f"🧩 *Parte {i+1}:* [Descargar]({part_url})\n`{part_url}`\n\n"
                os.remove(part)

            await status_msg.edit_text(links_text, parse_mode="Markdown", disable_web_page_preview=True)

        else:
            # Subida normal para archivos pequeños
            UPLOAD_STATES[msg.chat_id]["status"] = "uploading"
            UPLOAD_STATES[msg.chat_id]["current"] = 0
            
            s3_url = await asyncio.to_thread(upload_to_todus_sync, upload_path, os.getenv("TODUS_PHONE"), msg.chat_id)
            await status_msg.edit_text(
                f"✅ *¡Enlace Generado!*\n\n📄 *Nombre:* `{safe_name}`\n🔗 [Haz clic aquí para descargar]({s3_url})\n\n`{s3_url}`", 
                parse_mode="Markdown", disable_web_page_preview=True
            )
            os.remove(upload_path)
        
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
        for temp_file in glob.glob(f"temp_uploads/{safe_name}.part*"):
            try: os.remove(temp_file)
            except: pass
