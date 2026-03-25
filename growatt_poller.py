import requests
import hashlib
import time
import json
import os
from datetime import datetime

# ── Config from environment variables ────────────────────────
BASE_URL     = os.environ.get("BASE_URL", "https://shiner-us.growatt.com").rstrip("/")
DEVICE_SN    = os.environ.get("GROWATT_DEVICE_SN", "")
USERNAME     = os.environ["GROWATT_USERNAME"]
PASSWORD     = os.environ["GROWATT_PASSWORD"]
US_AUTHORIZE = "0f0eb546e47cabb05093efe2887b9137"

HA_URL   = os.environ.get("HA_URL", "http://homeassistant.local:8123")
HA_TOKEN = os.environ["HA_TOKEN"]
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))

# Server-side sessions expire after ~15 minutes regardless of JWT exp claim.
# Re-login proactively at 13 minutes to stay ahead of the cutoff.
TOKEN_LIFETIME = 13 * 60  # seconds

HA_HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type": "application/json"
}

access_token = None
token_acquired_at = 0  # epoch seconds

# ── Auth helpers ──────────────────────────────────────────────
def sha1(s):
    return hashlib.sha1(s.encode('utf-8')).hexdigest()

def login(retry=3, backoff=5):
    """
    Full login with retry and exponential backoff.
    The server enforces ~15 min server-side session expiry independent of JWT exp.
    We re-login proactively at 13 min via token_is_stale() to avoid mid-poll 401s.
    """
    global access_token, token_acquired_at
    for attempt in range(1, retry + 1):
        try:
            session = requests.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept": "application/json"
            })

            r = session.get(f"{BASE_URL}/web/v1/auth/login", timeout=15)
            if r.status_code != 200:
                raise Exception(f"getLoginKey failed: {r.status_code}")
            login_key = r.json()["data"]["key"]

            captcha_resp = session.post(f"{BASE_URL}/web/v1/auth/captcha", timeout=15)
            captcha_data = captcha_resp.json()["data"]

            payload = {
                "username": USERNAME,
                "password": sha1(login_key + sha1(PASSWORD)),
                "captcha": "",
                "captchaKey": captcha_data["captchaKey"],
                "us_authorize": US_AUTHORIZE,
                "expire_minutes": 43200
            }
            login_resp = session.post(f"{BASE_URL}/web/v1/auth/login", json=payload, timeout=15)

            if login_resp.status_code == 200 and login_resp.json().get("code") == 0:
                access_token = login_resp.json()["data"]["accessToken"]
                token_acquired_at = time.time()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ Logged in")
                return True
            else:
                raise Exception(f"Login rejected: {login_resp.text[:200]}")

        except Exception as e:
            if attempt < retry:
                wait = backoff * attempt
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Login attempt {attempt}/{retry} failed: {e} — retrying in {wait}s")
                time.sleep(wait)
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Login failed after {retry} attempts: {e}")
                return False

def token_is_stale():
    """Returns True if the token is older than TOKEN_LIFETIME seconds."""
    return (time.time() - token_acquired_at) >= TOKEN_LIFETIME

# ── HA helpers ────────────────────────────────────────────────
def push_to_ha(entity_id, state, attributes):
    try:
        requests.post(
            f"{HA_URL}/api/states/{entity_id}",
            headers=HA_HEADERS,
            json={"state": state, "attributes": attributes},
            timeout=5
        )
    except Exception as e:
        print(f"  HA push failed for {entity_id}: {e}")

def send_ha_notification(title, message):
    try:
        requests.post(
            f"{HA_URL}/api/services/persistent_notification/create",
            headers=HA_HEADERS,
            json={"title": title, "message": message, "notification_id": "growatt_poller"},
            timeout=5
        )
    except Exception as e:
        print(f"  HA notification failed: {e}")

# ── Startup check ─────────────────────────────────────────────
def test_connections():
    print("Testing connections...")
    all_ok = True

    print("  Growatt login...", end=" ", flush=True)
    if login():
        print("✓")
    else:
        print("❌ Check GROWATT_USERNAME and GROWATT_PASSWORD")
        all_ok = False

    print("  Inverter data...", end=" ", flush=True)
    try:
        r = requests.get(
            f"{BASE_URL}/web/v1/inverter/{DEVICE_SN}/diagram",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10
        )
        if r.status_code == 200:
            pv = r.json()["data"].get("pvPower", 0)
            print(f"✓ (PV: {pv}W)")
        else:
            print(f"❌ Got {r.status_code}")
            all_ok = False
    except Exception as e:
        print(f"❌ {e}")
        all_ok = False

    print("  Home Assistant...", end=" ", flush=True)
    try:
        r = requests.get(f"{HA_URL}/api/", headers=HA_HEADERS, timeout=5)
        if r.status_code == 200:
            print(f"✓ ({HA_URL})")
        else:
            print(f"❌ Got {r.status_code} — check HA_TOKEN")
            all_ok = False
    except Exception as e:
        print(f"❌ {e} — check HA_URL")
        all_ok = False

    print()
    return all_ok

