import re
from datetime import datetime
from json import dumps, loads
from typing import Optional

from .db import get_db
from .models import BoilerConfig, Room


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "szoba"


class RoomRepository:
    def list_rooms(self) -> list[Room]:
        rows = get_db().execute(
            """
            SELECT r.*, rr.last_temperature, rr.last_setpoint, rr.last_hysteresis,
                   rr.last_call_for_heat, rr.last_valve_open, rr.last_decision_reason,
                   rr.manual_override_mode, rr.manual_override_until,
                   rr.last_heating_change_at, rr.last_sample_at
            FROM rooms r
            LEFT JOIN room_runtime rr ON rr.room_id = r.id
            ORDER BY r.name COLLATE NOCASE
            """
        ).fetchall()
        return [Room.from_row(row) for row in rows]

    def get_room(self, room_id: int) -> Optional[Room]:
        row = get_db().execute(
            """
            SELECT r.*, rr.last_temperature, rr.last_setpoint, rr.last_hysteresis,
                   rr.last_call_for_heat, rr.last_valve_open, rr.last_decision_reason,
                   rr.manual_override_mode, rr.manual_override_until,
                   rr.last_heating_change_at, rr.last_sample_at
            FROM rooms r
            LEFT JOIN room_runtime rr ON rr.room_id = r.id
            WHERE r.id = ?
            """,
            (room_id,),
        ).fetchone()
        return Room.from_row(row) if row else None

    def create_room(self, data: dict) -> int:
        db = get_db()
        slug = slugify(data["name"])
        suffix = 2
        while db.execute("SELECT 1 FROM rooms WHERE slug = ?", (slug,)).fetchone():
            slug = f"{slugify(data['name'])}-{suffix}"
            suffix += 1

        cur = db.execute(
            """
            INSERT INTO rooms (
                slug, name, temperature_entity_id, valve_entity_id, setpoint_entity_id,
                hysteresis_entity_id, circadian_enabled_entity_id, circadian_night_start,
                circadian_morning_start, circadian_night_delta, circadian_morning_delta,
                enabled, learning_enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                data["name"],
                data["temperature_entity_id"],
                data["valve_entity_id"],
                data["setpoint_entity_id"],
                data["hysteresis_entity_id"],
                data.get("circadian_enabled_entity_id") or None,
                data.get("circadian_night_start", "22:00"),
                data.get("circadian_morning_start", "05:30"),
                float(data.get("circadian_night_delta", 0.0)),
                float(data.get("circadian_morning_delta", 0.0)),
                int(bool(data.get("enabled", True))),
                int(bool(data.get("learning_enabled", False))),
            ),
        )
        room_id = cur.lastrowid
        db.execute("INSERT INTO room_runtime (room_id) VALUES (?)", (room_id,))
        db.commit()
        return room_id

    def update_room(self, room_id: int, data: dict):
        db = get_db()
        db.execute(
            """
            UPDATE rooms
            SET name = ?, temperature_entity_id = ?, valve_entity_id = ?, setpoint_entity_id = ?,
                hysteresis_entity_id = ?, circadian_enabled_entity_id = ?, circadian_night_start = ?,
                circadian_morning_start = ?, circadian_night_delta = ?, circadian_morning_delta = ?,
                enabled = ?, learning_enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                data["name"],
                data["temperature_entity_id"],
                data["valve_entity_id"],
                data["setpoint_entity_id"],
                data["hysteresis_entity_id"],
                data.get("circadian_enabled_entity_id") or None,
                data.get("circadian_night_start", "22:00"),
                data.get("circadian_morning_start", "05:30"),
                float(data.get("circadian_night_delta", 0.0)),
                float(data.get("circadian_morning_delta", 0.0)),
                int(bool(data.get("enabled", True))),
                int(bool(data.get("learning_enabled", False))),
                room_id,
            ),
        )
        db.commit()

    def delete_room(self, room_id: int):
        db = get_db()
        db.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        db.commit()


