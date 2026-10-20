from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from booking.config import settings

COMMANDS = [
    BotCommand(command="start", description="Записаться"),
    BotCommand(command="my", description="Мои записи"),
]


def storage() -> BaseStorage:
    if settings.redis_url:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)
    return MemoryStorage()


def create_bot() -> Bot:
    return Bot(settings.bot_token.get_secret_value())


def create_dispatcher() -> Dispatcher:
    from booking.bot import admin, handlers, payments

    dp = Dispatcher(storage=storage())
    # Админка раньше клиента: её рассылка ловит любое сообщение админа
    dp.include_routers(admin.router, payments.router, handlers.router)
    return dp
