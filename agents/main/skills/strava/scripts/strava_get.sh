#!/usr/bin/env bash
# Strava GET with automatic token refresh.
#
# Usage:
#   ./strava_get.sh /api/v3/athlete
#   ./strava_get.sh "/api/v3/athlete/activities?per_page=10"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/strava_request.py" "$1"
