import os
import asyncio
import glob
import shutil
import time
import zipfile
from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import RetryAfter
from keyboards import main_panel, back_button
from decorators import admin_only
from pyrogram import Client
from todus import ToDusClient2

try:
    from mega_downloader import download_mega_file
except ImportError:
    download_mega_file = None

UPLOAD_STATES = {}

def cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="cancel_upload")]])

class ProgressFileWrapper:
    def __init__(self, file_path, chat_id):
        self.file = open(file_path, "rb")
        self.chat_id = chat_id
        self.file.seek(0, 2)
        self.total_size = self.file.tell()
        self.file.seek(0)
    def read(self, size=-1):
        state = UPLOAD_STATES.get(self.chat_id)
        if state and state.get("cancelled", False): raise Exception("Subida cancelada.")
        chunk = self.file.read(size)
        if chunk and state: state["current"] += len(chunk)
        return chunk
    def __len__(self): return self.total_size
    def __getattr__(self, attr): return getattr(self.file, attr)
    def close(self): self.file.close()

def upload_to_todus_sync(file_path: str, phone: str, chat_id: int) -> str:
    max_reintentos = 3
    for intento in range(max_reintentos):
        try:
            client = ToDusClient2(phone)
            client.login_with_phone_only()
            wrapper = ProgressFileWrapper(file_path, chat_id)
            result = client.upload_file(wrapper)
            wrapper.close()
            
            url = ""
            if hasattr(result, 'file_url') and result.file_url:
                url = str(result.file_url)
            elif isinstance(result, dict) and result.get('file_url'):
                url = str(result['file_url'])
            elif isinstance(result, str) and result.startswith("http"):
                url = result
                
            if not url.startswith("http"):
                raise Exception(f"URL inválida: {url}")
            return url
        except Exception as e:
            print(f"[Intento {intento + 1}/{max_reintentos}] Fallo en toDus: {e}")
            if intento == max_reintentos - 1:
                raise Exception(f"Error al subir a toDus: {str(e)}")
            time.sleep(5)

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
                
                if state["status"] == "downloading":
                    text = f"⏳ Descargando...\n\n{bar} {pct}%\n📦 {round(curr/(1024*1024),1)} MB / {round(tot/(1024*1024),1)} MB"
                else:
                    text = f"☁️ Subiendo a toDus...\n\n{bar} {pct}%\n📦 {round(curr/(1024*1024),1)} MB / {round(tot/(1024*1024),1)} MB"
            try: 
                await status_msg.edit_text(text, reply_markup=cancel_keyboard())
            except RetryAfter: pass
            except Exception: pass
            await asyncio.sleep(3)
    except asyncio.CancelledError: pass

@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Bienvenido a *TotalDown*.\n\nEnvíame un archivo o un enlace de **MEGA** o **MediaFire**.", reply_markup=main_panel(), parse_mode="Markdown")

@admin_only
async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎛️ *Panel de control*", reply_markup=main_panel(), parse_mode="Markdown")

@admin_only
async def clean_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🧹 Iniciando limpieza...")
    freed_space, deleted_files = 0, 0
    for pattern in ["tmp_*", "*.temp", "temp_uploads/*", "downloads/*", "*.part*", "*.tdl", "*.txt", "temp_mega_*", "temp_mf_*", "*.zip"]:
        for file_path in glob.glob(pattern):
            try:
                if os.path.isfile(file_path):
                    freed_space += os.path.getsize(file_path)
                    os.remove(file_path)
                    deleted_files += 1
            except Exception: pass
    if os.path.exists("__pycache__"):
        try: shutil.rmtree("__pycache__")
        except Exception: pass
    try:
        await status_msg.edit_text(f"✅ *Limpieza completada*\n• Archivos eliminados: `{deleted_files}`\n• Espacio liberado: `{round(freed_space/(1024*1024),2)} MB`", parse_mode="Markdown")
    except: pass

@admin_only
async def panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    if data == "cancel_upload":
        if chat_id in UPLOAD_STATES: UPLOAD_STATES[chat_id]["cancelled"] = True
        try: await query.edit_message_text("🛑 *Cancelando...*", parse_mode="Markdown")
        except: pass
        return
    if data == "main":
        try: await query.edit_message_text("🎛️ *Panel de control*", parse_mode="Markdown", reply_markup=main_panel())
        except: pass
    elif data == "info_upload":
        try: await query.edit_message_text("📤 Envíame un archivo o un enlace de MEGA/MediaFire.", parse_mode="Markdown", reply_markup=back_button())
        except: pass
    elif data == "help":
        try: await query.edit_message_text("❓ *Ayuda*\n• `/start` - Inicio\n• `/limpiar` - Limpiar", parse_mode="Markdown", reply_markup=back_button())
        except: pass

