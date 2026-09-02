from __future__ import annotations

import copy
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (
    ApplyRequest,
    EditSpec,
    FilterSpec,
    NotificationMode,
    OperationResponse,
    OperationResult,
    PreviewItem,
    PreviewRequest,
    PreviewResponse,
    RecurrenceMode,
    TextCriterion,
    TextMode,
)

PREVIEW_TTL = timedelta(minutes=30)
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
WRITABLE_FIELDS = {
    "anyoneCanAddSelf",
    "attachments",
    "attendees",
    "attendeesOmitted",
    "birthdayProperties",
    "colorId",
    "conferenceData",
    "description",
    "end",
    "endTimeUnspecified",
    "eventType",
    "extendedProperties",
    "focusTimeProperties",
    "gadget",
    "guestsCanInviteOthers",
    "guestsCanModify",
    "guestsCanSeeOtherGuests",
    "location",
    "originalStartTime",
    "outOfOfficeProperties",
    "recurrence",
    "reminders",
    "sequence",
    "source",
    "start",
    "status",
    "summary",
    "transparency",
    "visibility",
    "workingLocationProperties",
}


@dataclass
class StoredEvent:
    key: str
    calendar_id: str
    event: dict[str, Any]
    title: str
    match_count: int = 1


@dataclass
class PreviewSnapshot:
    expires_at: datetime
    recurrence_mode: RecurrenceMode
    events: dict[str, StoredEvent]


