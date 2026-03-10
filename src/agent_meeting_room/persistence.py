from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        if self._schema_reset_required():
            self._backup_incompatible_database()

        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS rooms (
                    room_id TEXT PRIMARY KEY,
                    room_name TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_profiles (
                    profile_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    temperature REAL NOT NULL,
                    max_tokens INTEGER NOT NULL,
                    enable_thinking INTEGER NOT NULL,
                    is_default INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    sender_id TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    sender_role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    owner_name TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    approved INTEGER NOT NULL,
                    reviewer_name TEXT NOT NULL,
                    note TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _schema_reset_required(self) -> bool:
        if not self.db_path.exists():
            return False

        connection = sqlite3.connect(self.db_path)
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }

            # 旧版本使用 room_meta 和不带 room_id 的单会议室表结构，当前版本无法直接兼容。
            if "room_meta" in tables and "rooms" not in tables:
                return True

            required_columns = {
                "rooms": {"room_id", "room_name", "goal", "phase", "status", "created_at", "updated_at"},
                "messages": {"room_id", "sender_id", "sender_name", "sender_role", "content", "kind", "created_at"},
                "tasks": {"room_id", "task_id", "title", "description", "owner_id", "owner_name", "acceptance_criteria", "status", "created_at", "updated_at"},
                "decisions": {"room_id", "approved", "reviewer_name", "note", "created_at"},
                "memories": {"room_id", "title", "content", "tags", "source", "created_at", "updated_at"},
            }

            for table_name, expected_columns in required_columns.items():
                if table_name not in tables:
                    continue
                actual_columns = {
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
                }
                if not expected_columns.issubset(actual_columns):
                    return True
            return False
        finally:
            connection.close()

    def _backup_incompatible_database(self) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = self.db_path.with_name(f"{self.db_path.stem}.legacy-{timestamp}{self.db_path.suffix}")
        self.db_path.replace(backup_path)

    def get_meta(self, key: str, default: str = "") -> str:
        return default

    def set_meta(self, key: str, value: str) -> None:
        _ = (key, value)

    def insert_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        keys = list(rows[0].keys())
        columns = ", ".join(keys)
        placeholders = ", ".join("?" for _ in keys)
        values = [tuple(row[key] for key in keys) for row in rows]
        with self.connect() as connection:
            connection.executemany(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                values,
            )

    def query_all(self, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return connection.execute(query, params).fetchall()

    def query_one(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(query, params).fetchone()

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        with self.connect() as connection:
            connection.execute(query, params)

    def export_state(self) -> dict[str, Any]:
        with self.connect() as connection:
            tables = [
                "rooms",
                "llm_profiles",
                "messages",
                "tasks",
                "decisions",
                "memories",
            ]
            data: dict[str, Any] = {}
            for table in tables:
                rows = connection.execute(f"SELECT * FROM {table}").fetchall()
                data[table] = [dict(row) for row in rows]
            return data


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def pretty_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)