@admin_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.text and msg.text.startswith("http"):
        if "mega.nz" not in msg.text and "mediafire.com" not in msg.text:
            await msg.reply_text("⚠️ Por ahora solo acepto enlaces de **MEGA** o **MediaFire**.")
            return
            
        context.user_data['pending_url'] = msg.text.strip()
        keyboard = [
            [InlineKeyboardButton("☁️ Subir a toDus", callback_data="url_target_todus")]
        ]
        await msg.reply_text("¿Dónde quieres subir este archivo?", reply_markup=InlineKeyboardMarkup(keyboard))
        return

async def handle_url_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    url = context.user_data.get('pending_url')
    
    if not url:
        await query.edit_message_text("❌ URL expirada. Envía el enlace de nuevo.")
        return
    
    target = "todus"
    await query.edit_message_text(f"⏳ Iniciando descarga para subir a {target.upper()}...")
    
    status_msg = await query.message.reply_text("⏳ Conectando con el servidor...")
    await process_url_download(url, query.message.chat_id, status_msg, target)
    context.user_data.pop('pending_url', None)

async def process_url_download(url: str, chat_id: int, status_msg, target: str):
    os.makedirs("temp_uploads", exist_ok=True)
    file_name_base = f"downloaded_{int(time.time())}"
    
    try:
        chunk_size = 100 * 1024 * 1024
        current_part_data = bytearray()
        part_num = 1

        if "mega.nz" in url:
            temp_full_file = os.path.join("temp_uploads", f"{file_name_base}.bin")
            await download_mega_to_disk(url, temp_full_file, status_msg)
            
            if not os.path.exists(temp_full_file) or os.path.getsize(temp_full_file) < 1024:
                raise Exception("El archivo descargado es demasiado pequeño. Verifica el enlace.")
                
            await status_msg.edit_text(f"✅ Descarga completa. Dividiendo, comprimiendo y subiendo...")
            
            with open(temp_full_file, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk: break
                    current_part_data.extend(chunk)

                    if len(current_part_data) >= chunk_size:
                        await procesar_parte(current_part_data, file_name_base, part_num, chat_id, status_msg)
                        current_part_data.clear()
                        part_num += 1
                        
            if os.path.exists(temp_full_file):
                os.remove(temp_full_file)

        else:
            await status_msg.edit_text("⏳ Conectando con MediaFire...")
            session = curl_requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            })
            
            res = await asyncio.to_thread(session.get, url, impersonate="chrome124")
            res.raise_for_status()
            
            soup = BeautifulSoup(res.text, 'html.parser')
            link = soup.find('a', {'class': 'input popsok'}) or soup.find('a', {'id': 'downloadButton'})
            if not link:
                raise Exception("No se encontró el enlace de descarga. Puede ser una carpeta o un enlace inválido.")
                
            direct_url = link['href']
            
            res_file = await asyncio.to_thread(session.get, direct_url, stream=True, impersonate="chrome124")
            res_file.raise_for_status()

            for chunk in res_file.iter_content(chunk_size=1024*1024):
                if not chunk: continue
                current_part_data.extend(chunk)

                if len(current_part_data) >= chunk_size:
                    await procesar_parte(current_part_data, file_name_base, part_num, chat_id, status_msg)
                    current_part_data.clear()
                    part_num += 1

        if len(current_part_data) > 0:
            await procesar_parte(current_part_data, file_name_base, part_num, chat_id, status_msg)
            current_part_data.clear()

        await status_msg.edit_text("✅ Proceso completado.")
            
    except Exception as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")
    finally:
        if chat_id in UPLOAD_STATES:
            del UPLOAD_STATES[chat_id]

async def procesar_parte(current_part_data, file_name_base, part_num, chat_id, status_msg):
    part_name = f"{file_name_base}.part{part_num:03d}"
    part_path = os.path.join("temp_uploads", part_name)
    
    # 1. Guardar la parte en el disco
    with open(part_path, "wb") as f_part:
        f_part.write(current_part_data)
        
    # 2. Comprimir la parte en un ZIP
    zip_path = f"{part_path}.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(part_path, arcname=part_name)
        
    zip_name = f"{part_name}.zip"
    zip_size = os.path.getsize(zip_path)
    
    # 3. Subir el ZIP a toDus
    UPLOAD_STATES[chat_id] = {"current": 0, "total": zip_size, "status": "uploading", "cancelled": False}
    upload_monitor = asyncio.create_task(monitor_progress(chat_id, status_msg))
    try:
        part_url = await asyncio.to_thread(upload_to_todus_sync, zip_path, os.getenv("TODUS_PHONE"), chat_id)
    finally:
        upload_monitor.cancel()
        
    # 4. Enviar el enlace al chat
    await status_msg.reply_text(
        f"🔗 *Parte {part_num}:*\n`{part_url}`\n📄 *Nombre:* `{zip_name}`", 
        parse_mode="Markdown"
    )
    
    # 5. Limpiar archivos temporales
    os.remove(part_path)
    os.remove(zip_path)

