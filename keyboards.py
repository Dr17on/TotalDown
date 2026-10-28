from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def main_panel() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📤 Cómo subir archivos", callback_data="info_upload")],
        [InlineKeyboardButton("❓ Ayuda", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def back_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver", callback_data="main")]])
