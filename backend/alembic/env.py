from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from sqlalchemy.ext.asyncio import AsyncEngine
from alembic import context
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import Base
from app.config import settings

# Import model registry so Alembic can detect all mapped tables
import app.models.registry  # noqa: F401

config = context.config


def _sync_url_from_settings() -> str:
    # Alembic runs over psycopg2, so normalize asyncpg URL/query params.
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
    return sync_url.replace("ssl=require", "sslmode=require")


config.set_main_option("sqlalchemy.url", _sync_url_from_settings())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine
    sync_url = _sync_url_from_settings()
    connectable = create_engine(sync_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
