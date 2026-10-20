"""Telegram без сети: сессия aiogram запоминает запросы и возвращает правдоподобные ответы."""

import itertools
from datetime import UTC, datetime

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import EditMessageReplyMarkup, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import Chat
from aiogram.types import Message as TgMessage


class FakeSession(BaseSession):
    """Сессия aiogram без сети: запоминает запросы к Telegram и возвращает правдоподобные ответы."""

    def __init__(self):
        super().__init__()
        self.requests: list[TelegramMethod] = []
        self.ids = itertools.count(1000)

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout=None):  # noqa: ASYNC109 — сигнатура aiogram
        self.requests.append(method)
        if isinstance(method, SendMessage | EditMessageText):
            chat_id = getattr(method, "chat_id", None) or 1
            msg = TgMessage(
                message_id=getattr(method, "message_id", None) or next(self.ids),
                date=datetime.now(UTC),
                chat=Chat(id=chat_id, type="private"),
                text=method.text,
            )
            return msg.as_(bot)
        if isinstance(method, EditMessageReplyMarkup):
            return True
        if method.__returning__ is bool:
            return True
        if method.__class__.__name__ == "CreateInvoiceLink":
            return "https://t.me/$invoice"
        return True

    async def close(self):
        pass

    async def stream_content(self, *a, **kw):
        yield b""

    def texts(self) -> list[str]:
        return [m.text for m in self.requests if isinstance(m, SendMessage | EditMessageText)]
