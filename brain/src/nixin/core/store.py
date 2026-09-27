"""SQLite persistence: paired devices, tasks + steps, audit log, usage, memory.

Writes are tiny and infrequent, so a single connection guarded by a lock is plenty.
Nothing secret (API keys, private keys) is stored here.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model TEXT,
    public_key TEXT NOT NULL,
    paired_at REAL NOT NULL,
    last_seen REAL,
    revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    route TEXT,
    status TEXT NOT NULL,
    summary TEXT,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS steps_task ON steps(task_id);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    task_id TEXT,
    method TEXT NOT NULL,
    risk TEXT,
    origin TEXT,
    ok INTEGER,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS usage (
    day TEXT NOT NULL,
    candidate TEXT NOT NULL,
    requests INTEGER NOT NULL DEFAULT 0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, candidate)
);
CREATE TABLE IF NOT EXISTS contact_aliases (
    alias TEXT PRIMARY KEY,
    contact_name TEXT NOT NULL,
    number TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS app_aliases (
    alias TEXT PRIMARY KEY,
    package TEXT NOT NULL,
    label TEXT,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    task_id TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    # ------------------------------------------------------------------ helpers
    def _exec(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._db.execute(sql, args)

    def _all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        with self._lock:
            r = self._db.execute(sql, args).fetchone()
            return dict(r) if r else None

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ devices
    def add_device(self, device_id: str, name: str, model: str, public_key: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO devices(device_id,name,model,public_key,paired_at,last_seen,revoked) "
            "VALUES(?,?,?,?,?,?,0)",
            (device_id, name, model, public_key, time.time(), time.time()),
        )

    def get_device(self, device_id: str) -> dict | None:
        return self._one("SELECT * FROM devices WHERE device_id=? AND revoked=0", (device_id,))

    def list_devices(self) -> list[dict]:
        return self._all("SELECT device_id,name,model,paired_at,last_seen,revoked FROM devices ORDER BY paired_at DESC")

    def touch_device(self, device_id: str) -> None:
        self._exec("UPDATE devices SET last_seen=? WHERE device_id=?", (time.time(), device_id))

    def revoke_device(self, device_id: str) -> bool:
        return self._exec("UPDATE devices SET revoked=1 WHERE device_id=?", (device_id,)).rowcount > 0

    # ------------------------------------------------------------------ tasks
    def create_task(self, task_id: str, source: str, text: str) -> None:
        self._exec(
            "INSERT INTO tasks(task_id,created_at,source,text,status) VALUES(?,?,?,?,?)",
            (task_id, time.time(), source, text, "running"),
        )

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        self._exec(f"UPDATE tasks SET {cols} WHERE task_id=?", (*fields.values(), task_id))

    def finish_task(self, task_id: str, status: str, summary: str) -> None:
        self.update_task(task_id, status=status, summary=summary, finished_at=time.time())

    def add_step(self, task_id: str, kind: str, data: dict) -> None:
        self._exec(
            "INSERT INTO steps(task_id,ts,kind,data) VALUES(?,?,?,?)",
            (task_id, time.time(), kind, json.dumps(data, ensure_ascii=False, default=str)),
        )

    def list_tasks(self, limit: int = 50) -> list[dict]:
        return self._all("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,))

    def get_task(self, task_id: str) -> dict | None:
        t = self._one("SELECT * FROM tasks WHERE task_id=?", (task_id,))
        if t:
            t["steps"] = [
                {**s, "data": json.loads(s["data"])}
                for s in self._all("SELECT ts,kind,data FROM steps WHERE task_id=? ORDER BY id", (task_id,))
            ]
        return t

    # ------------------------------------------------------------------ audit
    def audit(self, method: str, risk: str | None, origin: str | None, ok: bool | None,
              detail: dict, task_id: str | None = None) -> None:
        self._exec(
            "INSERT INTO audit(ts,task_id,method,risk,origin,ok,detail) VALUES(?,?,?,?,?,?,?)",
            (time.time(), task_id, method, risk, origin, None if ok is None else int(ok),
             json.dumps(detail, ensure_ascii=False, default=str)[:4000]),
        )

    def list_audit(self, limit: int = 100) -> list[dict]:
        rows = self._all("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        for r in rows:
            r["detail"] = json.loads(r["detail"]) if r["detail"] else None
        return rows

    # ------------------------------------------------------------------ usage
    def add_usage(self, candidate: str, prompt_tokens: int, completion_tokens: int, error: bool = False) -> None:
        day = date.today().isoformat()
        self._exec(
            "INSERT INTO usage(day,candidate,requests,prompt_tokens,completion_tokens,errors) VALUES(?,?,1,?,?,?) "
            "ON CONFLICT(day,candidate) DO UPDATE SET requests=requests+1, prompt_tokens=prompt_tokens+excluded.prompt_tokens, "
            "completion_tokens=completion_tokens+excluded.completion_tokens, errors=errors+excluded.errors",
            (day, candidate, prompt_tokens, completion_tokens, int(error)),
        )

    def usage_today(self) -> dict[str, dict]:
        day = date.today().isoformat()
        return {r["candidate"]: r for r in self._all("SELECT * FROM usage WHERE day=?", (day,))}

    def usage_days(self, days: int = 7) -> list[dict]:
        return self._all("SELECT * FROM usage ORDER BY day DESC, candidate LIMIT ?", (days * 20,))

    # ------------------------------------------------------------------ memory
    def set_contact_alias(self, alias: str, contact_name: str, number: str | None = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO contact_aliases(alias,contact_name,number,updated_at) VALUES(?,?,?,?)",
            (alias.lower().strip(), contact_name.strip(), number, time.time()),
        )

    def get_contact_alias(self, alias: str) -> dict | None:
        return self._one("SELECT * FROM contact_aliases WHERE alias=?", (alias.lower().strip(),))

    def list_contact_aliases(self) -> list[dict]:
        return self._all("SELECT * FROM contact_aliases ORDER BY alias")

    def delete_contact_alias(self, alias: str) -> bool:
        return self._exec("DELETE FROM contact_aliases WHERE alias=?", (alias.lower().strip(),)).rowcount > 0

    def set_app_alias(self, alias: str, package: str, label: str | None = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO app_aliases(alias,package,label,updated_at) VALUES(?,?,?,?)",
            (alias.lower().strip(), package, label, time.time()),
        )

    def list_app_aliases(self) -> list[dict]:
        return self._all("SELECT * FROM app_aliases ORDER BY alias")

    def delete_app_alias(self, alias: str) -> bool:
        return self._exec("DELETE FROM app_aliases WHERE alias=?", (alias.lower().strip(),)).rowcount > 0

    def add_fact(self, text: str) -> int:
        return self._exec("INSERT INTO facts(text,created_at) VALUES(?,?)", (text.strip(), time.time())).lastrowid

    def list_facts(self, limit: int = 50) -> list[dict]:
        return self._all("SELECT * FROM facts ORDER BY id DESC LIMIT ?", (limit,))

    def delete_fact(self, fact_id: int) -> bool:
        return self._exec("DELETE FROM facts WHERE id=?", (fact_id,)).rowcount > 0

    def add_turn(self, role: str, text: str, task_id: str | None = None) -> None:
        self._exec("INSERT INTO conversation(ts,role,text,task_id) VALUES(?,?,?,?)", (time.time(), role, text, task_id))

    def recent_turns(self, limit: int = 6) -> list[dict]:
        rows = self._all("SELECT role,text,ts FROM conversation ORDER BY id DESC LIMIT ?", (limit,))
        return list(reversed(rows))

    # ------------------------------------------------------------------ settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        r = self._one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(r["value"]) if r else default

    def set_setting(self, key: str, value: Any) -> None:
        self._exec("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, json.dumps(value)))

    def all_settings(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self._all("SELECT key,value FROM settings")}

    # ------------------------------------------------------------------ retention
    def purge_older_than(self, days: int = 30) -> None:
        cutoff = time.time() - days * 86400
        self._exec("DELETE FROM steps WHERE ts < ?", (cutoff,))
        self._exec("DELETE FROM audit WHERE ts < ?", (cutoff,))
        self._exec("DELETE FROM tasks WHERE created_at < ?", (cutoff,))
        self._exec("DELETE FROM conversation WHERE ts < ?", (cutoff,))
