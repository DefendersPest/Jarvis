"""Database engine/session factory.

* Local / tests: SQLite (``sqlite:///jarvis.db``).
* Azure: Azure SQL Database with **passwordless** Microsoft Entra ID auth. The
  Function App's managed identity requests an access token and hands it to the
  ODBC driver - there is no SQL password anywhere.
  URL form: ``mssql+pyodbc://@<server>.database.windows.net/<db>?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes``
"""

from __future__ import annotations

import struct
from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from jarvis.db.models import Base

_SQL_COPT_SS_ACCESS_TOKEN = 1256  # msodbcsql pre-connect attribute for Entra tokens
_AZURE_SQL_SCOPE = "https://database.windows.net/.default"


def _attach_entra_token(engine: Engine) -> None:
    from azure.identity import DefaultAzureCredential

    credential = DefaultAzureCredential()

    @event.listens_for(engine, "do_connect")
    def _provide_token(dialect, conn_rec, cargs, cparams):  # pragma: no cover - needs Azure
        token = credential.get_token(_AZURE_SQL_SCOPE).token.encode("utf-16-le")
        token_struct = struct.pack(f"<I{len(token)}s", len(token), token)
        cparams["attrs_before"] = {_SQL_COPT_SS_ACCESS_TOKEN: token_struct}


@lru_cache(maxsize=4)
def get_engine(url: str) -> Engine:
    if url.startswith("mssql"):
        engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800, fast_executemany=True)
        if "UID=" not in url and "Authentication=" not in url:
            _attach_entra_token(engine)
        return engine
    return create_engine(url, future=True)


def init_db(url: str) -> Engine:
    """Create tables if missing. Production schema changes go through reviewed
    migration scripts (see db/schema.sql); create_all is for local/dev only."""
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(url: str) -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(url), expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
