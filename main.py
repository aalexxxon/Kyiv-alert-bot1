import os
import asyncio
import logging
from datetime import datetime

import pytz
import httpx

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
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
# Ваш фіксований URL
WEBHOOK_URL = "https://kyiv-alert-bot1.onrender.com"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID is missing")

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
    keyboard = [[
        InlineKeyboardButton("🔄 Refresh", callback_data="refresh"),
        InlineKeyboardButton("📡 Ping", callback_data="ping"),
    ]]
    text = (
        f"🟢 Bot Status: RUNNING\n"
        f"📍 Region: Kyiv (31)\n"
        f"📡 Alert: {current_status}\n"
        f"⏰ Last check: {last_check_time}"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_status, last_check_time
    query = update.callback_query
    await query.answer()

    if query.data == "refresh":
        await query.edit_message_text(
            f"🟢 Bot Status: RUNNING\n"
            f"📍 Region: Kyiv (31)\n"
            f"📡 Alert: {current_status}\n"
            f"⏰ Last check: {last_check_time}"
        )
    elif query.data == "ping":
        await query.edit_message_text("📡 Pong!")

# ===================== ALERT LOOP =====================
async def alert_loop(app: Application):
    global last_state, alert_start_time, current_status, last_check_time

    async with httpx.AsyncClient() as client:
        while True:
            try:
                last_check_time = now()
                r = await client.get(API_URL, timeout=10)
                data = r.json().get("states", [])
                active = any(x.get("id") == REGION_ID and x.get("alert", False) for x in data)
                current_status = "ALERT" if active else "CLEAR"

                if last_state is None:
                    last_state = active
                elif active != last_state:
                    if active:
                        alert_start_time = datetime.now(KYIV_TZ)
                        await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=f"🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n⏰ {now()}\n⏱️ Триває: 00:00:00",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📡 Статус", callback_data="refresh")]])
                        )
                    else:
                        duration_text = "⏱️ Тривалість невідома"
                        if alert_start_time:
                            delta = datetime.now(KYIV_TZ) - alert_start_time
                            h, m, s = delta.seconds // 3600, (delta.seconds % 3600) // 60, delta.seconds % 60
                            duration_text = f"⏱️ Тривала: {h:02}:{m:02}:{s:02}"
                        await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=f"🟢 КИЇВ | ВІДБІЙ ТРИВОГИ\n⏰ {now()}\n{duration_text}"
                        )
                last_state = active
            except Exception as e:
                logger.error(f"[ALERT LOOP ERROR] {e}")
            await asyncio.sleep(15)

# ===================== MAIN =====================
async def run_bot():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    await app.initialize()
    asyncio.create_task(alert_loop(app))

    # Повний URL для вебхука
    full_webhook_url = f"{WEBHOOK_URL}/{BOT_TOKEN}"

    # Видаляємо старий вебхук, щоб уникнути конфліктів 429/400
    await app.bot.delete_webhook()

    # Запускаємо сервер вебхуків
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        url_path=BOT_TOKEN,
        webhook_url=full_webhook_url,
        drop_pending_updates=True,
    )
    
    # Реєстрація вебхука в Telegram
    await app.bot.set_webhook(url=full_webhook_url)
    
    logger.info(f"Bot successfully started with webhook: {full_webhook_url}")
    await app.updater.idle()

if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except Exception as e:
        logger.error(f"CRITICAL ERROR: {e}")
