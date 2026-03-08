#!/usr/bin/env python3
"""Strava request helper with automatic token refresh.

Usage:
  strava_request.py <path>

Example:
  ./strava_request.py /api/v3/athlete
  ./strava_request.py "/api/v3/athlete/activities?per_page=10"

Token sources (in precedence order):
  1) STRAVA_TOKEN_FILE (default: /data/.openclaw/credentials/strava-tokens.json)
  2) Environment variables: STRAVA_ACCESS_TOKEN / STRAVA_REFRESH_TOKEN

When the access token is expired (or a request returns 401 invalid/expired token),
this script refreshes via the refresh token, updates the token file, and retries once.

Note: Refreshing does NOT add missing scopes. You must authorize with the correct scopes
(e.g., activity:read_all) at least once.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.strava.com"
DEFAULT_TOKEN_FILE = "/data/.openclaw/credentials/strava-tokens.json"


def eprint(*a):
    print(*a, file=sys.stderr)


def load_tokens() -> tuple[dict, Path]:
    token_path = Path(os.environ.get("STRAVA_TOKEN_FILE", DEFAULT_TOKEN_FILE))
    tokens: dict = {}
    if token_path.exists():
        try:
            tokens = json.loads(token_path.read_text())
        except Exception:
            tokens = {}

    # env fallback/override
    if os.environ.get("STRAVA_ACCESS_TOKEN"):
        tokens.setdefault("access_token", os.environ.get("STRAVA_ACCESS_TOKEN"))
    if os.environ.get("STRAVA_REFRESH_TOKEN"):
        tokens.setdefault("refresh_token", os.environ.get("STRAVA_REFRESH_TOKEN"))
    if os.environ.get("STRAVA_CLIENT_ID"):
        tokens.setdefault("client_id", os.environ.get("STRAVA_CLIENT_ID"))
    if os.environ.get("STRAVA_CLIENT_SECRET"):
        tokens.setdefault("client_secret", os.environ.get("STRAVA_CLIENT_SECRET"))

    return tokens, token_path


def save_tokens(tokens: dict, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps(tokens, indent=2, sort_keys=True))
    try:
        os.chmod(token_path, 0o600)
    except Exception:
        pass


def needs_refresh(tokens: dict, skew_seconds: int = 120) -> bool:
    access = tokens.get("access_token")
    exp = tokens.get("expires_at")
    if not access:
        return True
    if isinstance(exp, (int, float)):
        return time.time() >= float(exp) - skew_seconds
    return False


def refresh(tokens: dict, token_path: Path) -> dict:
    cid = tokens.get("client_id") or os.environ.get("STRAVA_CLIENT_ID")
    secret = tokens.get("client_secret") or os.environ.get("STRAVA_CLIENT_SECRET")
    rtoken = tokens.get("refresh_token") or os.environ.get("STRAVA_REFRESH_TOKEN")

    if not cid or not secret or not rtoken:
        raise RuntimeError("Need STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, STRAVA_REFRESH_TOKEN to refresh")

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

    # Update token set; Strava may rotate refresh tokens.
    for k in ("access_token", "refresh_token", "expires_at", "expires_in", "token_type"):
        if k in payload:
            tokens[k] = payload[k]

    # persist
    save_tokens(tokens, token_path)
    return tokens


def request_json(path: str, tokens: dict) -> object:
    if not path.startswith("/"):
        path = "/" + path
    url = f"{BASE}{path}"

    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {tokens.get('access_token','')}")

    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode("utf-8", "ignore"))


def is_retryable_401(body: str) -> bool:
    # Strava uses different shapes, but these are common.
    # We only retry on token problems, not missing-scope.
    b = body.lower()
    if "invalid" in b and "token" in b:
        return True
    if "access_token" in b and "invalid" in b:
        return True
    if "authorization error" in b and "invalid" in b:
        return True
    return False


def main() -> int:
    if len(sys.argv) != 2:
        eprint("Usage: strava_request.py <path>")
        return 2

    path = sys.argv[1]
    tokens, token_path = load_tokens()

    if needs_refresh(tokens):
        tokens = refresh(tokens, token_path)

    try:
        data = request_json(path, tokens)
        sys.stdout.write(json.dumps(data))
        return 0
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        if e.code == 401 and is_retryable_401(body):
            tokens = refresh(tokens, token_path)
            data = request_json(path, tokens)
            sys.stdout.write(json.dumps(data))
            return 0
        # pass through the error
        eprint(f"HTTP {e.code}: {body}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
