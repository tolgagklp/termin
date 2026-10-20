# ABOUTME: Tests appointment parsing, preference ranking, local scheduling, and slot history.
# ABOUTME: Exercises duplicate protection with local state and lock files.
"""Pure tests for appointment parsing, selection, scheduling, and observation."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from src.driver_license_monitor import (
    Settings,
    _write_state,
    acquire_instance_lock,
    append_metrics,
    booking_is_pending,
    choose_slot,
    monitor_status,
    next_check_delay,
    parse_schedule,
    parse_slots,
    parse_windows,
    record_slot_events,
)


def test_parse_slots_groups_times_under_visible_date_headings():
    text = """
    Verfügbare Termine
    Dienstag, 03.11.2026
    Nachmittag
    14:20 Uhr, Führerscheinstelle
    16:00 Uhr, Führerscheinstelle
    Mittwoch, 04.11.2026
    Vormittag
    08:00 Uhr, Führerscheinstelle
    """

    assert parse_slots(text) == [
        (date(2026, 11, 3), time(14, 20)),
        (date(2026, 11, 3), time(16, 0)),
        (date(2026, 11, 4), time(8, 0)),
    ]


def test_parse_slots_reads_plain_time_button_labels_from_appointment_widget():
    text = """
    Dienstag, 03.11.2026
    Nachmittag
    14:40
    15:00
    16:20
    """

    assert parse_slots(text) == [
        (date(2026, 11, 3), time(14, 40)),
        (date(2026, 11, 3), time(15, 0)),
        (date(2026, 11, 3), time(16, 20)),
    ]


def test_choose_slot_respects_preference_order_before_chronology():
    windows = parse_windows(
        "2026-11-02..2026-11-20@16:00-23:59;2026-11-02..2026-11-20@07:00-10:00"
    )
    slots = [
        (date(2026, 11, 3), time(8, 0)),
        (date(2026, 11, 10), time(16, 20)),
        (date(2026, 11, 3), time(17, 0)),
    ]

    selected = choose_slot(slots, windows)

    assert selected is not None
    assert selected.appointment_date == date(2026, 11, 3)
    assert selected.appointment_time == time(17, 0)


def test_choose_slot_returns_none_when_no_slot_matches():
    windows = parse_windows("2026-11-02..2026-11-20@07:00-10:00")

    assert choose_slot([(date(2026, 11, 3), time(14, 20))], windows) is None


def test_parse_windows_rejects_reversed_ranges():
    with pytest.raises(ValueError, match="reversed range"):
        parse_windows("2026-11-20..2026-11-02@07:00-10:00")


def test_choose_slot_uses_earliest_morning_and_latest_evening_and_excludes_past():
    windows = parse_windows(
        "2026-10-20..2026-10-30@00:00-23:59#earliest;"
        "2026-11-02..2026-11-20@07:00-08:40#earliest;"
        "2026-11-02..2026-11-20@16:00-23:59#latest"
    )
    today = date(2026, 11, 3)
    slots = [
        (date(2026, 10, 25), time(9)),
        (today, time(16, 20)),
        (today, time(16, 40)),
        (date(2026, 11, 4), time(7, 40)),
        (date(2026, 11, 4), time(8, 20)),
    ]
    selected = choose_slot(slots, windows, today=today)
    assert selected is not None
    assert selected.appointment_date == date(2026, 11, 4)
    assert selected.appointment_time == time(7, 40)
    assert selected.preference_rank == 1

    selected = choose_slot(slots[:3], windows, today=today)
    assert selected is not None
    assert selected.appointment_time == time(16, 40)
    selected = choose_slot(
        slots[:3] + [(date(2026, 11, 4), time(18, 0))], windows, today=today
    )
    assert selected is not None
    assert selected.appointment_date == today
    assert selected.appointment_time == time(16, 40)


def test_schedule_respects_weekday_boundaries_and_dst_transition():
    schedule = parse_schedule(
        "weekday@06:55-08:45=120;weekday@08:45-23:00=240;"
        "weekday@23:00-06:55=900;weekend@00:00-24:00=600"
    )
    berlin = ZoneInfo("Europe/Berlin")
    monday = datetime(2026, 10, 26, 6, 53, tzinfo=berlin)
    delay, interval = next_check_delay(monday, schedule)
    assert interval == 900
    assert delay == 120
    assert next_check_delay(datetime(2026, 10, 26, 7, tzinfo=berlin), schedule) == (
        120,
        120,
    )

    before_fallback = datetime(2026, 10, 25, 0, 55, tzinfo=UTC)
    after_fallback = datetime(2026, 10, 25, 1, 5, tzinfo=UTC)
    assert before_fallback.astimezone(berlin).hour == 2
    assert after_fallback.astimezone(berlin).hour == 2
    assert next_check_delay(before_fallback.astimezone(berlin), schedule) == (600, 600)
    assert next_check_delay(after_fallback.astimezone(berlin), schedule) == (600, 600)


def test_slot_events_keep_first_seen_and_track_visibility(tmp_path):
    path = tmp_path / "slots.json"
    windows = parse_windows("2026-11-02..2026-11-20@16:00-23:59#latest")
    a = (date(2026, 11, 3), time(16, 20))
    b = (date(2026, 11, 3), time(14, 40))
    first = datetime(2026, 10, 20, 14, tzinfo=ZoneInfo("Europe/Berlin"))
    later = datetime(2026, 10, 20, 14, 2, tzinfo=ZoneInfo("Europe/Berlin"))
    changes = record_slot_events(path, [a, b], windows, first)
    assert changes.first_seen == (b, a)
    assert changes.reappeared == ()
    changes = record_slot_events(path, [a], windows, later)
    assert changes.first_seen == ()
    assert changes.reappeared == ()
    import json

    events = json.loads(path.read_text(encoding="utf-8"))
    assert events["2026-11-03 16:20"]["first_seen"] == first.isoformat()
    assert events["2026-11-03 16:20"]["last_seen"] == later.isoformat()
    assert events["2026-11-03 16:20"]["matches_preferences"] is True
    assert events["2026-11-03 14:40"]["visible_now"] is False
    changes = record_slot_events(path, [a, b], windows, later)
    assert changes.first_seen == ()
    assert changes.reappeared == (b,)
    events = json.loads(path.read_text(encoding="utf-8"))
    assert events["2026-11-03 14:40"]["first_seen"] == first.isoformat()
    assert events["2026-11-03 14:40"]["appearance_count"] == 2


def test_booking_guard_and_instance_lock_prevent_duplicate_attempts(tmp_path):
    state = tmp_path / "booking.state.json"
    assert booking_is_pending(state) is False
    _write_state(state, {"booking_pending": True})
    assert booking_is_pending(state) is True
    _write_state(state, {"booking_pending": False, "booking_submitted": True})
    assert booking_is_pending(state) is True
    state.write_text("broken JSON", encoding="utf-8")
    assert booking_is_pending(state) is True

    lock = acquire_instance_lock(state)
    try:
        with pytest.raises(RuntimeError, match="already be running"):
            acquire_instance_lock(state)
    finally:
        lock.unlink()


def test_local_status_reports_booking_and_last_scan_without_contact_data(tmp_path):
    settings = Settings(
        windows=parse_windows("2026-11-02..2026-11-20@16:00-23:59#latest"),
        schedule=parse_schedule("weekday@00:00-24:00=120;weekend@00:00-24:00=600"),
        auto_book=True,
        first_name="Private",
        last_name="Person",
        email="private@example.com",
        date_of_birth="01.01.1990",
        telegram_token="secret-token",
        telegram_chat_id="123",
        state_file=tmp_path / "booking.state.json",
        events_file=tmp_path / "slots.json",
        metrics_file=tmp_path / "metrics.jsonl",
        log_file=tmp_path / "monitor.log",
    )
    _write_state(
        settings.state_file,
        {
            "booking_submitted": True,
            "slot": "03.11.2026 16:40",
            "submitted_at": "2026-10-20T16:00:00+02:00",
            "activation_deadline_at": "2026-10-20T17:00:00+02:00",
        },
    )
    append_metrics(
        settings.metrics_file,
        {
            "started_at": "2026-10-20T15:59:00+02:00",
            "visible_slots": 2,
            "outcome": "booking_attempted",
        },
    )
    status = monitor_status(settings)
    assert "03.11.2026 16:40" in status
    assert "Last scan: 2026-10-20T15:59:00+02:00; 2 visible" in status
    assert "email activation" in status
    assert "private@example.com" not in status
    assert "secret-token" not in status
