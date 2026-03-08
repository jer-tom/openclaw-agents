#!/usr/bin/env python3
"""Daily Strava fitness coach report.

- Pulls recent Strava activities
- Finds activities completed since local midnight (Asia/Kolkata)
- For each activity, compares against previous 10 activities of same sport_type
- Outputs a brief WhatsApp-friendly report with emojis

Notes:
- Strava API does not reliably provide HRV. If you want HRV-based analysis,
  we need an HRV source (Garmin/Oura/Whoop/Apple Health) or manual inputs.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import urllib.parse
import urllib.request
import urllib.error

BASE = "https://www.strava.com"
TZ = ZoneInfo("Asia/Kolkata")
TOKEN_FILE = Path(os.environ.get("STRAVA_TOKEN_FILE", "/data/.openclaw/credentials/strava-tokens.json"))
STATE_FILE = Path(os.environ.get("STRAVA_COACH_STATE_FILE", "/data/.openclaw/workspace/coach/state.json"))


def load_tokens() -> dict:
    if TOKEN_FILE.exists():
        t = json.loads(TOKEN_FILE.read_text())
    else:
        t = {}
    # env fallback
    for k in ("access_token", "refresh_token", "client_id", "client_secret", "expires_at"):
        envk = "STRAVA_" + k.upper() if k not in ("client_id", "client_secret") else ("STRAVA_CLIENT_ID" if k == "client_id" else "STRAVA_CLIENT_SECRET")
        if os.environ.get(envk) and k not in t:
            t[k] = os.environ.get(envk)
    return t


def save_tokens(t: dict) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(t, indent=2, sort_keys=True))
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass


def refresh_if_needed(t: dict, skew_seconds: int = 120) -> dict:
    exp = t.get("expires_at")
    access = t.get("access_token")
    if not access:
        return refresh(t)
    if isinstance(exp, (int, float)):
        if datetime.now(timezone.utc).timestamp() >= float(exp) - skew_seconds:
            return refresh(t)
    return t


def refresh(t: dict) -> dict:
    cid = os.environ.get("STRAVA_CLIENT_ID") or t.get("client_id")
    secret = os.environ.get("STRAVA_CLIENT_SECRET") or t.get("client_secret")
    rtoken = os.environ.get("STRAVA_REFRESH_TOKEN") or t.get("refresh_token")
    if not (cid and secret and rtoken):
        raise RuntimeError("Missing STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET/STRAVA_REFRESH_TOKEN for refresh")

    data = urllib.parse.urlencode(
        {
            "client_id": cid,
            "client_secret": secret,
            "grant_type": "refresh_token",
            "refresh_token": rtoken,
        }
    ).encode("utf-8")
    req = urllib.request.Request(f"{BASE}/oauth/token", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        payload = json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"Refresh failed HTTP {e.code}: {body[:500]}")

    for k in ("access_token", "refresh_token", "expires_at", "expires_in", "token_type"):
        if k in payload:
            t[k] = payload[k]
    # also store client_id/client_secret pointers for convenience
    t.setdefault("client_id", cid)
    t.setdefault("client_secret", secret)

    save_tokens(t)
    return t


def api_get_json(path: str, t: dict) -> object:
    if not path.startswith("/"):
        path = "/" + path
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {t['access_token']}")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        body_l = body.lower()

        # If token invalid/expired, refresh once and retry.
        # Note: Refreshing cannot add missing scopes. If the error is a missing
        # permission (e.g. activity:read_permission), do NOT retry refresh.
        if e.code == 401 and ("activity:read_permission" not in body_l):
            # Strava uses a few different 401 bodies; treat most as refreshable.
            # We'll still only retry once to avoid loops.
            try:
                t = refresh(t)
                req = urllib.request.Request(url, method="GET")
                req.add_header("Authorization", f"Bearer {t['access_token']}")
                resp = urllib.request.urlopen(req, timeout=30)
                return json.loads(resp.read().decode("utf-8", "ignore"))
            except Exception:
                # fall through to the original error
                pass

        raise RuntimeError(f"GET {path} failed HTTP {e.code}: {body[:500]}")


@dataclass
class Summary:
    id: int
    name: str
    sport: str
    start_local: datetime
    distance_m: float
    moving_s: int
    elev_m: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_speed: float | None


def pace_min_per_km(avg_speed_ms: float | None) -> str | None:
    if not avg_speed_ms or avg_speed_ms <= 0:
        return None
    # min/km = 1000m / (m/s) = seconds per km
    sec = 1000.0 / avg_speed_ms
    m = int(sec // 60)
    s = int(round(sec - 60 * m))
    if s == 60:
        m += 1
        s = 0
    return f"{m}:{s:02d}/km"


def fmt_hms(seconds: int) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def midnight_local(dt: datetime) -> datetime:
    loc = dt.astimezone(TZ)
    return loc.replace(hour=0, minute=0, second=0, microsecond=0)


def get_recent_activities(t: dict, per_page: int = 50) -> list[dict]:
    return api_get_json(f"/api/v3/athlete/activities?per_page={per_page}", t)  # type: ignore


def to_summary(a: dict) -> Summary:
    # start_date_local is ISO; Strava sometimes returns Z. Parse best-effort.
    # Strava's `start_date` is UTC. Use that and convert to IST to avoid any
    # inconsistencies in `start_date_local` formatting.
    s = a.get("start_date") or a.get("start_date_local")
    start = datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(TZ)
    return Summary(
        id=int(a["id"]),
        name=str(a.get("name") or ""),
        sport=str(a.get("sport_type") or a.get("type") or "Workout"),
        start_local=start,
        distance_m=float(a.get("distance") or 0.0),
        moving_s=int(a.get("moving_time") or 0),
        elev_m=(float(a.get("total_elevation_gain")) if a.get("total_elevation_gain") is not None else None),
        avg_hr=(float(a.get("average_heartrate")) if a.get("average_heartrate") is not None else None),
        max_hr=(float(a.get("max_heartrate")) if a.get("max_heartrate") is not None else None),
        avg_speed=(float(a.get("average_speed")) if a.get("average_speed") is not None else None),
    )


def metric(values: list[float | None]) -> tuple[float | None, float | None]:
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return (vals[0] if vals else None, None)
    return (statistics.mean(vals), statistics.pstdev(vals))


def trend_word(delta: float, bigger_is_better: bool) -> str:
    # small deadzone
    if abs(delta) < 0.01:
        return "↔️"
    better = delta > 0 if bigger_is_better else delta < 0
    return "📈" if better else "📉"


def report_for_activity(today: Summary, prev10: list[Summary]) -> str:
    # Compare: pace (lower better), avg_hr (lower for same pace maybe better), moving time, distance.
    prev_paces = [pace_min_per_km(s.avg_speed) for s in prev10]
    # convert pace strings to seconds for comparison
    def pace_to_sec(p: str | None) -> float | None:
        if not p:
            return None
        mm, ss = p.split(":")
        ss2, _ = ss.split("/")
        return int(mm) * 60 + int(ss2)

    today_pace_s = pace_to_sec(pace_min_per_km(today.avg_speed))
    prev_pace_s = [pace_to_sec(p) for p in prev_paces]
    prev_pace_mean, _ = metric(prev_pace_s)  # type: ignore

    lines = []
    dist_km = today.distance_m / 1000.0
    pace = pace_min_per_km(today.avg_speed)

    lines.append(f"🏋️ {today.sport}: *{today.name}*")
    lines.append(f"🗓️ {today.start_local.strftime('%d %b %Y, %I:%M %p')}")
    lines.append(f"📏 {dist_km:.2f} km  ⏱️ {fmt_hms(today.moving_s)}" + (f"  ⛰️ +{today.elev_m:.0f} m" if today.elev_m is not None else ""))
    if pace:
        lines.append(f"⚡ Pace: {pace}")
    if today.avg_hr is not None:
        lines.append(f"❤️ HR: avg {today.avg_hr:.0f} / max {today.max_hr:.0f}" if today.max_hr is not None else f"❤️ HR: avg {today.avg_hr:.0f}")

    if prev10:
        lines.append(f"📊 vs prev 10 {today.sport} workouts:")
        # Pace trend
        if today_pace_s is not None and prev_pace_mean is not None:
            delta = today_pace_s - prev_pace_mean
            # lower pace seconds is better
            lines.append(f"  {trend_word(delta, bigger_is_better=False)} Pace change: {delta:+.0f} sec/km (today vs avg)")
        # HR at pace proxy (only if both present)
        prev_hr_mean, _ = metric([s.avg_hr for s in prev10])
        if today.avg_hr is not None and prev_hr_mean is not None:
            delta_hr = today.avg_hr - prev_hr_mean
            lines.append(f"  {trend_word(delta_hr, bigger_is_better=False)} Avg HR change: {delta_hr:+.0f} bpm (lower = less stress)")

    # Stress note (HRV not available)
    lines.append("🧠 Stress: using HR today (HRV not available from Strava). If you want HRV, tell me your tracker (Garmin/Oura/Whoop/Apple Health).")

    return "\n".join(lines)


def main() -> int:
    t = load_tokens()
    t = refresh_if_needed(t)

    acts = get_recent_activities(t, per_page=50)
    sums = [to_summary(a) for a in acts]
    now = datetime.now(TZ)
    since = midnight_local(now)

    state = load_state()
    last_ids = set(state.get("last_reported_activity_ids", []))

    mode = (os.environ.get("STRAVA_COACH_MODE") or "daily").strip().lower()
    # daily: only report activities since local midnight
    # realtime: report any unreported activities (useful for frequent polling)
    if mode == "realtime":
        new_acts = [s for s in sums if s.id not in last_ids]
        # Only consider the most recent few to avoid spam if state resets
        todays = sorted(new_acts, key=lambda x: x.start_local, reverse=True)[:5]
    else:
        todays = [s for s in sums if s.start_local >= since and s.id not in last_ids]

    if not todays:
        if mode == "realtime":
            # stay quiet on realtime polls when nothing new
            print("")
            return 0
        print("📭 *Strava check (9am)*: No new activities since midnight.")
        return 0

    # Build report for each of today's activities.
    out_blocks = []
    new_reported = []

    for s in sorted(todays, key=lambda x: x.start_local):
        prev = [p for p in sums if p.sport == s.sport and p.start_local < s.start_local]
        prev10 = prev[:10]
        out_blocks.append(report_for_activity(s, prev10))
        new_reported.append(s.id)

    # Save state to avoid duplicate reporting
    state["last_reported_activity_ids"] = list(last_ids.union(new_reported))[-200:]
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)

    # Weekly focus suggestions (simple heuristics)
    focus = []
    focus.append("🎯 *This week focus*:")
    focus.append("• 💤 1-2 easy recovery sessions (keep HR low)")
    focus.append("• 🧱 2 strength sessions (legs + core)")
    focus.append("• 🚶 daily steps + nutrition consistency (fat loss driver)")
    focus_text = "\n".join(focus)

    header = "🏃‍♂️ *Daily Strava Coach Report (9am)*"
    print(header)
    print("\n\n".join(out_blocks))
    print("\n" + focus_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
