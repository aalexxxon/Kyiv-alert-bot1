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
last_check_time = "Ще не було"

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🟢 Бот активний\n📡 Статус: {current_status}\n⏰ Ост. перевірка: {last_check_time}")

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(CHANNEL_ID, "🔔 Перевірка зв'язку: Бот успішно підключений до каналу!")
        await update.message.reply_text("✅ Повідомлення успішно відправлено в канал!")
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: не вдалося відправити повідомлення. {e}")

async def alert_loop(app):
    global last_state, current_status, last_check_time
    
    while True:
        try:
            async with httpx.AsyncClient() as client:
                url = "https://ubilling.net.ua/aerialalerts/json"
                r = await client.get(url, timeout=10)
                
                if r.status_code == 200:
                    data = r.json()
                    # ID 2 відповідає за Київ
                    kyiv_data = data.get("2", {})
                    active = kyiv_data.get("alarm", 0) == 1
                    
                    logger.info(f"Статус Київ (Ubilling): {'ТРИВОГА' if active else 'ВІДБІЙ'}")
                else:
                    logger.error(f"Помилка API Ubilling: {r.status_code}")
                    active = last_state if last_state is not None else False
            
            last_check_time = datetime.now(KYIV_TZ).strftime("%H:%M:%S")
            current_status = "🚨 ТРИВОГА" if active else "🟢 ВІДБІЙ"
            
            # Відправка в канал тільки при зміні статусу (після першого запуску)
            if last_state is not None and active != last_state:
                message = "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА" if active else "🟢 КИЇВ | ВІДБІЙ ТРИВОГИ"
                await app.bot.send_message(CHANNEL_ID, message)
            
            last_state = active
        except Exception as e:
            logger.error(f"Помилка в alert_loop: {e}")
        
        await asyncio.sleep(45)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("test", test_cmd))

    # Очистка черги повідомлень
    await app.bot.delete_webhook(drop_pending_updates=True)

    # Веб-сервер для Render
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
