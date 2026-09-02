from datetime import datetime

import pytest
from pydantic import ValidationError

from bulk_edit_calendar.calendar import apply_edit_to_event, event_matches, resolve_date_range
from bulk_edit_calendar.models import DateRange, EditSpec, FilterSpec, TextCriterion, TextMode


def event() -> dict:
    return {
        "id": "event-1",
        "summary": "Project Planning",
        "description": "Quarterly roadmap",
        "location": "Toronto",
        "organizer": {"email": "owner@example.com"},
        "attendees": [{"email": "guest@example.com"}],
        "start": {"dateTime": "2026-03-08T01:30:00-05:00"},
        "end": {"dateTime": "2026-03-08T02:30:00-05:00"},
        "eventType": "default",
    }


def filters(**kwargs) -> FilterSpec:
    kwargs.setdefault("date_range", DateRange())
    return FilterSpec(calendar_ids=["primary"], **kwargs)


def test_combined_text_filters_and_regex():
    spec = filters(
        title=TextCriterion(value="project", mode=TextMode.CONTAINS),
        attendee=TextCriterion(value=r"guest@.*\.com", mode=TextMode.REGEX),
        timing="timed",
    )
    assert event_matches(event(), spec)
    assert not event_matches(
        event(), spec.model_copy(update={"location": TextCriterion(value="Montreal", mode=TextMode.EXACT)})
    )


def test_invalid_regex_has_safe_validation_error():
    with pytest.raises(ValueError, match="Invalid regular expression"):
        event_matches(event(), filters(title=TextCriterion(value="(", mode=TextMode.REGEX)))


def test_relative_range_respects_timezone_and_dst():
    with pytest.raises(ValidationError):
        DateRange(mode="relative", days_before=0, days_after=0, timezone="America/Toronto")


def test_resolve_relative_range_uses_calendar_days():
    spec = filters(date_range=DateRange(mode="relative", days_before=1, days_after=1, timezone="America/Toronto"))
    start, end = resolve_date_range(spec, datetime.fromisoformat("2026-03-08T12:00:00+00:00"))
    assert start.isoformat() == "2026-03-07T00:00:00-05:00"
    assert end.isoformat() == "2026-03-10T00:00:00-04:00"


def test_edit_combines_text_time_visibility_and_reminders():
    changed = apply_edit_to_event(
        event(),
        EditSpec(
            title_find="project",
            title_replace="Team",
            description_mode="append",
            description_value="Bring notes",
            shift_minutes=30,
            duration_minutes=45,
            visibility="private",
            replace_reminders=True,
            reminders=[{"method": "popup", "minutes": 15}],
        ),
    )
    assert changed["summary"] == "Team Planning"
    assert changed["description"].endswith("Bring notes")
    assert changed["start"]["dateTime"] == "2026-03-08T02:00:00-05:00"
    assert changed["end"]["dateTime"] == "2026-03-08T02:45:00-05:00"
    assert changed["visibility"] == "private"
    assert changed["reminders"]["overrides"] == [{"method": "popup", "minutes": 15}]


def test_all_day_shift_requires_whole_days():
    all_day = event() | {"start": {"date": "2026-04-01"}, "end": {"date": "2026-04-02"}}
    with pytest.raises(ValueError, match="whole days"):
        apply_edit_to_event(all_day, EditSpec(shift_minutes=30))


def test_delete_is_exclusive():
    with pytest.raises(ValidationError, match="Deletion cannot be combined"):
        EditSpec(delete=True, title_set="Nope")
