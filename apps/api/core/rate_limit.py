import sqlite3
import time
from pathlib import Path


class SQLiteRateLimiter:
    def __init__(self, db_path: str, limit_per_minute: int) -> None:
        if limit_per_minute <= 0:
            raise ValueError("limit_per_minute must be > 0")
        self.db_path = db_path
        self.limit_per_minute = limit_per_minute
        self.window_seconds = 60
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        path = Path(self.db_path)
        if path.parent and str(path.parent) not in ("", "."):
            path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rate_limit_counters (
                    identity TEXT NOT NULL,
                    window INTEGER NOT NULL,
                    count INTEGER NOT NULL,
                    PRIMARY KEY(identity, window)
                )
                """
            )
            conn.commit()

    def allow(self, identity: str) -> bool:
        now = int(time.time())
        window = now // self.window_seconds
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM rate_limit_counters WHERE window < ?",
                (window - 2,),
            )
            row = conn.execute(
                "SELECT count FROM rate_limit_counters WHERE identity = ? AND window = ?",
                (identity, window),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO rate_limit_counters(identity, window, count) VALUES(?, ?, 1)",
                    (identity, window),
                )
                conn.commit()
                return True

            new_count = int(row[0]) + 1
            conn.execute(
                "UPDATE rate_limit_counters SET count = ? WHERE identity = ? AND window = ?",
                (new_count, identity, window),
            )
            conn.commit()
            return new_count <= self.limit_per_minute
