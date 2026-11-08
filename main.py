import os
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from aiohttp import web
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

# =====================================================
# НАЛАШТУВАННЯ
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003777875292"))

API_URL = "https://alerts.com.ua/api/states"

# Якщо API-ключ є, додай його в Render Environment
# як ALERTS_API_KEY. Якщо немає — залиш порожнім.
ALERTS_API_KEY = os.getenv("ALERTS_API_KEY", "")

KYIV_TZ = ZoneInfo("Europe/Kyiv")

POLL_INTERVAL = 45
REQUEST_TIMEOUT = 15

SOURCE_NAME = "alerts.com.ua"

# =====================================================
# ЛОГУВАННЯ
# =====================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)

logger = logging.getLogger("KyivAlertBot")

# Не виводимо URL Telegram API з токеном у логах
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# =====================================================
# ГЛОБАЛЬНИЙ СТАН
# =====================================================

last_state = None

current_status = "⚠️ НЕМАЄ АКТУАЛЬНИХ ДАНИХ"

api_ok = False
api_errors = 0

last_check_time = "Ще не було"
last_success_time = "Ще не було"
last_api_update = "Невідомо"
last_api_error = "Немає"

alert_start_time = None

# =====================================================
# ДОПОМІЖНІ ФУНКЦІЇ
# =====================================================

def kyiv_now():
    return datetime.now(KYIV_TZ)


def format_time(value):
    if not value:
        return "Невідомо"

    if isinstance(value, datetime):
        return value.astimezone(KYIV_TZ).strftime("%H:%M:%S")

    return str(value)


def parse_api_datetime(value):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=KYIV_TZ)

        return result.astimezone(KYIV_TZ)

    except (ValueError, TypeError):
        return None


def get_alert_value(value):
    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        return value.lower().strip() in (
            "true", "1", "yes", "active"
        )

    raise ValueError("Невідомий формат статусу тривоги")


def find_kyiv(data):
    states = data.get("states")

    if not isinstance(states, list):
        raise ValueError("API не повернув список states")

    for item in states:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip().lower()

        # Тільки місто Київ, не Київська область
        if "область" in name:
            continue

        if name in ("київ", "м. київ", "місто київ"):
            return item

    # Додаткова перевірка назви
    for item in states:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip().lower()

        if (
            "київ" in name
            and "область" not in name
            and "район" not in name
        ):
            return item

    raise ValueError("Київ не знайдено у відповіді API")


def calculate_duration(start):
    if not start:
        return "невідомо"

    seconds = int((kyiv_now() - start).total_seconds())

    if seconds < 0:
        return "невідомо"

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


def make_api_headers():
    headers = {
        "Accept": "application/json",
        "User-Agent": "Kyiv-Alert-Bot/2.0",
    }

    if ALERTS_API_KEY:
        headers["X-API-Key"] = ALERTS_API_KEY

    return headers


# =====================================================
# ОТРИМАННЯ СТАТУСУ КИЄВА
# =====================================================

async def get_kyiv_alert(client):

    response = await client.get(
        API_URL,
        headers=make_api_headers(),
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Некоректна відповідь API")

    kyiv_data = find_kyiv(data)

    active = get_alert_value(
        kyiv_data.get("alert")
    )

    changed = parse_api_datetime(
        kyiv_data.get("changed")
    )

    api_update = data.get("last_update", "Невідомо")

    return active, changed, api_update


# =====================================================
# КОМАНДА /START
# =====================================================

async def start_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🇺🇦 <b>Тривога Київ</b>\n\n"
        "Бот автоматично повідомляє канал "
        "про початок та відбій повітряної тривоги "
        "у місті Києві.\n\n"
        "📡 /status — поточний стан бота\n"
        "🔔 /test — перевірка повідомлення в каналі",
        parse_mode="HTML",
    )


# =====================================================
# КОМАНДА /STATUS
# =====================================================

async def status_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if api_ok:
        status = current_status
        api_status = "🟢 API працює"
    else:
        status = "⚠️ НЕМАЄ АКТУАЛЬНИХ ДАНИХ"
        api_status = "🔴 API недоступне"

    message = (
        "🟢 <b>Бот активний</b>\n"
        f"📡 Статус: {status}\n"
        f"⏰ Ост. перевірка: {last_check_time}\n"
        f"🔄 Оновлення API: {last_api_update}\n"
        f"📶 Стан API: {api_status}\n"
        f"❗ Помилок API: {api_errors}\n"
        f"📍 Джерело: {SOURCE_NAME}"
    )

    if not api_ok:
        message += (
            f"\n⚠️ Остання помилка: {last_api_error}"
        )

        message += (
            f"\n🕒 Остання успішна перевірка: "
            f"{last_success_time}"
        )

    await update.message.reply_text(
        message,
        parse_mode="HTML",
    )


# =====================================================
# КОМАНДА /TEST
# =====================================================

