import os
from dotenv import load_dotenv

# ⚠️ ESTO ES VITAL: Cargar las variables ANTES de importar los handlers y decoradores
load_dotenv() 

from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from handlers import (
    start, panel, panel_callback, handle_file
)

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ ERROR: Falta TELEGRAM_BOT_TOKEN en las variables de entorno.")
        return

    app = Application.builder().token(token).build()

    # Comandos protegidos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    
    # Botones protegidos
    app.add_handler(CallbackQueryHandler(panel_callback))
    
    # Archivos protegidos
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO |
        filters.PHOTO | filters.VOICE,
        handle_file
    ))

    print("🤖 TotalDown Bot iniciado correctamente (Modo Lista Blanca)...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
