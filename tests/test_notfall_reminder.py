"""Checks the separate Notfall reminder schedule and persistent delivery history."""

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.notfall_reminder import (
    BOOKING_URL,
    SERVICE_URL,
    Settings,
    parse_schedule,
    read_sent,
    reminder_message,
    reminders_from,
    write_sent,
)


def settings(tmp_path: Path, *, until: date | None = None) -> Settings:
    return Settings(
        token="unused",
        chat_id="unused",
        schedule=parse_schedule("mon@06:30;tue@07:30;wed@06:30;thu@07:30;fri@06:30"),
        lead_minutes=10,
        until=until,
        state_file=tmp_path / "notfall.state.json",
        log_file=tmp_path / "notfall.log",
    )


def test_official_student_release_times_and_weekend_gap(tmp_path):
    events = reminders_from(date(2026, 10, 23), settings(tmp_path), days=5)
    assert [(item.at.weekday(), item.at.strftime("%H:%M"), item.kind) for item in events] == [
        (4, "06:20", "before"),
        (4, "06:30", "release"),
        (0, "06:20", "before"),
        (0, "06:30", "release"),
        (1, "07:20", "before"),
        (1, "07:30", "release"),
    ]
    assert all(item.at.tzinfo == ZoneInfo("Europe/Berlin") for item in events)


def test_cutoff_excludes_later_dates(tmp_path):
    events = reminders_from(
        date(2026, 10, 20), settings(tmp_path, until=date(2026, 10, 20))
    )
    assert len(events) == 2
    assert all(item.release_at.date() == date(2026, 10, 20) for item in events)


def test_reminder_messages_include_booking_and_info_links(tmp_path):
    before, opening = reminders_from(date(2026, 10, 20), settings(tmp_path), days=1)
    assert BOOKING_URL in reminder_message(before, 10)
    assert SERVICE_URL in reminder_message(opening, 10)
    assert "boş randevu bulunduğu anlamına gelmez" in reminder_message(opening, 10)


def test_sent_history_survives_restart(tmp_path):
    path = tmp_path / "notfall" / "reminders.state.json"
    assert read_sent(path) == {}
    sent = {"2026-10-20:before": "2026-10-20T07:20:00+02:00"}
    write_sent(path, sent)
    assert read_sent(path) == sent


def test_rejects_duplicate_weekday():
    with pytest.raises(ValueError, match="Duplicate"):
        parse_schedule("mon@06:30;mon@07:30")
