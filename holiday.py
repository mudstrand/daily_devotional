#!/usr/bin/env python3
from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
import calendar
import sys
from typing import Optional, Tuple, Dict


class Holiday(str, Enum):
    new_years_day = "new_years_day"
    mlk_day = "mlk_day"
    presidents_day = "presidents_day"
    valentines_day = "valentines_day"
    st_patricks_day = "st_patricks_day"
    independence_day = "independence_day"
    halloween = "halloween"
    veterans_day = "veterans_day"
    christmas_eve = "christmas_eve"
    christmas = "christmas"
    mothers_day = "mothers_day"
    fathers_day = "fathers_day"
    election_day = "election_day"
    easter = "easter"
    good_friday = "good_friday"
    ash_wednesday = "ash_wednesday"
    palm_sunday = "palm_sunday"
    pentecost = "pentecost"
    all_saints_day = "all_saints_day"
    memorial_day = "memorial_day"
    labor_day = "labor_day"
    columbus_day = "columbus_day"
    thanksgiving = "thanksgiving"


# Maps Holiday enum -> (emoji, human-readable label)
# Sacred days use a “gentle” set by default: 🕯️ candle (Easter/Good Friday/Ash Wednesday/All Saints’/Christmas Eve),
# 🌿 Palm Sunday, 🕊️ Pentecost.
HOLIDAY_META: Dict[Holiday, Tuple[str, str]] = {
    Holiday.new_years_day: ("🎆", "New Year's Day"),
    Holiday.mlk_day: ("🕊️", "Martin Luther King Jr. Day"),
    Holiday.presidents_day: ("🇺🇸", "Presidents Day"),
    Holiday.valentines_day: ("❤️", "Valentine's Day"),
    Holiday.st_patricks_day: ("🍀", "St. Patrick's Day"),
    Holiday.independence_day: ("🎇", "Independence Day"),
    Holiday.halloween: ("🎃", "Halloween"),
    Holiday.veterans_day: ("🎖️", "Veterans Day"),
    Holiday.christmas_eve: ("🕯️", "Christmas Eve"),
    Holiday.christmas: ("🎄", "Christmas"),
    Holiday.mothers_day: ("🌷", "Mother's Day"),
    Holiday.fathers_day: ("🛠️", "Father's Day"),
    Holiday.election_day: ("🗳️", "Election Day"),
    Holiday.easter: ("🕯️", "Easter"),
    Holiday.good_friday: ("🕯️", "Good Friday"),
    Holiday.ash_wednesday: ("🕯️", "Ash Wednesday"),
    Holiday.palm_sunday: ("🌿", "Palm Sunday"),
    Holiday.pentecost: ("🕊️", "Pentecost"),
    Holiday.all_saints_day: ("🕯️", "All Saints' Day"),
    Holiday.memorial_day: ("🇺🇸", "Memorial Day"),
    Holiday.labor_day: ("🧰", "Labor Day"),
    Holiday.columbus_day: ("🧭", "Columbus Day"),
    Holiday.thanksgiving: ("🦃", "Thanksgiving"),
}


def holiday_emoji(h: Holiday) -> str:
    return HOLIDAY_META.get(h, ("", ""))[0]


def holiday_label(h: Holiday) -> str:
    return HOLIDAY_META.get(h, ("", h.value.replace("_", " ").title()))[1]


# -----------------------------
# Date helpers
# -----------------------------
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """
    weekday: Monday=0 ... Sunday=6, n>=1
    """
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last_dom = calendar.monthrange(year, month)[1]
    last = date(year, month, last_dom)
    back = (last.weekday() - weekday) % 7
    return last - timedelta(days=back)


