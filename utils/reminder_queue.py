"""
Приоритетная очередь для напоминаний.
Оптимизирует проверку напоминаний, используя очередь вместо проверки всех событий каждую минуту.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ReminderType(Enum):
    """Тип напоминания"""
    ALARM = "alarm"
    MAINTENANCE = "maintenance"
    JIRA_STATUS = "jira_status"


@dataclass
class ReminderItem:
    """Элемент очереди напоминаний"""
    reminder_time: datetime
    item_id: str
    reminder_type: ReminderType
    data: Dict[str, Any] = field(default_factory=dict)
    
    def __lt__(self, other):
        """Для сортировки в приоритетной очереди (min-heap)"""
        return self.reminder_time < other.reminder_time


class ReminderPriorityQueue:
    """
    Приоритетная очередь для напоминаний.
    Использует heapq для эффективной работы с приоритетами.
    """
    
    def __init__(self):
        self._queue: list = []  # Min-heap для приоритетной очереди
        self._items: Dict[Tuple[str, ReminderType], ReminderItem] = {}  # Быстрый поиск
        self._lock = asyncio.Lock()
    
    async def add(
        self,
        item_id: str,
        reminder_time: datetime,
        reminder_type: ReminderType,
        data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Добавляет напоминание в очередь.
        
        Args:
            item_id: ID события (alarm_id, work_id и т.д.)
            reminder_time: Время напоминания
            reminder_type: Тип напоминания
            data: Дополнительные данные
        
        Returns:
            True если добавлено, False если уже существует
        """
        async with self._lock:
            key = (item_id, reminder_type)
            
            # Если уже есть, обновляем
            if key in self._items:
                old_item = self._items[key]
                # Удаляем старый элемент из кучи
                try:
                    self._queue.remove(old_item)
                except ValueError:
                    pass
                # Восстанавливаем структуру кучи
                import heapq
                heapq.heapify(self._queue)
            
            # Создаем новый элемент
            item = ReminderItem(
                reminder_time=reminder_time,
                item_id=item_id,
                reminder_type=reminder_type,
                data=data or {}
            )
            
            # Добавляем в кучу
            import heapq
            heapq.heappush(self._queue, item)
            self._items[key] = item
            
            logger.debug(f"Добавлено напоминание: {item_id} ({reminder_type.value}) на {reminder_time}")
            return True
    
    async def remove(self, item_id: str, reminder_type: ReminderType) -> bool:
        """
        Удаляет напоминание из очереди.
        
        Args:
            item_id: ID события
            reminder_type: Тип напоминания
        
        Returns:
            True если удалено, False если не найдено
        """
        async with self._lock:
            key = (item_id, reminder_type)
            if key not in self._items:
                return False
            
            item = self._items[key]
            try:
                self._queue.remove(item)
            except ValueError:
                pass
            
            # Восстанавливаем структуру кучи
            import heapq
            heapq.heapify(self._queue)
            
            del self._items[key]
            logger.debug(f"Удалено напоминание: {item_id} ({reminder_type.value})")
            return True
    
    async def get_due_reminders(self, now: Optional[datetime] = None) -> list[ReminderItem]:
        """
        Получает все напоминания, которые должны быть отправлены сейчас.
        
        Args:
            now: Текущее время (по умолчанию datetime.now())
        
        Returns:
            Список элементов напоминаний, которые нужно отправить
        """
        if now is None:
            now = datetime.now()
        
        async with self._lock:
            due_items = []
            
            # Извлекаем все элементы, время которых наступило
            import heapq
            while self._queue and self._queue[0].reminder_time <= now:
                item = heapq.heappop(self._queue)
                key = (item.item_id, item.reminder_type)
                
                # Удаляем из индекса
                if key in self._items:
                    del self._items[key]
                
                due_items.append(item)
            
            return due_items
    
    async def get_next_reminder_time(self) -> Optional[datetime]:
        """
        Возвращает время следующего напоминания.
        
        Returns:
            Время следующего напоминания или None если очередь пуста
        """
        async with self._lock:
            if not self._queue:
                return None
            return self._queue[0].reminder_time
    
    async def size(self) -> int:
        """Возвращает количество элементов в очереди"""
        async with self._lock:
            return len(self._queue)
    
    async def clear(self):
        """Очищает очередь"""
        async with self._lock:
            self._queue.clear()
            self._items.clear()
            logger.debug("Очередь напоминаний очищена")

