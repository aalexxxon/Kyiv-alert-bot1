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

# ===================== ENV =====================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID missing")

PORT = int(os.environ.get("PORT", 8000))
WEBHOOK_URL = os.environ.get(
    "WEBHOOK_URL",
    "https://kyiv-alert-bot1-production.up.railway.app"
)

API_URL = "https://alerts.com.ua/api/states"
REGION_ID = 31
KYIV_TZ = pytz.timezone("Europe/Kyiv")

print(">>> BOT STARTING")
print(">>> CHANNEL_ID:", CHANNEL_ID)


# ===================== STATE =====================

last_state = None
alert_start = None
msg_id = None
running = False
status = "CLEAR"
last_check = "never"


def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")


# ===================== ALERT LOOP =====================

async def alert_loop(app: Application):
    global last_state, alert_start, msg_id, running, status, last_check

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

                    if active:
                        alert_start = datetime.now(KYIV_TZ)
                        running = True

                        msg = await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text="🚨 КИЇВ | ТРИВОГА\n⏱️ 00:00:00",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("📡 Status", callback_data="status")]
                            ])
                        )

                        msg_id = msg.message_id
                        print("[ALERT] START")

                    else:
                        running = False
                        msg_id = None

                        await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text="🟢 КИЇВ | ВІДБІЙ ТРИВОГИ"
                        )

                        print("[ALERT] END")

                    last_state = active

            except Exception as e:
                print("[ALERT ERROR]", e)

            await asyncio.sleep(20)


# ===================== TIMER =====================

async def timer_loop(app: Application):
    global msg_id, alert_start, running

    print("[INFO] Timer started")

    while True:
        try:
            if running and msg_id and alert_start:

                delta = datetime.now(KYIV_TZ) - alert_start
                t = int(delta.total_seconds())

                h = t // 3600
                m = (t % 3600) // 60
                s = t % 60

                text = (
                    "🚨 КИЇВ | ТРИВОГА\n"
                    f"⏰ {now()}\n"
                    f"⏱️ {h:02}:{m:02}:{s:02}"
                )

                try:
                    await app.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=msg_id,
                        text=text
                    )
                except:
                    pass

        except Exception as e:
            print("[TIMER ERROR]", e)

        await asyncio.sleep(10)


# ===================== COMMANDS =====================

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


# ===================== POST INIT (FIXED) =====================

async def post_init(app: Application):
    print("[INFO] POST INIT")

    try:
        await app.bot.delete_webhook(drop_pending_updates=True)

        await asyncio.sleep(2)

        await app.bot.set_webhook(
            url=f"{WEBHOOK_URL}/webhook",
            drop_pending_updates=True
        )

        print("[INFO] WEBHOOK SET OK")

    except Exception as e:
        print("[WEBHOOK ERROR]", e)

    asyncio.create_task(alert_loop(app))
    asyncio.create_task(timer_loop(app))


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
    app.add_handler(CallbackQueryHandler(buttons))

    print("STEP 3 START")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="webhook",
        webhook_url=f"{WEBHOOK_URL}/webhook",
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
