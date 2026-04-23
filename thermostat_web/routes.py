from flask import Blueprint, redirect, render_template, request, url_for

from .repository import BoilerRepository, RoomRepository, RuntimeRepository, SettingsRepository
from .services import ControllerService, DashboardService, OverrideService

bp = Blueprint("web", __name__)


def _room_form_data(form) -> dict:
    return {
        "name": form.get("name", "").strip(),
        "temperature_entity_id": form.get("temperature_entity_id", "").strip(),
        "valve_entity_id": form.get("valve_entity_id", "").strip(),
        "setpoint_entity_id": form.get("setpoint_entity_id", "").strip(),
        "hysteresis_entity_id": form.get("hysteresis_entity_id", "").strip(),
        "circadian_enabled_entity_id": form.get("circadian_enabled_entity_id", "").strip(),
        "circadian_night_start": form.get("circadian_night_start", "22:00").strip() or "22:00",
        "circadian_morning_start": form.get("circadian_morning_start", "05:30").strip() or "05:30",
        "circadian_night_delta": form.get("circadian_night_delta", "0").strip() or "0",
        "circadian_morning_delta": form.get("circadian_morning_delta", "0").strip() or "0",
        "enabled": form.get("enabled") == "on",
        "learning_enabled": form.get("learning_enabled") == "on",
    }


@bp.route("/")
def dashboard():
    data = DashboardService().dashboard_data()
    return render_template("dashboard.html", **data)


@bp.route("/settings", methods=["POST"])
def update_settings():
    SettingsRepository().set_many(
        {
            "ha_base_url": request.form.get("ha_base_url", "").strip(),
            "ha_token": request.form.get("ha_token", "").strip(),
            "outdoor_entity_id": request.form.get("outdoor_entity_id", "").strip(),
            "hvac_mode_entity_id": request.form.get("hvac_mode_entity_id", "").strip(),
            "controller_interval_seconds": request.form.get("controller_interval_seconds", "30").strip() or "30",
            "feature_multi_room_logic": "1" if request.form.get("feature_multi_room_logic") == "on" else "0",
            "feature_predictive_cutoff": "1" if request.form.get("feature_predictive_cutoff") == "on" else "0",
        }
    )
    RuntimeRepository().update_system_runtime(
        controller_enabled=int(request.form.get("controller_enabled") == "on"),
        learning_debug_enabled=int(request.form.get("learning_debug_enabled") == "on"),
    )
    return redirect(url_for("web.dashboard"))


@bp.route("/rooms/new", methods=["GET", "POST"])
def create_room():
    if request.method == "POST":
        RoomRepository().create_room(_room_form_data(request.form))
        return redirect(url_for("web.dashboard"))
    return render_template("room_form.html", room=None)


@bp.route("/rooms/<int:room_id>/edit", methods=["GET", "POST"])
def edit_room(room_id: int):
    repo = RoomRepository()
    room = repo.get_room(room_id)
    if request.method == "POST":
        repo.update_room(room_id, _room_form_data(request.form))
        return redirect(url_for("web.dashboard"))
    return render_template("room_form.html", room=room)


@bp.route("/rooms/<int:room_id>")
def room_detail(room_id: int):
    data = DashboardService().room_detail_data(room_id)
    return render_template("room_detail.html", **data)


@bp.route("/rooms/<int:room_id>/delete", methods=["POST"])
def delete_room(room_id: int):
    RoomRepository().delete_room(room_id)
    return redirect(url_for("web.dashboard"))


@bp.route("/boiler", methods=["POST"])
def update_boiler():
    BoilerRepository().update(
        {
            "name": request.form.get("name", "").strip(),
            "heating_entity_id": request.form.get("heating_entity_id", "").strip(),
            "pump_entity_id": request.form.get("pump_entity_id", "").strip(),
            "pump_overrun_minutes": request.form.get("pump_overrun_minutes", "90").strip() or "90",
            "enabled": request.form.get("enabled") == "on",
        }
    )
    return redirect(url_for("web.dashboard"))


@bp.route("/controller/sample", methods=["POST"])
def sample_controller():
    ControllerService().sample_once()
    return redirect(url_for("web.dashboard"))


@bp.route("/rooms/<int:room_id>/override", methods=["POST"])
def room_override(room_id: int):
    OverrideService().set_room_override(
        room_id,
        request.form.get("mode", "auto"),
        int(request.form.get("duration_minutes", "60") or "60"),
    )
    return redirect(url_for("web.room_detail", room_id=room_id))


@bp.route("/boiler/override", methods=["POST"])
def boiler_override():
    OverrideService().set_boiler_override(
        request.form.get("mode", "auto"),
        int(request.form.get("duration_minutes", "60") or "60"),
    )
    return redirect(url_for("web.dashboard"))
