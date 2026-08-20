import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional
from aiogram import BaseMiddleware
from aiogram.types import Message


class MediaGroupMiddleware(BaseMiddleware):
    """
    Middleware для сбора сообщений одного альбома (media_group_id) в один список `album`.
    Задерживает обработку на latency секунд (0.5с), собирает все Message с одним media_group_id,
    и передает в handler аргумент `album: List[Message]`.
    Для обычных одиночных сообщений передает `album: None`.
    """
    def __init__(self, latency: float = 0.5):
        self.latency = latency
        self.media_groups: Dict[str, List[Message]] = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not event.media_group_id:
            data["album"] = None
            return await handler(event, data)

        mg_id = event.media_group_id
        if mg_id not in self.media_groups:
            self.media_groups[mg_id] = [event]
            await asyncio.sleep(self.latency)
            album_messages = self.media_groups.pop(mg_id, [event])
            data["album"] = album_messages
            return await handler(event, data)
        else:
            self.media_groups[mg_id].append(event)
            return None
