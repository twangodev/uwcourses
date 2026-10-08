"""SQLAlchemy connections with the pipeline's existing row/transaction interface.

Core statements and remaining SQLite-specific SQL share one connection. Keeping
value iteration and named access preserves content hashes and archive readers.
"""

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool


class Row:
    def __init__(self, row):
        self.row = row

    def keys(self):
        return self.row._mapping.keys()

    def __getitem__(self, key):
        return self.row._mapping[key] if isinstance(key, str) else self.row[key]

    def __iter__(self):
        return iter(self.row)

    def __len__(self):
        return len(self.row)


class Cursor:
    def __init__(self, result):
        self.result = result

    def fetchone(self):
        row = self.result.fetchone()
        return None if row is None else Row(row)

    def fetchall(self):
        return [Row(row) for row in self.result.fetchall()]

    def fetchmany(self, size=1):
        return [Row(row) for row in self.result.fetchmany(size)]

    def __iter__(self):
        return (Row(row) for row in self.result)


class Database:
    def __init__(self, path, *, readonly=False, timeout=5, wal=False):
        path = Path(path).resolve()
        self.engine = create_engine(
            "sqlite+pysqlite://",
            creator=lambda: sqlite3.connect(
                path.as_uri() + ("?mode=ro" if readonly else "?mode=rwc"),
                uri=True,
                timeout=timeout,
            ),
            poolclass=NullPool,
        )
        self.connection = self.engine.connect()
        try:
            self.execute("PRAGMA foreign_keys=ON")
            if readonly:
                self.execute("PRAGMA query_only=ON")
            elif wal:
                self.execute("PRAGMA journal_mode=WAL")
            self.commit()
        except Exception:
            self.close()
            raise

    def execute(self, statement, parameters=None):
        try:
            if isinstance(statement, str):
                result = self.connection.exec_driver_sql(statement, parameters or ())
            else:
                result = self.connection.execute(statement, parameters)
        except DBAPIError as exc:
            # Existing callers intentionally catch SQLite errors, e.g. read-only writes.
            raise exc.orig from exc
        return Cursor(result)

    def executemany(self, statement, parameters):
        # SQLite accepted generators and treated empty batches as no-ops.
        parameters = list(parameters)
        if parameters:
            return self.execute(statement, parameters)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()
        self.engine.dispose()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.rollback() if exc_type else self.commit()
