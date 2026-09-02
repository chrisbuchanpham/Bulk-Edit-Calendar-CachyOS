from bulk_edit_calendar.models import DateRange, EditSpec, FilterSpec, Preset
from bulk_edit_calendar.presets import PresetStore


def test_preset_round_trip_and_delete(tmp_path):
    store = PresetStore(tmp_path / "presets.db")
    saved = store.save(
        Preset(
            name="Next month",
            filters=FilterSpec(calendar_ids=["primary"], date_range=DateRange(days_after=30)),
            edit=EditSpec(title_set="Focus"),
        )
    )
    assert saved.id is not None
    assert store.get(saved.id).edit.title_set == "Focus"
    assert store.database.stat().st_mode & 0o777 == 0o600
    assert store.delete(saved.id)
    assert store.list() == []
