import os
import asyncio
import logging
from datetime import datetime

import pytz
import aiohttp

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

logger.info(">>> Starting main.py")

# ===================== ENV =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

API_URL = "https://alerts.com.ua/api/states"
REGION_ID = 31
KYIV_TZ = pytz.timezone("Europe/Kyiv")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN missing")
if not CHANNEL_ID:
    raise RuntimeError("CHANNEL_ID missing")

logger.info(">>> BOT OK — token and channel loaded")


# ===================== STATE =====================
last_state = None
status_cache = "CLEAR"
last_check = None

alert_start = None
alert_msg_id = None
timer_running = False


def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")


# ===================== SAFE PARSER =====================
def is_alert(data):
    try:

        # format 1
        if isinstance(data, dict) and "states" in data:
            data = data["states"]

        # format 2
        if isinstance(data, list):
            for region in data:

                region_id = (
                    region.get("regionId")
                    or region.get("id")
                )

                alert = (
                    region.get("activeAlerts")
                    or region.get("alert")
                    or False
                )

                if int(region_id) == REGION_ID:
                    return bool(alert)

        return False

    except Exception as e:
        print("[PARSER ERROR]", e)
        return False


# ===================== FAST ALERT LOOP =====================
async def alert_loop(app: Application):
    global last_state, status_cache, last_check
    global alert_start, alert_msg_id, timer_running

    logger.info("[FAST] Alert loop started")

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=5)
    ) as session:

        while True:
            try:
                last_check = now()

                async with session.get(API_URL) as r:
                    data = await r.json()

                active = is_alert(data)
                print("[DEBUG ACTIVE]", active)
                print("[DEBUG DATA]", data)
                status_cache = "ALERT" if active else "CLEAR"

                if last_state is None:
                    last_state = active

                elif active != last_state:

                    # ALERT START
                    if active:
                        alert_start = datetime.now(KYIV_TZ)
                        timer_running = True

                        try:
                            msg = await app.bot.send_message(
                                chat_id=CHANNEL_ID,
                                text="🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n⏱️ 00:00:00",
                            )
                            alert_msg_id = msg.message_id
                            logger.info(
                                "[FAST] ALERT START — message_id=%s", alert_msg_id
                            )
                        except TelegramError as e:
                            logger.error(
                                "[FAST] Failed to send ALERT START message: %s", e
                            )

                    # ALERT END
                    else:
                        timer_running = False
                        alert_msg_id = None

                        try:
                            await app.bot.send_message(
                                chat_id=CHANNEL_ID,
                                text="🟢 КИЇВ | ВІДБІЙ ТРИВОГИ",
                            )
                            logger.info("[FAST] ALERT END — all-clear message sent")
                        except TelegramError as e:
                            logger.error(
                                "[FAST] Failed to send ALERT END message: %s", e
                            )

                    last_state = active

            except Exception as e:
                logger.error("[FAST ERROR] %s", e)

            # ⚡ 2–4 сек детект
            await asyncio.sleep(3)


# ===================== TIMER =====================
async def timer_loop(app: Application):
    global alert_msg_id, alert_start, timer_running

    logger.info("[TIMER] Timer loop started")

    while True:
        try:
            if timer_running and alert_msg_id and alert_start:

                delta = datetime.now(KYIV_TZ) - alert_start
                sec = int(delta.total_seconds())

                h = sec // 3600
                m = (sec % 3600) // 60
                s = sec % 60

                text = (
                    "🚨 КИЇВ | ПОВІТРЯНА ТРИВОГА\n"
                    f"⏰ {now()}\n"
                    f"⏱️ {h:02}:{m:02}:{s:02}"
                )

                try:
                    await app.bot.edit_message_text(
                        chat_id=CHANNEL_ID,
                        message_id=alert_msg_id,
                        text=text,
                    )
                except TelegramError as e:
                    logger.warning("[TIMER] Could not edit message: %s", e)

        except Exception as e:
            logger.error("[TIMER ERROR] %s", e)

        await asyncio.sleep(10)


# ===================== COMMANDS =====================
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🟢 Bot RUNNING\n"
        f"📡 Status: {status_cache}\n"
        f"⏰ Last check: {last_check}"
    )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "status":
        await q.edit_message_text(f"📡 Status: {status_cache}")


# ===================== MAIN =====================
async def post_init(app: Application) -> None:
    """Called by python-telegram-bot after the Application is fully started.
    Creating tasks here (instead of before run_polling) avoids the
    'coroutine attached to a different loop' / 'task created before app
    is running' warnings and ensures only one polling instance is active."""
    logger.info("[INIT] Application ready — starting background tasks")
    app.create_task(alert_loop(app))
    app.create_task(timer_loop(app))


def main():
    logger.info("STEP 1 — building application")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    logger.info("STEP 2 — registering handlers")

    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button))

    logger.info("STEP 3 — starting polling")
    async def test(app):
    await app.bot.send_message(
        chat_id=CHANNEL_ID,
        text="✅ TEST MESSAGE"
    )

app.post_init = test
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()

