import sqlite3
from pathlib import Path

from flask import Flask, current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS boiler_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    heating_entity_id TEXT NOT NULL,
    pump_entity_id TEXT NOT NULL,
    pump_overrun_minutes INTEGER NOT NULL DEFAULT 90,
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    temperature_entity_id TEXT NOT NULL,
    valve_entity_id TEXT NOT NULL,
    setpoint_entity_id TEXT NOT NULL,
    hysteresis_entity_id TEXT NOT NULL,
    circadian_enabled_entity_id TEXT,
    circadian_night_start TEXT NOT NULL DEFAULT '22:00',
    circadian_morning_start TEXT NOT NULL DEFAULT '05:30',
    circadian_night_delta REAL NOT NULL DEFAULT 0.0,
    circadian_morning_delta REAL NOT NULL DEFAULT 0.0,
    enabled INTEGER NOT NULL DEFAULT 1,
    learning_enabled INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS room_runtime (
    room_id INTEGER PRIMARY KEY,
    last_temperature REAL,
    last_setpoint REAL,
    last_hysteresis REAL,
    last_call_for_heat INTEGER NOT NULL DEFAULT 0,
    last_valve_open INTEGER NOT NULL DEFAULT 0,
    last_decision_reason TEXT,
    manual_override_mode TEXT NOT NULL DEFAULT 'auto',
    manual_override_until TEXT,
    last_heating_change_at TEXT,
    last_sample_at TEXT,
    FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS room_learning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    outdoor_temperature REAL,
    room_temperature REAL,
    setpoint REAL,
    duration_seconds REAL,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS room_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL,
    temperature REAL,
    effective_setpoint REAL,
    hysteresis REAL,
    call_for_heat INTEGER NOT NULL DEFAULT 0,
    outdoor_temperature REAL,
    sampled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS room_learning_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL,
    outdoor_bin TEXT NOT NULL,
    heat_on_events INTEGER NOT NULL DEFAULT 0,
    avg_heat_on_seconds REAL,
    heat_off_events INTEGER NOT NULL DEFAULT 0,
    avg_overshoot REAL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(room_id, outdoor_bin),
    FOREIGN KEY (room_id) REFERENCES rooms (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system_runtime (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    outdoor_entity_id TEXT,
    controller_enabled INTEGER NOT NULL DEFAULT 1,
    learning_debug_enabled INTEGER NOT NULL DEFAULT 0,
    hvac_mode TEXT NOT NULL DEFAULT 'heat',
    cooling_call INTEGER NOT NULL DEFAULT 0,
    average_temperature REAL,
    average_setpoint REAL,
    average_hysteresis REAL,
    boiler_heating_state INTEGER NOT NULL DEFAULT 0,
    boiler_pump_state INTEGER NOT NULL DEFAULT 0,
    pump_countdown_started_at TEXT,
    pump_countdown_target_at TEXT,
    boiler_manual_override_mode TEXT NOT NULL DEFAULT 'auto',
    boiler_manual_override_until TEXT,
    last_controller_snapshot_json TEXT,
    last_controller_run_at TEXT,
    last_controller_status TEXT,
    last_controller_error TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def get_db():
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"]).resolve()
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def seed_defaults(db: sqlite3.Connection):
    db.execute(
        """
        INSERT INTO settings (key, value) VALUES
            ('ha_base_url', 'http://homeassistant.local:8123'),
            ('ha_token', ''),
            ('outdoor_entity_id', ''),
            ('hvac_mode_entity_id', ''),
            ('controller_interval_seconds', '30'),
            ('feature_multi_room_logic', '0'),
            ('feature_predictive_cutoff', '0')
        ON CONFLICT(key) DO NOTHING
        """
    )
    db.execute(
        """
        INSERT INTO boiler_config (id, name, heating_entity_id, pump_entity_id, pump_overrun_minutes, enabled)
        VALUES (1, ?, ?, ?, 90, 1)
        ON CONFLICT(id) DO NOTHING
        """,
        ("Kazán", "input_boolean.boiler_heat", "input_boolean.boiler_pump"),
    )
    db.execute(
        """
        INSERT INTO system_runtime (id, controller_enabled, learning_debug_enabled, boiler_heating_state, boiler_pump_state)
        VALUES (1, 1, 0, 0, 0)
        ON CONFLICT(id) DO NOTHING
        """
    )
    columns = {row["name"] for row in db.execute("PRAGMA table_info(rooms)").fetchall()}
    if "circadian_night_start" not in columns:
        db.execute("ALTER TABLE rooms ADD COLUMN circadian_night_start TEXT NOT NULL DEFAULT '22:00'")
    if "circadian_morning_start" not in columns:
        db.execute("ALTER TABLE rooms ADD COLUMN circadian_morning_start TEXT NOT NULL DEFAULT '05:30'")
    runtime_columns = {row["name"] for row in db.execute("PRAGMA table_info(system_runtime)").fetchall()}
    if "last_controller_run_at" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN last_controller_run_at TEXT")
    if "last_controller_status" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN last_controller_status TEXT")
    if "last_controller_error" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN last_controller_error TEXT")
    if "hvac_mode" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN hvac_mode TEXT NOT NULL DEFAULT 'heat'")
    if "cooling_call" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN cooling_call INTEGER NOT NULL DEFAULT 0")
    if "average_temperature" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN average_temperature REAL")
    if "average_setpoint" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN average_setpoint REAL")
    if "average_hysteresis" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN average_hysteresis REAL")
    if "boiler_manual_override_mode" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN boiler_manual_override_mode TEXT NOT NULL DEFAULT 'auto'")
    if "boiler_manual_override_until" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN boiler_manual_override_until TEXT")
    if "last_controller_snapshot_json" not in runtime_columns:
        db.execute("ALTER TABLE system_runtime ADD COLUMN last_controller_snapshot_json TEXT")
    room_runtime_columns = {row["name"] for row in db.execute("PRAGMA table_info(room_runtime)").fetchall()}
    if "last_valve_open" not in room_runtime_columns:
        db.execute("ALTER TABLE room_runtime ADD COLUMN last_valve_open INTEGER NOT NULL DEFAULT 0")
    if "last_decision_reason" not in room_runtime_columns:
        db.execute("ALTER TABLE room_runtime ADD COLUMN last_decision_reason TEXT")
    if "manual_override_mode" not in room_runtime_columns:
        db.execute("ALTER TABLE room_runtime ADD COLUMN manual_override_mode TEXT NOT NULL DEFAULT 'auto'")
    if "manual_override_until" not in room_runtime_columns:
        db.execute("ALTER TABLE room_runtime ADD COLUMN manual_override_until TEXT")
    db.commit()


def init_db(app: Flask):
    app.teardown_appcontext(close_db)
    app.extensions["sqlite_db"] = get_db

    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        seed_defaults(db)