class BoilerRepository:
    def get(self) -> BoilerConfig:
        row = get_db().execute("SELECT * FROM boiler_config WHERE id = 1").fetchone()
        return BoilerConfig.from_row(row)

    def update(self, data: dict):
        get_db().execute(
            """
            UPDATE boiler_config
            SET name = ?, heating_entity_id = ?, pump_entity_id = ?, pump_overrun_minutes = ?,
                enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (
                data["name"],
                data["heating_entity_id"],
                data["pump_entity_id"],
                int(data["pump_overrun_minutes"]),
                int(bool(data.get("enabled", True))),
            ),
        )
        get_db().commit()


class RuntimeRepository:
    def get_system_runtime(self) -> dict:
        row = get_db().execute("SELECT * FROM system_runtime WHERE id = 1").fetchone()
        data = dict(row) if row else {}
        snapshot = data.get("last_controller_snapshot_json")
        if snapshot:
            try:
                data["last_controller_snapshot"] = loads(snapshot)
            except Exception:
                data["last_controller_snapshot"] = None
        else:
            data["last_controller_snapshot"] = None
        return data

    def update_system_runtime(self, **values):
        if not values:
            return
        assignments = ", ".join(f"{key} = ?" for key in values)
        params = list(values.values())
        params.append(1)
        get_db().execute(
            f"UPDATE system_runtime SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            params,
        )
        get_db().commit()

    def update_room_runtime(
        self,
        room_id: int,
        *,
        temperature: Optional[float],
        setpoint: Optional[float],
        hysteresis: Optional[float],
        call_for_heat: bool,
        valve_open: bool,
        decision_reason: Optional[str],
    ):
        get_db().execute(
            """
            UPDATE room_runtime
            SET last_temperature = ?, last_setpoint = ?, last_hysteresis = ?,
                last_call_for_heat = ?, last_valve_open = ?, last_decision_reason = ?,
                last_heating_change_at = COALESCE(last_heating_change_at, CURRENT_TIMESTAMP),
                last_sample_at = CURRENT_TIMESTAMP
            WHERE room_id = ?
            """,
            (
                temperature,
                setpoint,
                hysteresis,
                int(call_for_heat),
                int(valve_open),
                decision_reason,
                room_id,
            ),
        )
        get_db().commit()

    def set_room_override(self, room_id: int, mode: str, until_iso: Optional[str]):
        get_db().execute(
            "UPDATE room_runtime SET manual_override_mode = ?, manual_override_until = ? WHERE room_id = ?",
            (mode, until_iso, room_id),
        )
        get_db().commit()

    def clear_expired_room_overrides(self, now_iso: str):
        get_db().execute(
            """
            UPDATE room_runtime
            SET manual_override_mode = 'auto', manual_override_until = NULL
            WHERE manual_override_mode != 'auto'
              AND manual_override_until IS NOT NULL
              AND manual_override_until <= ?
            """,
            (now_iso,),
        )
        get_db().commit()

    def set_boiler_override(self, mode: str, until_iso: Optional[str]):
        get_db().execute(
            """
            UPDATE system_runtime
            SET boiler_manual_override_mode = ?, boiler_manual_override_until = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (mode, until_iso),
        )
        get_db().commit()

    def clear_expired_boiler_override(self, now_iso: str):
        get_db().execute(
            """
            UPDATE system_runtime
            SET boiler_manual_override_mode = 'auto', boiler_manual_override_until = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
              AND boiler_manual_override_mode != 'auto'
              AND boiler_manual_override_until IS NOT NULL
              AND boiler_manual_override_until <= ?
            """,
            (now_iso,),
        )
        get_db().commit()

    def save_controller_snapshot(self, payload: dict):
        get_db().execute(
            """
            UPDATE system_runtime
            SET last_controller_snapshot_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
            """,
            (dumps(payload, ensure_ascii=True),),
        )
        get_db().commit()

    def set_room_change_timestamp(self, room_id: int):
        get_db().execute(
            "UPDATE room_runtime SET last_heating_change_at = CURRENT_TIMESTAMP WHERE room_id = ?",
            (room_id,),
        )
        get_db().commit()

    def add_learning_event(
        self,
        room_id: int,
        event_type: str,
        *,
        outdoor_temperature: Optional[float],
        room_temperature: Optional[float],
        setpoint: Optional[float],
        duration_seconds: Optional[float],
        payload: Optional[dict],
    ):
        get_db().execute(
            """
            INSERT INTO room_learning_events (
                room_id, event_type, outdoor_temperature, room_temperature, setpoint,
                duration_seconds, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                room_id,
                event_type,
                outdoor_temperature,
                room_temperature,
                setpoint,
                duration_seconds,
                dumps(payload or {}, ensure_ascii=True),
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        get_db().commit()

    def recent_learning_events(self, room_id: int, limit: int = 20) -> list[dict]:
        rows = get_db().execute(
            """
            SELECT id, event_type, outdoor_temperature, room_temperature, setpoint,
                   duration_seconds, payload_json, created_at
            FROM room_learning_events
            WHERE room_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (room_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_room_sample(
        self,
        room_id: int,
        *,
        temperature: Optional[float],
        effective_setpoint: Optional[float],
        hysteresis: Optional[float],
        call_for_heat: bool,
        outdoor_temperature: Optional[float],
    ):
        get_db().execute(
            """
            INSERT INTO room_samples (
                room_id, temperature, effective_setpoint, hysteresis, call_for_heat, outdoor_temperature
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                room_id,
                temperature,
                effective_setpoint,
                hysteresis,
                int(call_for_heat),
                outdoor_temperature,
            ),
        )
        get_db().execute(
            """
            DELETE FROM room_samples
            WHERE room_id = ?
              AND id NOT IN (
                  SELECT id FROM room_samples
                  WHERE room_id = ?
                  ORDER BY sampled_at DESC, id DESC
                  LIMIT 288
              )
            """,
            (room_id, room_id),
        )
        get_db().commit()

    def recent_room_samples(self, room_id: int, limit: int = 96) -> list[dict]:
        rows = get_db().execute(
            """
            SELECT temperature, effective_setpoint, hysteresis, call_for_heat, outdoor_temperature, sampled_at
            FROM room_samples
            WHERE room_id = ?
            ORDER BY sampled_at DESC, id DESC
            LIMIT ?
            """,
            (room_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def upsert_learning_profile(
        self,
        room_id: int,
        outdoor_bin: str,
        *,
        heat_on_duration: Optional[float] = None,
        overshoot: Optional[float] = None,
    ):
        db = get_db()
        row = db.execute(
            """
            SELECT heat_on_events, avg_heat_on_seconds, heat_off_events, avg_overshoot
            FROM room_learning_profiles
            WHERE room_id = ? AND outdoor_bin = ?
            """,
            (room_id, outdoor_bin),
        ).fetchone()
        if row is None:
            db.execute(
                """
                INSERT INTO room_learning_profiles (
                    room_id, outdoor_bin, heat_on_events, avg_heat_on_seconds,
                    heat_off_events, avg_overshoot, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    room_id,
                    outdoor_bin,
                    1 if heat_on_duration is not None else 0,
                    heat_on_duration,
                    1 if overshoot is not None else 0,
                    overshoot,
                ),
            )
        else:
            heat_on_events = row["heat_on_events"]
            avg_heat_on_seconds = row["avg_heat_on_seconds"]
            heat_off_events = row["heat_off_events"]
            avg_overshoot = row["avg_overshoot"]
            if heat_on_duration is not None:
                new_count = heat_on_events + 1
                new_avg = heat_on_duration if avg_heat_on_seconds is None else (
                    ((avg_heat_on_seconds * heat_on_events) + heat_on_duration) / new_count
                )
                heat_on_events = new_count
                avg_heat_on_seconds = new_avg
            if overshoot is not None:
                new_count = heat_off_events + 1
                new_avg = overshoot if avg_overshoot is None else (
                    ((avg_overshoot * heat_off_events) + overshoot) / new_count
                )
                heat_off_events = new_count
                avg_overshoot = new_avg
            db.execute(
                """
                UPDATE room_learning_profiles
                SET heat_on_events = ?, avg_heat_on_seconds = ?, heat_off_events = ?,
                    avg_overshoot = ?, updated_at = CURRENT_TIMESTAMP
                WHERE room_id = ? AND outdoor_bin = ?
                """,
                (
                    heat_on_events,
                    avg_heat_on_seconds,
                    heat_off_events,
                    avg_overshoot,
                    room_id,
                    outdoor_bin,
                ),
            )
        db.commit()

    def learning_profiles(self, room_id: int) -> list[dict]:
        rows = get_db().execute(
            """
            SELECT outdoor_bin, heat_on_events, avg_heat_on_seconds, heat_off_events, avg_overshoot, updated_at
            FROM room_learning_profiles
            WHERE room_id = ?
            ORDER BY outdoor_bin
            """,
            (room_id,),
        ).fetchall()
        return [dict(row) for row in rows]


class SettingsRepository:
    def get_many(self, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        placeholders = ", ".join("?" for _ in keys)
        rows = get_db().execute(
            f"SELECT key, value FROM settings WHERE key IN ({placeholders})",
            keys,
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def set_many(self, values: dict[str, str]):
        db = get_db()
        for key, value in values.items():
            db.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
        db.commit()

    def get_bool(self, key: str, default: bool = False) -> bool:
        row = get_db().execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"]).strip().lower() in {"1", "true", "on", "yes"}
