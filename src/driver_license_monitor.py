# ABOUTME: Monitors Munich driving-licence exchange appointments through the official browser UI.
# ABOUTME: Records slot observations and timing while allowing one configured reservation request.
"""Monitor the official Munich appointment UI for foreign driving licence exchange."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import time as clock
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from itertools import pairwise
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
BERLIN = ZoneInfo("Europe/Berlin")

BOOKING_URL = "https://stadt.muenchen.de/buergerservice/terminvereinbarung.html"
SERVICE_NAME = "Umschreibung eines ausländischen Führerscheins"
OFFICE_NAME = "Führerscheinstelle"
DEFAULT_WINDOWS = (
    "2026-10-20..2026-10-30@00:00-23:59;"
    "2026-11-02..2026-11-20@07:00-08:40#earliest;"
    "2026-11-02..2026-11-20@16:00-23:59#latest;"
    "2026-11-21..2026-11-24@00:00-23:59"
)
DEFAULT_SCHEDULE = (
    "weekday@06:55-08:45=120;weekday@08:45-13:40=240;"
    "weekday@13:40-14:45=120;weekday@14:45-18:00=240;"
    "weekday@18:00-23:00=600;weekday@23:00-06:55=900;"
    "weekend@00:00-24:00=750"
)
DATE_HEADING = re.compile(
    r"(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),?\s+"
    r"(\d{2}\.\d{2}\.\d{4})",
    re.IGNORECASE,
)
CALENDAR_MONTH_HEADING = re.compile(
    r"^(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|November|Dezember)\s+(\d{4})$"
)
CALENDAR_DAY_BUTTON = re.compile(r"^\d{1,2}\s+auswählen$", re.IGNORECASE)
GERMAN_WEEKDAYS = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)
GERMAN_MONTHS = {
    "Januar": 1,
    "Februar": 2,
    "März": 3,
    "April": 4,
    "Mai": 5,
    "Juni": 6,
    "Juli": 7,
    "August": 8,
    "September": 9,
    "Oktober": 10,
    "November": 11,
    "Dezember": 12,
}
TIME_SLOT = re.compile(r"^\s*(\d{2}:\d{2})(?:\s+Uhr,\s+Führerscheinstelle)?\s*$")
BLOCKING_TEXT = (
    "captcha",
    "verify you are human",
    "zugriff verweigert",
    "access denied",
    "sicherheitsprüfung",
)


@dataclass(frozen=True, order=True)
class AppointmentSlot:
    preference_rank: int
    appointment_date: date
    appointment_time: time

    @property
    def label(self) -> str:
        return f"{self.appointment_date:%d.%m.%Y} {self.appointment_time:%H:%M}"


@dataclass(frozen=True)
class PreferenceWindow:
    start_date: date
    end_date: date
    start_time: time
    end_time: time
    order: str = "earliest"

    def contains(self, slot_date: date, slot_time: time) -> bool:
        return (
            self.start_date <= slot_date <= self.end_date
            and self.start_time <= slot_time <= self.end_time
        )


@dataclass(frozen=True)
class Settings:
    windows: tuple[PreferenceWindow, ...]
    schedule: tuple[ScheduleWindow, ...]
    auto_book: bool
    first_name: str
    last_name: str
    email: str
    date_of_birth: str
    telegram_token: str
    telegram_chat_id: str
    state_file: Path
    events_file: Path
    metrics_file: Path
    log_file: Path


@dataclass(frozen=True)
class ScheduleWindow:
    day_type: str
    start_minute: int
    end_minute: int
    interval: int


@dataclass(frozen=True)
class ScanResult:
    selected: AppointmentSlot | None
    arrivals: tuple[tuple[date, time], ...]
    reappeared: tuple[tuple[date, time], ...]
    visible_count: int


@dataclass(frozen=True)
class SlotChanges:
    first_seen: tuple[tuple[date, time], ...]
    reappeared: tuple[tuple[date, time], ...]


def parse_windows(value: str) -> tuple[PreferenceWindow, ...]:
    """Parse ordered `date..date@time-time` preferences from the environment."""
    windows: list[PreferenceWindow] = []
    for item in value.split(";"):
        item = item.strip()
        if not item:
            continue
        try:
            dates, times = item.split("@", 1)
            start_date, end_date = dates.split("..", 1)
            times, _, order = times.partition("#")
            order = order or "earliest"
            start_time, end_time = times.split("-", 1)
            window = PreferenceWindow(
                date.fromisoformat(start_date),
                date.fromisoformat(end_date),
                time.fromisoformat(start_time),
                time.fromisoformat(end_time),
                order,
            )
        except ValueError as exc:
            raise ValueError(
                "APPOINTMENT_WINDOWS must use date..date@HH:MM-HH:MM entries "
                "separated by semicolons"
            ) from exc
        if window.start_date > window.end_date or window.start_time > window.end_time:
            raise ValueError("Appointment preference window has a reversed range")
        if window.order not in {"earliest", "latest"}:
            raise ValueError("Appointment preference order must be earliest or latest")
        windows.append(window)
    if not windows:
        raise ValueError("At least one appointment preference window is required")
    return tuple(windows)


def parse_schedule(value: str) -> tuple[ScheduleWindow, ...]:
    """Parse local weekday/weekend clock ranges with second intervals."""
    windows = []
    for entry in value.split(";"):
        try:
            day_type, rest = entry.strip().split("@", 1)
            times, seconds = rest.split("=", 1)
            start_text, end_text = times.split("-", 1)

            def minutes(text: str) -> int:
                if text == "24:00":
                    return 1440
                value = time.fromisoformat(text)
                return value.hour * 60 + value.minute

            start, end, interval = minutes(start_text), minutes(end_text), int(seconds)
        except (ValueError, AttributeError) as exc:
            raise ValueError(
                "MONITOR_SCHEDULE entry must use weekday@HH:MM-HH:MM=seconds"
            ) from exc
        if day_type not in {"weekday", "weekend"} or start == end or interval < 120:
            raise ValueError(
                "Schedule requires weekday/weekend, a clock range, and at least 120 seconds"
            )
        windows.append(ScheduleWindow(day_type, start, end, interval))
    if not windows:
        raise ValueError("MONITOR_SCHEDULE needs at least one range")
    for day_type in ("weekday", "weekend"):
        for minute in range(1440):
            if sum(_schedule_contains(item, day_type, minute) for item in windows) != 1:
                raise ValueError(
                    f"MONITOR_SCHEDULE must cover every {day_type} minute exactly once"
                )
    return tuple(windows)


def _schedule_contains(item: ScheduleWindow, day_type: str, minute: int) -> bool:
    if item.day_type != day_type:
        return False
    if item.start_minute < item.end_minute:
        return item.start_minute <= minute < item.end_minute
    return minute >= item.start_minute or minute < item.end_minute


def schedule_interval(at: datetime, schedule: tuple[ScheduleWindow, ...]) -> int:
    local = at.astimezone(BERLIN)
    day_type = "weekend" if local.weekday() >= 5 else "weekday"
    minute = local.hour * 60 + local.minute
    return next(
        item.interval for item in schedule if _schedule_contains(item, day_type, minute)
    )


def next_check_delay(
    at: datetime, schedule: tuple[ScheduleWindow, ...]
) -> tuple[int, int]:
    """Return seconds until the next start, clipped at the next local schedule change."""
    interval = schedule_interval(at, schedule)
    start_utc = at.astimezone(UTC)
    for offset in range(1, interval + 1):
        if (
            schedule_interval(start_utc + timedelta(seconds=offset), schedule)
            != interval
        ):
            return max(120, offset), interval
    return interval, interval


def parse_slots(page_text: str) -> list[tuple[date, time]]:
    """Read date/time pairs from the visible appointment list text."""
    current_date: date | None = None
    slots: list[tuple[date, time]] = []
    for line in page_text.splitlines():
        date_match = DATE_HEADING.search(line.strip())
        if date_match:
            current_date = datetime.strptime(date_match.group(1), "%d.%m.%Y").date()
            continue
        time_match = TIME_SLOT.search(line.strip())
        if current_date and time_match:
            slots.append((current_date, time.fromisoformat(time_match.group(1))))
    return slots


def choose_slot(
    slots: Iterable[tuple[date, time]],
    windows: tuple[PreferenceWindow, ...],
    *,
    today: date | None = None,
) -> AppointmentSlot | None:
    """Choose by preference rank, earliest day, and each window's time order."""
    today = today or datetime.now(BERLIN).date()
    candidates: list[AppointmentSlot] = []
    for slot_date, slot_time in slots:
        if slot_date < today:
            continue
        for rank, window in enumerate(windows):
            if window.contains(slot_date, slot_time):
                candidates.append(AppointmentSlot(rank, slot_date, slot_time))
                break
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda slot: (
            slot.preference_rank,
            slot.appointment_date,
            -slot.appointment_time.hour * 60 - slot.appointment_time.minute
            if windows[slot.preference_rank].order == "latest"
            else slot.appointment_time.hour * 60 + slot.appointment_time.minute,
        ),
    )


