import os
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes

# Leemos la variable ADMIN_IDS y la convertimos en una lista de números
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(i.strip()) for i in ADMIN_IDS_STR.split(",") if i.strip().isdigit()]

def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        
        # Verificamos si el ID del usuario está en la lista permitida
        if user.id not in ADMIN_IDS:
            mensaje = "⛔ *Acceso denegado.*\nNo estás en la lista de usuarios autorizados para usar este bot."
            
            if update.message:
                await update.message.reply_text(mensaje, parse_mode="Markdown")
            elif update.callback_query:
                await update.callback_query.answer("⛔ No tienes permiso para usar este bot.", show_alert=True)
            return
            
        return await func(update, context, *args, **kwargs)
    return wrapper