async def download_mega_to_disk(url: str, dest_path: str, status_msg):
    await status_msg.edit_text("⏳ Conectando con MEGA...")
    try:
        if not download_mega_file: raise Exception("mega-lite no instalado.")
        file_path = await asyncio.to_thread(download_mega_file, url, os.path.dirname(dest_path))
        if os.path.exists(file_path): os.rename(file_path, dest_path)
        else: raise Exception("mega-lite no pudo descargar el archivo.")
    except Exception as e:
        raise Exception(f"Error de MEGA: {str(e)}")

@admin_only
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    file_obj = msg.document or msg.video or msg.audio or (msg.photo[-1] if msg.photo else None) or msg.voice
    if not file_obj: return

    file_size = file_obj.file_size or 0
    os.makedirs("temp_uploads", exist_ok=True)

    try:
        total, used, free = shutil.disk_usage("/")
        if free < (150 * 1024 * 1024):
            await msg.reply_text(f"❌ *Espacio insuficiente.* Libre: `{round(free/(1024*1024),1)} MB`. Usa `/limpiar`.", parse_mode="Markdown")
            return
    except: pass

    status_msg = await msg.reply_text("⏳ *Iniciando descarga por partes...*", parse_mode="Markdown", reply_markup=cancel_keyboard())

    original_name = getattr(file_obj, 'file_name', f"{file_obj.file_unique_id}.mp4")
    safe_name = "".join(c for c in original_name if c.isalnum() or c in "._- ").strip()
    if len(safe_name) > 100: safe_name = safe_name[:95] + os.path.splitext(safe_name)[1]

    chunk_size = 100 * 1024 * 1024
    part_num = 1
    current_part_data = bytearray()
    total_downloaded = 0

    try:
        async with Client("totaldown_session", api_id=int(os.getenv("API_ID")), api_hash=os.getenv("API_HASH"), bot_token=os.getenv("TELEGRAM_BOT_TOKEN"), sleep_threshold=120) as app:
            
            msg_pyro = await app.get_messages(chat_id=msg.chat_id, message_ids=msg.message_id)
            
            if msg_pyro.document: file_size = msg_pyro.document.file_size
            elif msg_pyro.video: file_size = msg_pyro.video.file_size
            elif msg_pyro.audio: file_size = msg_pyro.audio.file_size
            elif msg_pyro.voice: file_size = msg_pyro.voice.file_size
            elif msg_pyro.photo: file_size = msg_pyro.photo.file_size
                
            UPLOAD_STATES[msg.chat_id] = {"current": 0, "total": file_size, "status": "downloading", "cancelled": False}
            monitor_task = asyncio.create_task(monitor_progress(msg.chat_id, status_msg))

            async for chunk in app.stream_media(msg_pyro):
                if not chunk: break
                if UPLOAD_STATES[msg.chat_id].get("cancelled", False): raise Exception("Descarga cancelada.")
                
                if total_downloaded + len(chunk) > file_size:
                    chunk = chunk[:file_size - total_downloaded]

                current_part_data.extend(chunk)
                UPLOAD_STATES[msg.chat_id]["current"] += len(chunk)
                total_downloaded += len(chunk)

                if len(current_part_data) >= chunk_size:
                    await procesar_parte(current_part_data, safe_name, part_num, msg.chat_id, status_msg)
                    current_part_data.clear()
                    part_num += 1

                if total_downloaded >= file_size:
                    break

            if len(current_part_data) > 0:
                await procesar_parte(current_part_data, safe_name, part_num, msg.chat_id, status_msg)
                current_part_data.clear()

        await status_msg.edit_text("✅ Proceso completado. Copia los enlaces y pégalos en la APK.")
        try: await status_msg.delete()
        except: pass

    except Exception as e:
        try: await status_msg.edit_text(f"❌ Error:\n`{str(e)}`", parse_mode="Markdown")
        except: pass
    finally:
        if msg.chat_id in UPLOAD_STATES: del UPLOAD_STATES[msg.chat_id]
        if 'monitor_task' in locals(): monitor_task.cancel()
        for temp_file in glob.glob(f"temp_uploads/{safe_name}.part*"):
            try: os.remove(temp_file)
            except: pass
