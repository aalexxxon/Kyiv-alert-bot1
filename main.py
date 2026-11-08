
import os
import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from aiohttp import web
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# ==========================================
# 1. НАЛАШТУВАННЯ
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

logger = logging.getLogger("kyiv_alert_bot")

# Прибираємо журнали HTTP із URL, у яких може бути токен
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL_ID = os.getenv(
    "CHANNEL_ID",
    "-1003777875292"
)

KYIV_TZ = ZoneInfo("Europe/Kyiv")

API_URL = os.getenv(
    "ALERTS_API_URL",
    "https://tryvoha.online/api/v1/alerts"
)

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "45"))

MAX_DATA_AGE = int(
    os.getenv("MAX_DATA_AGE_SECONDS", "240")
)

# ==========================================
# 2. СТАН БОТА
# ==========================================

last_state = None

current_status = "⚪ ОЧІКУВАННЯ ДАНИХ"

last_check_time = "Ще не було"

data_update_time = "Невідомо"

alert_start_time = None

api_errors = 0

# ==========================================
# 3. ДОПОМІЖНІ ФУНКЦІЇ
# ==========================================

def kyiv_now():
    return datetime.now(KYIV_TZ)


def parse_datetime(value):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)

        return result

    except (ValueError, TypeError):
        return None


