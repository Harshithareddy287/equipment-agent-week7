"""Shared configuration: today's date, data file paths, and month arithmetic.

Environment variables are read at call time (not import time) so tests can
override them with monkeypatch. See docs/requirements.md section 3.
"""

import calendar
import os
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


def get_today() -> date:
    """Today's date: DEMO_TODAY (YYYY-MM-DD) if set, otherwise the real date."""
    value = os.environ.get("DEMO_TODAY", "").strip()
    return date.fromisoformat(value) if value else date.today()


def _path(env_var: str, default_name: str) -> Path:
    """Path from an environment variable, else data/<default_name> under the repo root."""
    value = os.environ.get(env_var, "").strip()
    return Path(value) if value else DATA_DIR / default_name


def employees_path() -> Path:
    return _path("EMPLOYEES_PATH", "employees.json")


def policies_path() -> Path:
    return _path("POLICIES_PATH", "policies.json")


def escalations_path() -> Path:
    return _path("ESCALATIONS_PATH", "escalations.json")


def add_months(d: date, n: int) -> date:
    """Add n calendar months, clamping to the last day of the target month.

    e.g. 2024-01-31 + 1 month = 2024-02-29.
    """
    month_index = d.year * 12 + (d.month - 1) + n
    year, month = divmod(month_index, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def completed_months(start: date, end: date) -> int:
    """Number of completed calendar months from start to end (0 if end < start).

    e.g. 2021-03-15 -> 2026-11-01 = 67; 2021-03-15 -> 2026-11-15 = 68.
    """
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    # The last month only counts once its anniversary day has been reached.
    if add_months(start, months) > end:
        months -= 1
    return months