@dataclass
class UndoEntry:
    source_calendar_id: str
    current_calendar_id: str
    event_id: str
    original: dict[str, Any]
    expected_etag: str
    title: str


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_datetime(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _text_matches(actual: str | None, criterion: TextCriterion | None) -> bool:
    if criterion is None or criterion.value == "":
        return True
    actual = actual or ""
    needle = criterion.value
    if criterion.mode == TextMode.REGEX:
        flags = 0 if criterion.case_sensitive else re.IGNORECASE
        try:
            return re.search(needle, actual, flags) is not None
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc
    if not criterion.case_sensitive:
        actual, needle = actual.casefold(), needle.casefold()
    if criterion.mode == TextMode.EXACT:
        return actual == needle
    return needle in actual


def event_matches(event: dict[str, Any], filters: FilterSpec) -> bool:
    organizer = event.get("organizer", {}).get("email", "")
    attendees = " ".join(item.get("email", "") for item in event.get("attendees", []))
    all_day = "date" in event.get("start", {})
    recurring = bool(event.get("recurringEventId") or event.get("recurrence"))
    if not _text_matches(event.get("summary"), filters.title):
        return False
    if not _text_matches(event.get("description"), filters.description):
        return False
    if not _text_matches(event.get("location"), filters.location):
        return False
    if not _text_matches(organizer, filters.organizer):
        return False
    if not _text_matches(attendees, filters.attendee):
        return False
    if filters.timing == "all_day" and not all_day:
        return False
    if filters.timing == "timed" and all_day:
        return False
    if filters.recurrence == "recurring" and not recurring:
        return False
    if filters.recurrence == "single" and recurring:
        return False
    if filters.visibility and event.get("visibility", "default") not in filters.visibility:
        return False
    if filters.event_types and event.get("eventType", "default") not in filters.event_types:
        return False
    return True


def resolve_date_range(filters: FilterSpec, now: datetime | None = None) -> tuple[datetime, datetime]:
    spec = filters.date_range
    try:
        timezone = ZoneInfo(spec.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown time zone: {spec.timezone}") from exc
    if spec.mode == "absolute":
        assert spec.start is not None and spec.end is not None
        start = spec.start.replace(tzinfo=spec.start.tzinfo or timezone)
        end = spec.end.replace(tzinfo=spec.end.tzinfo or timezone)
    else:
        local_now = (now or datetime.now(UTC)).astimezone(timezone)
        start_day = local_now.date() - timedelta(days=spec.days_before)
        end_day = local_now.date() + timedelta(days=spec.days_after + 1)
        start = datetime.combine(start_day, datetime.min.time(), timezone)
        end = datetime.combine(end_day, datetime.min.time(), timezone)
    return start, end


def _shift_temporal(value: dict[str, Any], minutes: int) -> dict[str, Any]:
    shifted = copy.deepcopy(value)
    if "dateTime" in shifted:
        shifted["dateTime"] = _format_datetime(_parse_datetime(shifted["dateTime"]) + timedelta(minutes=minutes))
    else:
        if minutes % 1440:
            raise ValueError("All-day events can only be shifted by whole days")
        shifted["date"] = (date.fromisoformat(shifted["date"]) + timedelta(days=minutes // 1440)).isoformat()
    return shifted


def apply_edit_to_event(event: dict[str, Any], edit: EditSpec) -> dict[str, Any]:
    changed = copy.deepcopy(event)
    if edit.title_set is not None:
        changed["summary"] = edit.title_set
    elif edit.title_find is not None:
        source = changed.get("summary", "")
        if edit.title_case_sensitive:
            changed["summary"] = source.replace(edit.title_find, edit.title_replace)
        else:
            changed["summary"] = re.sub(
                re.escape(edit.title_find), lambda _: edit.title_replace, source, flags=re.IGNORECASE
            )
    if edit.description_mode == "replace":
        changed["description"] = edit.description_value
    elif edit.description_mode == "append":
        original = changed.get("description", "")
        changed["description"] = f"{original}\n{edit.description_value}".lstrip("\n")
    if edit.location_set is not None:
        changed["location"] = edit.location_set
    if edit.shift_minutes is not None:
        changed["start"] = _shift_temporal(changed["start"], edit.shift_minutes)
        changed["end"] = _shift_temporal(changed["end"], edit.shift_minutes)
    if edit.duration_minutes is not None or edit.duration_delta_minutes is not None:
        if "date" in changed["start"]:
            requested = edit.duration_minutes if edit.duration_minutes is not None else edit.duration_delta_minutes
            assert requested is not None
            if requested % 1440:
                raise ValueError("All-day durations must use whole days")
            current_days = (
                date.fromisoformat(changed["end"]["date"]) - date.fromisoformat(changed["start"]["date"])
            ).days
            days = requested // 1440 if edit.duration_minutes is not None else current_days + requested // 1440
            if days < 1:
                raise ValueError("Event duration must remain positive")
            changed["end"]["date"] = (date.fromisoformat(changed["start"]["date"]) + timedelta(days=days)).isoformat()
        else:
            start = _parse_datetime(changed["start"]["dateTime"])
            old_end = _parse_datetime(changed["end"]["dateTime"])
            minutes = (
                edit.duration_minutes
                if edit.duration_minutes is not None
                else int((old_end - start).total_seconds() // 60) + int(edit.duration_delta_minutes or 0)
            )
            if minutes <= 0:
                raise ValueError("Event duration must remain positive")
            changed["end"]["dateTime"] = _format_datetime(start + timedelta(minutes=minutes))
    if edit.visibility is not None:
        changed["visibility"] = edit.visibility
    if edit.replace_reminders:
        changed["reminders"] = {
            "useDefault": False,
            "overrides": [reminder.model_dump() for reminder in edit.reminders],
        }
    return changed


def writable_event(event: dict[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in event.items() if key in WRITABLE_FIELDS}


class CalendarEngine:
    def __init__(self, service_provider: Callable[[], Any], clock: Callable[[], datetime] | None = None):
        self._service_provider = service_provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._previews: dict[str, PreviewSnapshot] = {}
        self._undo: list[UndoEntry] = []
        self._lock = threading.RLock()

    def clear_session(self) -> None:
        with self._lock:
            self._previews.clear()
            self._undo.clear()

    def list_calendars(self) -> list[dict[str, Any]]:
        service = self._service_provider()
        calendars: list[dict[str, Any]] = []
        token = None
        while True:
            response = self._execute(service.calendarList().list(pageToken=token, maxResults=250))
            for item in response.get("items", []):
                calendars.append(
                    {
                        "id": item["id"],
                        "name": item.get("summaryOverride") or item.get("summary") or item["id"],
                        "timezone": item.get("timeZone", "UTC"),
                        "access_role": item.get("accessRole", "reader"),
                        "primary": item.get("primary", False),
                        "writable": item.get("accessRole") in {"writer", "owner"},
                        "background_color": item.get("backgroundColor", "#64748b"),
                    }
                )
            token = response.get("nextPageToken")
            if not token:
                return calendars

    def preview(self, request: PreviewRequest) -> PreviewResponse:
        service = self._service_provider()
        calendar_roles = {item["id"]: item for item in self.list_calendars()}
        unavailable = [
            calendar_id
            for calendar_id in request.filters.calendar_ids
            if not calendar_roles.get(calendar_id, {}).get("writable")
        ]
        if unavailable:
            raise ValueError("Choose calendars where you have write access")
        start, end = resolve_date_range(request.filters, self._clock())
        matched: list[StoredEvent] = []
        for calendar_id in request.filters.calendar_ids:
            page_token = None
            while True:
                response = self._execute(
                    service.events().list(
                        calendarId=calendar_id,
                        timeMin=start.isoformat(),
                        timeMax=end.isoformat(),
                        singleEvents=True,
                        showDeleted=False,
                        maxResults=2500,
                        pageToken=page_token,
                    )
                )
                for event in response.get("items", []):
                    if event_matches(event, request.filters):
                        key = f"{calendar_id}:{event['id']}"
                        matched.append(StoredEvent(key, calendar_id, event, event.get("summary", "(untitled)")))
                page_token = response.get("nextPageToken")
                if not page_token:
                    break

        warnings: list[str] = []
        if request.recurrence_mode == RecurrenceMode.SERIES:
            matched = self._expand_series(service, matched)
            if any(item.event.get("recurrence") for item in matched):
                warnings.append("Whole-series edits can affect occurrences outside the selected date range.")
        expires_at = self._clock() + PREVIEW_TTL
        token = secrets.token_urlsafe(24)
        snapshot = PreviewSnapshot(expires_at, request.recurrence_mode, {item.key: item for item in matched})
        with self._lock:
            self._prune_previews()
            self._previews[token] = snapshot
        return PreviewResponse(
            token=token,
            expires_at=expires_at,
            items=[self._preview_item(item) for item in matched],
            warnings=warnings,
        )

    def _expand_series(self, service: Any, matched: list[StoredEvent]) -> list[StoredEvent]:
        singles: dict[str, StoredEvent] = {}
        groups: dict[tuple[str, str], list[StoredEvent]] = {}
        for item in matched:
            recurring_id = item.event.get("recurringEventId")
            if recurring_id:
                groups.setdefault((item.calendar_id, recurring_id), []).append(item)
            else:
                singles[item.key] = item
        for (calendar_id, recurring_id), occurrences in groups.items():
            master = self._execute(service.events().get(calendarId=calendar_id, eventId=recurring_id))
            key = f"{calendar_id}:{recurring_id}"
            singles[key] = StoredEvent(key, calendar_id, master, master.get("summary", "(untitled)"), len(occurrences))
        return list(singles.values())

    def apply(self, request: ApplyRequest) -> OperationResponse:
        snapshot = self._get_preview(request.preview_token)
        selected = [snapshot.events[key] for key in request.selected_keys if key in snapshot.events]
        if len(selected) != len(set(request.selected_keys)):
            raise ValueError("One or more selected events are not in this preview")
        if request.edit.delete and request.delete_confirmation != f"DELETE {len(selected)}":
            raise ValueError(f'Type "DELETE {len(selected)}" to confirm permanent deletion')
        if request.edit.destination_calendar_id:
            destinations = {item["id"]: item for item in self.list_calendars()}
            destination = destinations.get(request.edit.destination_calendar_id)
            if not destination or not destination["writable"]:
                raise ValueError("The destination calendar is not writable")
            if all(item.calendar_id == request.edit.destination_calendar_id for item in selected):
                raise ValueError("Source and destination calendars are the same")
        service = self._service_provider()
        results: list[OperationResult] = []
        undo: list[UndoEntry] = []
        for stored in selected:
            try:
                result, undo_entry = self._apply_one(service, stored, request.edit, request.notifications)
                results.append(result)
                if undo_entry:
                    undo.append(undo_entry)
            except ValueError as exc:
                results.append(OperationResult(key=stored.key, title=stored.title, status="skipped", message=str(exc)))
            except Exception as exc:
                results.append(
                    OperationResult(key=stored.key, title=stored.title, status="failed", message=self._safe_error(exc))
                )
        with self._lock:
            self._undo = undo
            self._previews.pop(request.preview_token, None)
        return OperationResponse(results=results, undo_available=bool(undo))

    def _apply_one(
        self, service: Any, stored: StoredEvent, edit: EditSpec, notifications: NotificationMode
    ) -> tuple[OperationResult, UndoEntry | None]:
        current = self._execute(service.events().get(calendarId=stored.calendar_id, eventId=stored.event["id"]))
        if current.get("etag") != stored.event.get("etag"):
            return OperationResult(
                key=stored.key, title=stored.title, status="conflict", message="Event changed after preview"
            ), None
        if edit.delete:
            delete_request = service.events().delete(
                calendarId=stored.calendar_id,
                eventId=current["id"],
                sendUpdates=notifications.value,
            )
            self._execute(self._with_etag(delete_request, current.get("etag")))
            return OperationResult(
                key=stored.key, title=stored.title, status="success", message="Deleted permanently"
            ), None
        if edit.destination_calendar_id and current.get("eventType", "default") != "default":
            raise ValueError(f"{current.get('eventType')} events cannot be moved")
        original = copy.deepcopy(current)
        changed = apply_edit_to_event(current, edit)
        update_request = service.events().update(
            calendarId=stored.calendar_id,
            eventId=current["id"],
            body=writable_event(changed),
            sendUpdates=notifications.value,
        )
        updated = self._execute(self._with_etag(update_request, current.get("etag")))
        current_calendar = stored.calendar_id
        if edit.destination_calendar_id:
            move_request = service.events().move(
                calendarId=stored.calendar_id,
                eventId=updated["id"],
                destination=edit.destination_calendar_id,
                sendUpdates=notifications.value,
            )
            updated = self._execute(self._with_etag(move_request, updated.get("etag")))
            current_calendar = edit.destination_calendar_id
        undo = UndoEntry(
            source_calendar_id=stored.calendar_id,
            current_calendar_id=current_calendar,
            event_id=updated["id"],
            original=original,
            expected_etag=updated.get("etag", ""),
            title=stored.title,
        )
        return OperationResult(key=stored.key, title=stored.title, status="success", message="Updated"), undo

    def undo(self, notifications: NotificationMode = NotificationMode.NONE) -> OperationResponse:
        with self._lock:
            entries = list(self._undo)
            self._undo = []
        service = self._service_provider()
        results: list[OperationResult] = []
        for entry in entries:
            key = f"{entry.source_calendar_id}:{entry.event_id}"
            try:
                current = self._execute(
                    service.events().get(calendarId=entry.current_calendar_id, eventId=entry.event_id)
                )
                if current.get("etag") != entry.expected_etag:
                    results.append(
                        OperationResult(
                            key=key,
                            title=entry.title,
                            status="conflict",
                            message="Event changed after the bulk operation",
                        )
                    )
                    continue
                if entry.current_calendar_id != entry.source_calendar_id:
                    move_request = service.events().move(
                        calendarId=entry.current_calendar_id,
                        eventId=entry.event_id,
                        destination=entry.source_calendar_id,
                        sendUpdates=notifications.value,
                    )
                    current = self._execute(self._with_etag(move_request, current.get("etag")))
                update_request = service.events().update(
                    calendarId=entry.source_calendar_id,
                    eventId=current["id"],
                    body=writable_event(entry.original),
                    sendUpdates=notifications.value,
                )
                restored = self._execute(self._with_etag(update_request, current.get("etag")))
                results.append(
                    OperationResult(
                        key=key,
                        title=entry.title,
                        status="success",
                        message=f"Restored {restored.get('summary', entry.title)}",
                    )
                )
            except Exception as exc:
                results.append(
                    OperationResult(key=key, title=entry.title, status="failed", message=self._safe_error(exc))
                )
        return OperationResponse(results=results, undo_available=False)

    def _preview_item(self, stored: StoredEvent) -> PreviewItem:
        event = stored.event
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")
        event_type = event.get("eventType", "default")
        return PreviewItem(
            key=stored.key,
            calendar_id=stored.calendar_id,
            event_id=event["id"],
            etag=event.get("etag", ""),
            title=stored.title,
            start=start,
            end=end,
            all_day="date" in event.get("start", {}),
            recurring=bool(event.get("recurringEventId") or event.get("recurrence")),
            event_type=event_type,
            visibility=event.get("visibility", "default"),
            location=event.get("location", ""),
            move_eligible=event_type == "default",
            match_count=stored.match_count,
        )

    def _get_preview(self, token: str) -> PreviewSnapshot:
        with self._lock:
            self._prune_previews()
            snapshot = self._previews.get(token)
        if snapshot is None:
            raise ValueError("Preview expired; run the search again")
        return snapshot

    def _prune_previews(self) -> None:
        now = self._clock()
        self._previews = {key: value for key, value in self._previews.items() if value.expires_at > now}

    @staticmethod
    def _execute(request: Any) -> Any:
        delay = 0.25
        for attempt in range(4):
            try:
                return request.execute()
            except Exception as exc:
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status not in TRANSIENT_STATUS or attempt == 3:
                    raise
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("Unreachable")

    @staticmethod
    def _with_etag(request: Any, etag: str | None) -> Any:
        if etag and hasattr(request, "headers"):
            request.headers["If-Match"] = etag
        return request

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status:
            return f"Google Calendar request failed (HTTP {status})"
        return str(exc) or exc.__class__.__name__
