"""db.py - Conexiones a PostgreSQL: una para el agente y otra para el dueño."""
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import config

_pools = {}


def _pool(nombre: str, url: str) -> ConnectionPool:
    if nombre not in _pools:
        _pools[nombre] = ConnectionPool(url, min_size=1, max_size=8, open=True,
                                        kwargs={"autocommit": True, "row_factory": dict_row})
    return _pools[nombre]


@contextmanager
def agente():
    """Conexión como agente_decorer: lee catálogo y ejecuta las funciones de venta."""
    with _pool("agente", config.URL_AGENTE).connection() as conn:
        yield conn


@contextmanager
def dueno():
    """Conexión como dueno_decorer: reportes, abonos, entregas y mercancía."""
    with _pool("dueno", config.URL_DUENO).connection() as conn:
        yield conn


def cerrar():
    for p in _pools.values():
        p.close()
    _pools.clear()


def error_legible(e: psycopg.Error) -> dict:
    """Convierte un RAISE EXCEPTION de las funciones en algo que el LLM puede explicar."""
    diag = getattr(e, "diag", None)
    return {"error": (diag.message_primary if diag and diag.message_primary else str(e)).strip(),
            "tipo": (diag.message_hint if diag else None) or "error"}
