#!/usr/bin/env python3
"""Preprocessing script for OpenClaw fitness coach.

Fetches Strava activities, Apple Watch CSVs, and food orders,
then outputs a compact JSON summary for the LLM to analyze.

Usage:
  python3 coach_data.py --mode daily    # Yesterday's data
  python3 coach_data.py --mode weekly   # This week + last week
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

# --- Config ---
IST = ZoneInfo("Asia/Kolkata")
MAX_HR = 185
TOKEN_FILE = Path("/data/.openclaw/credentials/strava-tokens.json")
COACH_DIR = Path("/data/.openclaw/workspace/coach")
GOG_BIN = "/data/linuxbrew/.linuxbrew/bin/gog"
GOG_ENV = {
    **os.environ,
    "GOG_ACCOUNT": os.environ.get("GOG_ACCOUNT", ""),
    "GOG_KEYRING_PASSWORD": os.environ.get("GOG_KEYRING_PASSWORD", ""),
}

# HR Zones based on max HR 185
ZONES = [
    ("Z1", 0, 111),
    ("Z2", 111, 130),
    ("Z3", 130, 148),
    ("Z4", 148, 167),
    ("Z5", 167, MAX_HR + 50),
]


def eprint(*a):
    print(*a, file=sys.stderr)


# --- Strava token management (reused from strava_request.py) ---

def load_tokens() -> dict:
    tokens = {}
    if TOKEN_FILE.exists():
        try:
            tokens = json.loads(TOKEN_FILE.read_text())
        except Exception:
            pass
    for k, env_k in [
        ("access_token", "STRAVA_ACCESS_TOKEN"),
        ("refresh_token", "STRAVA_REFRESH_TOKEN"),
        ("client_id", "STRAVA_CLIENT_ID"),
        ("client_secret", "STRAVA_CLIENT_SECRET"),
    ]:
        if os.environ.get(env_k):
            tokens.setdefault(k, os.environ[env_k])
        if not tokens.get(k) and os.environ.get(env_k):
            tokens[k] = os.environ[env_k]
    return tokens


def save_tokens(tokens: dict):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2, sort_keys=True))
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass


def refresh_token(tokens: dict) -> dict:
    cid = tokens.get("client_id") or os.environ.get("STRAVA_CLIENT_ID")
    secret = tokens.get("client_secret") or os.environ.get("STRAVA_CLIENT_SECRET")
    rtoken = tokens.get("refresh_token") or os.environ.get("STRAVA_REFRESH_TOKEN")
    if not (cid and secret and rtoken):
        raise RuntimeError("Missing Strava credentials for token refresh")
    data = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret,
        "grant_type": "refresh_token", "refresh_token": rtoken,
    }).encode()
    req = urllib.request.Request("https://www.strava.com/oauth/token", data=data, method="POST")
    resp = urllib.request.urlopen(req, timeout=30)
    new = json.loads(resp.read())
    for k in ("access_token", "refresh_token", "expires_at", "expires_in"):
        if k in new:
            tokens[k] = new[k]
    save_tokens(tokens)
    return tokens


def ensure_token(tokens: dict) -> dict:
    exp = tokens.get("expires_at", 0)
    if isinstance(exp, (int, float)) and time.time() >= float(exp) - 120:
        tokens = refresh_token(tokens)
    elif not tokens.get("access_token"):
        tokens = refresh_token(tokens)
    return tokens


def strava_get(path: str, tokens: dict):
    if not path.startswith("/"):
        path = "/" + path
    url = f"https://www.strava.com{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            tokens = refresh_token(tokens)
            save_tokens(tokens)
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tokens['access_token']}"})
            resp = urllib.request.urlopen(req, timeout=30)
            return json.loads(resp.read())
        raise


# --- HR Zone helpers ---

def hr_zone(hr: float | None) -> str:
    if not hr:
        return "?"
    for name, lo, hi in ZONES:
        if lo <= hr < hi:
            return name
    return "Z5" if hr >= 167 else "?"


def pace_str(speed_mps: float | None) -> str:
    """Convert m/s to min:sec/km pace string."""
    if not speed_mps or speed_mps <= 0:
        return "?"
    secs_per_km = 1000 / speed_mps
    mins = int(secs_per_km // 60)
    secs = int(secs_per_km % 60)
    return f"{mins}:{secs:02d}/km"


def classify_run(zone_counts: dict) -> str:
    total = sum(zone_counts.values())
    if total == 0:
        return "Unknown"
    z2_pct = zone_counts.get("Z2", 0) / total
    z4z5 = (zone_counts.get("Z4", 0) + zone_counts.get("Z5", 0)) / total
    z3_pct = zone_counts.get("Z3", 0) / total
    if z2_pct >= 0.7:
        return "Easy Z2 base run"
    if z4z5 >= 0.4:
        return "Hard/interval run"
    if z3_pct >= 0.4:
        return "Tempo run"
    return "Mixed effort"


# --- Strava activity processing ---

def process_activity(raw: dict, tokens: dict) -> dict:
    """Fetch detailed view and extract only useful fields."""
    aid = raw["id"]
    atype = raw.get("type", "Unknown")

    # Fetch detailed view
    try:
        detail = strava_get(f"/api/v3/activities/{aid}", tokens)
    except Exception as e:
        eprint(f"Warning: could not fetch detail for {aid}: {e}")
        detail = raw

    # Convert start_date to IST
    start_utc = detail.get("start_date", "")
    try:
        dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00")).astimezone(IST)
        date_ist = dt.strftime("%Y-%m-%d %H:%M IST")
        day_name = dt.strftime("%A")
    except Exception:
        date_ist = detail.get("start_date_local", start_utc)
        day_name = ""

    result = {
        "name": detail.get("name", ""),
        "type": atype,
        "sport_type": detail.get("sport_type", atype),
        "date": date_ist,
        "day": day_name,
        "distance_km": round(detail.get("distance", 0) / 1000, 2),
        "moving_time_min": round(detail.get("moving_time", 0) / 60, 1),
        "elapsed_time_min": round(detail.get("elapsed_time", 0) / 60, 1),
        "elevation_gain_m": detail.get("total_elevation_gain", 0),
        "avg_hr": detail.get("average_heartrate"),
        "max_hr": detail.get("max_heartrate"),
        "calories": detail.get("calories"),
    }

    desc = detail.get("description")
    if desc:
        result["description"] = desc.strip()

    rpe = detail.get("perceived_exertion")
    if rpe:
        result["rpe"] = rpe

    # Run-specific: splits and zone analysis
    splits = detail.get("splits_metric", [])
    if splits and atype in ("Run", "TrailRun", "VirtualRun"):
        compact_splits = []
        zone_counts = {}
        zone_time = {}
        for s in splits:
            hr = s.get("average_heartrate")
            z = hr_zone(hr)
            zone_counts[z] = zone_counts.get(z, 0) + 1
            zone_time[z] = zone_time.get(z, 0) + s.get("moving_time", 0)
            compact_splits.append({
                "km": s.get("split"),
                "pace": pace_str(s.get("average_speed")),
                "hr": round(hr) if hr else None,
                "zone": z,
            })
        result["splits"] = compact_splits
        result["zone_summary"] = {
            z: f"{zone_counts.get(z, 0)} splits ({round(zone_time.get(z, 0)/60, 1)}min)"
            for z in ["Z1", "Z2", "Z3", "Z4", "Z5"]
        }
        result["zone_classification"] = classify_run(zone_counts)

    return result


def fetch_activities(tokens: dict, date_start: datetime, date_end: datetime, per_page: int = 10) -> list:
    """Fetch and filter Strava activities for a date range (IST)."""
    activities = strava_get(f"/api/v3/athlete/activities?per_page={per_page}", tokens)
    if not isinstance(activities, list):
        eprint(f"Warning: unexpected Strava response: {str(activities)[:200]}")
        return []

    filtered = []
    for a in activities:
        start_utc = a.get("start_date", "")
        try:
            dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00")).astimezone(IST)
        except Exception:
            continue
        if date_start <= dt < date_end:
            filtered.append(a)

    # Also collect recent activities of same type for progression comparison
    return filtered


def fetch_previous_activities(tokens: dict, sport_type: str, exclude_ids: set, limit: int = 3) -> list:
    """Fetch previous activities of the same type for progression tracking."""
    activities = strava_get(f"/api/v3/athlete/activities?per_page=30", tokens)
    if not isinstance(activities, list):
        return []
    prev = []
    for a in activities:
        if a.get("sport_type") == sport_type and a["id"] not in exclude_ids:
            prev.append(a)
            if len(prev) >= limit:
                break
    return prev


# --- Apple Watch CSV reading ---

def read_csv(filename: str, date_start: str, date_end: str) -> list:
    """Read CSV and filter to date range. Returns list of dicts."""
    path = COACH_DIR / filename
    if not path.exists():
        return []
    rows = []
    try:
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = row.get("date_iso", "")
                if date_start <= d <= date_end:
                    rows.append(row)
    except Exception as e:
        eprint(f"Warning: could not read {filename}: {e}")
    return rows


def get_health_data(date_start: str, date_end: str) -> dict:
    """Read all health CSVs and return filtered data."""
    result = {}
    for fname, key, val_key in [
        ("steps_log.csv", "steps", "steps"),
        ("hrv_log.csv", "hrv", "hrv"),
        ("rhr_log.csv", "rhr", "rhr"),
        ("weight_log.csv", "weight_kg", "weight_kg"),
        ("metrics_log.csv", "vo2max", "vo2max"),
    ]:
        rows = read_csv(fname, date_start, date_end)
        for row in rows:
            d = row.get("date_iso", "")
            if d not in result:
                result[d] = {}
            val = row.get(val_key, "")
            if val:
                try:
                    result[d][key] = float(val)
                except ValueError:
                    result[d][key] = val
    return result


# --- Gmail/Food order processing ---

def parse_swiggy_email(html_body: str, headers: dict) -> dict | None:
    """Extract order info from Swiggy email HTML."""
    # Strip HTML to text
    text = re.sub(r'<style[^>]*>.*?</style>', '', html_body, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '\n', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&#\d+;', '', text)
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    order = {"restaurant": None, "items": [], "order_time": None, "total": None, "late_night": False}

    # Stop words: lines starting with these indicate we've passed the items section
    fee_keywords = ("Item Total", "Restaurant Packaging", "Platform Fee", "Delivery Fee",
                    "Express Delivery", "Taxes:", "Paid Via", "Discount", "Order Total",
                    "BLCK Membership", "Handling Charge", "Surge Fee")

    i = 0
    while i < len(lines):
        line = lines[i]

        # Restaurant name
        if line == "Restaurant" and i + 1 < len(lines):
            order["restaurant"] = lines[i + 1]
            i += 2
            continue

        # Order placed time
        if line.startswith("Order placed at:") or line == "Order placed at:":
            time_str = line.replace("Order placed at:", "").strip()
            if not time_str and i + 1 < len(lines):
                time_str = lines[i + 1]
                i += 1
            order["order_time"] = time_str
            # Check if late night (after 9 PM)
            if time_str:
                pm_match = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)', time_str, re.IGNORECASE)
                if pm_match:
                    hour = int(pm_match.group(1))
                    ampm = pm_match.group(3).upper()
                    if ampm == "PM" and hour != 12:
                        hour += 12
                    elif ampm == "AM" and hour == 12:
                        hour = 0
                    order["late_night"] = hour >= 21  # 9 PM or later
            i += 1
            continue

        # Items section: look for pattern "Item Name" header
        if line == "Item Name":
            # Skip the "Quantity" and "Price" header lines
            i += 1
            while i < len(lines) and lines[i] in ("Quantity", "Price"):
                i += 1
            # Now read items in groups of 3 (name, qty, price) until we hit fees/totals
            while i < len(lines):
                # Check if we've hit the end of items
                if any(lines[i].startswith(kw) for kw in fee_keywords):
                    break
                # Read item: name, quantity, price
                item_name = lines[i]
                qty = "1"
                price = ""
                if i + 1 < len(lines) and re.match(r'^\d+$', lines[i + 1]):
                    qty = lines[i + 1]
                    if i + 2 < len(lines) and lines[i + 2].startswith("₹"):
                        price = lines[i + 2]
                        i += 3
                    else:
                        i += 2
                else:
                    i += 1
                if item_name and not item_name.startswith("₹") and not any(item_name.startswith(kw) for kw in fee_keywords):
                    order["items"].append(f"{item_name} x{qty} {price}")
            continue

        # Order total
        if line.startswith("Order Total:") or line == "Order Total:":
            total_str = line.replace("Order Total:", "").strip()
            if not total_str and i + 1 < len(lines):
                total_str = lines[i + 1]
                i += 1
            order["total"] = total_str
            i += 1
            continue

        i += 1

    if not order["restaurant"] and not order["items"]:
        return None

    return order


def fetch_food_orders(date_start: str, date_end: str, days: int = 2) -> list:
    """Fetch food delivery orders from Gmail via gog CLI."""
    orders = []
    try:
        # Search for Swiggy/Instamart emails
        result = subprocess.run(
            [GOG_BIN, "gmail", "search",
             f"(from:noreply@swiggy.in OR from:noreply@instamart.in OR from:swiggy.in OR from:instamart.in) newer_than:{days}d",
             "--plain"],
            capture_output=True, text=True, timeout=30, env=GOG_ENV,
        )
        if result.returncode != 0:
            eprint(f"Warning: gog search failed: {result.stderr[:200]}")
            return []

        # Parse TSV output
        msg_ids = []
        for line in result.stdout.strip().split("\n")[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 2:
                msg_id = parts[0].strip()
                date_str = parts[1].strip()  # e.g., "2026-02-22 09:39"
                if msg_id and date_str:
                    # Filter to date range
                    email_date = date_str[:10]  # YYYY-MM-DD
                    if date_start <= email_date <= date_end:
                        msg_ids.append(msg_id)

        # Fetch each email and extract order details
        for msg_id in msg_ids:
            try:
                result = subprocess.run(
                    [GOG_BIN, "gmail", "get", msg_id, "--json"],
                    capture_output=True, text=True, timeout=30, env=GOG_ENV,
                )
                if result.returncode != 0:
                    continue
                data = json.loads(result.stdout)
                body = data.get("body", "")
                headers = data.get("headers", {})
                order = parse_swiggy_email(body, headers)
                if order:
                    orders.append(order)
            except Exception as e:
                eprint(f"Warning: could not process email {msg_id}: {e}")

    except Exception as e:
        eprint(f"Warning: food order fetch failed: {e}")

    return orders


# --- Main modes ---

def daily_mode():
    """Generate compact JSON for daily coach debrief (yesterday)."""
    now_ist = datetime.now(IST)
    yesterday = now_ist - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    day_before = (now_ist - timedelta(days=2)).strftime("%Y-%m-%d")

    # Date range: yesterday 00:00 IST to today 00:00 IST
    start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

    tokens = ensure_token(load_tokens())

    # Fetch yesterday's activities
    raw_activities = fetch_activities(tokens, start, end, per_page=5)
    activities = []
    activity_ids = set()
    for a in raw_activities:
        processed = process_activity(a, tokens)
        activities.append(processed)
        activity_ids.add(a["id"])

    # For progression: fetch previous activities of same sport types
    prev_activities = {}
    sport_types_seen = set()
    for a in raw_activities:
        st = a.get("sport_type", a.get("type", ""))
        if st and st not in sport_types_seen:
            sport_types_seen.add(st)
            prev = fetch_previous_activities(tokens, st, activity_ids, limit=3)
            if prev:
                prev_activities[st] = []
                for p in prev:
                    pp = {
                        "name": p.get("name", ""),
                        "date": p.get("start_date_local", "")[:10],
                        "distance_km": round(p.get("distance", 0) / 1000, 2),
                        "moving_time_min": round(p.get("moving_time", 0) / 60, 1),
                        "avg_hr": p.get("average_heartrate"),
                    }
                    # For weight training, fetch description for progression
                    if st == "WeightTraining":
                        try:
                            detail = strava_get(f"/api/v3/activities/{p['id']}", tokens)
                            desc = detail.get("description")
                            if desc:
                                pp["description"] = desc.strip()
                        except Exception:
                            pass
                    prev_activities[st].append(pp)

    # Health data
    health = get_health_data(day_before, yesterday_str)

    # Food orders
    food_orders = fetch_food_orders(yesterday_str, yesterday_str, days=2)

    output = {
        "mode": "daily",
        "yesterday": yesterday_str,
        "yesterday_day": yesterday.strftime("%A"),
        "activities": activities,
        "previous_activities": prev_activities if prev_activities else None,
        "health": health if health else None,
        "food_orders": food_orders if food_orders else None,
    }

    print(json.dumps(output, indent=2, default=str))


def weekly_mode():
    """Generate compact JSON for weekly recap (this week Mon-Sun + last week)."""
    now_ist = datetime.now(IST)

    # This week: most recent Monday to today (Sunday)
    days_since_monday = now_ist.weekday()  # 0=Mon, 6=Sun
    this_monday = (now_ist - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
    last_monday = this_monday - timedelta(days=7)
    next_monday = this_monday + timedelta(days=7)

    this_week_start = this_monday.strftime("%Y-%m-%d")
    this_week_end = now_ist.strftime("%Y-%m-%d")
    last_week_start = last_monday.strftime("%Y-%m-%d")
    last_week_end = (this_monday - timedelta(days=1)).strftime("%Y-%m-%d")

    tokens = ensure_token(load_tokens())

    # Fetch 2 weeks of activities
    start_dt = last_monday
    end_dt = next_monday
    raw_activities = fetch_activities(tokens, start_dt, end_dt, per_page=30)

    this_week = []
    last_week = []
    for a in raw_activities:
        start_utc = a.get("start_date", "")
        try:
            dt = datetime.fromisoformat(start_utc.replace("Z", "+00:00")).astimezone(IST)
        except Exception:
            continue
        processed = process_activity(a, tokens)
        if dt >= this_monday:
            this_week.append(processed)
        else:
            last_week.append(processed)

    # Health data for both weeks
    health_this = get_health_data(this_week_start, this_week_end)
    health_last = get_health_data(last_week_start, last_week_end)

    # Food orders (7 days)
    food_orders = fetch_food_orders(this_week_start, this_week_end, days=7)

    output = {
        "mode": "weekly",
        "this_week": {"start": this_week_start, "end": this_week_end, "activities": this_week},
        "last_week": {"start": last_week_start, "end": last_week_end, "activities": last_week},
        "health_this_week": health_this,
        "health_last_week": health_last,
        "food_orders": food_orders if food_orders else None,
    }

    print(json.dumps(output, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Coach data preprocessor")
    parser.add_argument("--mode", required=True, choices=["daily", "weekly"])
    args = parser.parse_args()

    if args.mode == "daily":
        daily_mode()
    elif args.mode == "weekly":
        weekly_mode()


if __name__ == "__main__":
    main()
