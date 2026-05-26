"""Engine SQLAlchemy com PRAGMAs SQLite para concorrência (WAL)."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from app.logging import get_logger

logger = get_logger(__name__)

_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-64000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA busy_timeout=30000",
)


def _apply_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    for pragma in _SQLITE_PRAGMAS:
        cursor.execute(pragma)
    cursor.close()


def create_db_engine(sqlite_path: str, *, echo: bool = False) -> Engine:
    """Cria engine SQLite com WAL e cache ampliado (~64MB)."""
    engine = create_engine(
        f"sqlite:///{sqlite_path}",
        echo=echo,
        connect_args={"check_same_thread": False, "timeout": 30},
        pool_pre_ping=True,
    )
    event.listen(engine, "connect", _apply_sqlite_pragmas)
    logger.debug("sqlite_engine_created", path=sqlite_path, pragmas=list(_SQLITE_PRAGMAS))
    return engine
