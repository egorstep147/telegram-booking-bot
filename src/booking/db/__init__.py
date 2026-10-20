from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from booking.config import settings

engine = create_async_engine(settings.database_url, pool_size=10, pool_pre_ping=True)
Session = async_sessionmaker(engine, expire_on_commit=False)

__all__ = ["AsyncSession", "Session", "engine"]
