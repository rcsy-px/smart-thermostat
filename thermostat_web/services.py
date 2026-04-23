from datetime import datetime, time as dt_time, timedelta
from typing import Any

from .ha import HomeAssistantClient
from .repository import BoilerRepository, RoomRepository, RuntimeRepository, SettingsRepository


class DashboardService:
    def __init__(self):
        self.rooms = RoomRepository()
        self.boiler = BoilerRepository()
        self.runtime = RuntimeRepository()
        self.settings = SettingsRepository()

    def dashboard_data(self) -> dict[str, Any]:
        rooms = self.rooms.list_rooms()
        runtime = self.runtime.get_system_runtime()
        active_rooms = [room for room in rooms if room.enabled]
        demanding_rooms = [room for room in active_rooms if room.last_call_for_heat]
        settings = self.settings.get_many(
            [
                "ha_base_url",
                "ha_token",
                "outdoor_entity_id",
                "hvac_mode_entity_id",
                "controller_interval_seconds",
                "feature_multi_room_logic",
                "feature_predictive_cutoff",
            ]
        )
        return {
            "rooms": rooms,
            "room_count": len(rooms),
            "active_room_count": len(active_rooms),
            "demanding_room_count": len(demanding_rooms),
            "boiler": self.boiler.get(),
            "runtime": runtime,
            "settings": settings,
            "single_room_mode": len(active_rooms) <= 1,
            "multi_room_feature_enabled": self.settings.get_bool("feature_multi_room_logic"),
            "predictive_cutoff_feature_enabled": self.settings.get_bool("feature_predictive_cutoff"),
        }

    def room_detail_data(self, room_id: int) -> dict[str, Any]:
        room = self.rooms.get_room(room_id)
        samples = self.runtime.recent_room_samples(room_id)
        return {
            "room": room,
            "events": self.runtime.recent_learning_events(room_id),
            "profiles": self.runtime.learning_profiles(room_id),
            "samples": samples,
            "chart_points": build_chart_points(samples, "temperature"),
            "setpoint_chart_points": build_chart_points(samples, "effective_setpoint"),
        }


