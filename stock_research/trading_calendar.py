"""
US equity market (NYSE/Nasdaq) trading calendar.

The nightly routine only runs on trading days: no fresh data means no fresh
picks and no outcome grading. Horizons are measured in trading days, never
calendar days, so a Friday pick with a 3-day horizon resolves the following
Wednesday rather than over the weekend.

CLI:
  python -m stock_research.trading_calendar check [YYYY-MM-DD]
  python -m stock_research.trading_calendar add <YYYY-MM-DD> <n_trading_days>
"""

from __future__ import annotations

import datetime as dt
import json
import sys

WEEKEND = {5, 6}  # Saturday, Sunday


def _easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lam) // 451
    month, day = divmod(h + lam - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """n-th `weekday` (Mon=0) of a month; n=-1 means the last one."""
    if n > 0:
        first = dt.date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + dt.timedelta(days=offset + 7 * (n - 1))
    last_day = (dt.date(year + month // 12, month % 12 + 1, 1) - dt.timedelta(days=1))
    offset = (last_day.weekday() - weekday) % 7
    return last_day - dt.timedelta(days=offset)


def _observed(d: dt.date) -> dt.date:
    """NYSE observance: Saturday holidays shift to Friday, Sunday to Monday."""
    if d.weekday() == 5:
        return d - dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + dt.timedelta(days=1)
    return d


def market_holidays(year: int) -> dict[dt.date, str]:
    """Full-day NYSE/Nasdaq closures for a year (half days are still trading days)."""
    holidays: dict[dt.date, str] = {}

    new_years = dt.date(year, 1, 1)
    # A Saturday Jan 1 is not pulled back into the prior trading year.
    if new_years.weekday() != 5:
        holidays[_observed(new_years)] = "New Year's Day"

    holidays[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    holidays[_nth_weekday(year, 2, 0, 3)] = "Washington's Birthday"
    holidays[_easter(year) - dt.timedelta(days=2)] = "Good Friday"
    holidays[_nth_weekday(year, 5, 0, -1)] = "Memorial Day"
    holidays[_observed(dt.date(year, 6, 19))] = "Juneteenth"
    holidays[_observed(dt.date(year, 7, 4))] = "Independence Day"
    holidays[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    holidays[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving Day"
    holidays[_observed(dt.date(year, 12, 25))] = "Christmas Day"
    return holidays


def parse_date(value: str | dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value)[:10])


def holiday_name(day: str | dt.date) -> str | None:
    day = parse_date(day)
    return market_holidays(day.year).get(day)


def is_trading_day(day: str | dt.date) -> bool:
    day = parse_date(day)
    return day.weekday() not in WEEKEND and holiday_name(day) is None


def closed_reason(day: str | dt.date) -> str | None:
    """Why the market is closed on `day`, or None if it is a trading day."""
    day = parse_date(day)
    if day.weekday() in WEEKEND:
        return day.strftime("%A")
    return holiday_name(day)


def next_trading_day(day: str | dt.date) -> dt.date:
    """First trading day strictly after `day`."""
    day = parse_date(day) + dt.timedelta(days=1)
    while not is_trading_day(day):
        day += dt.timedelta(days=1)
    return day


def prev_trading_day(day: str | dt.date) -> dt.date:
    """Last trading day strictly before `day`."""
    day = parse_date(day) - dt.timedelta(days=1)
    while not is_trading_day(day):
        day -= dt.timedelta(days=1)
    return day


def add_trading_days(day: str | dt.date, n: int) -> dt.date:
    """Advance `n` trading days from `day` (n may be negative)."""
    day = parse_date(day)
    step = next_trading_day if n >= 0 else prev_trading_day
    for _ in range(abs(n)):
        day = step(day)
    return day


def trading_days_between(start: str | dt.date, end: str | dt.date) -> int:
    """Trading days strictly after `start` up to and including `end`."""
    start, end = parse_date(start), parse_date(end)
    if end <= start:
        return 0
    count, cursor = 0, start
    while cursor < end:
        cursor += dt.timedelta(days=1)
        if is_trading_day(cursor):
            count += 1
    return count


def _cli() -> None:
    args = sys.argv[1:]
    cmd = args[0] if args else "check"

    if cmd == "check":
        day = parse_date(args[1]) if len(args) > 1 else dt.date.today()
        trading = is_trading_day(day)
        print(json.dumps({
            "date": day.isoformat(),
            "weekday": day.strftime("%A"),
            "is_trading_day": trading,
            "closed_reason": closed_reason(day),
            "next_trading_day": next_trading_day(day).isoformat(),
            "prev_trading_day": prev_trading_day(day).isoformat(),
            "verdict": "RUN" if trading else "SKIP — market closed, do not run the routine",
        }, indent=2))

    elif cmd == "add":
        if len(args) < 3:
            print("Usage: add <YYYY-MM-DD> <n_trading_days>")
            sys.exit(1)
        result = add_trading_days(args[1], int(args[2]))
        print(json.dumps({"from": args[1], "trading_days": int(args[2]),
                          "date": result.isoformat()}, indent=2))

    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    _cli()
