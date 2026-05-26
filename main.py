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
alert_start_time = None  # Змінна для фіксації початку тривоги

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🟢 Бот активний\n📡 Статус: {current_status}\n⏰ Ост. перевірка: {last_check_time}")

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.send_message(chat_id=CHANNEL_ID, text="🔔 Перевірка зв'язку: Бот успішно підключений до каналу!")
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
                    # Динамічний пошук Києва
                    kyiv_data = next((x for x in data if "Київ" in x.get("name", "") and "область" not in x.get("name", "")), None)
                    
                    if kyiv_data:
                        active = kyiv_data.get("alert", False)
                        logger.info(f"DEBUG: Знайдено Київ! Дані: {kyiv_data}")
                        
                        current_status = "🚨 ТРИВОГА" if active else "🟢 ВІДБІЙ"
                        last_check_time = datetime.now(KYIV_TZ).strftime("%H:%M:%S")
                        
                        if last_state is not None and active != last_state:
                            if active:
                                # Тривога почалася
                                alert_start_time = datetime.now(KYIV_TZ)
                                msg = "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА"
                            else:
                                # Відбій, рахуємо тривалість
                                duration_str = "невідомо"
                                if alert_start_time:
                                    delta = datetime.now(KYIV_TZ) - alert_start_time
                                    minutes = int(delta.total_seconds() // 60)
                                    seconds = int(delta.total_seconds() % 60)
                                    duration_str = f"{minutes} хв {seconds} сек"
                                
                                msg = f"🟢 КИЇВ | ВІДБІЙ ТРИВОГИ\n⏳ Тривалість: {duration_str}"
                                alert_start_time = None # Скидаємо час після відбою
                            
                            await app.bot.send_message(CHANNEL_ID, msg)
                        
                        last_state = active
                    else:
                        logger.error("DEBUG: Не вдалося знайти Київ!")
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

    # Видаляємо вебхук, щоб працював polling
    await app.bot.delete_webhook(drop_pending_updates=True)

    # Запуск бота
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    
    # Запуск циклу перевірки
    asyncio.create_task(alert_loop(app))
    
    await asyncio.Future() 

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Критична помилка: {e}")