class ControllerService:
    def __init__(self):
        self.rooms = RoomRepository()
        self.boiler = BoilerRepository()
        self.runtime = RuntimeRepository()
        self.settings = SettingsRepository()
        self.ha = HomeAssistantClient()

    def sample_once(self) -> dict[str, Any]:
        boiler = self.boiler.get()
        now_iso = datetime.utcnow().isoformat(timespec="seconds")
        self.runtime.clear_expired_room_overrides(now_iso)
        self.runtime.clear_expired_boiler_override(now_iso)
        rooms = self.rooms.list_rooms()
        runtime = self.runtime.get_system_runtime()
        if not runtime.get("controller_enabled", 1):
            return {
                "boiler_should_heat": False,
                "pump_should_run": bool(runtime.get("boiler_pump_state", 0)),
                "outdoor_temperature": None,
                "hvac_mode": runtime.get("hvac_mode", "heat"),
                "cooling_call": bool(runtime.get("cooling_call", 0)),
                "room_samples": [],
            }
        settings = self.settings.get_many(["outdoor_entity_id", "hvac_mode_entity_id"])
        multi_room_logic_enabled = self.settings.get_bool("feature_multi_room_logic")
        predictive_cutoff_enabled = self.settings.get_bool("feature_predictive_cutoff")
        outdoor_temp = None
        hvac_mode = "heat"
        if settings.get("outdoor_entity_id"):
            try:
                outdoor_temp = self.ha.get_numeric_state(settings["outdoor_entity_id"])
            except Exception:
                outdoor_temp = None
        if settings.get("hvac_mode_entity_id"):
            try:
                hvac_mode = normalize_hvac_mode(self.ha.get_state(settings["hvac_mode_entity_id"]).get("state", ""))
            except Exception:
                hvac_mode = "heat"
        room_samples = []
        boiler_should_heat = False
        cooling_call = False
        enabled_rooms = [room for room in rooms if room.enabled]
        can_use_multi_room_logic = multi_room_logic_enabled and len(enabled_rooms) > 1
        can_use_predictive_cutoff = predictive_cutoff_enabled and can_use_multi_room_logic

        for room in rooms:
            sample = {
                "room_id": room.id,
                "name": room.name,
                "temperature": None,
                "setpoint": None,
                "hysteresis": None,
                "call_for_heat": False,
                "valve_open": False,
                "predictive_preheat": False,
                "predictive_cutoff_applied": False,
                "decision_reason": "nincs adat",
                "error": None,
            }
            if not room.enabled:
                sample["decision_reason"] = "szoba letiltva"
                room_samples.append(sample)
                continue

            try:
                temp = self.ha.get_numeric_state(room.temperature_entity_id)
                setpoint = self.ha.get_numeric_state(room.setpoint_entity_id)
                hysteresis = self.ha.get_numeric_state(room.hysteresis_entity_id)
                circadian_enabled = False
                if room.circadian_enabled_entity_id:
                    raw = self.ha.get_state(room.circadian_enabled_entity_id).get("state", "").lower()
                    circadian_enabled = raw in {"on", "true", "1"}
                if circadian_enabled:
                    setpoint = apply_circadian(room, setpoint)
                sample["temperature"] = temp
                sample["setpoint"] = setpoint
                sample["hysteresis"] = hysteresis
                if None not in (temp, setpoint, hysteresis):
                    sample["call_for_heat"] = temp <= setpoint - hysteresis
                    boiler_should_heat = boiler_should_heat or sample["call_for_heat"]
                    sample["decision_reason"] = "direkt futesi igeny" if sample["call_for_heat"] else "setpoint kozeleben"
                    if sample["call_for_heat"] != room.last_call_for_heat:
                        previous_change_at = room.last_heating_change_at
                        self.runtime.set_room_change_timestamp(room.id)
                        if room.learning_enabled:
                            previous_dt = parse_iso_datetime(previous_change_at)
                            duration_seconds = None
                            if previous_dt:
                                duration_seconds = max(0.0, (datetime.utcnow() - previous_dt).total_seconds())
                            outdoor_bin = classify_outdoor_temp(outdoor_temp)
                            self.runtime.add_learning_event(
                                room.id,
                                "heat_on" if sample["call_for_heat"] else "heat_off",
                                outdoor_temperature=outdoor_temp,
                                room_temperature=temp,
                                setpoint=setpoint,
                                duration_seconds=duration_seconds,
                                payload={"hysteresis": hysteresis, "outdoor_bin": outdoor_bin},
                            )
                            if sample["call_for_heat"]:
                                overshoot = None
                                if room.last_setpoint is not None and room.last_temperature is not None:
                                    overshoot = max(0.0, room.last_temperature - room.last_setpoint)
                                self.runtime.upsert_learning_profile(
                                    room.id,
                                    outdoor_bin,
                                    overshoot=overshoot,
                                )
                            else:
                                self.runtime.upsert_learning_profile(
                                    room.id,
                                    outdoor_bin,
                                    heat_on_duration=duration_seconds,
                                )
                    self.runtime.add_room_sample(
                        room.id,
                        temperature=temp,
                        effective_setpoint=setpoint,
                        hysteresis=hysteresis,
                        call_for_heat=sample["call_for_heat"],
                        outdoor_temperature=outdoor_temp,
                    )
            except Exception as exc:
                sample["error"] = str(exc)
                sample["decision_reason"] = "home assistant hiba"

            room_samples.append(sample)

        average_temperature, average_setpoint, average_hysteresis = summarize_room_averages(room_samples)
        self._resolve_valve_targets(
            room_samples,
            outdoor_temp=outdoor_temp,
            predictive_cutoff_enabled=can_use_predictive_cutoff,
            multi_room_logic_enabled=can_use_multi_room_logic,
        )
        self._apply_manual_room_overrides(room_samples, rooms)
        boiler_should_heat, cooling_call = self._apply_hvac_mode(
            hvac_mode=hvac_mode,
            room_samples=room_samples,
            average_temperature=average_temperature,
            average_setpoint=average_setpoint,
            average_hysteresis=average_hysteresis,
        )
        boiler_should_heat = self._apply_manual_boiler_override(boiler_should_heat, runtime)
        for sample in room_samples:
            if sample.get("error") is None:
                room = next((r for r in rooms if r.id == sample["room_id"]), None)
                if room:
                    if boiler.enabled:
                        self.ha.set_input_boolean(room.valve_entity_id, sample["valve_open"])
                    self.runtime.update_room_runtime(
                        room.id,
                        temperature=sample["temperature"],
                        setpoint=sample["setpoint"],
                        hysteresis=sample["hysteresis"],
                        call_for_heat=sample["call_for_heat"],
                        valve_open=sample["valve_open"],
                        decision_reason=sample["decision_reason"],
                    )

        pump_should_run = False
        countdown_target = runtime.get("pump_countdown_target_at")
        self.runtime.update_system_runtime(
            hvac_mode=hvac_mode,
            cooling_call=int(cooling_call),
            average_temperature=average_temperature,
            average_setpoint=average_setpoint,
            average_hysteresis=average_hysteresis,
            boiler_heating_state=int(boiler_should_heat),
            pump_countdown_target_at=countdown_target,
            last_controller_run_at=datetime.utcnow().isoformat(timespec="seconds"),
            last_controller_status="ok",
            last_controller_error=None,
        )
        if boiler.enabled:
            self.ha.set_input_boolean(boiler.heating_entity_id, boiler_should_heat)

        if boiler_should_heat:
            pump_should_run = True
            self.runtime.update_system_runtime(
                boiler_pump_state=1,
                pump_countdown_started_at=None,
                pump_countdown_target_at=None,
            )
        else:
            now = datetime.utcnow()
            if not countdown_target:
                target = now + timedelta(minutes=boiler.pump_overrun_minutes)
                countdown_target = target.isoformat(timespec="seconds")
                self.runtime.update_system_runtime(
                    pump_countdown_started_at=now.isoformat(timespec="seconds"),
                    pump_countdown_target_at=countdown_target,
                )
            pump_should_run = countdown_target > now.isoformat(timespec="seconds")
            self.runtime.update_system_runtime(boiler_pump_state=int(pump_should_run))

        if boiler.enabled:
            self.ha.set_input_boolean(boiler.pump_entity_id, pump_should_run)

        result = {
            "boiler_should_heat": boiler_should_heat,
            "pump_should_run": pump_should_run,
            "outdoor_temperature": outdoor_temp,
            "hvac_mode": hvac_mode,
            "cooling_call": cooling_call,
            "average_temperature": average_temperature,
            "average_setpoint": average_setpoint,
            "average_hysteresis": average_hysteresis,
            "multi_room_logic_active": can_use_multi_room_logic,
            "predictive_cutoff_active": can_use_predictive_cutoff,
            "room_samples": room_samples,
        }
        self.runtime.save_controller_snapshot(result)
        return result

    def _apply_manual_room_overrides(self, room_samples: list[dict[str, Any]], rooms: list[Any]):
        room_map = {room.id: room for room in rooms}
        for sample in room_samples:
            room = room_map.get(sample["room_id"])
            if not room or sample.get("error") is not None:
                continue
            if room.manual_override_mode == "force_open":
                sample["valve_open"] = True
                sample["decision_reason"] = "manual override: szelep kenyszeritett nyitas"
            elif room.manual_override_mode == "force_closed":
                sample["valve_open"] = False
                sample["decision_reason"] = "manual override: szelep kenyszeritett zaras"

    def _apply_manual_boiler_override(self, boiler_should_heat: bool, runtime: dict[str, Any]) -> bool:
        mode = runtime.get("boiler_manual_override_mode", "auto")
        if mode == "force_on":
            return True
        if mode == "force_off":
            return False
        return boiler_should_heat

    def _apply_hvac_mode(
        self,
        *,
        hvac_mode: str,
        room_samples: list[dict[str, Any]],
        average_temperature: float | None,
        average_setpoint: float | None,
        average_hysteresis: float | None,
    ) -> tuple[bool, bool]:
        heat_call = any(sample["valve_open"] for sample in room_samples if sample.get("error") is None)
        cooling_call = False

        if hvac_mode == "vent":
            for sample in room_samples:
                if sample.get("error") is None:
                    sample["valve_open"] = False
                    sample["decision_reason"] = "vent mode: futesi kor letiltva"
            return False, False

        if hvac_mode == "cool":
            cooling_call = should_call_cooling(average_temperature, average_setpoint, average_hysteresis)
            for sample in room_samples:
                if sample.get("error") is None:
                    sample["valve_open"] = False
                    sample["decision_reason"] = (
                        "cool mode: globalis atlag alapjan hut" if cooling_call else "cool mode: nincs hutesi igeny"
                    )
            return False, cooling_call

        if hvac_mode == "auto":
            cooling_call = should_call_cooling(average_temperature, average_setpoint, average_hysteresis)
            if cooling_call:
                for sample in room_samples:
                    if sample.get("error") is None:
                        sample["valve_open"] = False
                        sample["decision_reason"] = "auto mode: cooling ag aktiv, futes tiltva"
                return False, True
            return heat_call, False

        return heat_call, False

    def _resolve_valve_targets(
        self,
        room_samples: list[dict[str, Any]],
        *,
        outdoor_temp: float | None,
        predictive_cutoff_enabled: bool,
        multi_room_logic_enabled: bool,
    ) -> dict[int, bool]:
        demanders = [sample for sample in room_samples if sample["call_for_heat"]]
        valve_targets: dict[int, bool] = {}

        if not multi_room_logic_enabled:
            for sample in room_samples:
                sample["valve_open"] = bool(sample["call_for_heat"])
                sample["decision_reason"] = (
                    "simple mode: futesi igeny" if sample["call_for_heat"] else "simple mode: nincs futesi igeny"
                )
                valve_targets[sample["room_id"]] = sample["valve_open"]
            return valve_targets

        warm_candidates = []
        for sample in room_samples:
            if sample["error"] is not None:
                continue
            temp = sample.get("temperature")
            setpoint = sample.get("setpoint")
            if None in (temp, setpoint):
                continue
            if sample["call_for_heat"]:
                sample["valve_open"] = True
                sample["decision_reason"] = "multi-room: direkt futesi igeny"
                valve_targets[sample["room_id"]] = True
                continue
            margin = setpoint - temp
            if 0 < margin <= 0.25:
                warm_candidates.append(sample)

        if demanders:
            for sample in warm_candidates:
                if predictive_cutoff_enabled:
                    should_preheat = self._should_preheat_room(sample["room_id"], outdoor_temp, sample["temperature"], sample["setpoint"])
                    sample["predictive_preheat"] = should_preheat
                    sample["valve_open"] = should_preheat
                    sample["decision_reason"] = (
                        "predictive preheat engedelyezve" if should_preheat else "predictive cutoff visszatartotta"
                    )
                    sample["predictive_cutoff_applied"] = not should_preheat
                    valve_targets[sample["room_id"]] = should_preheat
                else:
                    sample["valve_open"] = True
                    sample["decision_reason"] = "multi-room: kozel a setpointhoz, kozosen fut"
                    valve_targets[sample["room_id"]] = True

        for sample in room_samples:
            if sample["error"] is None and not sample["decision_reason"]:
                sample["decision_reason"] = "multi-room: nincs aktiv futesi ok"
            valve_targets.setdefault(sample["room_id"], bool(sample["valve_open"]))
        return valve_targets

    def _should_preheat_room(
        self,
        room_id: int,
        outdoor_temp: float | None,
        temperature: float | None,
        setpoint: float | None,
    ) -> bool:
        if None in (temperature, setpoint):
            return False
        profiles = self.runtime.learning_profiles(room_id)
        wanted_bin = classify_outdoor_temp(outdoor_temp)
        profile = next((item for item in profiles if item["outdoor_bin"] == wanted_bin), None)
        if not profile:
            return True
        avg_overshoot = profile.get("avg_overshoot")
        if avg_overshoot is None:
            return True
        margin = setpoint - temperature
        return margin > float(avg_overshoot)


