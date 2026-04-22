import json
import os
import time
from datetime import datetime, timezone

import aiosqlite


class EventStore:
    def __init__(self, config: dict):
        evt_cfg = config.get("events", {})
        self._db_path = evt_cfg.get("db_path", "data/events.db")
        self._retention_hours = evt_cfg.get("retention_hours", 48)

    async def init(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT    NOT NULL,
                    event_type TEXT   NOT NULL,
                    message   TEXT    NOT NULL,
                    tags      TEXT    NOT NULL DEFAULT '[]'
                )
                """
            )
            await db.commit()

    async def save(self, event_type: str, message: str, tags: list) -> dict:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        tags_json = json.dumps(tags)
        async with aiosqlite.connect(self._db_path) as db:
            cur = await db.execute(
                "INSERT INTO events (timestamp, event_type, message, tags) VALUES (?,?,?,?)",
                (ts, event_type, message, tags_json),
            )
            await db.commit()
            row_id = cur.lastrowid
        record = {"id": row_id, "timestamp": ts, "event_type": event_type, "message": message, "tags": tags}
        await self._purge_old()
        return record

    async def get_recent(self, limit: int = 50, types: tuple | None = None) -> list[dict]:
        query = "SELECT id, timestamp, event_type, message, tags FROM events"
        params: list = []
        if types:
            placeholders = ",".join("?" * len(types))
            query += f" WHERE event_type IN ({placeholders})"
            params.extend(types)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()

        result = []
        for row in reversed(rows):  # chronological order
            result.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "event_type": row["event_type"],
                    "message": row["message"],
                    "tags": json.loads(row["tags"]),
                }
            )
        return result

    async def _purge_old(self):
        cutoff_ts = time.time() - self._retention_hours * 3600
        cutoff = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
            await db.commit()
