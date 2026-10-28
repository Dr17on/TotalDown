import os
from dotenv import load_dotenv

# ⬇️ ESTO ES LO QUE FALTABA: Cargar las variables ANTES de importar los handlers
load_dotenv() 

from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters
)
from database import init_db
from handlers import (
    start, panel, key_command, panel_callback, handle_file
)

def main():
    # Iniciar base de datos
    init_db()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ ERROR: Falta TELEGRAM_BOT_TOKEN en las variables de entorno.")
        return

    app = Application.builder().token(token).build()

    # Comandos
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel))
    app.add_handler(CommandHandler("key", key_command))
    
    # Botones
    app.add_handler(CallbackQueryHandler(panel_callback))
    
    # Archivos (Documentos, Video, Audio, Fotos, Notas de voz)
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.AUDIO |
        filters.PHOTO | filters.VOICE,
        handle_file
    ))

    print("🤖 TotalDown Bot iniciado correctamente...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
