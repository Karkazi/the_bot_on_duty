"""
Очередь для асинхронного сохранения состояния.
Позволяет не блокировать основной поток при сохранении.
"""
import asyncio
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class StateSaveQueue:
    """
    Очередь для сохранения состояния бота.
    Обеспечивает асинхронное сохранение без блокировки основного потока.
    """
    
    def __init__(self, save_function, save_interval: float = 2.0):
        """
        Args:
            save_function: Функция для сохранения состояния (async)
            save_interval: Минимальный интервал между сохранениями (секунды)
        """
        self._save_function = save_function
        self._save_interval = save_interval
        self._queue = asyncio.Queue(maxsize=1)  # Только последнее состояние
        self._last_save_time: Optional[datetime] = None
        self._save_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def start(self):
        """Запускает фоновую задачу сохранения"""
        if self._running:
            return
        
        self._running = True
        self._save_task = asyncio.create_task(self._save_worker())
        logger.info("Очередь сохранения состояния запущена")
    
    async def stop(self):
        """Останавливает фоновую задачу и сохраняет оставшиеся данные"""
        if not self._running:
            return
        
        self._running = False
        
        # Сохраняем последнее состояние перед остановкой
        if not self._queue.empty():
            try:
                state = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._save_function(state)
            except (asyncio.TimeoutError, asyncio.QueueEmpty):
                pass
        
        if self._save_task:
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Очередь сохранения состояния остановлена")
    
    async def enqueue(self, state: dict) -> bool:
        """
        Добавляет состояние в очередь для сохранения.
        
        Args:
            state: Состояние для сохранения
        
        Returns:
            True если добавлено, False если очередь переполнена
        """
        try:
            # Если очередь полна, заменяем элемент (сохраняем только последнее состояние)
            if self._queue.full():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            
            self._queue.put_nowait(state)
            return True
        except Exception as e:
            logger.error(f"Ошибка при добавлении в очередь сохранения: {e}")
            return False
    
    async def _save_worker(self):
        """Фоновая задача для сохранения состояния"""
        while self._running:
            try:
                # Ждем состояние с таймаутом
                try:
                    state = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Проверяем интервал между сохранениями
                now = datetime.now()
                if self._last_save_time:
                    time_since_last = (now - self._last_save_time).total_seconds()
                    if time_since_last < self._save_interval:
                        # Ждем до следующего разрешенного момента
                        await asyncio.sleep(self._save_interval - time_since_last)
                
                # Сохраняем
                try:
                    await self._save_function(state)
                    self._last_save_time = datetime.now()
                    logger.debug("Состояние сохранено через очередь")
                except Exception as e:
                    logger.error(f"Ошибка сохранения состояния: {e}", exc_info=True)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в worker сохранения: {e}", exc_info=True)
                await asyncio.sleep(1)  # Небольшая задержка при ошибке

