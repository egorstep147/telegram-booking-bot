"""Точка входа: `booking [run|migrate|seed]`."""

import argparse
import asyncio
import logging


def run() -> None:
    import uvicorn

    from booking.app import create_app
    from booking.config import settings

    uvicorn.run(create_app(), host=settings.host, port=settings.port, proxy_headers=True, log_level="info")


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    from booking.config import ROOT

    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


def seed() -> None:
    from booking.db import Session, engine
    from booking.services.seed import seed as load

    async def go() -> None:
        async with Session() as s, s.begin():
            counts = await load(s)
        await engine.dispose()
        print("Каталог загружен:", ", ".join(f"{k}: {v}" for k, v in counts.items()))

    asyncio.run(go())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="booking", description="Запись на услуги в Telegram")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "migrate", "seed"])
    {"run": run, "migrate": migrate, "seed": seed}[parser.parse_args().command]()
