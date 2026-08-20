"""Test fixtures, including a throwaway PostgreSQL cluster for the Task 3.1 SQL.

The SQL uses PostgreSQL-specific constructs — ``ILIKE``, ``DISTINCT ON``,
``LEFT JOIN LATERAL`` — so it cannot be tested against SQLite. Rather than
requiring a running server or Docker, this spins up a temporary cluster with
``initdb`` in a temp directory, listening on a Unix socket only (no TCP, so no
port collisions with anything the reviewer already has running).

If the PostgreSQL binaries are not on ``PATH`` the SQL tests skip with a clear
reason rather than failing, so ``uv run pytest`` stays green on a machine without
PostgreSQL. Everything else in the suite is pure Python and always runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_SQL = PROJECT_ROOT / "sql" / "schema.sql"
QUERY_DIR = PROJECT_ROOT / "sql" / "queries"

_REQUIRED_BINARIES = ("initdb", "pg_ctl")


def _missing_binaries() -> list[str]:
    return [b for b in _REQUIRED_BINARIES if shutil.which(b) is None]


@pytest.fixture(scope="session")
def pg_cluster() -> Iterator[str]:
    """Start a temporary PostgreSQL cluster; yield a psycopg connection string."""
    missing = _missing_binaries()
    if missing:
        pytest.skip(
            f"PostgreSQL binaries not found on PATH ({', '.join(missing)}). "
            f"Install PostgreSQL (e.g. `brew install postgresql@18`) to run the "
            f"Task 3.1 SQL tests."
        )
    pytest.importorskip("psycopg", reason="psycopg is required for the SQL tests")

    tmp = Path(tempfile.mkdtemp(prefix="samueli-pg-"))
    datadir, sockdir, logfile = tmp / "data", tmp / "sock", tmp / "pg.log"
    sockdir.mkdir()

    try:
        subprocess.run(
            ["initdb", "-D", str(datadir), "-U", "postgres", "--auth=trust", "--no-sync"],
            check=True,
            capture_output=True,
        )
        # fsync off and socket-only: this cluster is disposable, so durability is
        # wasted work, and skipping TCP avoids clashing with a real local server.
        subprocess.run(
            [
                "pg_ctl", "-D", str(datadir), "-l", str(logfile), "-w", "start",
                "-o", f"-k {sockdir} -h '' -c fsync=off -c full_page_writes=off",
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - environment issue
        detail = (exc.stderr or b"").decode(errors="replace")
        log = logfile.read_text(errors="replace") if logfile.exists() else ""
        shutil.rmtree(tmp, ignore_errors=True)
        pytest.skip(f"could not start a temporary PostgreSQL cluster: {detail}\n{log}")

    try:
        yield f"postgresql://postgres@/postgres?host={sockdir}"
    finally:
        subprocess.run(
            ["pg_ctl", "-D", str(datadir), "-m", "immediate", "stop"],
            capture_output=True,
            check=False,
        )
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def db(pg_cluster: str):
    """A connection with the schema applied, rolled back after each test.

    DDL is transactional in PostgreSQL, so creating the tables inside a
    transaction and rolling back gives each test a pristine database with no
    teardown cost and no cross-test leakage.
    """
    import psycopg

    with psycopg.connect(pg_cluster, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL.read_text())
        yield conn
        conn.rollback()


@pytest.fixture
def run_query(db):
    """Execute a numbered query file and return its rows as dicts."""
    import psycopg.rows

    def _run(query_stem: str) -> list[dict]:
        matches = sorted(QUERY_DIR.glob(f"{query_stem}*.sql"))
        assert matches, f"no query file matching {query_stem}*.sql in {QUERY_DIR}"
        assert len(matches) == 1, f"ambiguous query stem {query_stem}: {matches}"
        sql = matches[0].read_text()
        with db.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql)
            return cur.fetchall()

    return _run


@pytest.fixture
def seed(db):
    """Insert rows into a table. Keeps the test bodies about the query, not the plumbing."""

    def _seed(table: str, columns: str, rows: list[tuple]) -> None:
        if not rows:
            return
        placeholders = ", ".join(["%s"] * len(rows[0]))
        with db.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", rows
            )

    return _seed


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "sql: tests that need a PostgreSQL cluster")


# Keep the temporary cluster out of the developer's way if a run is interrupted.
os.environ.setdefault("PGCONNECT_TIMEOUT", "10")
