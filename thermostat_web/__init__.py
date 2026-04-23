from flask import Flask

from .db import init_db
from .routes import bp
from .worker import ControllerWorker, should_start_worker


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY="dev",
        DATABASE="thermostat.db",
        HA_BASE_URL="http://homeassistant.local:8123",
        HA_TOKEN="",
        ENABLE_CONTROLLER_WORKER=True,
    )

    init_db(app)
    app.register_blueprint(bp)
    worker = ControllerWorker(app)
    app.extensions["controller_worker"] = worker
    if should_start_worker(app):
        worker.start()
    return app
