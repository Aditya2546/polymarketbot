"""
Async database connection management.

Supports both PostgreSQL (production) and SQLite (development/testing).
"""

import asyncio
import logging
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    AsyncEngine,
    async_sessionmaker
)
from sqlalchemy.pool import NullPool

from .models import Base
from ..config import get_settings

logger = logging.getLogger(__name__)


class Database:
    """
    Async database manager.
    
    Provides connection pooling and session management for
    SQLAlchemy async operations.
    """
    
    def __init__(self, url: Optional[str] = None):
        """
        Initialize database manager.
        
        Args:
            url: Database URL. If None, uses config setting.
        """
        self._url = url or get_settings().database_url
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """
        Initialize database connection and create tables.
        """
        if self._initialized:
            return
        
        logger.info(f"Initializing database: {self._url.split('@')[-1] if '@' in self._url else self._url}")
        
        # Configure engine based on database type
        if "sqlite" in self._url:
            # SQLite: use NullPool for async compatibility
            self._engine = create_async_engine(
                self._url,
                poolclass=NullPool,
                echo=False
            )
        else:
            # PostgreSQL: use connection pooling
            self._engine = create_async_engine(
                self._url,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                echo=False
            )
        
        # Create session factory
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False
        )
        
        # Create tables
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        self._initialized = True
        logger.info("Database initialized successfully")
    
    async def close(self) -> None:
        """Close database connection."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
            self._initialized = False
            logger.info("Database connection closed")
    
    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Get a database session.
        
        Usage:
            async with db.session() as session:
                result = await session.execute(query)
        """
        if not self._initialized:
            await self.initialize()
        
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    @property
    def engine(self) -> AsyncEngine:
        """Get the SQLAlchemy engine."""
        if not self._engine:
            raise RuntimeError("Database not initialized")
        return self._engine
    
    @property
    def is_initialized(self) -> bool:
        """Check if database is initialized."""
        return self._initialized


# Global database instance
_database: Optional[Database] = None


def get_database() -> Database:
    """Get or create the global database instance."""
    global _database
    if _database is None:
        _database = Database()
    return _database


async def init_database() -> Database:
    """Initialize and return the database."""
    db = get_database()
    await db.initialize()
    return db

