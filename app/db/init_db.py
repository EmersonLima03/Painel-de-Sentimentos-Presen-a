"""Inicialização do banco de dados."""

from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.db.database import create_db_engine
from app.db.models import Base
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_engine = None
_SessionLocal = None


def init_database() -> None:
    """Cria tabelas se não existirem e executa migrations."""
    settings = get_settings()

    db_path = Path(settings.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        try:
            import importlib.util

            run_path = (
                Path(__file__).resolve().parent.parent.parent
                / "migrations"
                / "sqlite"
                / "003_embedding_blob.py"
            )
            if run_path.exists():
                spec = importlib.util.spec_from_file_location("migration_003", run_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.run_migration(str(db_path))
        except Exception as e:
            logger.debug("migration_003_skipped", error=str(e))

    engine = get_engine()
    Base.metadata.create_all(engine)

    logger.info("database_initialized", path=settings.sqlite_path)


def get_engine():
    """Retorna engine SQLAlchemy singleton com PRAGMAs WAL."""
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_db_engine(settings.sqlite_path, echo=False)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_session():
    """Retorna nova sessão SQLAlchemy."""
    if _SessionLocal is None:
        get_engine()
    return _SessionLocal()


def close_session(session) -> None:
    """Fecha sessão (sempre usar em endpoints que chamam get_session())."""
    if session is not None:
        session.close()
