from datetime import UTC, datetime

import pytest

from bulk_edit_calendar.calendar import CalendarEngine
from bulk_edit_calendar.models import ApplyRequest, DateRange, EditSpec, FilterSpec, PreviewRequest, RecurrenceMode

from .fakes import FakeService, sample_event

NOW = datetime(2026, 9, 2, tzinfo=UTC)


def request(mode=RecurrenceMode.OCCURRENCES):
    return PreviewRequest(
        filters=FilterSpec(calendar_ids=["primary"], date_range=DateRange(mode="relative", days_after=30)),
        recurrence_mode=mode,
    )


def test_calendar_list_marks_writable_entries():
    engine = CalendarEngine(lambda: FakeService([]), clock=lambda: NOW)
    calendars = engine.list_calendars()
    assert [item["writable"] for item in calendars] == [True, True]


def test_preview_update_move_and_session_undo():
    service = FakeService([("primary", sample_event())])
    engine = CalendarEngine(lambda: service, clock=lambda: NOW)
    preview = engine.preview(request())
    response = engine.apply(
        ApplyRequest(
            preview_token=preview.token,
            selected_keys=[preview.items[0].key],
            edit=EditSpec(title_set="Updated", destination_calendar_id="work"),
        )
    )
    assert response.results[0].status == "success"
    assert response.undo_available
    assert service.data[("work", "e1")]["summary"] == "Updated"
    undo = engine.undo()
    assert undo.results[0].status == "success"
    assert service.data[("primary", "e1")]["summary"] == "Planning"


def test_stale_preview_is_reported_as_conflict():
    service = FakeService([("primary", sample_event())])
    engine = CalendarEngine(lambda: service, clock=lambda: NOW)
    preview = engine.preview(request())
    service.data[("primary", "e1")]["etag"] = '"external"'
    response = engine.apply(
        ApplyRequest(
            preview_token=preview.token, selected_keys=[preview.items[0].key], edit=EditSpec(title_set="No overwrite")
        )
    )
    assert response.results[0].status == "conflict"
    assert service.data[("primary", "e1")]["summary"] == "Planning"


def test_delete_requires_typed_count_and_has_no_undo():
    service = FakeService([("primary", sample_event())])
    engine = CalendarEngine(lambda: service, clock=lambda: NOW)
    preview = engine.preview(request())
    with pytest.raises(ValueError, match="DELETE 1"):
        engine.apply(
            ApplyRequest(preview_token=preview.token, selected_keys=[preview.items[0].key], edit=EditSpec(delete=True))
        )
    response = engine.apply(
        ApplyRequest(
            preview_token=preview.token,
            selected_keys=[preview.items[0].key],
            edit=EditSpec(delete=True),
            delete_confirmation="DELETE 1",
        )
    )
    assert response.results[0].status == "success"
    assert not response.undo_available


def test_whole_series_deduplicates_occurrences():
    master = sample_event("series", recurrence=["RRULE:FREQ=DAILY"])
    first = sample_event("instance-1", recurringEventId="series")
    second = sample_event("instance-2", recurringEventId="series")
    service = FakeService([("primary", master), ("primary", first), ("primary", second)])
    engine = CalendarEngine(lambda: service, clock=lambda: NOW)
    preview = engine.preview(request(RecurrenceMode.SERIES))
    series = [item for item in preview.items if item.event_id == "series"]
    assert len(series) == 1
    assert series[0].match_count == 2
    assert preview.warnings


def test_special_event_move_is_skipped():
    service = FakeService([("primary", sample_event(eventType="birthday"))])
    engine = CalendarEngine(lambda: service, clock=lambda: NOW)
    preview = engine.preview(request())
    response = engine.apply(
        ApplyRequest(
            preview_token=preview.token,
            selected_keys=[preview.items[0].key],
            edit=EditSpec(destination_calendar_id="work"),
        )
    )
    assert response.results[0].status == "skipped"
