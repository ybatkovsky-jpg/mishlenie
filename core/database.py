"""Async database engine and session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    future=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """Yield an async database session."""
    async with async_session_factory() as session:
        yield session


async def create_tables() -> None:
    """Create all tables from models metadata."""
    from core.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    """Drop all tables (for development only)."""
    from core.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
