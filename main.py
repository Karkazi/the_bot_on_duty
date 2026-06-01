import asyncio
import logging
import os
import sys

import utils.paths_bootstrap  # noqa: F401

from bot_state import STATE_FILE, bot_state
from config import CONFIG
from services.reminder_worker import check_reminders
from services.confluence_calendar_worker import check_confluence_maintenances
from services.calendar_digest_worker import run_calendar_digest_scheduler
from utils.app_paths import APP_DATA_DIR, BOT_LOG_FILE

SIMPLEONE_TOKEN_REFRESH_MINUTES = 100

logger = logging.getLogger(__name__)


def setup_logging():
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_format = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    file_handler = logging.FileHandler(BOT_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))
    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[file_handler, console_handler],
    )
    logging.getLogger().setLevel(log_level)


setup_logging()
logger = logging.getLogger(__name__)
logger.info("📁 Каталог данных: %s", APP_DATA_DIR)
logger.info("📄 state.json: %s", STATE_FILE)
logger.info("📋 Лог-файл: %s", BOT_LOG_FILE)

_lock_fd = None


async def main():
    global _lock_fd
    build_id = os.getenv("BUILD_ID", "unknown")
    logger.info("🚀 Запуск бота (MAX), сборка BUILD_ID=%s", build_id)

    lock_file = "/tmp/bot.lock"
    try:
        import fcntl

        _lock_fd = open(lock_file, "w")
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _lock_fd.close()
            _lock_fd = None
            logger.critical("❌ Бот уже запущен!")
            sys.exit(1)
    except ImportError:
        logger.warning("⚠️ Не удалось проверить дублирование запуска — возможно, это Windows")

    await bot_state.load_state()
    logger.info("📂 Состояние загружено")

    from services.state_cleanup import prune_stale_state

    if prune_stale_state(bot_state):
        await bot_state.save_state()

    if CONFIG.get("SIMPLEONE", {}).get("USERNAME") and CONFIG.get("SIMPLEONE", {}).get("PASSWORD"):
        try:
            from services.simpleone_service import SimpleOneService

            async with SimpleOneService() as svc:
                if await svc._refresh_token_if_configured(save_to_env=True):
                    logger.info("✅ Токен SimpleOne обновлён при запуске")
        except Exception as e:
            logger.warning("При запуске не удалось обновить токен SimpleOne: %s", e)

    await bot_state.start_save_queue()
    logger.info("✅ Очередь сохранения состояния запущена")

    async def refresh_simpleone_token_task():
        while True:
            await asyncio.sleep(SIMPLEONE_TOKEN_REFRESH_MINUTES * 60)
            try:
                simpleone = CONFIG.get("SIMPLEONE", {})
                if not simpleone.get("USERNAME") or not simpleone.get("PASSWORD"):
                    continue
                from services.simpleone_service import SimpleOneService

                async with SimpleOneService() as svc:
                    await svc._refresh_token_if_configured(save_to_env=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Фоновая задача обновления токена SimpleOne: %s", e)

    max_task = None
    refresh_task = None
    confluence_task = None
    digest_task = None
    reminders_task = None

    try:
        logger.info("🤖 Бот начал работу")
        reminders_task = asyncio.create_task(check_reminders())

        if CONFIG.get("MAX", {}).get("CALENDAR_ADMIN_IDS") and CONFIG.get("CONFLUENCE", {}).get("LOGIN_URL"):
            confluence_task = asyncio.create_task(check_confluence_maintenances())
            logger.info("Запущена проверка календаря Confluence каждые 10 с")
            if CONFIG.get("CALENDAR", {}).get("DIGEST_ENABLED", True):
                digest_task = asyncio.create_task(run_calendar_digest_scheduler())
                times = CONFIG.get("CALENDAR", {}).get("DIGEST_TIMES") or []
                logger.info(
                    "Запущена ежедневная сводка календаря (%s)",
                    ", ".join(f"{h:02d}:{m:02d}" for h, m in times),
                )

        if CONFIG.get("SIMPLEONE", {}).get("USERNAME") and CONFIG.get("SIMPLEONE", {}).get("PASSWORD"):
            refresh_task = asyncio.create_task(refresh_simpleone_token_task())
            logger.info(
                "✅ Запущено фоновое обновление токена SimpleOne каждые %s мин",
                SIMPLEONE_TOKEN_REFRESH_MINUTES,
            )

        if CONFIG.get("MAX", {}).get("MANAGEMENT_ENABLED") and CONFIG.get("MAX", {}).get("BOT_TOKEN"):
            from adapters.max import run_max_polling

            max_task = asyncio.create_task(run_max_polling())
            logger.info("✅ Запущен приём команд из MAX")

        if max_task is not None:
            await max_task
        else:
            await asyncio.Event().wait()
    finally:
        logger.info("🛑 Бот остановлен")
        if _lock_fd is not None:
            try:
                import fcntl

                fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            try:
                _lock_fd.close()
            except OSError:
                pass
            _lock_fd = None

        for task in (max_task, refresh_task, confluence_task, digest_task, reminders_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await bot_state.stop_save_queue()
        await bot_state.save_state()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Бот остановлен пользователем")
