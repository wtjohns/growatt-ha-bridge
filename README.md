# growatt-ha-bridge

Polls your Growatt solar inverter every 5 minutes and pushes real-time power data to Home Assistant as sensors. Built for the `shiner-us.growatt.com` portal (US/Canada), with support for other regional portals.

Runs as a Docker container — designed for Unraid but works anywhere Docker runs.

## Sensors created in Home Assistant

| Entity | Unit | Description |
|---|---|---|
| `sensor.growatt_pv_power` | W | Solar generation (live) |
| `sensor.growatt_load_power` | W | House load (live) |
| `sensor.growatt_grid_import` | W | Importing from grid |
| `sensor.growatt_grid_export` | W | Exporting to grid |
| `sensor.growatt_battery_soc` | % | Battery state of charge |
| `sensor.growatt_today_solar` | kWh | Solar production today |
| `sensor.growatt_today_to_grid` | kWh | Exported to grid today |
| `sensor.growatt_today_from_grid` | kWh | Imported from grid today |
| `sensor.growatt_total_production` | kWh | Lifetime production |
| `sensor.growatt_last_updated` | timestamp | Watchdog — last successful poll |

## Requirements

- Growatt inverter registered on a Growatt portal (see [Regional portals](#regional-portals))
- Home Assistant with a long-lived access token
- Docker (Unraid, standalone, or docker-compose)

## Installation on Unraid

### 1. Build the image

SSH into your Unraid server and run:

```bash
mkdir -p /mnt/user/appdata/growatt-poller
cd /mnt/user/appdata/growatt-poller
git clone https://github.com/wtjohns/growatt-ha-bridge.git .
docker build -t growatt-poller .
```

### 2. Install the template

Copy `growatt-poller.xml` to your Unraid USB templates folder:

```bash
cp /mnt/user/appdata/growatt-poller/growatt-poller.xml \
   /boot/config/plugins/dockerMan/templates-user/
```

### 3. Add the container

In the Unraid UI: **Docker → Add Container → scroll to "User templates"** → select `growatt-poller`.

Fill in the fields:

| Field | Description |
|---|---|
| Growatt Portal URL | Your regional portal URL (default: `https://shiner-us.growatt.com`) |
| Growatt Username | Your Growatt portal email |
| Growatt Password | Your Growatt portal password |
| Device Serial Number | Your inverter serial (find it on the portal or inverter label) |
| Home Assistant URL | e.g. `http://192.168.1.100:8123` |
| Home Assistant Token | Long-lived access token from HA |
| Poll Interval | Seconds between polls (default: `300`) |

### 4. Generate a Home Assistant token

In Home Assistant: **Profile → Long-Lived Access Tokens → Create Token**

## Installation with docker-compose

Create a `.env` file alongside `docker-compose.yml`:

```env
GROWATT_USERNAME=you@example.com
GROWATT_PASSWORD=yourpassword
GROWATT_DEVICE_SN=ABC1234567
HA_URL=http://192.168.1.100:8123
HA_TOKEN=your_ha_long_lived_token
# Optional:
BASE_URL=https://shiner-us.growatt.com
POLL_INTERVAL_SECONDS=300
```

Then:

```bash
docker-compose up -d
```

## Regional portals

Set `BASE_URL` to match your region:

| Region | Portal URL |
|---|---|
| US / Canada | `https://shiner-us.growatt.com` *(default)* |
| Global | `https://server.growatt.com` |
| EU | `https://server-api.growatteurope.com` |
| Australia | `https://server-api.growattcloud.com.au` |

## Notes on authentication

This integration was reverse-engineered from the Growatt web portal's JavaScript. A few things discovered along the way that differ from older Growatt libraries:

- **No captcha enforcement** — the portal shows a captcha but the server doesn't validate it; a blank string is accepted
- **Server-side session expiry** — the server enforces a ~15 minute session lifetime independent of the JWT exp claim; the poller re-loggins proactively at 13 minutes to stay ahead of this
- **Password hashing** — `sha1(loginKey + sha1(password))` using the `loginKey` returned from `GET /web/v1/auth/login`
- **`us_authorize`** — a static app token required in the login body: `0f0eb546e47cabb05093efe2887b9137a

The poller logs in once on startup and reuses the token indefinitely, re-authenticating only on a genuine 401 response.

## Tested with

- Growatt SPH 10000TL-HU-US(B) inverter
- `shiner-us.growatt.com` portal

## License

MIT
