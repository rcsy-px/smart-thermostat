from dataclasses import dataclass
from sqlite3 import Row
from typing import Optional


@dataclass
class Room:
    id: int
    slug: str
    name: str
    temperature_entity_id: str
    valve_entity_id: str
    setpoint_entity_id: str
    hysteresis_entity_id: str
    circadian_enabled_entity_id: Optional[str]
    circadian_night_start: str
    circadian_morning_start: str
    circadian_night_delta: float
    circadian_morning_delta: float
    enabled: bool
    learning_enabled: bool
    last_temperature: Optional[float]
    last_setpoint: Optional[float]
    last_hysteresis: Optional[float]
    last_call_for_heat: bool
    last_valve_open: bool
    last_decision_reason: Optional[str]
    manual_override_mode: str
    manual_override_until: Optional[str]
    last_heating_change_at: Optional[str]
    last_sample_at: Optional[str]

    @classmethod
    def from_row(cls, row: Row) -> "Room":
        return cls(
            id=row["id"],
            slug=row["slug"],
            name=row["name"],
            temperature_entity_id=row["temperature_entity_id"],
            valve_entity_id=row["valve_entity_id"],
            setpoint_entity_id=row["setpoint_entity_id"],
            hysteresis_entity_id=row["hysteresis_entity_id"],
            circadian_enabled_entity_id=row["circadian_enabled_entity_id"],
            circadian_night_start=row["circadian_night_start"],
            circadian_morning_start=row["circadian_morning_start"],
            circadian_night_delta=row["circadian_night_delta"],
            circadian_morning_delta=row["circadian_morning_delta"],
            enabled=bool(row["enabled"]),
            learning_enabled=bool(row["learning_enabled"]),
            last_temperature=row["last_temperature"],
            last_setpoint=row["last_setpoint"],
            last_hysteresis=row["last_hysteresis"],
            last_call_for_heat=bool(row["last_call_for_heat"] or 0),
            last_valve_open=bool(row["last_valve_open"] or 0),
            last_decision_reason=row["last_decision_reason"],
            manual_override_mode=row["manual_override_mode"] or "auto",
            manual_override_until=row["manual_override_until"],
            last_heating_change_at=row["last_heating_change_at"],
            last_sample_at=row["last_sample_at"],
        )


@dataclass
class BoilerConfig:
    name: str
    heating_entity_id: str
    pump_entity_id: str
    pump_overrun_minutes: int
    enabled: bool

    @classmethod
    def from_row(cls, row: Row) -> "BoilerConfig":
        return cls(
            name=row["name"],
            heating_entity_id=row["heating_entity_id"],
            pump_entity_id=row["pump_entity_id"],
            pump_overrun_minutes=row["pump_overrun_minutes"],
            enabled=bool(row["enabled"]),
        )
