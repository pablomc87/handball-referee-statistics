from logging.config import fileConfig
from pathlib import Path
import sys

# Make the project root importable so we can read config.DB_PATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import engine_from_config, pool
from sqlalchemy import event
from alembic import context
import config as app_config

alembic_config = context.config
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

# No SQLAlchemy models — migrations are written as raw SQL via op.execute()
target_metadata = None


def _db_url() -> str:
    db_path = (Path(__file__).parent.parent / app_config.DB_PATH).resolve()
    return f"sqlite:///{db_path}"


def _configure_sqlite(connectable):
    """Enable WAL mode on every new SQLite connection opened by Alembic."""
    @event.listens_for(connectable, "connect")
    def set_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = alembic_config.get_section(alembic_config.config_ini_section, {})
    cfg["sqlalchemy.url"] = _db_url()
    connectable = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    _configure_sqlite(connectable)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
