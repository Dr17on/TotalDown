from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from database import is_authorized
import os

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

def require_auth(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not is_authorized(user.id):
            msg = (
                "🔒 *Acceso restringido a TotalDown*\n\n"
                "Envía tu key de acceso así:\n"
                "`/key TD-XXXXXXXXXX`\n\n"
                "Si no tienes una, pídesela al administrador."
            )
            if update.message:
                await update.message.reply_text(msg, parse_mode="Markdown")
            elif update.callback_query:
                await update.callback_query.answer("🔒 Necesitas autorización. Usa /key", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

def require_admin(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user.id != ADMIN_ID:
            if update.message:
                await update.message.reply_text("⛔ Solo el administrador puede usar esto.")
            elif update.callback_query:
                await update.callback_query.answer("⛔ Solo admin", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)
    return wrapper
