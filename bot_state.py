# bot_state.py

import os
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from collections import deque
import logging
from aiogram.fsm.state import State
from config import CONFIG

logger = logging.getLogger(__name__)
# Путь к файлу состояния относительно корня пакета (не зависит от CWD при запуске)
STATE_FILE = str(Path(__file__).resolve().parent / "data" / "state.json")
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)


def safe_parse_time(time_str: str) -> Optional[datetime]:
    """
    Безопасный парсер времени из строки.
    Возвращает None, если формат некорректен.
    """
    if not time_str:
        return None
    try:
        # Если уже datetime — возвращаем как есть
        if isinstance(time_str, datetime):
            return time_str
        # Иначе пробуем разобрать как ISO-строку
        return datetime.fromisoformat(time_str)
    except Exception as e:
        logger.warning(f"⚠️ Невозможно разобрать время: {time_str} ({e})")
        return None


class BotState:
    def __init__(self, use_queue: bool = True):
        """
        Args:
            use_queue: Использовать очередь для сохранения (по умолчанию True)
        """
        logger.info("🔧 Инициализация BotState")
        self.active_alarms: Dict[str, Dict] = {}
        self.user_states: Dict[int, Dict] = {}
        self._lock = asyncio.Lock()  # Асинхронная блокировка вместо RLock
        self.extension_queue: Dict[int, deque] = {}  # {user_id: deque(alarm_ids)}
        self.user_processing: set = set()
        self.active_maintenances: Dict[str, Dict] = {}
        # Работы из Confluence: work_id -> {status, description, start_time_str, end_time_str, ...} для детекции новых и кнопок Информировать/Пропустить
        self.known_maintenances_from_confluence: Dict[str, Dict] = {}

        # Очередь для асинхронного сохранения
        self._use_queue = use_queue
        self._save_queue = None
        if use_queue:
            from utils.state_queue import StateSaveQueue
            self._save_queue = StateSaveQueue(self._save_state_sync, save_interval=2.0)

    def get_user_active_alarms(self, user_id: int) -> dict:
        """Все сбои для админа/суперадмина, иначе только созданные пользователем."""
        admin_ids = CONFIG.get("TELEGRAM", {}).get("ADMIN_IDS", [])
        superadmin_ids = CONFIG.get("TELEGRAM", {}).get("SUPERADMIN_IDS", [])
        if user_id in admin_ids or user_id in superadmin_ids:
            return dict(self.active_alarms)
        return {
            aid: alarm for aid, alarm in self.active_alarms.items()
            if alarm.get("user_id") == user_id
        }

    def get_user_active_maintenances(self, user_id: int) -> dict:
        """Все работы для админа/суперадмина, иначе только созданные пользователем."""
        admin_ids = CONFIG.get("TELEGRAM", {}).get("ADMIN_IDS", [])
        superadmin_ids = CONFIG.get("TELEGRAM", {}).get("SUPERADMIN_IDS", [])
        if user_id in admin_ids or user_id in superadmin_ids:
            return dict(self.active_maintenances)
        return {
            wid: work for wid, work in self.active_maintenances.items()
            if work.get("user_id") == user_id
        }

    def _save_to_file(self, state: dict):
        """
        Атомарное сохранение состояния в файл через временный файл.
        Это предотвращает потерю данных при сбое во время записи.
        """
        temp_file = f"{STATE_FILE}.tmp"
        try:
            # Записываем во временный файл
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            # Атомарная замена через os.replace (работает на всех платформах)
            os.replace(temp_file, STATE_FILE)
            logger.debug("Состояние успешно сохранено атомарно")
        except Exception as e:
            # Удаляем временный файл при ошибке
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception as rm_err:
                    logger.debug("Не удалось удалить временный файл при ошибке сохранения: %s", rm_err)
            logger.error(f"Ошибка при атомарном сохранении: {e}", exc_info=True)
            raise

    async def save_state(self):
        """Сохраняет текущее состояние бота в файл"""
        logger.info("💾 Начинаю сохранение состояния бота")

        state = {
            'active_alarms': {},
            'active_maintenances': {},
            'user_states': {},
            'known_maintenances_from_confluence': {},
        }

        async with self._lock:  # Используем async with для асинхронной блокировки
            # --- Сохранение аварий ---
            for alarm_id, alarm in self.active_alarms.items():
                logger.debug(f"💾 Сохраняю аварию: {alarm_id}")
                fix_time = alarm['fix_time']
                created_at = alarm.get('created_at')

                # Проверяем тип перед isoformat
                state['active_alarms'][alarm_id] = {
                    'issue': alarm['issue'],
                    'fix_time': fix_time.isoformat() if isinstance(fix_time, datetime) else fix_time,
                    'user_id': alarm['user_id'],
                    'created_at': created_at.isoformat() if isinstance(created_at, datetime) else created_at,
                    'jira_key': alarm.get('jira_key'),  # Новое поле: ключ задачи в Jira или None
                    'has_jira': alarm.get('has_jira', False),  # Новое поле: есть ли задача в Jira (по умолчанию False для обратной совместимости)
                    'reminder_sent_for': alarm.get('reminder_sent_for'),  # Новое поле: время, для которого было отправлено напоминание
                    'last_status_check': alarm.get('last_status_check'),  # Новое поле: время последней проверки статуса в Jira
                    'scm_topic_id': alarm.get('scm_topic_id'),  # Новое поле: ID темы в SCM канале или None
                    'max_chat_id': alarm.get('max_chat_id'),  # Чат MAX для обсуждения сбоя (FA-XXXX), архивация при закрытии
                    # Дополнительные поля (опционально)
                    'service': alarm.get('service'),
                    'description': alarm.get('description'),
                    'petlocal_post_id': alarm.get('petlocal_post_id'),
                    'petlocal_object_id': alarm.get('petlocal_object_id'),
                    'publish_petlocal': alarm.get('publish_petlocal', False),
                }

            # --- Сохранение регламентных работ ---
            for work_id, work in self.active_maintenances.items():
                logger.debug(f"💾 Сохраняю работу: {work_id}")
                start_time = work['start_time']
                end_time = work['end_time']
                created_at = work['created_at']

                state['active_maintenances'][work_id] = {
                    'description': work['description'],
                    'start_time': start_time.isoformat() if isinstance(start_time, datetime) else start_time,
                    'end_time': end_time.isoformat() if isinstance(end_time, datetime) else end_time,
                    'unavailable_services': work.get('unavailable_services', 'не указано'),
                    'user_id': work.get('user_id'),
                    'created_at': created_at.isoformat() if isinstance(created_at, datetime) else created_at,
                    'reminder_sent_for': work.get('reminder_sent_for'),  # Новое поле: время, для которого было отправлено напоминание
                    # Дополнительные поля (опционально)
                    'petlocal_post_id': work.get('petlocal_post_id'),
                    'petlocal_object_id': work.get('petlocal_object_id'),
                    'publish_petlocal': work.get('publish_petlocal', False),
                }

            # --- Сохранение известных работ из Confluence ---
            for work_id, work in self.known_maintenances_from_confluence.items():
                start_time = work.get("start_time")
                end_time = work.get("end_time")
                state['known_maintenances_from_confluence'][work_id] = {
                    **{k: v for k, v in work.items() if k not in ("start_time", "end_time")},
                    "start_time": start_time.isoformat() if isinstance(start_time, datetime) else start_time,
                    "end_time": end_time.isoformat() if isinstance(end_time, datetime) else end_time,
                }

            # --- Сохранение пользовательских состояний ---
            for user_id, user_state in self.user_states.items():
                logger.debug(f"💾 Сохраняю состояние пользователя: {user_id}")
                # Сохраняем все поля user_state для полноты
                saved_state = {
                    'state': user_state.get('state').name if isinstance(user_state.get('state'), State) else user_state.get('state'),
                    'alarm_id': user_state.get('alarm_id'),
                    'issue': user_state.get('issue'),
                    'type': user_state.get('type'),  # Для напоминаний: "reminder" или "maintenance_reminder"
                    'work_id': user_state.get('work_id'),  # Для напоминаний о работах
                    'chat_id': user_state.get('chat_id'),  # ID чата для напоминаний
                    'message_id': user_state.get('message_id')  # ID сообщения для напоминаний
                }
                # Удаляем None значения для чистоты
                saved_state = {k: v for k, v in saved_state.items() if v is not None}
                state['user_states'][str(user_id)] = saved_state

        # Используем очередь для сохранения, если включена
        if self._use_queue and self._save_queue:
            # Добавляем в очередь (не блокируем)
            await self._save_queue.enqueue(state)
            logger.debug("Состояние добавлено в очередь сохранения")
        else:
            # Синхронное сохранение (старый способ)
            try:
                await asyncio.to_thread(self._save_to_file, state)
                logger.info("✅ Состояние успешно сохранено")
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения состояния: {str(e)}", exc_info=True)
    
    async def _save_state_sync(self, state: dict):
        """Синхронная функция сохранения для очереди"""
        try:
            await asyncio.to_thread(self._save_to_file, state)
            logger.info("✅ Состояние успешно сохранено через очередь")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения состояния: {str(e)}", exc_info=True)
    
    async def start_save_queue(self):
        """Запускает очередь сохранения"""
        if self._save_queue:
            await self._save_queue.start()
    
    async def stop_save_queue(self):
        """Останавливает очередь сохранения и сохраняет оставшиеся данные"""
        if self._save_queue:
            await self._save_queue.stop()

    async def load_state(self):
        """Загружает состояние бота из файла"""
        logger.info("📂 Загружаю состояние из файла...")
        
        # Загружаем данные из файла с обработкой всех ошибок
        try:
            def _load_json():
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            
            data = await asyncio.to_thread(_load_json)
            logger.info("✅ Файл состояния загружен")
            
        except FileNotFoundError:
            # BUG #2 FIX: Файл не найден - используем пустое состояние
            logger.info("🆕 Файл состояния не найден. Создание нового состояния")
            data = {
                'active_alarms': {},
                'active_maintenances': {},
                'user_states': {},
                'known_maintenances_from_confluence': {},
            }

        except json.JSONDecodeError as je:
            # BUG #2 FIX: Обработка поврежденного JSON файла
            logger.warning(f"⚠️ Файл состояния поврежден: {je}")
            logger.info("🔄 Создаю резервную копию и новое состояние")
            
            # Создаем резервную копию поврежденного файла
            try:
                from datetime import datetime
                backup_path = f"{STATE_FILE}.corrupted.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                if os.path.exists(STATE_FILE):
                    os.rename(STATE_FILE, backup_path)
                    logger.info(f"📦 Резервная копия создана: {backup_path}")
            except Exception as backup_error:
                logger.error(f"❌ Не удалось создать резервную копию: {backup_error}")
            
            # Используем пустое состояние
            data = {
                'active_alarms': {},
                'active_maintenances': {},
                'user_states': {},
                'known_maintenances_from_confluence': {},
            }
            logger.info("🆕 Используется новое пустое состояние")

        except Exception as e:
            # BUG #2 FIX: Обработка всех остальных ошибок
            logger.critical(f"❌ Критическая ошибка при загрузке состояния: {str(e)}", exc_info=True)
            data = {
                'active_alarms': {},
                'active_maintenances': {},
                'user_states': {},
                'known_maintenances_from_confluence': {},
            }

        # Загружаем данные из data (может быть пустым при ошибках)
        try:
            async with self._lock:
                self.active_alarms.clear()
                self.active_maintenances.clear()
                self.user_states.clear()
                self.known_maintenances_from_confluence.clear()

            # --- Загрузка аварий ---
            for alarm_id, alarm_data in data.get("active_alarms", {}).items():
                try:
                    fix_time = safe_parse_time(alarm_data.get("fix_time"))
                    created_at = safe_parse_time(alarm_data.get("created_at"))

                    if not all([fix_time, created_at]):
                        logger.warning(f"⚠️ Пропущена авария {alarm_id}: некорректные данные времени")
                        continue

                    # Валидация обязательных полей
                    if "issue" not in alarm_data or "user_id" not in alarm_data:
                        logger.warning(f"⚠️ Пропущена авария {alarm_id}: отсутствуют обязательные поля")
                        continue

                    # Миграция данных: если есть старое поле "reminded", устанавливаем reminder_sent_for
                    reminder_sent_for = alarm_data.get("reminder_sent_for")
                    if reminder_sent_for is None and alarm_data.get("reminded", False):
                        # Миграция: если было reminded=True, устанавливаем reminder_sent_for на текущий fix_time
                        reminder_sent_for = fix_time.isoformat() if isinstance(fix_time, datetime) else fix_time
                        logger.debug(f"🔄 Миграция данных для {alarm_id}: reminded=True → reminder_sent_for={reminder_sent_for}")

                    self.active_alarms[alarm_id] = {
                        "issue": alarm_data["issue"],
                        "fix_time": fix_time,
                        "user_id": alarm_data["user_id"],
                        "created_at": created_at,
                        "jira_key": alarm_data.get("jira_key"),  # Новое поле: ключ задачи в Jira или None
                        "has_jira": alarm_data.get("has_jira", False),  # Новое поле: есть ли задача в Jira (по умолчанию False для обратной совместимости)
                        "reminder_sent_for": reminder_sent_for,  # Новое поле: время, для которого было отправлено напоминание
                        "last_status_check": alarm_data.get("last_status_check"),  # Новое поле: время последней проверки статуса в Jira
                        "scm_topic_id": alarm_data.get("scm_topic_id"),  # Новое поле: ID темы в SCM канале или None
                        "max_chat_id": alarm_data.get("max_chat_id"),  # Чат MAX для обсуждения сбоя (FA-XXXX)
                        # Дополнительные поля (опционально)
                        "service": alarm_data.get("service"),
                        "description": alarm_data.get("description"),
                        "petlocal_post_id": alarm_data.get("petlocal_post_id"),
                        "petlocal_object_id": alarm_data.get("petlocal_object_id"),
                        "publish_petlocal": alarm_data.get("publish_petlocal", False),
                    }
                    logger.debug(f"📥 Восстановлена авария: {alarm_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка при загрузке аварии {alarm_id}: {e}", exc_info=True)

            # --- Загрузка регламентных работ ---
            for work_id, work_data in data.get("active_maintenances", {}).items():
                try:
                    start_time = safe_parse_time(work_data.get("start_time"))
                    end_time = safe_parse_time(work_data.get("end_time"))
                    created_at = safe_parse_time(work_data.get("created_at"))

                    if not all([start_time, end_time, created_at]):
                        logger.warning(f"⚠️ Пропущена работа {work_id}: некорректные данные времени")
                        continue

                    # Валидация обязательных полей
                    if "description" not in work_data or "user_id" not in work_data:
                        logger.warning(f"⚠️ Пропущена работа {work_id}: отсутствуют обязательные поля")
                        continue

                    self.active_maintenances[work_id] = {
                        "description": work_data["description"],
                        "start_time": start_time,
                        "end_time": end_time,
                        "user_id": work_data["user_id"],
                        "created_at": created_at,
                        "unavailable_services": work_data.get("unavailable_services", "не указано"),
                        "reminder_sent_for": work_data.get("reminder_sent_for"),  # Новое поле: время, для которого было отправлено напоминание
                        # Дополнительные поля (опционально)
                        "petlocal_post_id": work_data.get("petlocal_post_id"),
                        "petlocal_object_id": work_data.get("petlocal_object_id"),
                        "publish_petlocal": work_data.get("publish_petlocal", False),
                    }
                    logger.debug(f"📥 Восстановлена работа: {work_id}")
                except Exception as e:
                    logger.error(f"❌ Ошибка при загрузке работы {work_id}: {e}", exc_info=True)

            # --- Загрузка пользовательских состояний ---
            for user_id_str, user_state in data.get("user_states", {}).items():
                try:
                    user_id = int(user_id_str)
                    state_name = user_state.get('state')
                    
                    # Для обратной совместимости: если нет state, но есть другие поля, создаем состояние
                    if not state_name and not user_state:
                        logger.warning(f"⚠️ Пропущено пустое состояние пользователя {user_id_str}")
                        continue

                    # Восстанавливаем все поля user_state
                    self.user_states[user_id] = {
                        'state': state_name,
                        'alarm_id': user_state.get('alarm_id'),
                        'issue': user_state.get('issue'),
                        'type': user_state.get('type'),  # Для напоминаний
                        'work_id': user_state.get('work_id'),  # Для напоминаний о работах
                        'chat_id': user_state.get('chat_id'),  # ID чата для напоминаний
                        'message_id': user_state.get('message_id')  # ID сообщения для напоминаний
                    }
                    # Удаляем None значения
                    self.user_states[user_id] = {k: v for k, v in self.user_states[user_id].items() if v is not None}
                except ValueError as ve:
                    logger.warning(f"⚠️ Ошибка при обработке состояния пользователя {user_id_str}: {ve}")
                except Exception as e:
                    logger.error(f"❌ Неожиданная ошибка: {e}", exc_info=True)

            # --- Загрузка известных работ из Confluence ---
            for work_id, work_data in data.get("known_maintenances_from_confluence", {}).items():
                try:
                    start_time = safe_parse_time(work_data.get("start_time"))
                    end_time = safe_parse_time(work_data.get("end_time"))
                    if start_time is None or end_time is None:
                        continue
                    self.known_maintenances_from_confluence[work_id] = {
                        "status": work_data.get("status", "pending_decision"),
                        "description": work_data.get("description", ""),
                        "start_time_str": work_data.get("start_time_str", ""),
                        "end_time_str": work_data.get("end_time_str", ""),
                        "unavailable_services": work_data.get("unavailable_services", "не указано"),
                        "notify": work_data.get("notify", ""),
                        "owner": work_data.get("owner", ""),
                        "start_time": start_time,
                        "end_time": end_time,
                    }
                except Exception as e:
                    logger.debug("Пропущена запись known_confluence %s: %s", work_id, e)

        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных состояния: {e}", exc_info=True)

# --- Глобальное состояние бота ---
bot_state = BotState()