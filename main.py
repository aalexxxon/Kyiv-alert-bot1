import asyncio
import requests
from datetime import datetime
import os
import pytz

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ===================== DEBUG =====================
print(">>> Starting main.py")

# ===================== TIMEZONE =====================
KYIV_TZ = pytz.timezone("Europe/Kyiv")

# ===================== ENV =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
API_KEY = os.getenv("ALERTS_API_KEY", "")

print(">>> BOT_TOKEN:", BOT_TOKEN)
print(">>> CHANNEL_ID:", CHANNEL_ID)

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
    global alert_message_id
    global alert_start_time
    global live_timer_running

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
                    f"🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n"
                    f"⏰ {now()}\n"
                    f"⏱️ Триває: "
                    f"{h:02}:{m:02}:{s:02}"
                )

                try:
                    await application.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=alert_message_id,
                        text=text
                    )

                except Exception as e:
                    print("[EDIT ERROR]", e)

        except Exception as e:
            print("[TIMER ERROR]", e)

        await asyncio.sleep(10)

# ===================== STATUS =====================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

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
        f"🟢 Bot Status: RUNNING\n"
        f"📍 Region: Kyiv (31)\n"
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
    global current_status
    global last_check_time

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

        await query.edit_message_text(
            "📡 Pong!"
        )

# ===================== ALERT LOOP =====================
async def check_alerts(application):

    global last_state
    global alert_start_time
    global last_check_time
    global current_status
    global alert_message_id
    global live_timer_running

    print(f"[{now()}] Alert monitoring started")

    while True:
        try:
            last_check_time = now()

            headers = (
                {"X-API-Key": API_KEY}
                if API_KEY else {}
            )

            response = requests.get(
                API_URL,
                headers=headers,
                timeout=10
            )

            data = response.json()

            states = data.get("states", data)

            active = any(
                r.get("id") == REGION_ID
                and r.get("alert", False)
                for r in states
            )

            current_status = (
                "ALERT"
                if active else "CLEAR"
            )

            if last_state is None:
                last_state = active

            elif active != last_state:

                # ================= ALERT START =================
                if active:

                    alert_start_time = datetime.now(KYIV_TZ)

                    live_timer_running = True

                    msg = await application.bot.send_message(
                        chat_id=CHANNEL_ID,

                        text=(
                            f"🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n"
                            f"⏰ {now()}\n"
                            f"⏱️ Триває: 00:00:00"
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

                    print(">>> ALERT STARTED")

                # ================= ALERT END =================
                else:

                    live_timer_running = False

                    alert_message_id = None

                    duration_text = (
                        "⏱️ Тривалість невідома"
                    )

                    if alert_start_time:

                        duration = (
                            datetime.now(KYIV_TZ)
                            - alert_start_time
                        )

                        total = int(
                            duration.total_seconds()
                        )

                        h = total // 3600
                        m = (total % 3600) // 60
                        s = total % 60

                        duration_text = (
                            f"⏱️ Тривала: "
                            f"{h:02}:{m:02}:{s:02}"
                        )

                    await application.bot.send_message(
                        chat_id=CHANNEL_ID,

                        text=(
                            f"🟢 КИЇВ | "
                            f"ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ\n"
                            f"⏰ {now()}\n"
                            f"{duration_text}"
                        )
                    )

                    print(">>> ALERT ENDED")

                last_state = active

        except Exception as e:
            print("[ERROR]", e)

        await asyncio.sleep(20)

# ===================== MAIN =====================
def main():

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # ================= COMMANDS =================
    application.add_handler(
        CommandHandler(
            "status",
            status
        )
    )

    # ================= BUTTONS =================
    application.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    print(">>> BOT STARTED")

    # ================= BACKGROUND =================
    async def start_tasks(app):

        asyncio.create_task(
            check_alerts(app)
        )

        asyncio.create_task(
            live_timer(app)
        )

    application.post_init = start_tasks

    # ================= START BOT =================
    application.run_polling()


# ===================== START =====================
if __name__ == "__main__":
    main()
