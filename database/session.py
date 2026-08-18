from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from bot.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

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
