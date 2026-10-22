"""The deterministic date resolver: spoken due phrases to calendar dates, relative to the call date.

Weeks start on Monday. A bare weekday means the next one after the call date; "next <weekday>" means
that weekday in the next calendar week. Unrecognised phrases resolve to nothing and keep the model's
precision hint (event or vague only).
"""

from datetime import date

import pytest

from commitment_tracker.extractor.dates import ResolvedDue, resolve_due
from commitment_tracker.schemas import Precision

WED = date(2026, 10, 21)  # the spec's call date
D, W, E, V, N = Precision.DAY, Precision.WEEK, Precision.EVENT, Precision.VAGUE, Precision.NONE


def d(month: int, day: int, year: int = 2026) -> date:
    return date(year, month, day)


# --- Phrases relative to Wednesday 2026-10-21 ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "resolved", "precision"),
    [
        # same day
        ("today", d(10, 21), D),
        ("this afternoon", d(10, 21), D),
        ("tonight", d(10, 21), D),
        ("by end of day", d(10, 21), D),
        ("EOD", d(10, 21), D),
        ("close of business", d(10, 21), D),
        # next days
        ("tomorrow", d(10, 22), D),
        ("first thing tomorrow", d(10, 22), D),
        ("tomorrow afternoon", d(10, 22), D),
        ("the day after tomorrow", d(10, 23), D),
        # weekdays (spec #1, #8)
        ("by Friday", d(10, 23), D),
        ("Friday", d(10, 23), D),
        ("on Friday afternoon", d(10, 23), D),
        ("Friday at 5pm", d(10, 23), D),
        ("this Friday", d(10, 23), D),
        ("Monday", d(10, 26), D),
        ("Wednesday", d(10, 28), D),  # said on a Wednesday: next week's
        ("Tuesday", d(10, 27), D),
        # next <weekday> = that weekday in the next calendar week (spec #12)
        ("next Tuesday", d(10, 27), D),
        ("next Friday", d(10, 30), D),
        ("next Monday", d(10, 26), D),
        # weeks (spec #2, #7)
        ("by end of next week", d(10, 30), D),
        ("end of the week", d(10, 23), D),
        ("EOW", d(10, 23), D),
        ("this week", d(10, 19), W),
        ("later this week", d(10, 19), W),
        ("next week", d(10, 26), W),
        ("early next week", d(10, 26), W),
        # day of month (spec #11)
        ("on the 1st", d(11, 1), D),
        ("the 15th", d(11, 15), D),
        ("the 30th", d(10, 30), D),
        ("the 21st", d(11, 21), D),  # today's date means next month's
        ("Monday the 26th", d(10, 26), D),
        # named dates
        ("October 30", d(10, 30), D),
        ("by Oct 30th", d(10, 30), D),
        ("30 October", d(10, 30), D),
        ("Nov. 3", d(11, 3), D),
        ("October 1", d(10, 1, 2027), D),  # already past this year
        ("December 5, 2027", d(12, 5, 2027), D),
        ("2026-11-04", d(11, 4), D),
        # offsets
        ("in 3 days", d(10, 24), D),
        ("in two weeks", d(11, 4), D),
        ("in a week", d(10, 28), D),
        ("within a couple of days", d(10, 23), D),
        # months
        ("end of the month", d(10, 31), D),
        ("by end of next month", d(11, 30), D),
    ],
)
def test_resolves_phrase(raw: str, resolved: date, precision: Precision) -> None:
    assert resolve_due(raw, WED) == ResolvedDue(resolved, precision)


# --- Week boundaries -----------------------------------------------------------------------------

SAT, SUN, MON = date(2026, 10, 24), date(2026, 10, 25), date(2026, 10, 26)


@pytest.mark.parametrize(
    ("raw", "call_date", "resolved", "precision"),
    [
        ("this week", SUN, d(10, 19), W),  # Sunday still belongs to the week of Monday the 19th
        ("next week", SUN, d(10, 26), W),
        ("next Monday", SUN, d(10, 26), D),
        ("Monday", SUN, d(10, 26), D),
        ("this week", MON, d(10, 26), W),
        ("next Monday", MON, d(11, 2), D),
        ("Monday", MON, d(11, 2), D),
        ("end of the week", SAT, d(10, 30), D),  # this Friday has passed
        ("end of next week", SAT, d(10, 30), D),
        ("Friday", SAT, d(10, 30), D),
        ("next week", date(2026, 12, 30), d(1, 4, 2027), W),  # across the year end
    ],
)
def test_week_boundaries(raw: str, call_date: date, resolved: date, precision: Precision) -> None:
    assert resolve_due(raw, call_date) == ResolvedDue(resolved, precision)


