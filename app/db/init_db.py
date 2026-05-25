"""Inicialização do banco de dados."""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base
from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)


def init_database() -> None:
    """Cria tabelas se não existirem e executa migrations."""
    settings = get_settings()

    db_path = Path(settings.sqlite_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        try:
            import importlib.util
            run_path = Path(__file__).resolve().parent.parent.parent / "migrations" / "sqlite" / "003_embedding_blob.py"
            if run_path.exists():
                spec = importlib.util.spec_from_file_location("migration_003", run_path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.run_migration(str(db_path))
        except Exception as e:
            logger.debug("migration_003_skipped", error=str(e))

    engine = create_engine(f"sqlite:///{settings.sqlite_path}", echo=False)
    Base.metadata.create_all(engine)

    logger.info("database_initialized", path=settings.sqlite_path)


def get_engine():
    """Retorna engine SQLAlchemy."""
    settings = get_settings()
    return create_engine(f"sqlite:///{settings.sqlite_path}", echo=False)


def get_session():
    """Retorna session factory."""
    engine = get_engine()
    return sessionmaker(bind=engine)()