async def test_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:
        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=(
                "🔔 <b>ПЕРЕВІРКА ЗВ'ЯЗКУ</b>\n\n"
                "✅ Бот працює!\n"
                "📡 Зв'язок із Telegram успішний."
            ),
            parse_mode="HTML",
        )

        await update.message.reply_text(
            "✅ Тестове повідомлення успішно "
            "відправлено в канал!"
        )

    except Exception as e:
        logger.exception("Помилка команди test")

        await update.message.reply_text(
            f"❌ Не вдалося відправити повідомлення:\n{e}"
        )


# =====================================================
# ВІДПРАВКА ПОВІДОМЛЕНЬ У КАНАЛ
# =====================================================

async def send_channel_message(app, message):

    await app.bot.send_message(
        chat_id=CHANNEL_ID,
        text=message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


# =====================================================
# ОСНОВНИЙ ЦИКЛ ПЕРЕВІРКИ ТРИВОГИ
# =====================================================

async def alert_loop(app):

    global last_state
    global current_status
    global api_ok
    global api_errors
    global last_check_time
    global last_success_time
    global last_api_update
    global last_api_error
    global alert_start_time

    logger.info("Запущено перевірку повітряних тривог Києва")

    async with httpx.AsyncClient(
        follow_redirects=True
    ) as client:

        while True:

            try:

                active, changed, api_update = (
                    await get_kyiv_alert(client)
                )

                # API відповів правильно
                api_ok = True
                last_check_time = kyiv_now().strftime("%H:%M:%S")
                last_success_time = last_check_time
                last_api_update = str(api_update)
                last_api_error = "Немає"

                current_status = (
                    "🚨 ТРИВОГА" if active
                    else "🟢 ВІДБІЙ"
                )

                # Перша успішна перевірка після запуску
                if last_state is None:

                    last_state = active

                    if active:
                        alert_start_time = changed or kyiv_now()

                        await send_channel_message(
                            app,
                            "🚨 <b>КИЇВ | ТРИВОГА ТРИВАЄ!</b>\n\n"
                            "⚠️ Бот відновив роботу та отримав "
                            "підтвердження активної тривоги."
                        )

                    else:
                        alert_start_time = None

                    logger.info(
                        f"Початковий статус Києва: {current_status}"
                    )

                # Зміна статусу
                elif active != last_state:

                    if active:

                        alert_start_time = changed or kyiv_now()

                        message = (
                            "🚨 <b>КИЇВ | ПОВІТРЯНА ТРИВОГА!</b>\n\n"
                            "⚠️ Перебувайте в безпечному місці!\n"
                            "Бережіть себе та близьких."
                        )

                    else:

                        duration = calculate_duration(
                            alert_start_time
                        )

                        message = (
                            "🟢 <b>КИЇВ | ВІДБІЙ ТРИВОГИ!</b>\n\n"
                            f"⏳ Тривалість: {duration}\n"
                            "Бережіть себе!"
                        )

                        alert_start_time = None

                    await send_channel_message(
                        app,
                        message,
                    )

                    last_state = active

                    logger.info(
                        f"Статус Києва змінився: {current_status}"
                    )

            except asyncio.CancelledError:
                raise

            except Exception as e:

                api_ok = False
                api_errors += 1
                last_api_error = str(e)[:250]

                logger.exception(
                    "Помилка перевірки API"
                )

                # Не змінюємо last_state і не надсилаємо
                # повідомлення про відбій без підтвердження API.

            await asyncio.sleep(POLL_INTERVAL)


# =====================================================
# ВЕБ-СЕРВЕР ДЛЯ RENDER
# =====================================================

async def health_check(request):

    return web.json_response({
        "service": "Kyiv Alert Bot",
        "status": "running",
        "api": "available" if api_ok else "unavailable",
        "last_check": last_check_time,
        "current_status": (
            current_status if api_ok
            else "NO_CURRENT_DATA"
        ),
    })


# =====================================================
# ЗАПУСК БОТА
# =====================================================

async def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не встановлено в Render Environment!"
        )

    logger.info("Запуск Kyiv Alert Bot")

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start_cmd)
    )

    app.add_handler(
        CommandHandler("status", status_cmd)
    )

    app.add_handler(
        CommandHandler("test", test_cmd)
    )

    # Веб-сервер Render
    web_app = web.Application()

    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/health", health_check)

    runner = web.AppRunner(web_app)

    await runner.setup()

    port = int(os.environ.get("PORT", 10000))

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port,
    )

    await site.start()

    logger.info(f"Веб-сервер запущено на порту {port}")

    await app.initialize()
    await app.start()

    # Telegram polling
    await app.updater.start_polling(
        drop_pending_updates=True
    )

    logger.info("Telegram бот запущено")

    # Запуск моніторингу
    monitor_task = asyncio.create_task(
        alert_loop(app)
    )

    try:
        await asyncio.Event().wait()

    finally:

        logger.info("Зупинка бота")

        monitor_task.cancel()

        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        await app.updater.stop()
        await app.stop()
        await app.shutdown()

        await runner.cleanup()


# =====================================================
# ГОЛОВНИЙ ЗАПУСК
# =====================================================

if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info("Бот зупинено вручну")