def apply_circadian(room, setpoint: float | None) -> float | None:
    if setpoint is None:
        return None
    now = datetime.now().time()
    night_start = _parse_clock(room.circadian_night_start)
    morning_start = _parse_clock(room.circadian_morning_start)
    if night_start and morning_start:
        if now >= night_start or now < morning_start:
            return setpoint - room.circadian_night_delta
        morning_boost_end = _add_minutes(morning_start, 120)
        if morning_start <= now < morning_boost_end:
            return setpoint + room.circadian_morning_delta
    return setpoint


def _parse_clock(value: str | None) -> dt_time | None:
    if not value:
        return None
    try:
        hours, minutes = value.split(":", 1)
        return dt_time(hour=int(hours), minute=int(minutes))
    except (ValueError, TypeError):
        return None


def _add_minutes(value: dt_time, minutes: int) -> dt_time:
    baseline = datetime.combine(datetime.today(), value)
    shifted = baseline + timedelta(minutes=minutes)
    return shifted.time()


def build_chart_points(samples: list[dict], field: str) -> str:
    numeric_samples = [s for s in samples if s.get(field) is not None]
    if len(numeric_samples) < 2:
        return ""
    temps = [float(s[field]) for s in numeric_samples]
    min_temp = min(temps)
    max_temp = max(temps)
    span = max(max_temp - min_temp, 0.5)
    points = []
    for idx, sample in enumerate(numeric_samples):
        x = (idx / (len(numeric_samples) - 1)) * 100
        y = 100 - (((float(sample[field]) - min_temp) / span) * 100)
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def classify_outdoor_temp(outdoor_temp: float | None) -> str:
    if outdoor_temp is None:
        return "unknown"
    bins = [(-30, -10), (-10, 0), (0, 10), (10, 20), (20, 35), (35, 60)]
    for lower, upper in bins:
        if lower <= outdoor_temp < upper:
            return f"{lower}..{upper}"
    return "unknown"


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def normalize_hvac_mode(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"heat", "cool", "vent", "auto"}:
        return normalized
    return "heat"


