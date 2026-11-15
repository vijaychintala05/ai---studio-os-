"""UTC time provider, with an explicit fail-closed simulation seam for TEST copies only.

Wall-clock performance measurement and external backup timestamps are not changed.
No HTTP endpoint can change time. An operator may configure a read-only fixture file
only when STUDIOOS_ENV=test. The default remains the real UTC clock.
"""
import json
import os
from datetime import datetime,timezone
from pathlib import Path


def utc_now():
    clock=os.getenv('STUDIOOS_SIMULATION_CLOCK','').strip()
    if not clock:return datetime.now(timezone.utc)
    if os.getenv('STUDIOOS_ENV','').strip().lower()!='test':
        raise RuntimeError('Simulation clock is permitted only in test copies')
    value=json.loads(Path(clock).read_text())
    if not isinstance(value,dict) or set(value)!={'utc'} or not isinstance(value['utc'],str):
        raise ValueError('Simulation clock must contain one UTC timestamp')
    instant=datetime.fromisoformat(value['utc'])
    if instant.tzinfo is None:raise ValueError('Simulation clock must be timezone-aware')
    return instant.astimezone(timezone.utc)
