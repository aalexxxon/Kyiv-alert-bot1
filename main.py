    raise RuntimeError("CHANNEL_ID missing")

logger.info(">>> BOT OK — token and channel loaded")

# ===================== STATE =====================
last_state = None
status_cache = "CLEAR"
last_check = None

alert_start = None
alert_msg_id = None
timer_running = False
manual_override = None  # True/False для ручного управления, None = авто


def now():
    return datetime.now(KYIV_TZ).strftime("%H:%M:%S")


# ===================== FAKE API =====================
async def fake_api_state():
    """Эмулируем ответ API: случайно включаем/выключаем тревогу, если нет ручного override"""
    if manual_override is not None:
        alert = manual_override
    else:
        alert = random.choice([True, False])
    return [
        {
            "regionId": REGION_ID,
            "alert": alert
        }
    ]


def is_alert(data):
    try:
        for region in data:
            if int(region.get("regionId")) == REGION_ID:
                return bool(region.get("alert"))
        return False
    except Exception as e:
        logger.error("[PARSER ERROR] %s", e)
        return False


# ===================== FAST ALERT LOOP =====================
async def alert_loop(app: Application):
    global last_state, status_cache, last_check
    global alert_start, alert_msg_id, timer_running

    logger.info("[FAST] Alert loop started (FAKE API)")

    while True:
        try:
            last_check = now()
            data = await fake_api_state()
            active = is_alert(data)
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
                        logger.info("[FAST] ALERT START — message_id=%s", alert_msg_id)
                    except TelegramError as e:
                        logger.error("[FAST] Failed to send ALERT START message: %s", e)

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
                        logger.error("[FAST] Failed to send ALERT END message: %s", e)

                last_state = active

        except Exception as e:
            logger.error("[FAST ERROR] %s", e)

        await asyncio.sleep(5)


# ===================== TIMER =====================
async def timer_loop(app: Application):
    global alert_msg_id, alert_start, timer_running

    logger.info("[TIMER] Timer loop started")

    while True:
        try:
            if timer_running and alert_msg_id and alert_start:
                delta = datetime.now(KYIV_TZ) - alert_start
                sec = int(delta.total_seconds())
                h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60

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
        f"🟢 Bot RUNNING (FAKE TEST)\n"
        f"📡 Status: {status_cache}\n"
        f"⏰ Last check: {last_check}\n"
        f"⚙️ Manual override: {manual_override}"
    )


async def alert_on_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global manual_override
    manual_override = True
    await update.message.reply_text("🚨 Manual ALERT ON")


async def alert_off_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global manual_override
    manual_override = False
    await update.message.reply_text("🟢 Manual ALERT OFF")


async def alert_auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global manual_override
    manual_override = None
    await update.message.reply_text("🔄 ALERT AUTO MODE — random fake API")


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "status":
        await q.edit_message_text(f"📡 Status: {status_cache}")


# ===================== MAIN =====================
async def post_init(app: Application) -> None:
    logger.info("[INIT] Application ready — starting background tasks")
    asyncio.create_task(alert_loop(app))
    asyncio.create_task(timer_loop(app))


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
    app.add_handler(CommandHandler("alert_on", alert_on_cmd))
    app.add_handler(CommandHandler("alert_off", alert_off_cmd))
    app.add_handler(CommandHandler("alert_auto", alert_auto_cmd))
    app.add_handler(CallbackQueryHandler(button))

    logger.info("STEP 3 — starting polling")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
