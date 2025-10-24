# helpers_weather.py
import os, requests, sqlite3
from datetime import datetime, timedelta
import json


# ==========================================================
# CONFIG
# ==========================================================
VC_API_KEY = os.getenv("VISUAL_CROSSING_KEY")  # store in .env or environment
VC_BASE_URL = "https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline"
CACHE_FILE = "weather_cache.db"  # local SQLite cache
CACHE_TTL_HOURS = 24             # re-fetch daily

LAT = 34.05909528965243   # CheckOut coords
LON = 35.64522931420599

# ==========================================================
# DB SETUP
# ==========================================================
def _init_cache():
    conn = sqlite3.connect(CACHE_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS weather_cache (
            date TEXT PRIMARY KEY,
            temp REAL,
            condition TEXT,
            icon TEXT,
            last_fetched DATETIME
        )
    """)
    conn.commit()
    conn.close()

_init_cache()

# ==========================================================
# FETCH FROM API
# ==========================================================
def _fetch_from_api(date_str: str):
    url = f"{VC_BASE_URL}/{LAT},{LON}/{date_str}"
    params = {
        "unitGroup": "metric",
        "include": "days",
        "key": VC_API_KEY,
        "contentType": "json",
    }
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    js = r.json()
    day = js["days"][0]
    temp = day.get("temp", 0)
    cond = day.get("conditions", "")
    icon = f"https://raw.githubusercontent.com/visualcrossing/WeatherIcons/main/PNG/2nd Set - Color/{day.get('icon', 'na')}.png"
    return {"temp": temp, "condition": cond, "icon": icon}

# ==========================================================
# MAIN PUBLIC FUNCTION
# ==========================================================
def get_weather(date_str: str):
    """Return dict { temp, condition, icon } for given date."""
    conn = sqlite3.connect(CACHE_FILE)
    cur = conn.cursor()
    cur.execute("SELECT temp, condition, icon, last_fetched FROM weather_cache WHERE date = ?", (date_str,))
    row = cur.fetchone()

    if row:
        temp, cond, icon, last_fetched = row
        last_dt = datetime.fromisoformat(last_fetched)
        if datetime.now() - last_dt < timedelta(hours=CACHE_TTL_HOURS):
            conn.close()
            return {"temp": temp, "condition": cond, "icon": icon}

    # fetch fresh
    data = _fetch_from_api(date_str)

    cur.execute("""
        INSERT OR REPLACE INTO weather_cache (date, temp, condition, icon, last_fetched)
        VALUES (?, ?, ?, ?, ?)
    """, (date_str, data["temp"], data["condition"], data["icon"], datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return data


def get_weather_hourly_5weeks(date_str: str):
    """
    Fetch hourly weather for the given date and the same weekday
    across the previous 4 weeks. Returns structure compatible with tooltips.
    """

    # Parse base date and compute previous 4 same weekdays
    base_date = datetime.strptime(date_str, "%Y-%m-%d")
    target_dates = [base_date - timedelta(weeks=i) for i in range(5)]

    conn = sqlite3.connect(CACHE_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS weather_cache_hourly (
            date TEXT PRIMARY KEY,
            json_data TEXT,
            last_fetched DATETIME
        )
    """)

    series = []

    for d in target_dates:
        d_str = d.strftime("%Y-%m-%d")

        # Try cached hourly data
        cur.execute(
            "SELECT json_data, last_fetched FROM weather_cache_hourly WHERE date = ?", (d_str,)
        )
        row = cur.fetchone()
        data = None

        if row:
            json_data, last_fetched = row
            last_dt = datetime.fromisoformat(last_fetched)
            if datetime.now() - last_dt < timedelta(hours=CACHE_TTL_HOURS):
                data = json.loads(json_data)

        # If not cached or expired, fetch fresh hourly data
        if not data:
            url = f"{VC_BASE_URL}/{LAT},{LON}/{d_str}"
            params = {
                "unitGroup": "metric",
                "include": "hours",
                "key": VC_API_KEY,
                "contentType": "json",
            }
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            js = r.json()
            hours = js["days"][0].get("hours", [])
            
            data = []
            for h in hours:
                dt_str = h.get("datetime", "")
                try:
                    if "T" in dt_str:
                        hour_val = datetime.fromisoformat(dt_str).hour
                    else:
                        hour_val = int(dt_str.split(":")[0])
                except Exception:
                    hour_val = 0

                data.append({
                    "hour": hour_val,
                    "temp": h.get("temp"),
                    "cond": h.get("conditions"),
                    "icon": h.get("icon"),
                })


            # Cache the fresh result
            cur.execute(
                "INSERT OR REPLACE INTO weather_cache_hourly VALUES (?, ?, ?)",
                (d_str, json.dumps(data), datetime.now().isoformat()),
            )
            conn.commit()

        series.append({"date": d_str, "hours": data})

    conn.close()

    return {"date": date_str, "series": series}