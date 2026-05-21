import asyncio
import requests
from datetime import datetime
import os
import pytz
import threading
import logging

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContexTypes

# ===================== LOGGING =====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================== TIMEZONE =====================
KYIV_TZ = pytz.timezone("Europe/Kyiv")

# ===================== FLASK =====================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running"

@flask_app.route("/health")
def health():
    return "OK", 200

def run_web():
    port = int(os.environ.get("PORT", 8080))
    logger.info(f">>> Flask starting on port {port}")
    flask_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_web, daemon=True).start()

# ===================== ENV =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
API_KEY = os.getenv("ALERTS_API_KEY", "")

logger.info(f">>> BOT_TOKEN: {BOT_TOKEN}")
logger.info(f">>> CHANNEL_ID: {CHANNEL_ID}")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID is missing")

# ===================== CONFIG =====================
REGION_ID = 31
API_URL = "https://alerts.com.ua/api/states"

# ===================== STATE =====================
last_state = None
alert_start_time = None
last_check_time = None
current_status = "CLEAR"

alert_message_id = None
live_timer_running = False

# ===================== TIME =====================
def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")

# ===================== LIVE TIMER =====================
async def live_timer(application):
    global alert_message_id, alert_start_time, live_timer_running
    while True:
        try:
            if live_timer_running and alert_message_id and alert_start_time:
                duration = datetime.now(KYIV_TZ) - alert_start_time
                total = int(duration.total_seconds())
                h, m, s = total // 3600, (total % 3600) // 60, total % 60
                text = f"🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n⏰ {now()}\n⏱️ Триває: {h:02}:{m:02}:{s:02}"
                try:
                    await application.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=alert_message_id,
                        text=text
                    )
                except Exception as e:
                    logger.error(f"[EDIT ERROR] {e}")
        except Exception as e:
            logger.error(f"[TIMER ERROR] {e}")
        await asyncio.sleep(10)

# ===================== STATUS =====================
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("🔄 Refresh", callback_data="refresh"),
        InlineKeyboardButton("📡 Ping", callback_data="ping")
    ]]
    text = (
        f"🟢 Bot Status: RUNNING\n"
        f"📍 Region: Kyiv (31)\n"
        f"📡 Alert: {current_status}\n"
        f"⏰ Last check: {last_check_time}"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ===================== BUTTONS =====================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_status, last_check_time
    query = update.callback_query
    await query.answer()
    if query.data == "refresh":
        await query.edit_message_text(
            f"🟢 Bot Status: RUNNING\n📍 Region: Kyiv (31)\n📡 Alert: {current_status}\n⏰ Last check: {last_check_time}"
        )
    elif query.data == "ping":
        await query.edit_message_text("📡 Pong!")

# ===================== ALERT LOOP =====================
async def check_alerts(application):
    global last_state, alert_start_time, last_check_time, current_status
    global alert_message_id, live_timer_running
    logger.info(f"[{now()}] Bot started")
    while True:
        try:
            last_check_time = now()
            headers = {"X-API-Key": API_KEY} if API_KEY else {}
            data = requests.get(API_URL, headers=headers, timeout=10).json()
            states = data.get("states", data)
            active = any(r.get("id") == REGION_ID and r.get("alert", False) for r in states)
            current_status = "ALERT" if active else "CLEAR"
            if last_state is None:
                last_state = active
            elif active != last_state:
                if active:
                    alert_start_time = datetime.now(KYIV_TZ)
                    live_timer_running = True
                    msg = await application.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=f"🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n⏰ {now()}\n⏱️ Триває: 00:00:00",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📡 Статус", callback_data="refresh")]])
                    )
                    alert_message_id = msg.message_id
                else:
                    live_timer_running = False
                    alert_message_id = None
                    duration_text = "⏱️ Тривалість невідома"
                    if alert_start_time:
                        duration = datetime.now(KYIV_TZ) - alert_start_time
                        h, m, s = duration.seconds // 3600, (duration.seconds % 3600) // 60, duration.seconds % 60
                        duration_text = f"⏱️ Тривала: {h:02}:{m:02}:{s:02}"
                    await application.bot.send_message(
                        chat_id=CHANNEL_ID,
                        text=f"🟢 КИЇВ | ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ\n⏰ {now()}\n{duration_text}"
                    )
                last_state = active
        except Exception as e:
            logger.error(f"[ERROR] {e}")
        await asyncio.sleep(20)

# ===================== MAIN =====================
def main():
    logger.info("STEP 1 - building application")
    app = Application.builder().token(BOT_TOKEN).build()

    logger.info("STEP 2 - registering handlers")
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button))

    asyncio.get_event_loop().create_task(live_timer(app))
    asyncio.get_event_loop().create_task(check_alerts(app))

    logger.info("STEP 3 - starting webhook")
    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        url_path=BOT_TOKEN,
        webhook_url=f"https://kyiv-alert-bot.onrender.com/{BOT_TOKEN}",
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )

if __name__ == "__main__":
    main()