def format_duration(start_time):

    if not start_time:
        return "невідомо"

    seconds = int(
        (datetime.now(timezone.utc) - start_time).total_seconds()
    )

    seconds = max(0, seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    parts = []

    if hours:
        parts.append(f"{hours} год.")

    if minutes or hours:
        parts.append(f"{minutes} хв.")

    parts.append(f"{secs} сек.")

    return " ".join(parts)


async def send_channel_message(app, message):

    try:
        await app.bot.send_message(
            chat_id=CHANNEL_ID,
            text=message,
            parse_mode="HTML"
        )

        logger.info("Повідомлення успішно відправлено в канал")

        return True

    except Exception:
        logger.exception("Помилка відправлення повідомлення в канал")

        return False


# ==========================================
# 4. ОТРИМАННЯ СТАТУСУ КИЄВА
# ==========================================

async def get_kyiv_alert(client):

    response = await client.get(API_URL)

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Неправильний формат відповіді API")

    updated_at = parse_datetime(
        data.get("updated_at")
    )

    if updated_at is None:
        raise ValueError("API не повернув час оновлення даних")

    age = (
        datetime.now(timezone.utc) - updated_at
    ).total_seconds()

    if age < -120:
        raise ValueError("Час оновлення API знаходиться в майбутньому")

    if age > MAX_DATA_AGE:
        raise ValueError(
            f"Застарілі дані API: {int(age)} секунд"
        )

    alerts = data.get("alerts")

    if not isinstance(alerts, list):
        raise ValueError("API не повернув список alerts")

    # Шукаємо тільки місто Київ.
    # Київська область має інший slug: kyivska.

    kyiv_data = next(
        (
            item for item in alerts
            if isinstance(item, dict)
            and item.get("slug") == "kyiv"
        ),
        None
    )

    active = kyiv_data is not None

    started_at = None

    if kyiv_data:
        started_at = parse_datetime(
            kyiv_data.get("started_at")
        )

    return active, updated_at, started_at


# ==========================================
# 5. МОНІТОРИНГ ПОВІТРЯНОЇ ТРИВОГИ
# ==========================================

async def alert_loop(app):

    global last_state
    global current_status
    global last_check_time
    global data_update_time
    global alert_start_time
    global api_errors

    logger.info("Моніторинг повітряних тривог запущено")

    timeout = httpx.Timeout(15.0)

    async with httpx.AsyncClient(
        timeout=timeout,
        headers={
            "User-Agent": "Kyiv-alert-bot/2.0"
        }
    ) as client:

        while True:

            try:

                active, updated_at, started_at = (
                    await get_kyiv_alert(client)
                )

                api_errors = 0

                last_check_time = kyiv_now().strftime(
                    "%H:%M:%S"
                )

                data_update_time = updated_at.astimezone(
                    KYIV_TZ
                ).strftime("%H:%M:%S")

                current_status = (
                    "🚨 ТРИВОГА"
                    if active
                    else "🟢 ВІДБІЙ"
                )

                logger.info(
                    "Київ: %s | Перевірка: %s | Оновлення API: %s",
                    current_status,
                    last_check_time,
                    data_update_time
                )

                # ПЕРШИЙ ЗАПУСК:
                # Якщо тривога вже активна,
                # повідомляємо про неї в канал.

                if last_state is None:

                    if active:

                        alert_start_time = (
                            started_at or datetime.now(timezone.utc)
                        )

                        message = (
                            "🚨 <b>КИЇВ | ТРИВОГА ТРИВАЄ!</b>\n"
                            "ℹ️ Бот відновив моніторинг "
                            "під час активної тривоги."
                        )

                        if await send_channel_message(app, message):
                            last_state = active

                    else:

                        last_state = False
                        alert_start_time = None

                        logger.info(
                            "Початковий стан: відбій"
                        )

                # ПОЧАТОК ТРИВОГИ

                elif active and not last_state:

                    alert_start_time = (
                        started_at or datetime.now(timezone.utc)
                    )

                    message = (
                        "🚨 <b>КИЇВ | ПОВІТРЯНА ТРИВОГА!</b>\n"
                        "⚠️ Перебувайте в безпечному місці."
                    )

                    if await send_channel_message(app, message):
                        last_state = True

                # ВІДБІЙ ТРИВОГИ

                elif not active and last_state:

                    duration = format_duration(
                        alert_start_time
                    )

                    message = (
                        "🟢 <b>КИЇВ | ВІДБІЙ ТРИВОГИ!</b>\n"
                        f"⏳ Тривалість: {duration}"
                    )

                    if await send_channel_message(app, message):
                        last_state = False
                        alert_start_time = None

            except asyncio.CancelledError:
                raise

            except Exception as e:

                api_errors += 1

                current_status = (
                    "⚠️ НЕМАЄ АКТУАЛЬНИХ ДАНИХ"
                )

                logger.exception(
                    "Помилка перевірки тривоги: %s",
                    e
                )

            await asyncio.sleep(CHECK_INTERVAL)


# ==========================================
# 6. КОМАНДА /STATUS
# ==========================================

async def status_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = (
        "🟢 <b>Бот активний</b>\n"
        f"📡 Статус: {current_status}\n"
        f"⏰ Ост. перевірка: {last_check_time}\n"
        f"🔄 Оновлення API: {data_update_time}\n"
        f"❗ Помилок API: {api_errors}\n"
        f"📍 Джерело: Tryvoha.online"
    )

    if update.effective_message:
        await update.effective_message.reply_text(
            message,
            parse_mode="HTML"
        )


# ==========================================
# 7. КОМАНДА /TEST
# ==========================================

async def test_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    success = await send_channel_message(
        context.application,
        "🔔 <b>Перевірка зв'язку:</b>\n"
        "Kyiv-alert-bot працює!"
    )

    if update.effective_message:

        if success:
            answer = "✅ Повідомлення відправлено в канал!"
        else:
            answer = "❌ Не вдалося відправити повідомлення."

        await update.effective_message.reply_text(answer)


# ==========================================
# 8. ВЕБ-СЕРВЕР RENDER
# ==========================================

async def home(request):

    return web.Response(
        text="Kyiv Alert Bot is running!"
    )


async def health(request):

    return web.json_response({
        "bot": "running",
        "status": current_status,
        "last_check": last_check_time,
        "api_updated": data_update_time,
        "api_errors": api_errors
    })


# ==========================================
# 9. ГОЛОВНИЙ ЗАПУСК
# ==========================================

async def main():

    if not BOT_TOKEN:

        logger.error(
            "BOT_TOKEN не встановлено в Render Environment!"
        )

        return

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("status", status_cmd)
    )

    app.add_handler(
        CommandHandler("test", test_cmd)
    )

    # Веб-сервер

    app_http = web.Application()

    app_http.router.add_get("/", home)
    app_http.router.add_get("/health", health)

    runner = web.AppRunner(app_http)

    await runner.setup()

    port = int(
        os.environ.get("PORT", 10000)
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    logger.info(
        "Веб-сервер запущено на порту %s",
        port
    )

    monitor_task = None

    try:

        await app.initialize()

        await app.bot.delete_webhook(
            drop_pending_updates=True
        )

        await app.start()

        await app.updater.start_polling()

        logger.info("Telegram-бот успішно запущено")

        monitor_task = asyncio.create_task(
            alert_loop(app)
        )

        await asyncio.Event().wait()

    finally:

        logger.info("Зупинка бота")

        if monitor_task:

            monitor_task.cancel()

            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

        if app.updater and app.updater.running:
            await app.updater.stop()

        if app.running:
            await app.stop()

        await app.shutdown()

        await runner.cleanup()


# ==========================================
# 10. ЗАПУСК ПРОГРАМИ
# ==========================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info("Бот зупинено")
