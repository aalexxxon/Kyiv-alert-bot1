import asyncio
import os
from datetime import datetime

import aiohttp
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ===================== CONFIG =====================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID missing")

CHANNEL_ID = int(CHANNEL_ID)

PORT = int(os.environ.get("PORT", 8000))
WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL",
    "https://kyiv-alert-bot1-production.up.railway.app"
)

API_URL = "https://alerts.com.ua/api/states"
REGION_ID = 31
KYIV_TZ = pytz.timezone("Europe/Kyiv")

print(">>> BOT STARTING")
print(">>> BOT_TOKEN OK")
print(">>> CHANNEL_ID:", CHANNEL_ID)

# ===================== STATE =====================

last_state = None
alert_start = None
message_id = None
running_timer = False
last_check = "never"
status = "CLEAR"


def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")


# ===================== ALERT LOOP =====================

async def alert_loop(app: Application):
    global last_state, alert_start, message_id, running_timer, status, last_check

    print("[INFO] Alert loop started")

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                last_check = now()

                async with session.get(API_URL, timeout=10) as resp:
                    data = await resp.json()

                states = data.get("states", data)

                active = any(
                    r.get("id") == REGION_ID and r.get("alert")
                    for r in states
                )

                status = "ALERT" if active else "CLEAR"

                if last_state is None:
                    last_state = active

                elif active != last_state:

                    # ALERT START
                    if active:
                        alert_start = datetime.now(KYIV_TZ)
                        running_timer = True

                        msg = await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text="🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n⏱️ 00:00:00",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("📡 Status", callback_data="status")]
                            ])
                        )

                        message_id = msg.message_id
                        print("[INFO] ALERT STARTED")

                    # ALERT END
                    else:
                        running_timer = False
                        message_id = None

                        await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text="🟢 КИЇВ | ВІДБІЙ ТРИВОГИ"
                        )

                        print("[INFO] ALERT ENDED")

                    last_state = active

            except Exception as e:
                print("[ALERT ERROR]", e)

            await asyncio.sleep(20)


# ===================== TIMER =====================

async def timer_loop(app: Application):
    global message_id, alert_start, running_timer

    print("[INFO] Timer started")

    while True:
        try:
            if running_timer and message_id and alert_start:

                delta = datetime.now(KYIV_TZ) - alert_start
                total = int(delta.total_seconds())

                h = total // 3600
                m = (total % 3600) // 60
                s = total % 60

                text = (
                    "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n"
                    f"⏰ {now()}\n"
                    f"⏱️ {h:02}:{m:02}:{s:02}"
                )

                try:
                    await app.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=message_id,
                        text=text
                    )
                except Exception:
                    pass

        except Exception as e:
            print("[TIMER ERROR]", e)

        await asyncio.sleep(10)


# ===================== HANDLERS =====================

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🟢 BOT OK\n📡 {status}\n⏰ {last_check}"
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    await q.edit_message_text(
        f"📡 STATUS: {status}\n⏰ {last_check}"
    )


# ===================== POST INIT =====================

async def post_init(app: Application):
    print("[INFO] POST INIT")

    await app.bot.set_webhook(
        url=f"{WEBHOOK_URL}/webhook",
        drop_pending_updates=True
    )

    asyncio.create_task(alert_loop(app))
    asyncio.create_task(timer_loop(app))

    print("[INFO] WEBHOOK SET")


# ===================== MAIN =====================

def main():
    print("STEP 1: create app")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    print("STEP 2: handlers")

    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(buttons))

    print("STEP 3: start webhook")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook",
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
