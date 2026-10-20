"""Приложение: FastAPI (API, мини-приложение, вебхук) + бот + фоновые задачи в одном процессе."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.types import MenuButtonDefault, MenuButtonWebApp, Update, WebAppInfo
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from booking.api.routes import router
from booking.bot import COMMANDS, create_bot, create_dispatcher, jobs
from booking.config import settings
from booking.db import engine
from booking.niche import niche
from booking.services.schedule import BookingError

log = logging.getLogger(__name__)
WEBHOOK_PATH = "/tg/webhook"
_tasks: set[asyncio.Task] = set()


async def setup_telegram(bot: Bot, dp: Dispatcher) -> asyncio.Task | None:
    if not settings.webhook_url and not settings.polling:
        return None
    await bot.set_my_commands(COMMANDS)
    await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(text="Записаться", web_app=WebAppInfo(url=settings.webapp_url))
        if settings.webapp_url
        else MenuButtonDefault()
    )
    if settings.webhook_url:
        if not settings.webhook_secret.get_secret_value():
            raise RuntimeError("Для вебхука задайте WEBHOOK_SECRET")
        await bot.set_webhook(
            settings.webhook_url.rstrip("/") + WEBHOOK_PATH,
            secret_token=settings.webhook_secret.get_secret_value(),
            allowed_updates=dp.resolve_used_update_types(),
        )
        return None
    await bot.delete_webhook()
    return asyncio.create_task(dp.start_polling(bot, handle_signals=False))


def create_app(bot: Bot | None = None, dp: Dispatcher | None = None) -> FastAPI:
    # Бот и диспетчер можно передать готовые (тесты); роутеры aiogram подключаются к диспетчеру один раз
    bot, dp = bot or create_bot(), dp or create_dispatcher()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.bot = bot
        tasks = [asyncio.create_task(jobs.loop(bot))]
        if polling := await setup_telegram(bot, dp):
            tasks.append(polling)
        log.info("Запись «%s» запущена", niche().name)
        yield
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        await bot.session.close()
        await engine.dispose()

    app = FastAPI(
        title=f"{niche().name} API",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.include_router(router)

    @app.exception_handler(BookingError)
    async def booking_error(request: Request, exc: BookingError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.post(WEBHOOK_PATH, include_in_schema=False)
    async def webhook(request: Request, x_telegram_bot_api_secret_token: str = Header("")) -> dict:
        if x_telegram_bot_api_secret_token != settings.webhook_secret.get_secret_value():
            raise HTTPException(403)
        task = asyncio.create_task(
            dp.feed_update(bot, Update.model_validate(await request.json(), context={"bot": bot}))
        )
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return {"ok": True}

    @app.get("/health", include_in_schema=False)
    async def health() -> dict:
        return {"ok": True, "niche": settings.niche}

    if (settings.webapp_dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=settings.webapp_dist, html=True), name="webapp")
    else:

        @app.get("/", include_in_schema=False)
        async def no_webapp() -> HTMLResponse:
            return HTMLResponse("Мини-приложение не собрано: cd webapp && npm ci && npm run build")

    return app
