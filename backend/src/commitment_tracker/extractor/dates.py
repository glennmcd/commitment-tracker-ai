"""Deterministic due-date resolution: a spoken phrase plus the call date gives a calendar date.

The model only returns the phrase (`due.raw`); every date is computed here so each rule is tested.
Conventions: weeks start on Monday; a bare weekday is the next one after the call date; "next
<weekday>" is that weekday in the next calendar week; "the Nth" is the next Nth after the call date;
a week-precision date is the Monday of that week; "before <date>" is the day before that date.
Phrases no rule recognises resolve to nothing and keep the model's precision hint, limited to event
or vague.
"""

import calendar
import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import NamedTuple

from dateutil.relativedelta import FR, MO, SA, SU, TH, TU, WE, relativedelta, weekday

from commitment_tracker.schemas import Precision


class ResolvedDue(NamedTuple):
    resolved: date | None
    precision: Precision


WEEKDAYS: dict[str, weekday] = {
    "monday": MO,
    "tuesday": TU,
    "wednesday": WE,
    "thursday": TH,
    "friday": FR,
    "saturday": SA,
    "sunday": SU,
}
MONTHS = {
    name: number
    for number, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
NUMBERS = {"a": 1, "one": 1, "a couple of": 2, "two": 2, "three": 3, "four": 4, "five": 5}
NUMBERS |= {"six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}

VAGUE = {
    "soon",
    "asap",
    "as soon as possible",
    "at some point",
    "eventually",
    "later",
    "shortly",
    "in a bit",
    "down the road",
    "in the future",
    "next month",
}
HINTABLE = {Precision.EVENT, Precision.VAGUE}

# Words around the date that don't change it: "by Friday", "Friday afternoon", "Friday at 5pm".
LEADING = re.compile(r"^(?:no later than|by|on|until|till|for|due|around|first thing)\s+")
TRAILING = re.compile(
    r"\s+(?:at the latest|first thing|morning|afternoon|evening|night|eod|cob|end of day"
    r"|at \d{1,2}(?::\d{2})?\s*(?:am|pm)?|\d{1,2}(?::\d{2})?\s*(?:am|pm))$"
)

WD = "(" + "|".join(WEEKDAYS) + ")"
MON = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")"
ORD = r"(\d{1,2})(?:st|nd|rd|th)?"
COUNT = "(" + "|".join(sorted(NUMBERS, key=len, reverse=True)) + r"|\d+)"


def _normalise(raw: str) -> str:
    text = raw.lower().replace("’", "'").replace(",", " ").replace(".", " ")
    text = re.sub(r"\s+", " ", text).strip(" !?;:")
    # "this afternoon" is today; say so before the trailing time of day is stripped.
    text = re.sub(r"\bthis (?:morning|afternoon|evening|night)\b", "today", text)
    previous = None
    while text != previous:
        previous = text
        text = LEADING.sub("", text)
        text = TRAILING.sub("", text)
    return text


def _monday(day: date) -> date:
    return day + relativedelta(weekday=MO(-1))


def _safe_date(year: int, month: int, day: int) -> date | None:
    if 1 <= month <= 12 and 1 <= day <= calendar.monthrange(year, month)[1]:
        return date(year, month, day)
    return None


def _next_day_of_month(call: date, day: int) -> date | None:
    """The first date after `call` falling on `day` of a month, skipping months without it."""
    for offset in range(25):
        first = call.replace(day=1) + relativedelta(months=offset)
        candidate = _safe_date(first.year, first.month, day)
        if candidate is not None and candidate > call:
            return candidate
    return None


def _next_named_date(call: date, month: int, day: int) -> date | None:
    """`month day` on or after `call`, looking up to eight years ahead (for February 29)."""
    for year in range(call.year, call.year + 9):
        candidate = _safe_date(year, month, day)
        if candidate is not None and candidate >= call:
            return candidate
    return None


def _named_date(call: date, month: str, day: str, year: str | None) -> date | None:
    """'October 30' (next one on or after the call) or 'October 30 2027' (as written)."""
    if year:
        return _safe_date(int(year), MONTHS[month], int(day))
    return _next_named_date(call, MONTHS[month], int(day))


def _offset(count: str, unit: str, call: date) -> date | None:
    n = NUMBERS[count] if count in NUMBERS else int(count)
    if n < 1:
        return None
    return call + timedelta(days=n * (7 if unit.startswith("week") else 1))


Rule = tuple[re.Pattern[str], Precision, Callable[[re.Match[str], date], date | None]]


def _rule(
    pattern: str, precision: Precision, fn: Callable[[re.Match[str], date], date | None]
) -> Rule:
    return re.compile(pattern), precision, fn


D, W = Precision.DAY, Precision.WEEK

RULES: list[Rule] = [
    _rule(
        r"today|tonight|(?:the )?end of (?:the )?day|eod|cob|close of business", D, lambda m, c: c
    ),
    _rule(r"tomorrow", D, lambda m, c: c + timedelta(days=1)),
    _rule(r"(?:the )?day after tomorrow", D, lambda m, c: c + timedelta(days=2)),
    _rule(
        r"(?:the )?end of (?:the |this )?week|eow",
        D,
        lambda m, c: c + relativedelta(weekday=FR(+1)),
    ),
    _rule(
        r"(?:the )?end of next week",
        D,
        lambda m, c: _monday(c) + timedelta(days=7) + relativedelta(weekday=FR(+1)),
    ),
    _rule(r"(?:early |later |late |sometime )?this week", W, lambda m, c: _monday(c)),
    _rule(
        r"(?:early |later |late |sometime )?next week",
        W,
        lambda m, c: _monday(c) + timedelta(days=7),
    ),
    _rule(r"(?:the )?end of (?:the |this )?month|eom", D, lambda m, c: c + relativedelta(day=31)),
    _rule(r"(?:the )?end of next month", D, lambda m, c: c + relativedelta(months=1, day=31)),
    _rule(
        rf"next {WD}",
        D,
        lambda m, c: _monday(c) + timedelta(days=7) + relativedelta(weekday=WEEKDAYS[m[1]](+1)),
    ),
    _rule(rf"this {WD}", D, lambda m, c: c + relativedelta(weekday=WEEKDAYS[m[1]](+1))),
    _rule(WD, D, lambda m, c: c + relativedelta(days=1, weekday=WEEKDAYS[m[1]](+1))),
    _rule(
        rf"(?:{WD} )?the {ORD}|(\d{{1,2}})(?:st|nd|rd|th)",
        D,
        lambda m, c: _next_day_of_month(c, int(m[2] or m[3])),
    ),
    _rule(rf"{MON} {ORD}(?: (\d{{4}}))?", D, lambda m, c: _named_date(c, m[1], m[2], m[3])),
    _rule(
        rf"(?:the )?{ORD} (?:of )?{MON}(?: (\d{{4}}))?",
        D,
        lambda m, c: _named_date(c, m[2], m[1], m[3]),
    ),
    _rule(r"(\d{4})-(\d{2})-(\d{2})", D, lambda m, c: _safe_date(int(m[1]), int(m[2]), int(m[3]))),
    _rule(rf"(?:in|within) {COUNT} (days?|weeks?)", D, lambda m, c: _offset(m[1], m[2], c)),
]


def _apply_rules(text: str, call_date: date) -> ResolvedDue | None:
    """The first rule that matches the whole phrase decides; None if none resolves it."""
    for pattern, precision, fn in RULES:
        match = pattern.fullmatch(text)
        if match:
            resolved = fn(match, call_date)
            return ResolvedDue(resolved, precision) if resolved is not None else None
    return None


def _day_before(target: ResolvedDue) -> ResolvedDue:
    """'before Thursday' is due Wednesday; 'before next week' is due the Sunday before it."""
    assert target.resolved is not None
    return ResolvedDue(target.resolved - timedelta(days=1), Precision.DAY)


def resolve_due(raw: str | None, call_date: date, hint: Precision | None = None) -> ResolvedDue:
    """Resolve a spoken due phrase against the call date."""
    if raw is None or not raw.strip():
        return ResolvedDue(None, Precision.NONE)
    fallback = ResolvedDue(None, hint if hint in HINTABLE else Precision.VAGUE)
    text = _normalise(raw)
    if text.startswith("before "):
        # A date after "before" is due the day before it; anything else ("before your board
        # meeting") is an event or vague deadline, so the hint decides.
        target = _apply_rules(text.removeprefix("before "), call_date)
        return _day_before(target) if target is not None else fallback
    if text in VAGUE:
        return ResolvedDue(None, Precision.VAGUE)
    return _apply_rules(text, call_date) or fallback
