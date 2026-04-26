# Hubitat Temperature Monitor (cron)

## What it does
- Reads temperature from one Hubitat sensor every run.
- Appends `timestamp,temperature` to a local text file.
- Sends an alert if temperature leaves 72F-74F (configurable).
- Sends a recovery notification when temperature returns to range.
- Sends one daily summary (default: 8PM local) with min/max/avg/latest values from the last 24 hours.

## Files
- Script: `hubitat_temp_monitor.py`
- Default log file: `./hubitat_temp_log.txt`
- Default state file: `./hubitat_temp_state.json`

## Recommended setup (uses your full endpoint)
Use the endpoint you provided:

```bash
export HUBITAT_DEVICES_ENDPOINT='http://192.168.1.117/apps/api/3/devices?access_token=b717e183-95cc-42e2-a8dd-7fa5f88e8f86'
```

Then set:

```bash
export TEMP_DEVICE_ID='104'
export NOTIFY_DEVICE_LABEL='Dad iPhone'
export SUMMARY_HOUR_LOCAL='20'
```

That is enough for a first run.

## Alternative setup (explicit app/token)
```bash
export HUBITAT_HOST='http://192.168.1.117'
export HUBITAT_APP_ID='3'
export HUBITAT_ACCESS_TOKEN='...'
```

## Optional environment variables
```bash
export NOTIFY_DEVICE_ID='123'             # If set, overrides label lookup
export TEMP_DEVICE_LABEL='Box Sensor'     # Used if TEMP_DEVICE_ID is unset
export TEMP_LOW_F='72'
export TEMP_HIGH_F='74'
export TEMP_ATTRIBUTE='sensorTemp'       # default in script
export NOTIFY_COMMAND='deviceNotification'
export LOG_FILE='/var/log/hubitat_temp_log.txt'
export STATE_FILE='/var/lib/hubitat_temp_state.json'
```

## Find your device IDs (optional)
```bash
python3 hubitat_temp_monitor.py --list-devices
```

## Test once
```bash
python3 hubitat_temp_monitor.py
```

## Cron (hourly)
Use `crontab -e` and add:

```cron
0 * * * * /usr/bin/env bash -lc 'source /opt/hubitat-monitor/env.sh && /usr/bin/python3 /path/to/hubitat_temp_monitor.py >> /var/log/hubitat_temp_monitor.log 2>&1'
```

Where `/opt/hubitat-monitor/env.sh` contains your exported variables.

## Notes
- This script uses Hubitat Maker API endpoints.
- Recovery notifications are enabled.
- Daily summary hour is local time; `20` means **8:00 PM**.
