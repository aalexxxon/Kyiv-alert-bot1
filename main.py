import os
import asyncio
from datetime import datetime

import pytz
import aiohttp

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ===================== DEBUG =====================
print(">>> Starting main.py")

# ===================== ENV =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()

API_URL = "https://alerts.com.ua/api/states"
REGION_ID = 31

KYIV_TZ = pytz.timezone("Europe/Kyiv")

print(">>> BOT_TOKEN OK:", bool(BOT_TOKEN))
print(">>> CHANNEL_ID:", CHANNEL_ID)
print(">>> WEBHOOK_URL:", WEBHOOK_URL)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID missing")

if not WEBHOOK_URL:
    raise RuntimeError("WEBHOOK_URL missing")

# ===================== STATE =====================
last_state = None
alert_start = None
alert_msg_id = None
timer_running = False
status_cache = "CLEAR"
last_check = None


def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")


# ===================== ALERT LOOP =====================
async def alert_loop(app: Application):
    global last_state, alert_start, alert_msg_id
    global timer_running, status_cache, last_check

    print("[INFO] Alert loop started")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                last_check = now()

                async with session.get(API_URL, timeout=10) as r:
                    data = await r.json()

                states = data.get("states", data)

                active = any(
                    x.get("id") == REGION_ID and x.get("alert", False)
                    for x in states
                )

                status_cache = "ALERT" if active else "CLEAR"

                if last_state is None:
                    last_state = active

                elif active != last_state:

                    # ALERT START
                    if active:
                        alert_start = datetime.now(KYIV_TZ)
                        timer_running = True

                        msg = await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text="🚨 КИЇВ | ТРИВОГА\n⏱️ 00:00:00",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("📡 Status", callback_data="status")]
                            ])
                        )

                        alert_msg_id = msg.message_id
                        print("[ALERT] START")

                    # ALERT END
                    else:
                        timer_running = False
                        alert_msg_id = None

                        await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text="🟢 КИЇВ | ВІДБІЙ ТРИВОГИ"
                        )

                        print("[ALERT] END")

                    last_state = active

            except Exception as e:
                print("[ALERT ERROR]", e)

            await asyncio.sleep(15)


# ===================== TIMER =====================
async def timer_loop(app: Application):
    global alert_msg_id, alert_start, timer_running

    print("[INFO] Timer started")

    while True:
        try:
            if timer_running and alert_msg_id and alert_start:
                delta = datetime.now(KYIV_TZ) - alert_start
                sec = int(delta.total_seconds())

                h = sec // 3600
                m = (sec % 3600) // 60
                s = sec % 60

                text = (
                    "🚨 КИЇВ | ТРИВОГА\n"
                    f"⏰ {now()}\n"
                    f"⏱️ {h:02}:{m:02}:{s:02}"
                )

                try:
                    await app.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=alert_msg_id,
                        text=text
                    )
                except Exception:
                    pass

        except Exception as e:
            print("[TIMER ERROR]", e)

        await asyncio.sleep(10)


# ===================== COMMANDS =====================
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🟢 Bot OK\n"
        f"📡 Status: {status_cache}\n"
        f"⏰ Last check: {last_check}"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "status":
        await q.edit_message_text(f"📡 Status: {status_cache}")


# ===================== STARTUP =====================
async def post_init(app: Application):
    print("[INFO] POST INIT")
    app.create_task(alert_loop(app))
    app.create_task(timer_loop(app))


# ===================== MAIN =====================
def main():
    print("STEP 1")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    print("STEP 2")

    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("STEP 3 START")

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 8080)),
        url_path="webhook",
        webhook_url=WEBHOOK_URL,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