def load_settings(*, validate_booking: bool = True) -> Settings:
    from dotenv import load_dotenv

    load_dotenv()
    windows = parse_windows(os.getenv("APPOINTMENT_WINDOWS", DEFAULT_WINDOWS))
    schedule = parse_schedule(os.getenv("MONITOR_SCHEDULE", DEFAULT_SCHEDULE))

    auto_book = os.getenv("AUTO_BOOK_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    fields = {
        "FIRST_NAME": os.getenv("BOOKING_FIRST_NAME", "").strip(),
        "LAST_NAME": os.getenv("BOOKING_LAST_NAME", "").strip(),
        "EMAIL": os.getenv("BOOKING_EMAIL", "").strip(),
        "DATE_OF_BIRTH": os.getenv("BOOKING_DATE_OF_BIRTH", "").strip(),
    }
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if token == "your_bot_token_here":
        token = ""
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if (
        validate_booking
        and auto_book
        and (not all(fields.values()) or not token or not chat_id)
    ):
        raise ValueError(
            "Auto booking requires all BOOKING_* fields and Telegram token/chat ID"
        )
    if (
        validate_booking
        and auto_book
        and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", fields["EMAIL"])
    ):
        raise ValueError("BOOKING_EMAIL must be a valid email address")
    return Settings(
        windows=windows,
        schedule=schedule,
        auto_book=auto_book,
        first_name=fields["FIRST_NAME"],
        last_name=fields["LAST_NAME"],
        email=fields["EMAIL"],
        date_of_birth=fields["DATE_OF_BIRTH"],
        telegram_token=token,
        telegram_chat_id=chat_id,
        state_file=Path(os.getenv("MONITOR_STATE_FILE", "monitor/booking.state.json")),
        events_file=Path(os.getenv("SLOT_EVENTS_FILE", "monitor/slot_events.json")),
        metrics_file=Path(os.getenv("MONITOR_METRICS_FILE", "monitor/metrics.jsonl")),
        log_file=Path(os.getenv("MONITOR_LOG_FILE", "monitor/monitor.log")),
    )


def configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    terminal_handler = logging.StreamHandler()
    for handler in (terminal_handler, file_handler):
        handler.addFilter(lambda record: record.name == logger.name)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[terminal_handler, file_handler],
        force=True,
    )


async def _privacy_choices(page) -> None:
    """Save essential-only cookie preferences when the consent dialog appears."""
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError

    customize = page.get_by_role("button", name="Anpassen", exact=True)
    try:
        # The consent widget is injected after the main page's DOM is ready.
        await customize.wait_for(state="visible", timeout=4_000)
    except PlaywrightTimeoutError:
        logger.debug("Cookie preference dialog was not shown")
    if await customize.count():
        await customize.click()
        switches = page.get_by_role("switch")
        if await switches.count() == 0:
            await switches.first.wait_for(state="visible", timeout=5_000)
        if await switches.count() >= 3:
            # Munich's visible consent panel lists Funktional, Essentiell, Analyse.
            for index in (0, 2):
                toggle = switches.nth(index)
                if await toggle.is_checked():
                    await toggle.click()
        save = page.get_by_role("button", name="Auswahl speichern", exact=True)
        if await save.count() == 0:
            await save.wait_for(state="visible", timeout=5_000)
        if await save.count():
            await save.click()
            return

    # Some consent versions provide a direct reject button; never choose "accept all".
    reject = page.get_by_role(
        "button", name=re.compile("Ablehnen|Nur notwendige", re.IGNORECASE)
    )
    if await reject.count():
        await reject.click()


async def read_available_slots(
    page,
    windows: tuple[PreferenceWindow, ...] | None = None,
    metrics: dict[str, float] | None = None,
) -> list[tuple[date, time]]:
    windows = windows or parse_windows(
        os.getenv("APPOINTMENT_WINDOWS", DEFAULT_WINDOWS)
    )
    metrics = metrics if metrics is not None else {}
    blocked: list[int] = []

    def inspect_response(response) -> None:
        host = urlparse(response.url).hostname or ""
        if response.status in (403, 429) and host.endswith("muenchen.de"):
            blocked.append(response.status)

    def check_access() -> None:
        if blocked:
            raise RuntimeError(
                f"Official appointment service returned HTTP {blocked[0]}; monitoring stopped."
            )

    page.on("response", inspect_response)
    try:
        with timed(metrics, "page_open"):
            response = await page.goto(
                BOOKING_URL, wait_until="domcontentloaded", timeout=20_000
            )
            if response and response.status in (403, 429):
                blocked.append(response.status)
            check_access()
            await _privacy_choices(page)
        with timed(metrics, "service_selection"):
            combo = page.get_by_role("combobox")
            await combo.click()
            await page.get_by_role("option", name=SERVICE_NAME, exact=True).click()
        with timed(metrics, "first_weiter"):
            await page.get_by_role("button", name="Weiter", exact=True).click()
        with timed(metrics, "calendar_load"):
            await page.get_by_role("heading", name="Datum und Uhrzeit").wait_for(
                timeout=30_000
            )
            if (
                await page.get_by_role("heading", name=OFFICE_NAME, exact=True).count()
                != 1
            ):
                raise RuntimeError(
                    "The expected Führerscheinstelle office was not shown; monitoring stopped."
                )
            empty = page.get_by_role(
                "heading",
                name=re.compile("Aktuell ist kein Termin verfügbar", re.IGNORECASE),
            )
            calendar = page.get_by_role("heading", name=CALENDAR_MONTH_HEADING)
            await empty.or_(calendar).first.wait_for(timeout=30_000)
            month = None if await empty.count() else await _calendar_month(page)
        check_access()
        body_text = (await page.locator("body").inner_text()).casefold()
        if any(marker in body_text for marker in BLOCKING_TEXT):
            raise RuntimeError(
                "The official page presented a CAPTCHA or access check; monitoring stopped."
            )
        for marker in BLOCKING_TEXT:
            visible_marker = page.get_by_text(
                re.compile(re.escape(marker), re.IGNORECASE)
            )
            if await visible_marker.count() and await visible_marker.first.is_visible():
                raise RuntimeError(
                    "The official page presented a CAPTCHA or access check; monitoring stopped."
                )
        if month is None:
            logger.info(
                "Official page says no appointments are available; waiting for the next scheduled check."
            )
            metrics["active_days"] = 0.0
            metrics["slot_reading"] = 0.0
            return []
        return await _scan_calendar(page, month, windows, metrics, check_access)
    finally:
        page.remove_listener("response", inspect_response)


