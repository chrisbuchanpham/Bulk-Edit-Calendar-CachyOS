from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .models import Preset


class PresetStore:
    def __init__(self, database: Path):
        self.database = database
        database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS presets (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            db.commit()
        self.database.chmod(0o600)

    def list(self) -> list[Preset]:
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM presets ORDER BY name COLLATE NOCASE").fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, preset_id: int) -> Preset | None:
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
        return self._from_row(row) if row else None

    def save(self, preset: Preset) -> Preset:
        now = datetime.now(UTC).isoformat()
        payload = preset.model_dump_json(exclude={"id", "created_at", "updated_at"})
        with closing(self._connect()) as db:
            if preset.id is None:
                cursor = db.execute(
                    "INSERT INTO presets(name, payload, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (preset.name.strip(), payload, now, now),
                )
                preset_id = int(cursor.lastrowid)
            else:
                db.execute(
                    "UPDATE presets SET name = ?, payload = ?, updated_at = ? WHERE id = ?",
                    (preset.name.strip(), payload, now, preset.id),
                )
                preset_id = preset.id
            db.commit()
        saved = self.get(preset_id)
        if saved is None:
            raise RuntimeError("Preset could not be saved")
        return saved

    def delete(self, preset_id: int) -> bool:
        with closing(self._connect()) as db:
            cursor = db.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
            db.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Preset:
        preset = Preset.model_validate_json(row["payload"])
        return preset.model_copy(
            update={
                "id": row["id"],
                "name": row["name"],
                "created_at": datetime.fromisoformat(row["created_at"]),
                "updated_at": datetime.fromisoformat(row["updated_at"]),
            }
        )
