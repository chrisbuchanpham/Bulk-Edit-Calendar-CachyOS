from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TextMode(StrEnum):
    CONTAINS = "contains"
    EXACT = "exact"
    REGEX = "regex"


class RecurrenceMode(StrEnum):
    OCCURRENCES = "occurrences"
    SERIES = "series"


class NotificationMode(StrEnum):
    NONE = "none"
    EXTERNAL_ONLY = "externalOnly"
    ALL = "all"


class TextCriterion(BaseModel):
    value: str = ""
    mode: TextMode = TextMode.CONTAINS
    case_sensitive: bool = False


class DateRange(BaseModel):
    mode: Literal["absolute", "relative"] = "relative"
    start: datetime | None = None
    end: datetime | None = None
    days_before: int = Field(default=0, ge=0, le=3650)
    days_after: int = Field(default=30, ge=0, le=3650)
    timezone: str = "UTC"

    @model_validator(mode="after")
    def validate_range(self) -> DateRange:
        if self.mode == "absolute":
            if self.start is None or self.end is None:
                raise ValueError("Absolute ranges require both start and end")
            if self.end <= self.start:
                raise ValueError("End must be after start")
        elif self.days_before == 0 and self.days_after == 0:
            raise ValueError("A relative range cannot be empty")
        return self


class FilterSpec(BaseModel):
    calendar_ids: list[str] = Field(min_length=1)
    date_range: DateRange = Field(default_factory=DateRange)
    title: TextCriterion | None = None
    description: TextCriterion | None = None
    location: TextCriterion | None = None
    organizer: TextCriterion | None = None
    attendee: TextCriterion | None = None
    timing: Literal["any", "all_day", "timed"] = "any"
    recurrence: Literal["any", "recurring", "single"] = "any"
    visibility: list[str] = Field(default_factory=list)
    event_types: list[str] = Field(default_factory=list)


class Reminder(BaseModel):
    method: Literal["popup", "email"]
    minutes: int = Field(ge=0, le=40320)


class EditSpec(BaseModel):
    title_set: str | None = None
    title_find: str | None = None
    title_replace: str = ""
    title_case_sensitive: bool = False
    description_mode: Literal["keep", "replace", "append"] = "keep"
    description_value: str = ""
    location_set: str | None = None
    shift_minutes: int | None = Field(default=None, ge=-5256000, le=5256000)
    duration_minutes: int | None = Field(default=None, gt=0, le=5256000)
    duration_delta_minutes: int | None = Field(default=None, ge=-5256000, le=5256000)
    visibility: Literal["default", "public", "private", "confidential"] | None = None
    replace_reminders: bool = False
    reminders: list[Reminder] = Field(default_factory=list, max_length=5)
    destination_calendar_id: str | None = None
    delete: bool = False

    @model_validator(mode="after")
    def validate_actions(self) -> EditSpec:
        if self.title_set is not None and self.title_find is not None:
            raise ValueError("Choose either set title or find/replace title")
        if self.duration_minutes is not None and self.duration_delta_minutes is not None:
            raise ValueError("Choose either set duration or adjust duration")
        if self.description_mode != "keep" and not self.description_value:
            raise ValueError("Description text is required for replace or append")
        actions = [
            self.title_set is not None,
            self.title_find is not None,
            self.description_mode != "keep",
            self.location_set is not None,
            self.shift_minutes is not None,
            self.duration_minutes is not None,
            self.duration_delta_minutes is not None,
            self.visibility is not None,
            self.replace_reminders,
            self.destination_calendar_id is not None,
        ]
        if self.delete and any(actions):
            raise ValueError("Deletion cannot be combined with other edits")
        if not self.delete and not any(actions):
            raise ValueError("Choose at least one edit")
        return self


class PreviewRequest(BaseModel):
    filters: FilterSpec
    recurrence_mode: RecurrenceMode = RecurrenceMode.OCCURRENCES


class PreviewItem(BaseModel):
    key: str
    calendar_id: str
    event_id: str
    etag: str
    title: str
    start: str
    end: str
    all_day: bool
    recurring: bool
    event_type: str
    visibility: str
    location: str
    move_eligible: bool
    match_count: int = 1


class PreviewResponse(BaseModel):
    token: str
    expires_at: datetime
    items: list[PreviewItem]
    warnings: list[str] = Field(default_factory=list)


class ApplyRequest(BaseModel):
    preview_token: str
    selected_keys: list[str] = Field(min_length=1)
    edit: EditSpec
    notifications: NotificationMode = NotificationMode.NONE
    delete_confirmation: str | None = None


class OperationResult(BaseModel):
    key: str
    title: str
    status: Literal["success", "skipped", "conflict", "failed"]
    message: str


class OperationResponse(BaseModel):
    results: list[OperationResult]
    undo_available: bool


class Preset(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=80)
    filters: FilterSpec
    edit: EditSpec
    recurrence_mode: RecurrenceMode = RecurrenceMode.OCCURRENCES
    notifications: NotificationMode = NotificationMode.NONE
    created_at: datetime | None = None
    updated_at: datetime | None = None