async def _scan_calendar(page, month, windows, metrics, check_access):
    # The appointment widget lives in a shadow root, so body.inner_text() omits it.
    # Scan every enabled day in the requested month range, then read that day's slot group.
    first_month = min(w.start_date for w in windows).replace(day=1)
    last_month = max(w.end_date for w in windows).replace(day=1)

    while month > first_month:
        previous = page.get_by_role("button", name="Vorheriger Monat", exact=True)
        if (
            not await previous.count()
            or await previous.get_attribute("aria-disabled") == "true"
        ):
            break
        month = _shift_month(month, -1)
        await previous.click()
        await page.get_by_role(
            "heading", name=f"{_month_name(month.month)} {month.year}", exact=True
        ).wait_for(timeout=10_000)

    while month < first_month:
        if not await _advance_calendar_month(page, month, 1):
            return []
        month = _shift_month(month, 1)

    slots: list[tuple[date, time]] = []
    while month <= last_month:
        with timed(metrics, "active_days"):
            day_buttons = page.get_by_role("button", name=CALENDAR_DAY_BUTTON)
            enabled_days: list[int] = []
            for index in range(await day_buttons.count()):
                button = day_buttons.nth(index)
                if await button.get_attribute("aria-disabled") != "false":
                    continue
                match = re.match(r"\d{1,2}", (await button.inner_text()).strip())
                if match:
                    enabled_days.append(int(match.group()))
        logger.info(
            "Calendar %s active days: %s",
            month.strftime("%Y-%m"),
            enabled_days or "none",
        )

        with timed(metrics, "slot_reading"):
            for day in enabled_days:
                slot_date = date(month.year, month.month, day)
                button = page.get_by_role("button", name=f"{day} auswählen", exact=True)
                if "selected" not in (await button.get_attribute("class") or ""):
                    await button.click()
                    target_heading = (
                        f"{GERMAN_WEEKDAYS[slot_date.weekday()]}, {slot_date:%d.%m.%Y}"
                    )
                    await page.get_by_role(
                        "heading", name=target_heading, exact=True
                    ).wait_for(timeout=10_000)

                heading = page.get_by_role("heading", name=DATE_HEADING)
                if not await heading.count():
                    continue
                slot_group = heading.last.locator("xpath=../following-sibling::*[1]")
                group_text = await slot_group.inner_text()
                day_slots = parse_slots(
                    f"{GERMAN_WEEKDAYS[slot_date.weekday()]}, {slot_date:%d.%m.%Y}\n{group_text}"
                )
                logger.info(
                    "Date %s visible times: %s",
                    slot_date,
                    ", ".join(f"{slot_time:%H:%M}" for _, slot_time in day_slots)
                    or "none",
                )
                slots.extend(day_slots)

        check_access()
        if month == last_month or not await _advance_calendar_month(page, month, 1):
            break
        month = _shift_month(month, 1)

    return sorted(set(slots))


def _month_name(number: int) -> str:
    return next(name for name, value in GERMAN_MONTHS.items() if value == number)


def _shift_month(value: date, offset: int) -> date:
    index = value.year * 12 + value.month - 1 + offset
    return date(index // 12, index % 12 + 1, 1)


async def _calendar_month(page) -> date:
    for heading in await page.get_by_role("heading").all_text_contents():
        match = CALENDAR_MONTH_HEADING.fullmatch(heading.strip())
        if match:
            return date(int(match.group(2)), GERMAN_MONTHS[match.group(1)], 1)
    raise RuntimeError("Could not read the appointment calendar month.")


async def _advance_calendar_month(page, current: date, offset: int) -> bool:
    name = "Nächster Monat" if offset > 0 else "Vorheriger Monat"
    button = page.get_by_role("button", name=name, exact=True)
    if (
        not await button.count()
        or await button.get_attribute("aria-disabled") == "true"
    ):
        return False
    target = _shift_month(current, offset)
    await button.click()
    await page.get_by_role(
        "heading", name=f"{_month_name(target.month)} {target.year}", exact=True
    ).wait_for(timeout=10_000)
    return True


async def _check_electronic_communication_consent(page) -> None:
    """Apply the user's explicit consent before submitting the reservation request."""
    consent = page.locator("#checkbox-electronic-communication")
    if await consent.count() != 1:
        raise RuntimeError(
            "The electronic-communication consent checkbox was not uniquely found; "
            "refusing to submit without the requested consent."
        )
    if not await consent.is_checked():
        await consent.check()
    if not await consent.is_checked():
        raise RuntimeError(
            "Could not select the electronic-communication consent checkbox."
        )


async def _select_calendar_date(page, target: date) -> None:
    month = await _calendar_month(page)
    target_month = target.replace(day=1)
    while month != target_month:
        offset = 1 if month < target_month else -1
        if not await _advance_calendar_month(page, month, offset):
            raise RuntimeError(
                f"Could not return to the selected date {target:%d.%m.%Y}."
            )
        month = _shift_month(month, offset)

    day_button = page.get_by_role("button", name=f"{target.day} auswählen", exact=True)
    if await day_button.get_attribute("aria-disabled") == "true":
        raise RuntimeError(
            f"Appointment date {target:%d.%m.%Y} is no longer available."
        )
    if "selected" not in (await day_button.get_attribute("class") or ""):
        await day_button.click()
        label = f"{GERMAN_WEEKDAYS[target.weekday()]}, {target:%d.%m.%Y}"
        await page.get_by_role("heading", name=label, exact=True).wait_for(
            timeout=10_000
        )


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError):
        logger.error(
            "Could not read monitor state; refusing to risk a duplicate booking"
        )
        return {"booking_pending": True}


def booking_is_pending(path: Path) -> bool:
    state = _read_state(path)
    return bool(state.get("booking_pending") or state.get("booking_submitted"))


def _write_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temporary, path)