def _easter_sunday(year: int) -> date:
    """
    Anonymous Gregorian algorithm for Easter Sunday.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


# -----------------------------
# Holiday calculators
# -----------------------------
def _fixed_holiday(
    y: int, m: int, d: int, target: date, enum_val: Holiday
) -> Optional[Holiday]:
    return enum_val if target == date(y, m, d) else None


def _mlk_day(y: int, target: date) -> Optional[Holiday]:
    # Third Monday in January
    return Holiday.mlk_day if target == _nth_weekday(y, 1, 0, 3) else None


def _presidents_day(y: int, target: date) -> Optional[Holiday]:
    # Third Monday in February
    return Holiday.presidents_day if target == _nth_weekday(y, 2, 0, 3) else None


def _mothers_day(y: int, target: date) -> Optional[Holiday]:
    # Second Sunday in May
    return Holiday.mothers_day if target == _nth_weekday(y, 5, 6, 2) else None


def _fathers_day(y: int, target: date) -> Optional[Holiday]:
    # Third Sunday in June
    return Holiday.fathers_day if target == _nth_weekday(y, 6, 6, 3) else None


def _election_day(y: int, target: date) -> Optional[Holiday]:
    # U.S. General Election Day: first Tuesday after the first Monday in November
    first = date(y, 11, 1)
    first_monday = first + timedelta(days=(0 - first.weekday()) % 7)
    first_tuesday_after_first_monday = first_monday + timedelta(days=1)
    return Holiday.election_day if target == first_tuesday_after_first_monday else None


def _memorial_day(y: int, target: date) -> Optional[Holiday]:
    # Last Monday in May
    return Holiday.memorial_day if target == _last_weekday(y, 5, 0) else None


def _labor_day(y: int, target: date) -> Optional[Holiday]:
    # First Monday in September
    return Holiday.labor_day if target == _nth_weekday(y, 9, 0, 1) else None


def _columbus_day(y: int, target: date) -> Optional[Holiday]:
    # Second Monday in October
    return Holiday.columbus_day if target == _nth_weekday(y, 10, 0, 2) else None


def _thanksgiving(y: int, target: date) -> Optional[Holiday]:
    # Fourth Thursday in November
    return Holiday.thanksgiving if target == _nth_weekday(y, 11, 3, 4) else None


def _moveable_feasts(y: int, target: date) -> Optional[Holiday]:
    easter = _easter_sunday(y)
    if target == easter:
        return Holiday.easter
    if target == easter - timedelta(days=2):
        return Holiday.good_friday
    if target == easter - timedelta(days=46):
        return Holiday.ash_wednesday
    if target == easter - timedelta(days=7):
        return Holiday.palm_sunday
    if target == easter + timedelta(days=49):
        return Holiday.pentecost
    return None


def holiday_info(date_iso: str) -> Optional[tuple[str, str]]:
    """
    Return (label, emoji) for the date if it is a holiday, else None.
    Example: ("Easter", "🕯️")
    """
    h = holiday_name_or_none(date_iso)
    if h is None:
        return None
    return h, holiday_label(h), holiday_emoji(h)


def holiday_name_or_none(date_iso: str) -> Optional[Holiday]:
    """
    Return the Holiday enum for a given YYYY-MM-DD, or None if not a listed holiday.
    """
    try:
        y, m, d = map(int, date_iso.split("-"))
    except Exception:
        raise ValueError("date_iso must be in YYYY-MM-DD format")
    dt = date(y, m, d)

    # Fixed-date holidays
    fixed_checks = (
        (1, 1, Holiday.new_years_day),
        (2, 14, Holiday.valentines_day),
        (3, 17, Holiday.st_patricks_day),
        (7, 4, Holiday.independence_day),
        (10, 31, Holiday.halloween),
        (11, 1, Holiday.all_saints_day),
        (11, 11, Holiday.veterans_day),
        (12, 24, Holiday.christmas_eve),
        (12, 25, Holiday.christmas),
    )
    for fm, fd, enum_val in fixed_checks:
        if dt == date(y, fm, fd):
            return enum_val

    # Variable U.S. holidays (weekday rules)
    for fn in (
        _mlk_day,
        _presidents_day,
        _mothers_day,
        _fathers_day,
        _memorial_day,
        _labor_day,
        _columbus_day,
        _thanksgiving,
        _election_day,
    ):
        val = fn(y, dt)
        if val:
            return val

    # Christian moveable feasts
    mv = _moveable_feasts(y, dt)
    if mv:
        return mv

    return None


# -----------------------------
# CLI
# -----------------------------
def _main():
    if len(sys.argv) != 2:
        print("Usage: python3 holiday.py YYYY-MM-DD")
        sys.exit(2)
    date_iso = sys.argv[1]
    try:
        info = holiday_info(date_iso)  # returns (label, emoji) or None
    except ValueError as e:
        print(str(e))
        sys.exit(2)
    if info is None:
        sys.exit(1)
    h_enum, label, emoji = info
    print(f"{label} {emoji}".strip())
    sys.exit(0)


if __name__ == "__main__":
    _main()
