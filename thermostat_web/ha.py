from typing import Any, Optional

import requests
from flask import current_app

from .repository import SettingsRepository


class HomeAssistantClient:
    def __init__(self, base_url: Optional[str] = None, token: Optional[str] = None):
        settings = SettingsRepository().get_many(["ha_base_url", "ha_token"])
        resolved_url = base_url or settings.get("ha_base_url") or current_app.config["HA_BASE_URL"]
        resolved_token = token if token is not None else settings.get("ha_token", current_app.config["HA_TOKEN"])
        self.base_url = resolved_url.rstrip("/")
        self.token = resolved_token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def get_state(self, entity_id: str) -> dict[str, Any]:
        resp = requests.get(
            f"{self.base_url}/api/states/{entity_id}",
            headers=self._headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def get_numeric_state(self, entity_id: str) -> Optional[float]:
        state = self.get_state(entity_id).get("state")
        try:
            return float(str(state).replace(",", "."))
        except (TypeError, ValueError):
            return None

    def set_input_boolean(self, entity_id: str, enabled: bool):
        service = "turn_on" if enabled else "turn_off"
        resp = requests.post(
            f"{self.base_url}/api/services/input_boolean/{service}",
            headers=self._headers(),
            json={"entity_id": entity_id},
            timeout=10,
        )
        resp.raise_for_status()
