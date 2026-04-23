import os

from thermostat_web import create_app


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("THERMOSTAT_HOST", "0.0.0.0")
    port = int(os.environ.get("THERMOSTAT_PORT", "5001"))
    debug = os.environ.get("THERMOSTAT_DEBUG", "true").strip().lower() in {"1", "true", "yes", "on"}
    app.run(host=host, port=port, debug=debug)
