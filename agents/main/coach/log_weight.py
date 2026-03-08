#!/usr/bin/env python3
"""Append a weight entry to coach/weight_log.csv

Usage:
  log_weight.py <weight_kg> [notes...]
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

TZ = ZoneInfo('Asia/Kolkata')
LOG = Path('/data/.openclaw/workspace/coach/weight_log.csv')


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: log_weight.py <weight_kg> [notes...]', file=sys.stderr)
        return 2
    w = float(sys.argv[1])
    notes = ' '.join(sys.argv[2:]).strip()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = LOG.exists()
    with LOG.open('a', newline='') as f:
        wr = csv.writer(f)
        if not exists:
            wr.writerow(['date_iso','weight_kg','notes'])
        wr.writerow([datetime.now(TZ).isoformat(timespec='minutes'), f'{w:.2f}', notes])
    print('OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
