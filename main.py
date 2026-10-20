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
alert_start_time = None 

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🟢 <b>Бот активний</b>\n📡 Статус: {current_status}\n⏰ Ост. перевірка: {last_check_time}",
        parse_mode='HTML'
    )

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text="🔔 <b>Перевірка зв'язку:</b> Бот працює!", parse_mode='HTML')
        await update.message.reply_text("✅ Повідомлення успішно відправлено в канал!")
    except Exception as e:
        await update.message.reply_text(f"❌ Помилка: {e}")

async def alert_loop(app):
    global last_state, current_status, last_check_time, alert_start_time
    url = "https://alerts.com.ua/api/states"
    
    while True:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, timeout=10)
                
                if r.status_code == 200:
                    data = r.json().get("states", [])
                    kyiv_data = next((x for x in data if "Київ" in x.get("name", "") and "область" not in x.get("name", "")), None)
                    
                    if kyiv_data:
                        active = kyiv_data.get("alert", False)
                        current_status = "🚨 ТРИВОГА" if active else "🟢 ВІДБІЙ"
                        last_check_time = datetime.now(KYIV_TZ).strftime("%H:%M:%S")
                        
                        if last_state is not None and active != last_state:
                            if active:
                                alert_start_time = datetime.now(KYIV_TZ)
                                msg = "🚨 <b>КИЇВ | ПОВІТРЯНА ТРИВОГА!</b>"
                            else:
                                duration_str = "невідомо"
                                if alert_start_time:
                                    delta = datetime.now(KYIV_TZ) - alert_start_time
                                    total_seconds = int(delta.total_seconds())
                                    
                                    hours = total_seconds // 3600
                                    minutes = (total_seconds % 3600) // 60
                                    seconds = total_seconds % 60
                                    
                                    parts = []
                                    if hours > 0: parts.append(f"{hours} год.")
                                    if minutes > 0 or hours > 0: parts.append(f"{minutes} хв.")
                                    parts.append(f"{seconds} сек.")
                                    
                                    duration_str = " ".join(parts)
                                
                                msg = f"🟢 <b>КИЇВ | ВІДБІЙ ТРИВОГИ!</b>\n⏳ Тривалість: {duration_str}"
                                alert_start_time = None
                            
                            await app.bot.send_message(CHANNEL_ID, msg, parse_mode='HTML')
                        
                        last_state = active
                else:
                    logger.error(f"Помилка API: {r.status_code}")
                    
        except Exception as e:
            logger.error(f"Помилка в alert_loop: {e}")
        
        await asyncio.sleep(45)

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не встановлено!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("test", test_cmd))

    await app.bot.delete_webhook(drop_pending_updates=True)

    # Веб-сервер для Render
    app_http = web.Application()
    app_http.router.add_get('/', lambda r: web.Response(text="Bot is running!"))
    
    runner = web.AppRunner(app_http)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    asyncio.create_task(alert_loop(app))
    
    await asyncio.Future() 

if __name__ == "__main__":
    asyncio.run(main())
