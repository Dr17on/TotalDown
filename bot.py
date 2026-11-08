import os
from dotenv import load_dotenv

load_dotenv() 

from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from handlers import (
    start, panel, panel_callback, handle_file, clean_memory
)

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ ERROR: Falta TELEGRAM_BOT_TOKEN en las variables de entorno.")
        return

    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    # REGISTRO DEL COMANDO LIMPIAR
    app.add_handler(CommandHandler("limpiar", clean_memory))
    
    # Botones
    app.add_handler(CallbackQueryHandler(panel_callback))
    
    # Archivos
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO |
        filters.PHOTO | filters.VOICE,
        handle_file
    ))

    print("🤖 TotalDown Bot iniciado correctamente...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
