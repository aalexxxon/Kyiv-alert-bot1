import os
import asyncio
import logging
from datetime import datetime
import pytz
import httpx
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Налаштування логів
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфігурація
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = -1003777875292 
KYIV_TZ = pytz.timezone("Europe/Kyiv")

# Глобальні змінні
last_state = None
current_status = "🟢 ВІДБІЙ"
last_check_time = None

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🟢 Бот активний\n📡 Статус: {current_status}\n⏰ Ост. перевірка: {last_check_time}")

async def alert_loop(app):
    global last_state, current_status, last_check_time
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    while True:
        try:
            async with httpx.AsyncClient() as client:
                url = "https://alerts.com.ua/api/states"
                r = await client.get(url, headers=headers, timeout=10)
                
                if r.status_code != 200:
                    logger.error(f"Помилка API (код {r.status_code})")
                    await asyncio.sleep(45)
                    continue
                
                data = r.json().get("states", [])
                
                # Пошук за ID 30 для міста Київ
                kyiv_data = next((x for x in data if x.get("id") == 30), None)
                
                if kyiv_data is None:
                    logger.warning("Місто Київ (ID 30) не знайдено.")
                    active = False
                else:
                    active = kyiv_data.get("alert", False)
                    logger.info(f"Статус Київ (ID 30): {'ТРИВОГА' if active else 'ВІДБІЙ'}")
            
            last_check_time = datetime.now(KYIV_TZ).strftime("%H:%M:%S")
            current_status = "🚨 ТРИВОГА" if active else "🟢 ВІДБІЙ"
            
            # Логіка сповіщень
            if last_state is not None and active != last_state:
                if active:
                    await app.bot.send_message(CHANNEL_ID, "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА")
                else:
                    await app.bot.send_message(CHANNEL_ID, "🟢 КИЇВ | ВІДБІЙ ТРИВОГИ")
            
            last_state = active
        except Exception as e:
            logger.error(f"Помилка в циклі: {e}")
        
        await asyncio.sleep(45)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", status_cmd))

    await app.bot.delete_webhook(drop_pending_updates=True)

    app_http = web.Application()
    app_http.router.add_get('/', lambda r: web.Response(text="I am alive!"))
    
    runner = web.AppRunner(app_http)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    await site.start()

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    asyncio.create_task(alert_loop(app))
    
    await asyncio.Future() 

if __name__ == "__main__":
    asyncio.run(main())
