from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import os

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

def main_panel(user_id: int) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📤 Cómo subir archivos", callback_data="info_upload")],
        [InlineKeyboardButton("📊 Mis estadísticas", callback_data="my_stats")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="help")],
    ]
    if user_id == ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🔑 Gestionar Keys", callback_data="admin_keys")])
    return InlineKeyboardMarkup(keyboard)

def back_button(target="main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver", callback_data=target)]])

def keys_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Generar nueva key", callback_data="admin_gen_key")],
        [InlineKeyboardButton("📋 Ver todas las keys", callback_data="admin_list_keys")],
        [InlineKeyboardButton("⬅️ Volver", callback_data="main")],
    ])
