import asyncio
import os
from datetime import datetime

import aiohttp
import pytz

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

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

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")

if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID missing")

print(">>> BOT_TOKEN:", bool(BOT_TOKEN))
print(">>> CHANNEL_ID:", CHANNEL_ID)

# ===================== CONFIG =====================

API_URL = "https://alerts.com.ua/api/states"
REGION_ID = 31

WEBHOOK_URL = "https://kyiv-alert-bot1-production.up.railway.app"

KYIV_TZ = pytz.timezone("Europe/Kyiv")

# ===================== STATE =====================

last_state = None
alert_start_time = None
alert_message_id = None

live_timer_running = False

current_status = "CLEAR"
last_check_time = "never"

# ===================== TIME =====================

def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")


# ===================== ALERT LOOP =====================

async def check_alerts(app):
    global last_state
    global alert_start_time
    global alert_message_id
    global live_timer_running
    global current_status
    global last_check_time

    print("[INFO] Alert loop started")

    async with aiohttp.ClientSession() as session:

        while True:

            try:
                last_check_time = now()

                async with session.get(API_URL, timeout=10) as response:
                    data = await response.json()

                states = data.get("states", data)

                active = any(
                    region.get("id") == REGION_ID
                    and region.get("alert", False)
                    for region in states
                )

                current_status = "ALERT" if active else "CLEAR"

                # first launch
                if last_state is None:
                    last_state = active

                # state changed
                elif active != last_state:

                    # ================= ALERT START =================

                    if active:

                        alert_start_time = datetime.now(KYIV_TZ)

                        live_timer_running = True

                        msg = await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=(
                                "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n"
                                f"⏰ {now()}\n"
                                "⏱️ Триває: 00:00:00"
                            ),
                            reply_markup=InlineKeyboardMarkup([
                                [
                                    InlineKeyboardButton(
                                        "📡 Статус",
                                        callback_data="refresh"
                                    )
                                ]
                            ])
                        )

                        alert_message_id = msg.message_id

                        print("[INFO] ALERT STARTED")

                    # ================= ALERT END =================

                    else:

                        live_timer_running = False

                        duration_text = "⏱️ Тривалість невідома"

                        if alert_start_time:

                            duration = (
                                datetime.now(KYIV_TZ)
                                - alert_start_time
                            )

                            total = int(duration.total_seconds())

                            h = total // 3600
                            m = (total % 3600) // 60
                            s = total % 60

                            duration_text = (
                                f"⏱️ Тривала: "
                                f"{h:02}:{m:02}:{s:02}"
                            )

                        await app.bot.send_message(
                            chat_id=CHANNEL_ID,
                            text=(
                                "🟢 КИЇВ | ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ\n"
                                f"⏰ {now()}\n"
                                f"{duration_text}"
                            )
                        )

                        alert_message_id = None

                        print("[INFO] ALERT ENDED")

                    last_state = active

            except Exception as e:
                print("[ERROR]", e)

            await asyncio.sleep(20)


# ===================== LIVE TIMER =====================

async def live_timer(app):
    global alert_message_id
    global alert_start_time
    global live_timer_running

    print("[INFO] Timer started")

    while True:

        try:

            if (
                live_timer_running
                and alert_message_id
                and alert_start_time
            ):

                duration = (
                    datetime.now(KYIV_TZ)
                    - alert_start_time
                )

                total = int(duration.total_seconds())

                h = total // 3600
                m = (total % 3600) // 60
                s = total % 60

                text = (
                    "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n"
                    f"⏰ {now()}\n"
                    f"⏱️ Триває: {h:02}:{m:02}:{s:02}"
                )

                try:

                    await app.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=alert_message_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup([
                            [
                                InlineKeyboardButton(
                                    "📡 Статус",
                                    callback_data="refresh"
                                )
                            ]
                        ])
                    )

                except Exception:
                    pass

        except Exception as e:
            print("[TIMER ERROR]", e)

        await asyncio.sleep(10)


# ===================== COMMAND =====================

async def status_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = [[
        InlineKeyboardButton(
            "🔄 Refresh",
            callback_data="refresh"
        ),
        InlineKeyboardButton(
            "📡 Ping",
            callback_data="ping"
        )
    ]]

    text = (
        "🟢 Bot Status: RUNNING\n"
        f"📡 Alert: {current_status}\n"
        f"⏰ Last check: {last_check_time}"
    )

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ===================== BUTTONS =====================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.data == "refresh":

        text = (
            "🟢 Bot Status: RUNNING\n"
            f"📡 Alert: {current_status}\n"
            f"⏰ Last check: {last_check_time}"
        )

        await query.edit_message_text(text)

    elif query.data == "ping":

        await query.edit_message_text("📡 Pong!")


# ===================== POST INIT =====================

async def post_init(app):

    print("[INFO] Starting background tasks")

    asyncio.create_task(check_alerts(app))
    asyncio.create_task(live_timer(app))

    await app.bot.set_webhook(
        url=f"{WEBHOOK_URL}/webhook",
        drop_pending_updates=True
    )

    info = await app.bot.get_webhook_info()

    print("[WEBHOOK INFO]", info)


# ===================== MAIN =====================

def main():

    print("STEP 1: creating app")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    print("STEP 2: adding handlers")

    app.add_handler(
        CommandHandler(
            "status",
            status_cmd
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    print(">>> SETTING WEBHOOK...")

    app.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 8000)),
        webhook_url=f"{WEBHOOK_URL}/webhook",
        secret_token=None,
        drop_pending_updates=True,
    )


# ===================== START =====================

if __name__ == "__main__":
    main()