@contextmanager
def timed(metrics: dict[str, float], stage: str):
    start = clock.perf_counter()
    try:
        yield
    finally:
        metrics[stage] = round(
            metrics.get(stage, 0.0) + clock.perf_counter() - start, 3
        )


def record_slot_events(
    path: Path,
    slots: Iterable[tuple[date, time]],
    windows: tuple[PreferenceWindow, ...],
    observed_at: datetime,
) -> SlotChanges:
    """Persist first/last sightings and distinguish return from continuous visibility."""
    try:
        events = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(events, dict):
            raise TypeError("Invalid slot event store")
    except FileNotFoundError:
        events = {}
    current = set(slots)
    previously_visible = {
        key: bool(value.get("visible_now")) for key, value in events.items()
    }
    for value in events.values():
        value["visible_now"] = False
    arrivals = []
    reappeared = []
    for slot_date, slot_time in sorted(current):
        key = f"{slot_date:%Y-%m-%d} {slot_time:%H:%M}"
        matching = slot_date >= observed_at.date() and any(
            window.contains(slot_date, slot_time) for window in windows
        )
        if key not in events:
            events[key] = {
                "first_seen": observed_at.isoformat(),
                "appointment_date": slot_date.isoformat(),
                "appointment_time": slot_time.strftime("%H:%M"),
                "appearance_count": 1,
            }
            arrivals.append((slot_date, slot_time))
        elif not previously_visible[key]:
            events[key]["appearance_count"] = (
                int(events[key].get("appearance_count", 1)) + 1
            )
            events[key]["last_reappeared"] = observed_at.isoformat()
            reappeared.append((slot_date, slot_time))
        events[key].update(
            {
                "last_seen": observed_at.isoformat(),
                "matches_preferences": matching,
                "visible_now": True,
            }
        )
    _write_state(path, events)
    return SlotChanges(tuple(arrivals), tuple(reappeared))


def append_metrics(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record, ensure_ascii=False) + "\n")