def summarize_room_averages(room_samples: list[dict[str, Any]]) -> tuple[float | None, float | None, float | None]:
    numeric_temps = [float(sample["temperature"]) for sample in room_samples if sample.get("temperature") is not None]
    numeric_setpoints = [float(sample["setpoint"]) for sample in room_samples if sample.get("setpoint") is not None]
    numeric_hysteresis = [float(sample["hysteresis"]) for sample in room_samples if sample.get("hysteresis") is not None]
    avg_temp = sum(numeric_temps) / len(numeric_temps) if numeric_temps else None
    avg_setpoint = sum(numeric_setpoints) / len(numeric_setpoints) if numeric_setpoints else None
    avg_hysteresis = sum(numeric_hysteresis) / len(numeric_hysteresis) if numeric_hysteresis else None
    return avg_temp, avg_setpoint, avg_hysteresis


def should_call_cooling(
    average_temperature: float | None,
    average_setpoint: float | None,
    average_hysteresis: float | None,
) -> bool:
    if None in (average_temperature, average_setpoint, average_hysteresis):
        return False
    return float(average_temperature) >= float(average_setpoint) + float(average_hysteresis)


class OverrideService:
    def __init__(self):
        self.runtime = RuntimeRepository()

    def set_room_override(self, room_id: int, mode: str, duration_minutes: int):
        until_iso = None if mode == "auto" else (
            datetime.utcnow() + timedelta(minutes=max(1, duration_minutes))
        ).isoformat(timespec="seconds")
        self.runtime.set_room_override(room_id, mode, until_iso)

    def set_boiler_override(self, mode: str, duration_minutes: int):
        until_iso = None if mode == "auto" else (
            datetime.utcnow() + timedelta(minutes=max(1, duration_minutes))
        ).isoformat(timespec="seconds")
        self.runtime.set_boiler_override(mode, until_iso)
