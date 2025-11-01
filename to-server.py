#!/usr/bin/env python3

import time
import json
import requests
from datetime import datetime

# ---------------- CONFIG ----------------
ALERTS_FILE = r"C:\url-block\logs.json"
API_ENDPOINT = "http://192.168.1.189:5001/logs"  # your Flask server
POLL_INTERVAL = 1  # seconds
# ---------------------------------------


def send_raw_alert(alert):
    """
    Send the raw Wazuh alert JSON to the API endpoint.
    """
    try:
        response = requests.post(API_ENDPOINT, json=alert)
        print(f"[{datetime.now()}] Sent alert, status: {response.status_code}")
    except Exception as e:
        print(f"[{datetime.now()}] ERROR sending alert: {e}")


def follow(file):
    """
    Generator function that yields new lines as they are written to the file.
    Similar to `tail -f`.
    """
    file.seek(0, 2)  # move to end of file
    while True:
        line = file.readline()
        if not line:
            time.sleep(POLL_INTERVAL)
            continue
        yield line


if __name__ == "__main__":
    print(f"[{datetime.now()}] Monitoring {ALERTS_FILE} ...")
    try:
        with open(ALERTS_FILE, "r") as f:
            for line in follow(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    alert = json.loads(line)  # raw log JSON
                    send_raw_alert(alert)
                except json.JSONDecodeError:
                    # ignore incomplete lines or junk
                    continue
    except KeyboardInterrupt:
        print(f"[{datetime.now()}] Stopped by user")