# --- Month and year rollover ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "call_date", "resolved"),
    [
        ("the 1st", date(2026, 10, 30), d(11, 1)),
        ("the 3rd", date(2026, 12, 20), d(1, 3, 2027)),
        ("the 31st", date(2026, 11, 5), d(12, 31)),  # November has no 31st
        ("the 30th", date(2027, 1, 31), d(3, 30, 2027)),  # nor does February
        ("tomorrow", date(2026, 12, 31), d(1, 1, 2027)),
        ("in 2 weeks", date(2026, 12, 24), d(1, 7, 2027)),
        ("end of the month", date(2026, 2, 10), d(2, 28)),
        ("end of the month", date(2028, 2, 10), d(2, 29, 2028)),
        ("end of next month", date(2026, 12, 15), d(1, 31, 2027)),
        ("end of next week", date(2026, 12, 30), d(1, 8, 2027)),
        ("January 5", date(2026, 12, 20), d(1, 5, 2027)),
        ("Feb 29", date(2026, 10, 21), d(2, 29, 2028)),
    ],
)
def test_month_and_year_rollover(raw: str, call_date: date, resolved: date) -> None:
    assert resolve_due(raw, call_date) == ResolvedDue(resolved, D)


# --- No date -------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_no_phrase_is_precision_none(raw: str | None) -> None:
    assert resolve_due(raw, WED) == ResolvedDue(None, N)


@pytest.mark.parametrize("raw", ["soon", "at some point", "ASAP", "eventually", "next month"])
def test_vague_phrases(raw: str) -> None:
    assert resolve_due(raw, WED) == ResolvedDue(None, V)


@pytest.mark.parametrize(
    ("raw", "hint", "precision"),
    [
        ("before your board meeting", E, E),  # spec #4
        ("after the security review", E, E),
        ("when we circle back", V, V),
        ("whenever procurement is ready", None, V),
        ("before the offsite", D, V),  # the hint can't claim a day the resolver didn't find
        ("before the offsite", W, V),
    ],
)
def test_unrecognised_phrase_uses_the_hint(
    raw: str, hint: Precision | None, precision: Precision
) -> None:
    assert resolve_due(raw, WED, hint) == ResolvedDue(None, precision)


@pytest.mark.parametrize("raw", ["the 32nd", "February 30", "2026-13-01", "in 0 days"])
def test_impossible_dates_do_not_resolve(raw: str) -> None:
    assert resolve_due(raw, WED, E).resolved is None


def test_a_resolved_phrase_ignores_the_hint() -> None:
    assert resolve_due("by Friday", WED, E) == ResolvedDue(d(10, 23), D)


# --- "before <date>": the day before it ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "call_date", "resolved"),
    [
        ("before Thursday", WED, d(10, 21)),  # Thursday is the 22nd, so it's due today
        ("before Friday", WED, d(10, 22)),
        ("by before Friday", WED, d(10, 22)),
        ("before next Friday", WED, d(10, 29)),
        ("before tomorrow", WED, d(10, 21)),
        ("before the 1st", WED, d(10, 31)),
        ("before November 3", WED, d(11, 2)),
        ("before next week", WED, d(10, 25)),  # the Sunday before Monday the 26th
        ("before the 1st", date(2026, 12, 20), d(12, 31)),  # across the year end
    ],
)
def test_before_a_date_is_the_day_before(raw: str, call_date: date, resolved: date) -> None:
    assert resolve_due(raw, call_date) == ResolvedDue(resolved, D)


@pytest.mark.parametrize(
    ("raw", "hint", "precision"),
    [
        ("before your board meeting", E, E),  # spec #4 stays an event
        ("before the renewal call", E, E),
        ("before it ships", None, V),
        ("before soon", E, E),
    ],
)
def test_before_an_event_keeps_the_hint(
    raw: str, hint: Precision | None, precision: Precision
) -> None:
    assert resolve_due(raw, WED, hint) == ResolvedDue(None, precision)