def observation_report(events_file: Path, metrics_file: Path) -> str:
    try:
        events = json.loads(events_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        events = {}
    try:
        scans = [
            json.loads(line)
            for line in metrics_file.read_text(encoding="utf-8").splitlines()
            if line
        ]
    except FileNotFoundError:
        scans = []
    first_seen = [
        datetime.fromisoformat(value["first_seen"]).astimezone(BERLIN)
        for value in events.values()
    ]
    by_hour = {hour: sum(at.hour == hour for at in first_seen) for hour in range(24)}

    def in_window(at: datetime, start: int, end: int) -> bool:
        minute = at.hour * 60 + at.minute
        return start <= minute < end

    morning = sum(in_window(at, 420, 510) for at in first_seen)
    afternoon = sum(in_window(at, 820, 885) for at in first_seen)
    complete = [
        scan
        for scan in scans
        if scan.get("outcome")
        in {
            "completed",
            "no_match",
            "match_visible",
            "booking_attempted",
        }
        or (
            scan.get("outcome") is None
            and "preference_algorithm" in scan.get("stages", {})
        )
    ]
    durations = [float(scan["total_seconds"]) for scan in complete]
    gaps = [
        float(scan["actual_start_gap_seconds"])
        for scan in complete
        if scan.get("actual_start_gap_seconds") is not None
    ]
    if not gaps:
        dry_starts = [
            datetime.fromisoformat(scan["started_at"])
            for scan in complete
            if scan.get("mode") == "same-browser-dry-run"
        ]
        gaps = [
            (later - earlier).total_seconds() for earlier, later in pairwise(dry_starts)
        ]
    scan_times = [datetime.fromisoformat(scan["started_at"]) for scan in complete]
    span = (
        (max(scan_times) - min(scan_times)).total_seconds() / 3600
        if len(scan_times) > 1
        else 0
    )
    lines = [
        f"Scan attempts/completed: {len(scans)}/{len(complete)}; distinct appointment times first seen: {len(events)}",
        f"Recorded reappearances: {sum(max(0, int(value.get('appearance_count', 1)) - 1) for value in events.values())}",
        f"Observation span: {span:.1f} hours",
        f"First seen 07:00-08:30: {morning}; 13:40-14:45: {afternoon}; other times: {len(first_seen) - morning - afternoon}",
        "First sightings by Berlin hour: "
        + (
            ", ".join(
                f"{hour:02d}:00={count}" for hour, count in by_hour.items() if count
            )
            or "none"
        ),
        f"Scan duration mean/max: {sum(durations) / len(durations):.2f}s / {max(durations):.2f}s"
        if durations
        else "Scan duration: no data",
        f"Actual start gap mean/min: {sum(gaps) / len(gaps):.1f}s / {min(gaps):.1f}s"
        if gaps
        else "Actual start gap: no repeated monitor cycles yet",
        f"Schedule overruns: {sum(float(scan.get('overrun_seconds', 0)) > 0 for scan in scans)}",
    ]
    stage_names = sorted({name for scan in complete for name in scan.get("stages", {})})
    for name in stage_names:
        values = [
            float(scan["stages"][name])
            for scan in complete
            if name in scan.get("stages", {})
        ]
        lines.append(
            f"  {name}: mean {sum(values) / len(values):.3f}s, max {max(values):.3f}s"
        )
    if span < 24:
        lines.append(
            "Fewer than 24 hours of scans; release-time conclusions are premature."
        )
    return "\n".join(lines)


def monitor_status(settings: Settings) -> str:
    state = _read_state(settings.state_file)
    if state.get("booking_submitted"):
        booking = "Reservation request submitted; email activation is checked manually."
    elif state.get("booking_pending"):
        booking = "Reservation outcome pending or unclear; review email/site before restarting auto booking."
    else:
        booking = "No reservation request recorded by this monitor."
    lines = [
        f"Automatic booking: {'enabled' if settings.auto_book else 'disabled'}",
        booking,
    ]
    if state.get("slot"):
        lines.append(f"Recorded appointment: {state['slot']}")
    if state.get("pending_started_at"):
        lines.append(f"Reservation attempt started at: {state['pending_started_at']}")
    if state.get("submitted_at"):
        lines.append(f"Request submitted at: {state['submitted_at']}")
    if state.get("activation_deadline_at"):
        deadline = datetime.fromisoformat(state["activation_deadline_at"])
        seconds_left = (deadline.astimezone(UTC) - datetime.now(UTC)).total_seconds()
        time_left = (
            f"about {int((seconds_left + 59) // 60)} minutes remaining"
            if seconds_left > 0
            else "estimated deadline passed"
        )
        lines.append(
            f"Estimated email activation deadline: {deadline.isoformat()} ({time_left})"
        )
    try:
        last = settings.metrics_file.read_text(encoding="utf-8").splitlines()[-1]
        scan = json.loads(last)
        lines.append(
            f"Last scan: {scan.get('started_at', 'unknown')}; "
            f"{scan.get('visible_slots', '?')} visible; "
            f"outcome {scan.get('outcome', 'unknown')}"
        )
    except (FileNotFoundError, IndexError, json.JSONDecodeError):
        lines.append("Last scan: none recorded")
    return "\n".join(lines)


async def notify(
    settings: Settings, message: str, metrics: dict[str, float] | None = None
) -> None:
    metrics = metrics if metrics is not None else {}
    if not settings.telegram_token or not settings.telegram_chat_id:
        logger.info("Telegram is not configured; notification was not sent")
        return
    from telegram import Bot

    with timed(metrics, "telegram_notification"):
        async with Bot(settings.telegram_token) as bot:
            await bot.send_message(chat_id=settings.telegram_chat_id, text=message)


def acquire_instance_lock(path: Path) -> Path:
    """Prevent multiple monitor processes from racing to submit the same slot."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            f"Another monitor may already be running (lock: {lock_path}). "
            "If it crashed, remove the stale lock after confirming no monitor is active."
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as lock_file:
        lock_file.write(str(os.getpid()))
    return lock_path


async def submit_booking(
    page,
    settings: Settings,
    slot: AppointmentSlot,
    metrics: dict[str, float] | None = None,
) -> str:
    """Select one preferred slot, fill contact data, and request email confirmation."""
    metrics = metrics if metrics is not None else {}
    with timed(metrics, "slot_selection"):
        await _select_calendar_date(page, slot.appointment_date)
        slot_name = f"{slot.appointment_time:%H:%M} Uhr, {OFFICE_NAME}"
        await page.get_by_role("button", name=slot_name, exact=True).click()
    with timed(metrics, "form_filling"):
        await page.get_by_role("textbox", name="Vorname").fill(settings.first_name)
        await page.get_by_role("textbox", name="Nachname").fill(settings.last_name)
        await page.get_by_role("textbox", name="E-Mail-Adresse").fill(settings.email)
        await page.get_by_role("textbox", name="Geburtsdatum").fill(
            settings.date_of_birth
        )
    with timed(metrics, "overview_transition"):
        await page.get_by_role("button", name="Weiter", exact=True).click()
        await page.get_by_role(
            "heading", name=re.compile("Übersicht", re.IGNORECASE)
        ).wait_for(timeout=30_000)

    _write_state(
        settings.state_file,
        {
            "booking_pending": True,
            "slot": slot.label,
            "pending_started_at": datetime.now(BERLIN).isoformat(),
        },
    )
    final_button_names = (
        "Termin reservieren",
        "Termin verbindlich buchen",
        "Verbindlich buchen",
        "Termin buchen",
    )
    matching_buttons = []
    for name in final_button_names:
        button = page.get_by_role("button", name=name, exact=True)
        if await button.count():
            matching_buttons.append(button)
    if len(matching_buttons) != 1:
        return (
            f"Contact details are filled and the appointment is at the overview ({slot.label}), "
            "but the final booking button was ambiguous, so no reservation was submitted. "
            "Review the official site manually before restarting the monitor."
        )

    with timed(metrics, "consent_checkbox"):
        await _check_electronic_communication_consent(page)

    try:
        with timed(metrics, "final_reservation"):
            await matching_buttons[0].click()
            await page.get_by_text(
                re.compile(
                    "Bestätigungsmail|Bestätigungs-E-Mail|E-Mail wurde versendet|"
                    "Sie erhalten eine E-Mail|Termin wurde|Anfrage wurde",
                    re.IGNORECASE,
                )
            ).wait_for(timeout=20_000)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Final booking action was clicked but confirmation was unclear (%s)",
            type(exc).__name__,
        )
        return (
            f"The final booking action was clicked for {slot.label}, but the site did not show "
            f"a clear confirmation. Check {settings.email} and the browser result; the monitor "
            "will not retry automatically."
        )
    submitted_at = datetime.now(BERLIN)
    _write_state(
        settings.state_file,
        {
            "booking_pending": False,
            "booking_submitted": True,
            "slot": slot.label,
            "submitted_at": submitted_at.isoformat(),
            "activation_deadline_at": (
                submitted_at.astimezone(UTC) + timedelta(minutes=60)
            )
            .astimezone(BERLIN)
            .isoformat(),
        },
    )
    return (
        f"Appointment request submitted for {slot.label}. Check {settings.email} and "
        "manually activate the confirmation link within 60 minutes."
    )


async def check_page(
    page,
    settings: Settings,
    *,
    auto_book: bool,
    metrics: dict[str, float] | None = None,
) -> ScanResult:
    """Refresh the same browser tab, inspect slots, and optionally prepare one booking."""
    metrics = metrics if metrics is not None else {}
    slots = await read_available_slots(page, settings.windows, metrics)
    logger.info(
        "Visible appointment slots: %s",
        ", ".join(f"{d:%d.%m.%Y} {t:%H:%M}" for d, t in slots) or "none",
    )
    observed_at = datetime.now(BERLIN)
    changes = record_slot_events(
        settings.events_file, slots, settings.windows, observed_at
    )
    logger.info(
        "First seen slots: %s; reappeared slots: %s",
        ", ".join(f"{d:%d.%m.%Y} {t:%H:%M}" for d, t in changes.first_seen) or "none",
        ", ".join(f"{d:%d.%m.%Y} {t:%H:%M}" for d, t in changes.reappeared) or "none",
    )
    with timed(metrics, "preference_algorithm"):
        selected = choose_slot(slots, settings.windows, today=observed_at.date())
    if selected is None:
        logger.info("No slot matches the configured date and time preferences.")
        return ScanResult(None, changes.first_seen, changes.reappeared, len(slots))

    window = settings.windows[selected.preference_rank]
    logger.info(
        "Selected %s: preference %d (%s..%s, %s-%s, %s time on earliest day)",
        selected.label,
        selected.preference_rank + 1,
        window.start_date,
        window.end_date,
        window.start_time,
        window.end_time,
        window.order,
    )
    if not auto_book:
        return ScanResult(selected, changes.first_seen, changes.reappeared, len(slots))

    if booking_is_pending(settings.state_file):
        raise RuntimeError(
            "A previous booking is already pending; refusing to prepare another one."
        )
    message = await submit_booking(page, settings, selected, metrics)
    await notify(settings, message, metrics)
    return ScanResult(selected, changes.first_seen, changes.reappeared, len(slots))


async def run_once(
    settings: Settings, *, auto_book: bool = False
) -> AppointmentSlot | None:
    """Open one browser for a one-time check (monitor-only by default)."""
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page(locale="de-DE", timezone_id="Europe/Berlin")
            page.set_default_timeout(15_000)
            started_at = datetime.now(BERLIN)
            started = clock.perf_counter()
            metrics: dict[str, float] = {}
            outcome = "error"
            visible_count = 0
            arrival_count = 0
            reappeared_count = 0
            try:
                result = await check_page(
                    page, settings, auto_book=auto_book, metrics=metrics
                )
                visible_count = result.visible_count
                arrival_count = len(result.arrivals)
                reappeared_count = len(result.reappeared)
                outcome = "completed"
                return result.selected
            finally:
                duration = round(clock.perf_counter() - started, 3)
                append_metrics(
                    settings.metrics_file,
                    {
                        "started_at": started_at.isoformat(),
                        "mode": "once",
                        "outcome": outcome,
                        "visible_slots": visible_count,
                        "new_slots": arrival_count,
                        "reappeared_slots": reappeared_count,
                        "total_seconds": duration,
                        "stages": metrics,
                    },
                )
                logger.info("Scan completed in %.3fs; stages=%s", duration, metrics)
        finally:
            await browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--once",
        action="store_true",
        help="Check the official appointment page once without booking or notifying.",
    )
    mode.add_argument(
        "--report",
        action="store_true",
        help="Summarize local slot observations and scan durations.",
    )
    mode.add_argument(
        "--test-telegram",
        action="store_true",
        help="Send a test alert to the configured Telegram chat.",
    )
    mode.add_argument(
        "--status", action="store_true", help="Show local reservation and scan status."
    )
    mode.add_argument(
        "--telegram-chat-id",
        action="store_true",
        help="Read chat IDs from recent messages to the configured bot.",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Monitor continuously with terminal/file alerts only; never submit a reservation.",
    )
    return parser.parse_args()


async def main(args: argparse.Namespace | None = None) -> None:
    args = args or parse_args()
    settings = load_settings(
        validate_booking=not (
            args.once
            or args.report
            or args.test_telegram
            or args.status
            or args.telegram_chat_id
            or args.local_only
        )
    )
    if args.report:
        print(observation_report(settings.events_file, settings.metrics_file))
        return
    if args.status:
        print(monitor_status(settings))
        return
    if args.telegram_chat_id:
        if not settings.telegram_token:
            raise SystemExit("Set TELEGRAM_BOT_TOKEN before reading chat IDs.")
        from telegram import Bot

        try:
            async with Bot(settings.telegram_token) as bot:
                updates = await bot.get_updates(limit=20, timeout=0)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                f"Could not read bot messages ({type(exc).__name__}); check the token and bot setup."
            ) from None
        chat_ids = sorted(
            {
                update.effective_chat.id
                for update in updates
                if update.effective_chat is not None
            }
        )
        print(
            "Chat IDs from recent bot messages: "
            + (", ".join(map(str, chat_ids)) or "none; send /start to your bot first")
        )
        return
    if args.test_telegram:
        if not settings.telegram_token or not settings.telegram_chat_id:
            raise SystemExit(
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before testing Telegram."
            )
        await notify(
            settings, "KVR termin monitor test: Telegram notifications are working."
        )
        print("Telegram test message sent.")
        return
    if args.once:
        await run_once(settings, auto_book=False)
        return

    if args.local_only:
        if settings.auto_book:
            raise SystemExit("Disable AUTO_BOOK_ENABLED before using --local-only.")
        settings = replace(settings, telegram_token="", telegram_chat_id="")
        logger.warning(
            "Local-only monitoring: matching slots appear in terminal and monitor.log; Telegram alerts are disabled."
        )
    elif not settings.telegram_token or not settings.telegram_chat_id:
        raise SystemExit(
            "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before monitoring."
        )
    lock_path = acquire_instance_lock(settings.state_file)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                # Keep one browser alive; each check reloads the official page in this tab.
                page = await browser.new_page(
                    locale="de-DE", timezone_id="Europe/Berlin"
                )
                page.set_default_timeout(15_000)
                first_scan = True
                previous_started_perf: float | None = None
                while True:
                    started_at = datetime.now(BERLIN)
                    started_perf = clock.perf_counter()
                    actual_start_gap = (
                        round(started_perf - previous_started_perf, 3)
                        if previous_started_perf is not None
                        else None
                    )
                    previous_started_perf = started_perf
                    metrics: dict[str, float] = {}
                    outcome = "no_match"
                    visible_count = 0
                    arrival_count = 0
                    reappeared_count = 0
                    try:
                        if settings.auto_book and booking_is_pending(
                            settings.state_file
                        ):
                            await notify(
                                settings,
                                "A booking is already pending. Monitoring has stopped to prevent duplicates.",
                                metrics,
                            )
                            return
                        result = await check_page(
                            page,
                            settings,
                            auto_book=settings.auto_book,
                            metrics=metrics,
                        )
                        visible_count = result.visible_count
                        arrival_count = len(result.arrivals)
                        reappeared_count = len(result.reappeared)
                        if result.selected is not None and settings.auto_book:
                            outcome = "booking_attempted"
                            return
                        if not settings.auto_book:
                            arrivals = [
                                slot
                                for slot in (*result.arrivals, *result.reappeared)
                                if slot[0] >= started_at.date()
                                and any(
                                    window.contains(*slot)
                                    for window in settings.windows
                                )
                            ]
                            if first_scan and result.selected:
                                message = f"Matching appointment found: {result.selected.label}"
                                if args.local_only:
                                    logger.warning("LOCAL ALERT: %s", message)
                                else:
                                    await notify(settings, message, metrics)
                            elif arrivals:
                                labels = ", ".join(
                                    f"{d:%d.%m.%Y} {t:%H:%M}" for d, t in arrivals
                                )
                                message = (
                                    f"Newly visible matching appointments: {labels}"
                                )
                                if args.local_only:
                                    logger.warning("LOCAL ALERT: %s", message)
                                else:
                                    await notify(settings, message, metrics)
                            first_scan = False
                        outcome = "match_visible" if result.selected else "no_match"
                    except Exception as exc:  # noqa: BLE001
                        safe_error = (
                            str(exc)
                            if isinstance(exc, RuntimeError)
                            else type(exc).__name__
                        )
                        logger.error("Appointment check stopped: %s", safe_error)
                        outcome = "stopped_error"
                        await notify(
                            settings,
                            f"Appointment monitor stopped: {safe_error}",
                            metrics,
                        )
                        return
                    finally:
                        elapsed = round(clock.perf_counter() - started_perf, 3)
                        delay, interval = next_check_delay(
                            started_at, settings.schedule
                        )
                        append_metrics(
                            settings.metrics_file,
                            {
                                "started_at": started_at.isoformat(),
                                "mode": "monitor",
                                "outcome": outcome,
                                "total_seconds": elapsed,
                                "visible_slots": visible_count,
                                "new_slots": arrival_count,
                                "reappeared_slots": reappeared_count,
                                "actual_start_gap_seconds": actual_start_gap,
                                "target_interval_seconds": interval,
                                "next_start_after_seconds": delay,
                                "overrun_seconds": round(max(0, elapsed - delay), 3),
                                "stages": metrics,
                            },
                        )
                        logger.info(
                            "Scan %.3fs; prior start gap %s; schedule %ds; next start after %ds; overrun %.3fs; stages=%s",
                            elapsed,
                            actual_start_gap,
                            interval,
                            delay,
                            max(0, elapsed - delay),
                            metrics,
                        )
                    wait = max(0, delay - (clock.perf_counter() - started_perf))
                    if wait:
                        await asyncio.sleep(wait)
            finally:
                try:
                    await browser.close()
                except Exception:
                    task = asyncio.current_task()
                    if task is None or not task.cancelling():
                        raise
    finally:
        lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    options = parse_args()
    if options.report or options.status:
        configuration = load_settings(validate_booking=False)
        if options.report:
            print(
                observation_report(
                    configuration.events_file, configuration.metrics_file
                )
            )
        else:
            print(monitor_status(configuration))
    else:
        configuration = load_settings(validate_booking=False)
        configure_logging(configuration.log_file)
        try:
            asyncio.run(main(options))
        except KeyboardInterrupt:
            print("Monitor stopped by user.")
