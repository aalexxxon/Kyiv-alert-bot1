import asyncio
import os
import pytz
from datetime import datetime

import aiohttp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ===================== DEBUG =====================
print(">>> Starting main.py")

# ===================== CONFIG =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
API_KEY = os.getenv("ALERTS_API_KEY", "")

REGION_ID = 31
API_URL = "https://alerts.com.ua/api/states"

WEBHOOK_URL = "http://kyiv-alert-bot1-production.up.railway.app"

KYIV_TZ = pytz.timezone("Europe/Kyiv")

print(">>> BOT_TOKEN:", bool(BOT_TOKEN))
print(">>> CHANNEL_ID:", CHANNEL_ID)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID missing")

# ===================== STATE =====================
last_state = None
alert_start_time = None
alert_message_id = None
live_timer_running = False
last_check_time = None
current_status = "CLEAR"


def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")


# ===================== ALERT LOOP =====================
async def check_alerts(app):
    global last_state, alert_start_time, alert_message_id
    global live_timer_running, last_check_time, current_status

    print("[INFO] Alert loop started")

    async with aiohttp.ClientSession() as session:

        while True:
            try:
                last_check_time = now()

                headers = {"X-API-Key": API_KEY} if API_KEY else {}

                async with session.get(API_URL, headers=headers) as resp:
                    data = await resp.json()

                states = data.get("states", data)

                active = any(
                    r.get("id") == REGION_ID and r.get("alert", False)
                    for r in states
                )

                current_status = "ALERT" if active else "CLEAR"

                if last_state is None:
                    last_state = active

                elif active != last_state:

                    if active:
                        alert_start_time = datetime.now(KYIV_TZ)
                        live_timer_running = True

                        msg = await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text="🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n⏱️ 00:00:00",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("📡 Статус", callback_data="refresh")]
                            ])
                        )

                        alert_message_id = msg.message_id
                        print(">>> ALERT STARTED")

                    else:
                        live_timer_running = False
                        alert_message_id = None

                        await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text="🟢 КИЇВ | ВІДБІЙ ТРИВОГИ"
                        )

                        print(">>> ALERT ENDED")

                    last_state = active

            except Exception as e:
                print("[ERROR]", e)

            await asyncio.sleep(20)


# ===================== TIMER =====================
async def live_timer(app):
    global alert_message_id, alert_start_time, live_timer_running

    print("[INFO] Timer started")

    while True:
        try:
            if live_timer_running and alert_message_id and alert_start_time:

                delta = datetime.now(KYIV_TZ) - alert_start_time
                total = int(delta.total_seconds())

                h = total // 3600
                m = (total % 3600) // 60
                s = total % 60

                text = (
                    f"🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n"
                    f"⏰ {now()}\n"
                    f"⏱️ {h:02}:{m:02}:{s:02}"
                )

                await app.bot.edit_message_text(
                    chat_id=CHANNEL_ID,
                    message_id=alert_message_id,
                    text=text
                )

        except Exception as e:
            print("[TIMER ERROR]", e)

        await asyncio.sleep(10)


# ===================== COMMANDS =====================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🟢 Bot RUNNING\n"
        f"📡 Status: {current_status}\n"
        f"⏰ Last check: {last_check_time}"
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(f"📡 Status: {current_status}")


# ===================== STARTUP =====================
started = False

async def post_init(app):
    global started

    if started:
        return

    started = True

    print("[INFO] Starting background tasks")

    app.create_task(check_alerts(app))
    app.create_task(live_timer(app))

    await app.bot.delete_webhook(drop_pending_updates=True)


# ===================== MAIN =====================
def main():

    print("STEP 1: file loaded")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    print("STEP 2: app created")

    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button))

    print(">>> SETTING WEBHOOK...")

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        webhook_url=f"{WEBHOOK_URL}/webhook"
    )


if __name__ == "__main__":
    main()
