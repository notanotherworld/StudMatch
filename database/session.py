from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from bot.config import settings

engine_kwargs = {"echo": False, "pool_pre_ping": True}
if not str(settings.DATABASE_URL).startswith("sqlite"):
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs,
)

from sqlalchemy import event
from datetime import datetime

if str(settings.DATABASE_URL).startswith("sqlite"):
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_connect(dbapi_connection, connection_record):
        def _date_trunc(part, val):
            if val is None:
                return None
            try:
                d = datetime.fromisoformat(str(val))
                return d.strftime("%Y-%m-%d 00:00:00")
            except Exception:
                return str(val)[:10]

        dbapi_connection.create_function("date_trunc", 2, _date_trunc)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)
async_session = AsyncSessionLocal


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """Dependency для FastAPI и хэндлеров бота."""
    async with AsyncSessionLocal() as session:
        yield session
