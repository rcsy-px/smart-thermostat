import os
import threading
import time

from flask import Flask

from .services import ControllerService


class ControllerWorker:
    def __init__(self, app: Flask):
        self.app = app
        self._thread = None
        self._stop = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="thermostat-controller", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            interval = 30
            with self.app.app_context():
                try:
                    ControllerService().sample_once()
                except Exception as exc:
                    ControllerService().runtime.update_system_runtime(
                        last_controller_run_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                        last_controller_status="error",
                        last_controller_error=str(exc),
                    )
                try:
                    settings = ControllerService().settings.get_many(["controller_interval_seconds"])
                    interval = max(5, int(float(settings.get("controller_interval_seconds", "30"))))
                except Exception:
                    interval = 30
            self._stop.wait(interval)

    def stop(self):
        self._stop.set()


def should_start_worker(app: Flask) -> bool:
    if not app.config.get("ENABLE_CONTROLLER_WORKER", True):
        return False
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return True
    return not app.debug
