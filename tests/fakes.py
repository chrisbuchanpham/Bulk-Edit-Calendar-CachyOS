from __future__ import annotations

import copy


class Request:
    def __init__(self, callback):
        self.callback = callback
        self.headers = {}

    def execute(self):
        return self.callback()


class FakeEvents:
    def __init__(self, service):
        self.service = service

    def list(self, calendarId, **_kwargs):
        return Request(
            lambda: {
                "items": [copy.deepcopy(v) for (calendar, _), v in self.service.data.items() if calendar == calendarId]
            }
        )

    def get(self, calendarId, eventId):
        return Request(lambda: copy.deepcopy(self.service.data[(calendarId, eventId)]))

    def update(self, calendarId, eventId, body, sendUpdates):
        def callback():
            updated = copy.deepcopy(body) | {"id": eventId, "etag": f'"v{self.service.version}"'}
            self.service.version += 1
            self.service.data[(calendarId, eventId)] = updated
            self.service.calls.append(("update", calendarId, eventId, sendUpdates, copy.deepcopy(body)))
            return copy.deepcopy(updated)

        return Request(callback)

    def move(self, calendarId, eventId, destination, sendUpdates):
        def callback():
            moved = self.service.data.pop((calendarId, eventId))
            moved["etag"] = f'"v{self.service.version}"'
            self.service.version += 1
            self.service.data[(destination, eventId)] = moved
            self.service.calls.append(("move", calendarId, destination, eventId, sendUpdates))
            return copy.deepcopy(moved)

        return Request(callback)

    def delete(self, calendarId, eventId, sendUpdates):
        def callback():
            self.service.data.pop((calendarId, eventId))
            self.service.calls.append(("delete", calendarId, eventId, sendUpdates))
            return None

        return Request(callback)


class FakeCalendarList:
    def list(self, **_kwargs):
        return Request(
            lambda: {
                "items": [
                    {
                        "id": "primary",
                        "summary": "Personal",
                        "timeZone": "America/Toronto",
                        "accessRole": "owner",
                        "primary": True,
                    },
                    {"id": "work", "summary": "Work", "timeZone": "America/Toronto", "accessRole": "writer"},
                ]
            }
        )


class FakeService:
    def __init__(self, events):
        self.data = {(calendar, event["id"]): copy.deepcopy(event) for calendar, event in events}
        self.calls = []
        self.version = 10
        self._events = FakeEvents(self)
        self._calendars = FakeCalendarList()

    def events(self):
        return self._events

    def calendarList(self):
        return self._calendars


def sample_event(event_id="e1", **updates):
    event = {
        "id": event_id,
        "etag": '"v1"',
        "summary": "Planning",
        "description": "Roadmap",
        "location": "Toronto",
        "start": {"dateTime": "2026-09-10T09:00:00-04:00"},
        "end": {"dateTime": "2026-09-10T10:00:00-04:00"},
        "eventType": "default",
        "visibility": "default",
        "organizer": {"email": "me@example.com"},
    }
    event.update(updates)
    return event
