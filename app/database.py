import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def _normalize_database_url(url: str) -> str:
    """Accepts the plain connection string a host like Neon/Render hands you as-is --
    no manual editing required to add the +psycopg driver suffix."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


database_url = _normalize_database_url(settings.database_url)

db_path = database_url.replace("sqlite:///", "")
if db_path.startswith("./"):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

engine = create_engine(
    database_url,
    connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