# ── Poll ──────────────────────────────────────────────────────
def poll():
    global access_token

    # Proactively re-login before server-side session expires (~15 min)
    if token_is_stale():
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Token is 13min old — refreshing proactively...")
        if not login():
            print("❌ Proactive re-login failed — skipping poll, will retry next interval")
            return

    try:
        r = requests.get(
            f"{BASE_URL}/web/v1/inverter/{DEVICE_SN}/diagram",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
            timeout=10
        )

        if r.status_code == 401:
            # Fallback — shouldn't happen often given proactive refresh above
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 401 received — re-logging in...")
            if login():
                r = requests.get(
                    f"{BASE_URL}/web/v1/inverter/{DEVICE_SN}/diagram",
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                    timeout=10
                )
            else:
                send_ha_notification(
                    "❌ Growatt Poller Login Failed",
                    "Could not re-authenticate with Growatt. Check GROWATT_USERNAME / GROWATT_PASSWORD."
                )
                return

        r.raise_for_status()
        d = r.json()["data"]

        pv_power         = d.get("pvPower", 0)
        load_power       = d.get("loadPower", 0)
        from_grid        = d.get("sphFromGridPower", 0)
        to_grid          = d.get("sphToGridPower", 0)
        battery_soc      = d.get("sphBatterySoc", 0)
        today_solar      = d.get("etodayFromSolar", 0)
        today_to_grid    = d.get("v2TodayToGrid", 0)
        today_from_grid  = d.get("v2TodayFromGrid", 0)
        total_production = d.get("v2TotalProduction", 0)

        push_to_ha("sensor.growatt_pv_power", pv_power,
            {"friendly_name": "Growatt PV Power", "unit_of_measurement": "W", "device_#lass": "power", "state_class": "measurement"})
        push_to_ha("sensor.growatt_load_power", load_power,
            {"friendly_name": "Growatt Load Power", "unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"})
        push_to_ha("sensor.growatt_grid_import", from_grid,
            {"friendly_name": "Growatt Grid Import", "unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"})
        push_to_ha("sensor.growatt_grid_export", to_grid,
            {"friendly_name": "Growatt Grid Export", "unit_of_measurement": "W", "device_class": "power", "state_class": "measurement"})
        push_to_ha("sensor.growatt_battery_soc", battery_soc,
            {"friendly_name": "Growatt Battery SOC", "unit_of_measurement": "%", "device_class": "battery", "state_class": "measurement"})
        push_to_ha("sensor.growatt_today_solar", today_solar,
            {"friendly_name": "Growatt Solar Today", "unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
        push_to_ha("sensor.growatt_today_to_grid", today_to_grid,
            {"friendly_name": "Growatt Export Today", "unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
        push_to_ha("sensor.growatt_today_from_grid", today_from_grid,
            {"friendly_name": "Growatt Import Today", "unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
        push_to_ha("sensor.growatt_total_production", total_production,
            {"friendly_name": "Growatt Total Production", "unit_of_measurement": "kWh", "device_class": "energy", "state_class": "total_increasing"})
        push_to_ha("sensor.growatt_last_updated",
            datetime.now().isoformat(),
            {"friendly_name": "Growatt Last Updated", "device_class": "timestamp"})

        now = datetime.now().strftime("%H:%M:%S")
        print(f"[{now}] PV: {pv_power}W | Load: {load_power}W | Grid: +{from_grid}W/-{to_grid}W | SOC: {battery_soc}% | Today: {today_solar}kWh")

    except requests.exceptions.HTTPError as e:
        print(f"HTTP error: {e}")
    except Exception as e:
        print(f"Poll error: {e}")

# ── Main ──────────────────────────────────────────────────────
print("=" * 55)
print("  Growatt → Home Assistant Bridge")
print("=" * 55)

if test_connections():
    print(f"All systems go — polling every {POLL_INTERVAL}s\n")
    poll()
    while True:
        time.sleep(POLL_INTERVAL)
        poll()
else:
    print("❌ Startup checks failed — fix the issues above and restart")
