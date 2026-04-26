#!/usr/bin/env python3
"""
Hubitat temperature monitor for cron.

Runs safely once per hour:
1) Reads a temperature value from a Hubitat device via Maker API.
2) Appends timestamp + value to a local text file.
3) Sends a notification when the reading goes outside configured bounds.
4) Sends one daily summary for the last 24 hours.

It supports either:
- Direct Maker API values (`HUBITAT_APP_ID` + `HUBITAT_ACCESS_TOKEN`), OR
- A full devices endpoint URL (e.g. `/apps/api/3/devices?access_token=...`) via
  `HUBITAT_DEVICES_ENDPOINT`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass
class Config:
    host: str
    app_id: str
    token: str
    temp_device_id: str | None
    temp_device_label: str | None
    notify_device_id: str | None
    notify_device_label: str
    temp_attribute: str
    notify_command: str
    temp_low_f: float
    temp_high_f: float
    log_file: Path
    state_file: Path
    summary_hour_local: int


class ConfigError(Exception):
    pass


def parse_devices_endpoint(endpoint: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc:
        raise ConfigError("HUBITAT_DEVICES_ENDPOINT must be a full URL")

    match = re.search(r"/apps/api/([^/]+)/devices/?$", parsed.path)
    if not match:
        raise ConfigError(
            "HUBITAT_DEVICES_ENDPOINT must look like .../apps/api/<app_id>/devices?access_token=..."
        )

    app_id = match.group(1)
    query = urllib.parse.parse_qs(parsed.query)
    token_vals = query.get("access_token", [])
    if not token_vals or not token_vals[0]:
        raise ConfigError("HUBITAT_DEVICES_ENDPOINT must include access_token query param")

    host = f"{parsed.scheme}://{parsed.netloc}"
    return host, app_id, token_vals[0]


def load_api_details() -> tuple[str, str, str]:
    endpoint = os.getenv("HUBITAT_DEVICES_ENDPOINT", "").strip()
    if endpoint:
        return parse_devices_endpoint(endpoint)

    host = os.getenv("HUBITAT_HOST", "http://192.168.1.117").rstrip("/")
    app_id = os.getenv("HUBITAT_APP_ID", "").strip()
    token = os.getenv("HUBITAT_ACCESS_TOKEN", "").strip()
    if not app_id or not token:
        raise ConfigError(
            "Set HUBITAT_APP_ID + HUBITAT_ACCESS_TOKEN, or set HUBITAT_DEVICES_ENDPOINT."
        )
    return host, app_id, token


def load_config() -> Config:
    host, app_id, token = load_api_details()

    try:
        summary_hour = int(os.getenv("SUMMARY_HOUR_LOCAL", "20"))
    except ValueError as exc:
        raise ConfigError("SUMMARY_HOUR_LOCAL must be an integer between 0 and 23") from exc
    if summary_hour < 0 or summary_hour > 23:
        raise ConfigError("SUMMARY_HOUR_LOCAL must be between 0 and 23")

    try:
        low = float(os.getenv("TEMP_LOW_F", "72"))
        high = float(os.getenv("TEMP_HIGH_F", "74"))
    except ValueError as exc:
        raise ConfigError("TEMP_LOW_F and TEMP_HIGH_F must be numeric") from exc
    if low >= high:
        raise ConfigError("TEMP_LOW_F must be less than TEMP_HIGH_F")

    temp_device_id = os.getenv("TEMP_DEVICE_ID", "104").strip() or None
    temp_device_label = os.getenv("TEMP_DEVICE_LABEL", "").strip() or None
    if not temp_device_id and not temp_device_label:
        raise ConfigError("Set TEMP_DEVICE_ID or TEMP_DEVICE_LABEL")

    notify_device_id = os.getenv("NOTIFY_DEVICE_ID", "").strip() or None
    notify_device_label = os.getenv("NOTIFY_DEVICE_LABEL", "Dad iPhone").strip()

    return Config(
        host=host,
        app_id=app_id,
        token=token,
        temp_device_id=temp_device_id,
        temp_device_label=temp_device_label,
        notify_device_id=notify_device_id,
        notify_device_label=notify_device_label,
        temp_attribute=os.getenv("TEMP_ATTRIBUTE", "sensorTemp"),
        notify_command=os.getenv("NOTIFY_COMMAND", "deviceNotification"),
        temp_low_f=low,
        temp_high_f=high,
        log_file=Path(os.getenv("LOG_FILE", "./hubitat_temp_log.txt")),
        state_file=Path(os.getenv("STATE_FILE", "./hubitat_temp_state.json")),
        summary_hour_local=summary_hour,
    )


def maker_api_get_json(url: str) -> Any:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=15) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def maker_api_get(url: str) -> str:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode("utf-8")


def build_url(config: Config, path: str) -> str:
    token = urllib.parse.quote(config.token)
    return f"{config.host}/apps/api/{config.app_id}{path}?access_token={token}"


def fetch_all_devices(config: Config) -> list[dict[str, Any]]:
    url = build_url(config, "/devices")
    payload = maker_api_get_json(url)
    return payload if isinstance(payload, list) else []


def resolve_device_id_by_label(config: Config, label: str) -> str:
    label_lower = label.lower().strip()
    devices = fetch_all_devices(config)
    for device in devices:
        candidates = [
            str(device.get("label", "")).strip(),
            str(device.get("name", "")).strip(),
        ]
        if any(c.lower() == label_lower for c in candidates if c):
            return str(device.get("id"))
    raise RuntimeError(f"Could not find device with label/name '{label}'")


def get_temperature_f(config: Config, temp_device_id: str) -> float:
    url = build_url(config, f"/devices/{temp_device_id}")
    payload = maker_api_get_json(url)

    attrs = payload.get("attributes", []) if isinstance(payload, dict) else []
    for attr in attrs:
        if str(attr.get("name", "")).lower() == config.temp_attribute.lower():
            return float(attr.get("currentValue"))

    if isinstance(payload, dict) and config.temp_attribute in payload:
        return float(payload[config.temp_attribute])

    # Compatibility fallback for common Hubitat naming.
    if config.temp_attribute != "temperature":
        attrs_lower = {str(a.get("name", "")).lower(): a for a in attrs if isinstance(a, dict)}
        temp_attr = attrs_lower.get("temperature")
        if temp_attr and "currentValue" in temp_attr:
            return float(temp_attr["currentValue"])
        if isinstance(payload, dict) and "temperature" in payload:
            return float(payload["temperature"])

    raise RuntimeError(
        f"Temperature attribute '{config.temp_attribute}' not found on device {temp_device_id}"
    )


def send_notification(config: Config, notify_device_id: str, message: str) -> None:
    encoded_msg = urllib.parse.quote(message)
    path = f"/devices/{notify_device_id}/{config.notify_command}/{encoded_msg}"
    url = build_url(config, path)
    maker_api_get(url)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_log(log_file: Path, timestamp: datetime, temp_f: float) -> None:
    ensure_parent(log_file)
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp.isoformat()},{temp_f:.2f}\n")


def read_last_24h(log_file: Path, now: datetime) -> list[tuple[datetime, float]]:
    if not log_file.exists():
        return []

    since = now - timedelta(hours=24)
    rows: list[tuple[datetime, float]] = []
    with log_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ts_raw, temp_raw = line.split(",", 1)
                ts = datetime.fromisoformat(ts_raw)
                temp = float(temp_raw)
            except Exception:
                continue
            if ts >= since:
                rows.append((ts, temp))
    return rows


def load_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        with state_file.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state_file: Path, state: dict[str, Any]) -> None:
    ensure_parent(state_file)
    with state_file.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def maybe_send_threshold_notification(
    config: Config, state: dict[str, Any], notify_device_id: str, temp_f: float
) -> None:
    out_of_range = temp_f < config.temp_low_f or temp_f > config.temp_high_f
    prev_out_of_range = bool(state.get("out_of_range", False))

    if out_of_range and not prev_out_of_range:
        send_notification(
            config,
            notify_device_id,
            (
                f"Box Sensor alert: {temp_f:.1f}F is outside range "
                f"{config.temp_low_f:.1f}-{config.temp_high_f:.1f}F"
            ),
        )
    elif (not out_of_range) and prev_out_of_range:
        send_notification(
            config,
            notify_device_id,
            (
                f"Box Sensor recovered: {temp_f:.1f}F is back within "
                f"{config.temp_low_f:.1f}-{config.temp_high_f:.1f}F"
            ),
        )

    state["out_of_range"] = out_of_range


def maybe_send_daily_summary(
    config: Config, state: dict[str, Any], notify_device_id: str, now: datetime
) -> None:
    if now.hour != config.summary_hour_local:
        return

    today = now.date().isoformat()
    if state.get("last_summary_date") == today:
        return

    rows = read_last_24h(config.log_file, now)
    if not rows:
        send_notification(config, notify_device_id, "Box Sensor daily summary: no data in the last 24h.")
        state["last_summary_date"] = today
        return

    values = [temp for _, temp in rows]
    min_t = min(values)
    max_t = max(values)
    avg_t = statistics.mean(values)
    latest_ts, latest_temp = rows[-1]

    message = (
        "Box Sensor 24h summary: "
        f"samples={len(values)}, min={min_t:.1f}F, max={max_t:.1f}F, "
        f"avg={avg_t:.1f}F, latest={latest_temp:.1f}F @ {latest_ts.strftime('%H:%M')}"
    )
    send_notification(config, notify_device_id, message)
    state["last_summary_date"] = today


def list_devices(config: Config) -> int:
    devices = fetch_all_devices(config)
    if not devices:
        print("No devices returned.")
        return 1
    for device in devices:
        print(
            f"id={device.get('id')}\tlabel={device.get('label')}\t"
            f"name={device.get('name')}\ttype={device.get('type')}"
        )
    return 0


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hubitat temperature monitor")
    parser.add_argument("--list-devices", action="store_true", help="List devices and exit")
    args = parser.parse_args(argv)

    try:
        config = load_config()

        if args.list_devices:
            return list_devices(config)

        temp_device_id = config.temp_device_id or resolve_device_id_by_label(
            config, config.temp_device_label or ""
        )
        notify_device_id = config.notify_device_id or resolve_device_id_by_label(
            config, config.notify_device_label
        )

        now = datetime.now().astimezone()
        temp_f = get_temperature_f(config, temp_device_id)

        append_log(config.log_file, now, temp_f)

        state = load_state(config.state_file)
        maybe_send_threshold_notification(config, state, notify_device_id, temp_f)
        maybe_send_daily_summary(config, state, notify_device_id, now)
        save_state(config.state_file, state)

        print(
            "OK "
            f"{now.isoformat()} temp={temp_f:.2f}F "
            f"temp_device_id={temp_device_id} notify_device_id={notify_device_id}"
        )
        return 0
    except ConfigError as exc:
        print(f"CONFIG ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
