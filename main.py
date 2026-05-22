import os
import asyncio
import logging
from datetime import datetime
import pytz
import httpx
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
KYIV_TZ = pytz.timezone("Europe/Kyiv")

# Глобальні змінні
last_state = None
alert_start_time = None
current_status = "CLEAR"
last_check_time = None

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🟢 Бот активний\n📡 Статус: {current_status}\n⏰ Ост. перевірка: {last_check_time}")

async def alert_loop(app):
    global last_state, alert_start_time, current_status, last_check_time
    while True:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get("https://alerts.com.ua/api/states", timeout=10)
                data = r.json().get("states", [])
                active = any(x.get("id") == 31 and x.get("alert", False) for x in data)
            
            last_check_time = datetime.now(KYIV_TZ).strftime("%H:%M:%S")
            
            if last_state is not None and active != last_state:
                if active:
                    alert_start_time = datetime.now(KYIV_TZ)
                    await app.bot.send_message(CHANNEL_ID, "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА")
                else:
                    await app.bot.send_message(CHANNEL_ID, "🟢 КИЇВ | ВІДБІЙ ТРИВОГИ")
            last_state = active
        except Exception as e:
            logger.error(f"Error: {e}")
        await asyncio.sleep(45)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).drop_pending_updates(True).build()
    app.add_handler(CommandHandler("status", status_cmd))

    # Запуск web-сервера для Render
    runner = web.AppRunner(web.Application())
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    await site.start()

    # Ініціалізація та запуск бота
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    asyncio.create_task(alert_loop(app))
    
    # Підтримка роботи сервісу
    try:
        await asyncio.Future() 
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
