import os
import asyncio
import logging
from datetime import datetime

import pytz
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ===================== LOGGING =====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================== CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

if not BOT_TOKEN or not CHANNEL_ID:
    raise RuntimeError("BOT_TOKEN or CHANNEL_ID is missing")

# ===================== SETTINGS =====================
KYIV_TZ = pytz.timezone("Europe/Kyiv")
API_URL = "https://alerts.com.ua/api/states"
REGION_ID = 31

# ===================== STATE =====================
last_state = None
alert_start_time = None
current_status = "CLEAR"
last_check_time = None

def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")

# ===================== HANDLERS =====================
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (f"🟢 Бот активний\n📡 Статус: {current_status}\n⏰ Останній чек: {last_check_time}")
    await update.message.reply_text(text)

# ===================== ALERT LOOP =====================
async def alert_loop(app):
    global last_state, alert_start_time, current_status, last_check_time
    async with httpx.AsyncClient() as client:
        while True:
            try:
                last_check_time = now()
                r = await client.get(API_URL, timeout=10)
                data = r.json().get("states", [])
                active = any(x.get("id") == REGION_ID and x.get("alert", False) for x in data)
                current_status = "ALERT" if active else "CLEAR"

                if last_state is not None and active != last_state:
                    if active:
                        alert_start_time = datetime.now(KYIV_TZ)
                        await app.bot.send_message(CHANNEL_ID, f"🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n⏰ {now()}")
                    else:
                        delta = datetime.now(KYIV_TZ) - alert_start_time if alert_start_time else None
                        dur = f"\n⏱️ Тривала: {delta.seconds//3600:02}:{(delta.seconds%3600)//60:02}:{delta.seconds%60:02}" if delta else ""
                        await app.bot.send_message(CHANNEL_ID, f"🟢 КИЇВ | ВІДБІЙ ТРИВОГИ\n⏰ {now()}{dur}")
                last_state = active
            except Exception as e:
                logger.error(f"Loop error: {e}")
            await asyncio.sleep(45)

# ===================== MAIN =====================
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", status_cmd))
    
    # Запуск
    loop = asyncio.get_event_loop()
    loop.create_task(alert_loop(app))
    
    logger.info("Бот запущено в режимі Polling")
    app.run_polling()
