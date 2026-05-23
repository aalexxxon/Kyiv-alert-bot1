import os
import asyncio
import logging
from datetime import datetime
import pytz
import httpx
from aiohttp import web
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    while True:
        try:
            async with httpx.AsyncClient() as client:
                # Використовуємо надійне API без токенів
                url = "https://api.alerts.in.ua/v1/alerts.json"
                r = await client.get(url, timeout=10)
                data = r.json().get("alerts", {})
                
                # У цьому API дані для Києва часто знаходяться за ключем "Kyiv"
                kyiv_data = data.get("Kyiv", {})
                
                logger.info(f"Діагностика API (alerts.in.ua): {kyiv_data}")
                
                # Перевіряємо, чи є тривога (структура може залежати від API)
                # Зазвичай це поле 'active' або подібне
                active = kyiv_data.get("active", False) if kyiv_data else False
            
            last_check_time = datetime.now(KYIV_TZ).strftime("%H:%M:%S")
            current_status = "🚨 ТРИВОГА" if active else "🟢 ВІДБІЙ"
            
            if last_state is not None and active != last_state:
                if active:
                    await app.bot.send_message(CHANNEL_ID, "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА")
                else:
                    await app.bot.send_message(CHANNEL_ID, "🟢 КИЇВ | ВІДБІЙ ТРИВОГИ")
            elif last_state is None and active:
                await app.bot.send_message(CHANNEL_ID, "🚨 КИЇВ | БОТ ЗАПУЩЕНИЙ, У МІСТІ ТРИВОГА!")
            
            last_state = active
        except Exception as e:
            logger.error(f"Помилка в циклі: {e}")
        await asyncio.sleep(45)

async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", status_cmd))

    await app.bot.delete_webhook(drop_pending_updates=True)

    async def ping_handler(request):
        return web.Response(text="I am alive!")

    app_http = web.Application()
    app_http.router.add_get('/', ping_handler)
    
    runner = web.AppRunner(app_http)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get("PORT", 10000)))
    await site.start()

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    asyncio.create_task(alert_loop(app))
    
    try:
        await asyncio.Future() 
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
