import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

# Импорты из ваших модулей
from bot_state import BotState, bot_state  # Используем глобальный экземпляр из bot_state.py
from config import CONFIG
from domain.constants import (
    RATE_LIMIT_REQUESTS_PER_SECOND,
    RATE_LIMIT_WINDOW_SECONDS,
)

# Middleware
from middleware.error_handler import ErrorHandlerMiddleware
from middleware.rate_limiter import RateLimiterMiddleware
from middleware.dependency_injection import DependencyInjectionMiddleware
from handlers import (
    start_help,
    alarm_handlers,
    manage_handlers,
)
from handlers.current_events import router as current_events_router
from handlers.maintenance_spinners import router as maintenance_spinners_router
from handlers.manage.reminders import check_reminders

# Интервал перевыпуска токена SimpleOne (мин). Токен живёт ~120 мин — обновляем заранее.
SIMPLEONE_TOKEN_REFRESH_MINUTES = 100
# --- Настройка логирования ---
logger = logging.getLogger(__name__)

def setup_logging():
    """
    Настраивает логирование для бота.
    Уровень задаётся переменной окружения LOG_LEVEL (по умолчанию INFO).
    """
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_format = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"

    # Логирование в файл
    file_handler = logging.FileHandler("bot.log", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))

    # Логирование в консоль
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(log_format))

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[file_handler, console_handler]
    )
    logging.getLogger().setLevel(log_level)
    
    

setup_logging()  # Вызываем настройку логирования до всего
logger = logging.getLogger(__name__)


# Проверка наличия токена
if "TELEGRAM" not in CONFIG or "TOKEN" not in CONFIG["TELEGRAM"]:
    logger.critical("❌ Токен Telegram не найден в конфиге")
    sys.exit(1)

# Файловый дескриптор блокировки повторного запуска (только Unix); закрывается в main() в finally
_lock_fd = None


async def main():
    global _lock_fd
    logger.info("🚀 Запуск бота...")

    # Проверка дублирования запуска (только на Unix)
    lock_file = "/tmp/bot.lock"
    try:
        import fcntl
        _lock_fd = open(lock_file, 'w')
        try:
            fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            _lock_fd.close()
            _lock_fd = None
            logger.critical("❌ Бот уже запущен!")
            sys.exit(1)
    except ImportError:
        logger.warning("⚠️ Не удалось проверить дублирование запуска — возможно, это Windows")

    # Инициализация бота и диспетчера
    bot = Bot(token=CONFIG["TELEGRAM"]["TOKEN"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    await bot_state.load_state()
    logger.info("📂 Состояние загружено")

    # Обновление токена SimpleOne при старте (если заданы логин/пароль — после долгого простоя токен мог истечь)
    if CONFIG.get("SIMPLEONE", {}).get("USERNAME") and CONFIG.get("SIMPLEONE", {}).get("PASSWORD"):
        try:
            from services.simpleone_service import SimpleOneService
            async with SimpleOneService() as svc:
                if await svc._refresh_token_if_configured(save_to_env=True):
                    logger.info("✅ Токен SimpleOne обновлён при запуске")
                else:
                    logger.debug("Токен SimpleOne при запуске не обновлялся (уже актуален или ошибка)")
        except Exception as e:
            logger.warning("При запуске не удалось обновить токен SimpleOne: %s", e)

    # Запускаем очередь сохранения состояния
    await bot_state.start_save_queue()
    logger.info("✅ Очередь сохранения состояния запущена")

    # Регистрация middleware
    # Порядок важен: сначала error handler, потом rate limiter, потом DI
    dp.message.middleware(ErrorHandlerMiddleware())
    dp.callback_query.middleware(ErrorHandlerMiddleware())
    dp.message.middleware(RateLimiterMiddleware(max_requests=RATE_LIMIT_REQUESTS_PER_SECOND, time_window=RATE_LIMIT_WINDOW_SECONDS))
    dp.callback_query.middleware(RateLimiterMiddleware(max_requests=RATE_LIMIT_REQUESTS_PER_SECOND, time_window=RATE_LIMIT_WINDOW_SECONDS))
    dp.message.middleware(DependencyInjectionMiddleware(bot_state))
    dp.callback_query.middleware(DependencyInjectionMiddleware(bot_state))
    
    logger.info("✅ Middleware зарегистрированы")

    # Регистрация роутеров
    # Важно: maintenance_spinners_router должен быть зарегистрирован ДО manage_handlers.router
    # чтобы обработчики спиннеров имели приоритет
    dp.include_router(start_help.router)
    dp.include_router(alarm_handlers.router)
    dp.include_router(maintenance_spinners_router)  # Регистрируем раньше для приоритета
    dp.include_router(manage_handlers.router)
    dp.include_router(current_events_router)
    from handlers import bridge_scm_max
    dp.include_router(bridge_scm_max.router)

    # Установка команд
    from aiogram.types import BotCommand
    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="new_message", description="Создать сообщение"),
        BotCommand(command="manage", description="Управление событиями"),
        BotCommand(command="alarm_list", description="Список активных событий"),
    ]
    await bot.set_my_commands(commands)
    logger.info("✅ Команды установлены")

    async def refresh_simpleone_token_task():
        """Периодически обновляет токен SimpleOne по логину/паролю (если заданы в .env)."""
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

    # Запуск бота
    max_task = None
    refresh_task = None
    try:
        logger.info("🤖 Бот начал работу")
        asyncio.create_task(check_reminders(bot))
        if CONFIG.get("SIMPLEONE", {}).get("USERNAME") and CONFIG.get("SIMPLEONE", {}).get("PASSWORD"):
            refresh_task = asyncio.create_task(refresh_simpleone_token_task())
            logger.info("✅ Запущено фоновое обновление токена SimpleOne каждые %s мин", SIMPLEONE_TOKEN_REFRESH_MINUTES)
        if CONFIG.get("MAX", {}).get("MANAGEMENT_ENABLED") and CONFIG.get("MAX", {}).get("BOT_TOKEN"):
            from adapters.max import run_max_polling
            max_task = asyncio.create_task(run_max_polling(bot))
            logger.info("✅ Запущен приём команд из MAX (дублирование управления)")
        await dp.start_polling(bot)
    finally:
        logger.info("🛑 Бот остановлен")
        # Снимаем блокировку повторного запуска и закрываем файл (Unix)
        if _lock_fd is not None:
            try:
                import fcntl
                fcntl.flock(_lock_fd, fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            try:
                _lock_fd.close()
            except Exception:
                pass
            _lock_fd = None
        if max_task is not None and not max_task.done():
            max_task.cancel()
            try:
                await max_task
            except asyncio.CancelledError:
                pass
        if refresh_task is not None and not refresh_task.done():
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        # Останавливаем очередь и сохраняем последнее состояние
        await bot_state.stop_save_queue()
        # Дополнительное сохранение на всякий случай
        await bot_state.save_state()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("👋 Бот остановлен пользователем")