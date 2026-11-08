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
        "Envíame un archivo. Si supera los 100MB, lo dividiré automáticamente mientras lo descargo para no llenar el disco.",
        reply_markup=main_panel(), parse_mode="Markdown"
    )

@admin_only
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎛️ *Panel de control*", reply_markup=main_panel(), parse_mode="Markdown")

@admin_only
async def clean_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🧹 Iniciando limpieza...")
    freed_space, deleted_files, files_deleted_list = 0, 0, []
    
    search_paths = ["tmp_*", "*.temp", "temp_uploads/*", "downloads/*", "*.part*"]
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
        if chat_id in UPLOAD_STATES: UPLOAD_STATES[chat_id]["cancelled"] = True
        await query.edit_message_text("🛑 *Cancelando...*", parse_mode="Markdown")
        return

    if data == "main":
        await query.edit_message_text("🎛️ *Panel de control*", parse_mode="Markdown", reply_markup=main_panel())
    elif data == "help":
        await query.edit_message_text("❓ *Ayuda*\n\n• `/start` - Inicio\n• `/limpiar` - Borrar archivos temporales", parse_mode="Markdown", reply_markup=back_button())

# ---------- EL CORAZÓN DEL STREAMING (Descarga y subida por partes) ----------

async def process_large_file_streaming(file_id: str, file_size: int, chat_id: int, status_msg, safe_name: str):
    """Descarga en pedazos de 100MB usando stream_media y los sube a toDus sin llenar el disco"""
    api_id = int(os.getenv("API_ID", "0"))
    api_hash = os.getenv("API_HASH", "")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

    chunk_size = 100 * 1024 * 1024 # 100 MB
    part_num = 1
    current_chunk_size = 0
    total_downloaded = 0
    links_text = f"✅ *¡Enlaces Generados!*\n\n📄 *Nombre:* `{safe_name}`\n\n"
    
    os.makedirs("temp_uploads", exist_ok=True)
    part_file_path = os.path.join("temp_uploads", f"{safe_name}.part{part_num:03d}")
    f_out = open(part_file_path, "wb")

    async with Client("totaldown_session", api_id=api_id, api_hash=api_hash, bot_token=bot_token) as app:
        try:
            # Usamos stream_media para obtener el archivo en fragmentos pequeños (streaming)
            async for chunk in app.stream_media(file_id):
                if UPLOAD_STATES.get(chat_id, {}).get("cancelled", False):
                    raise Exception("Operación cancelada.")

                f_out.write(chunk)
                current_chunk_size += len(chunk)
                total_downloaded += len(chunk)

                # Actualizamos el progreso de descarga
                pct = int((total_downloaded / file_size) * 100)
                bar = "■" * (pct // 10) + "□" * (10 - (pct // 10))
                custom_txt = f"⏳ Descargando y dividiendo...\n\n{bar} {pct}%\n📦 {round(total_downloaded/(1024*1024),1)} MB / {round(file_size/(1024*1024),1)} MB"
                try: await status_msg.edit_text(custom_txt, reply_markup=cancel_keyboard())
                except: pass

                # Si el pedazo actual llegó a los 100MB, lo subimos
                if current_chunk_size >= chunk_size:
                    f_out.close()
                    
                    # Cambiamos el estado a subiendo
                    custom_txt = f"☁️ Subiendo parte {part_num} a toDus..."
                    try: await status_msg.edit_text(custom_txt)
                    except: pass

                    part_url = await asyncio.to_thread(upload_to_todus_sync, part_file_path, os.getenv("TODUS_PHONE"), chat_id)
                    links_text += f"🧩 *Parte {part_num}:* [Descargar]({part_url})\n`{part_url}`\n\n"
                    
                    # Borramos la parte subida para liberar espacio INMEDIATAMENTE
                    os.remove(part_file_path)
                    
                    # Preparamos el siguiente pedazo
                    part_num += 1
                    current_chunk_size = 0
                    part_file_path = os.path.join("temp_uploads", f"{safe_name}.part{part_num:03d}")
                    f_out = open(part_file_path, "wb")

            # Al terminar la descarga, subimos el último pedazo si quedó algo
            f_out.close()
            if current_chunk_size > 0:
                custom_txt = f"☁️ Subiendo última parte ({round(current_chunk_size/(1024*1024),1)} MB)..."
                try: await status_msg.edit_text(custom_txt)
                except: pass

                part_url = await asyncio.to_thread(upload_to_todus_sync, part_file_path, os.getenv("TODUS_PHONE"), chat_id)
                links_text += f"🧩 *Parte {part_num}:* [Descargar]({part_url})\n`{part_url}`\n\n"
                os.remove(part_file_path)

            links_text += "⚠️ *Para unir:* Descarga todas las partes y usa ZArchiver en la parte 1."
            await status_msg.edit_text(links_text, parse_mode="Markdown", disable_web_page_preview=True)

        except Exception as e:
            if f_out and not f_out.closed: f_out.close()
            if os.path.exists(part_file_path): os.remove(part_file_path)
            raise e

# ---------- Manejo de Archivos ----------

@admin_only
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = msg.document or msg.video or msg.audio or (msg.photo[-1] if msg.photo else None) or msg.voice
    if not file_obj: return

    file_size = file_obj.file_size or 0
    file_size_mb = round(file_size / (1024 * 1024), 2)
    
    os.makedirs("downloads", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)

    # DIAGNÓSTICO DE DISCO (Solo necesitamos 150MB libres, no todo el tamaño del video)
    try:
        total, used, free = shutil.disk_usage("/")
        free_mb = round(free / (1024 * 1024), 2)
        print(f"💾 [DIAGNÓSTICO] Espacio libre: {free_mb} MB. Archivo: {file_size_mb} MB")
        
        if free < 150 * 1024 * 1024:
            await msg.reply_text(
                f"❌ *Espacio crítico en el hosting*\n\n"
                f"Espacio libre: `{free_mb} MB`\n\n"
                f"Usa `/limpiar` para liberar espacio. Necesitas al menos 150MB libres.",
                parse_mode="Markdown"
            )
            return
    except Exception as e:
        print(f"Error chequeando disco: {e}")

    UPLOAD_STATES[msg.chat_id] = {"current": 0, "total": file_size, "status": "downloading", "cancelled": False}
    status_msg = await msg.reply_text("⏳ *Iniciando proceso...*", parse_mode="Markdown", reply_markup=cancel_keyboard())
    
    original_name = getattr(file_obj, 'file_name', f"{file_obj.file_unique_id}.mp4")
    safe_name = "".join(c for c in original_name if c.isalnum() or c in "._- ").strip()
    
    actual_path = None
    
    try:
        if file_size > 100 * 1024 * 1024:
            # Usamos la nueva función de streaming (no llena el disco)
            await process_large_file_streaming(file_obj.file_id, file_size, msg.chat_id, status_msg, safe_name)
        else:
            # Para archivos pequeños (menos de 100MB), descarga normal
            async with Client("totaldown_session", api_id=int(os.getenv("API_ID")), api_hash=os.getenv("API_HASH"), bot_token=os.getenv("TELEGRAM_BOT_TOKEN")) as app:
                local_path = os.path.join("downloads", f"tmp_{file_obj.file_unique_id}")
                actual_path = await app.download_media(message=file_obj.file_id, file_name=local_path)
            
            if UPLOAD_STATES[msg.chat_id]["cancelled"]:
                raise Exception("Operación cancelada.")

            upload_path = os.path.join("temp_uploads", safe_name)
            if os.path.exists(upload_path): os.remove(upload_path)
            os.rename(actual_path, upload_path)
            actual_path = upload_path

            UPLOAD_STATES[msg.chat_id]["status"] = "uploading"
            UPLOAD_STATES[msg.chat_id]["current"] = 0
            UPLOAD_STATES[msg.chat_id]["total"] = file_size
            
            s3_url = await asyncio.to_thread(upload_to_todus_sync, upload_path, os.getenv("TODUS_PHONE"), msg.chat_id)
            
            await status_msg.edit_text(
                f"✅ *¡Enlace Generado!*\n\n📄 *Nombre:* `{safe_name}`\n🔗 [Haz clic aquí para descargar]({s3_url})\n\n`{s3_url}`", 
                parse_mode="Markdown", disable_web_page_preview=True
            )
            os.remove(upload_path)
        
    except Exception as e:
        error_msg = str(e)
        if "cancelada" in error_msg.lower() or "cancelado" in error_msg.lower():
            await status_msg.edit_text("🛑 *Operación cancelada.*", parse_mode="Markdown")
        else:
            await status_msg.edit_text(f"❌ Error:\n`{error_msg}`", parse_mode="Markdown")
            
    finally:
        if msg.chat_id in UPLOAD_STATES: del UPLOAD_STATES[msg.chat_id]
        if actual_path and os.path.exists(actual_path): os.remove(actual_path)
        # Limpieza de partes huérfanas
        for temp_file in glob.glob(f"temp_uploads/{safe_name}.part*"):
            try: os.remove(temp_file)
            except: pass
