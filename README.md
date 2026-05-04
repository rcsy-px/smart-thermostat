# Smart Thermostat

A small Flask web application for controlling and observing a Home Assistant based smart thermostat setup. It manages rooms, boiler and pump state, heating/cooling decisions, manual overrides, floorplan zones, and simple learning data from recent room behavior.

The app uses a local SQLite database that is created automatically on startup. The database file is intentionally not committed so anyone trying the project starts with clean local data.

## Features

- Room configuration with Home Assistant entity IDs for temperature, valve, setpoint, and hysteresis.
- Boiler and pump control through Home Assistant `input_boolean` entities.
- Dashboard with room status, controller runtime state, floorplan zones, and system settings.
- Single-room and optional multi-room heating logic.
- Optional predictive cutoff based on simple learning profiles.
- Heating, cooling, ventilation, and auto HVAC mode handling.
- Manual room and boiler overrides with automatic expiry.
- Circadian setpoint adjustment support.
- Recent samples, events, and learning profile views per room.

## Tech Stack

- Python
- Flask
- SQLite
- Requests
- Home Assistant REST API

## Project Structure

```text
.
├── app.py                    # Application entrypoint
├── requirements.txt          # Python dependencies
└── thermostat_web/
    ├── __init__.py           # Flask app factory
    ├── db.py                 # SQLite schema and default seed data
    ├── ha.py                 # Home Assistant API client
    ├── models.py             # Dataclasses for domain objects
    ├── repository.py         # Database access layer
    ├── routes.py             # Web routes
    ├── services.py           # Thermostat control logic
    ├── worker.py             # Background controller worker
    ├── static/               # CSS assets
    └── templates/            # Jinja templates
```

## Requirements

- Python 3.10 or newer
- A Home Assistant instance if you want to control real entities

## Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python app.py
```

By default, the app listens on:

```text
http://localhost:5001
```

## Configuration

The app starts with development defaults and stores editable runtime settings in the local SQLite database. Configure Home Assistant connection details from the dashboard:

- Home Assistant base URL
- Long-lived access token
- Outdoor temperature entity
- HVAC mode entity
- Controller interval
- Optional feature flags

The entrypoint also supports these environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `THERMOSTAT_HOST` | `0.0.0.0` | Host address used by Flask. |
| `THERMOSTAT_PORT` | `5001` | Port used by Flask. |
| `THERMOSTAT_DEBUG` | `true` | Enables Flask debug mode when set to `1`, `true`, `yes`, or `on`. |

## Local Database

`thermostat.db` is created automatically when the app starts. It contains local configuration, Home Assistant tokens, room definitions, runtime state, samples, and learning data.

For privacy and clean test runs, the database is excluded from version control. Delete `thermostat.db` if you want to reset the app to a fresh local state.

## Home Assistant Notes

The controller expects Home Assistant entity IDs for:

- Room temperature sensors
- Room valve controls
- Room setpoints
- Room hysteresis values
- Boiler heating control
- Boiler pump control
- Optional outdoor temperature and HVAC mode entities

Boolean controls are toggled through the Home Assistant REST API using `input_boolean.turn_on` and `input_boolean.turn_off`.

## Development

Run a quick syntax check:

```bash
python -m py_compile app.py thermostat_web\__init__.py thermostat_web\db.py thermostat_web\models.py thermostat_web\repository.py thermostat_web\ha.py thermostat_web\services.py thermostat_web\routes.py thermostat_web\worker.py
```

There is no dedicated test suite in this repository yet.

## License

No license file is currently included. Add one before publishing or distributing the project.
