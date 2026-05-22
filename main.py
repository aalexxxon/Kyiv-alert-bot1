import os
import asyncio
import logging
from datetime import datetime

import pytz
import httpx
from aiohttp import web
from telegram import Update
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
    text = (f"🟢 Bot Status: RUNNING\n📍 Region: Kyiv (31)\n📡 Alert: {current_status}\n⏰ Last check: {last_check_time}")
    await update.message.reply_text(text)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

# ===================== WEB SERVER (FOR RENDER) =====================
async def handle_ping(request):
    return web.Response(text="Bot is running")

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
                        await app.bot.send_message(chat_id=CHANNEL_ID, text=f"🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n⏰ {now()}")
                    else:
                        delta = datetime.now(KYIV_TZ) - alert_start_time if alert_start_time else None
                        dur = f"\n⏱️ Тривала: {delta.seconds//3600:02}:{(delta.seconds%3600)//60:02}:{delta.seconds%60:02}" if delta else ""
                        await app.bot.send_message(chat_id=CHANNEL_ID, text=f"🟢 КИЇВ | ВІДБІЙ ТРИВОГИ\n⏰ {now()}{dur}")
                last_state = active
            except Exception as e:
                logger.error(f"[ALERT LOOP ERROR] {e}")
            await asyncio.sleep(45)

# ===================== MAIN =====================
async def main():
    # 1. Створення додатку
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    # 2. Запуск фонового сервера для Render (щоб не закривали порт)
    app_http = web.Application()
    app_http.router.add_get('/', handle_ping)
    runner = web.AppRunner(app_http)
    await runner.setup()
    
    # Використовуємо порт з оточення Render
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    # 3. Запуск циклу тривог
    asyncio.create_task(alert_loop(app))
    
    # 4. Запуск Polling
    logger.info("Starting bot in Polling mode...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
