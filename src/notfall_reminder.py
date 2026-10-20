"""Local Telegram reminders for the official student emergency appointment release times.

This module does not inspect appointment availability or interact with the
human-verification step on the booking website.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BERLIN = ZoneInfo("Europe/Berlin")
BOOKING_URL = "https://stadt.muenchen.de/buergerservice/terminvereinbarung.html"
SERVICE_URL = (
    "https://stadt.muenchen.de/service/info/"
    "servicestelle-fur-zuwanderung-und-einburgerung/10338844/"
)
SERVICE_NAME = (
    "Notfall-Hilfe Aufenthaltstitel – Studierende, Arbeitsplatzsuche nach Studium "
    "oder erstmalige Beschäftigung nach Studium"
)
DEFAULT_SCHEDULE = "mon@06:30;tue@07:30;wed@06:30;thu@07:30;fri@06:30"
WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4}
RELEASE_DELIVERY_WINDOW = timedelta(minutes=10)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    token: str
    chat_id: str
    schedule: dict[int, time]
    lead_minutes: int
    until: date | None
    state_file: Path
    log_file: Path
    second_lead_minutes: int | None = None


@dataclass(frozen=True)
class Reminder:
    at: datetime
    kind: str
    release_at: datetime
    lead_minutes: int = 0

    @property
    def key(self) -> str:
        if self.kind == "before" and self.lead_minutes != 10:
            return f"{self.release_at.date().isoformat()}:before_{self.lead_minutes}"
        return f"{self.release_at.date().isoformat()}:{self.kind}"


def parse_schedule(value: str) -> dict[int, time]:
    """Read a separate local schedule such as mon@06:30;tue@07:30."""
    schedule: dict[int, time] = {}
    for entry in value.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        try:
            day_text, hour_text = entry.split("@", 1)
            weekday = WEEKDAYS[day_text.lower()]
            hour = time.fromisoformat(hour_text)
        except (KeyError, ValueError) as exc:
            raise ValueError(
                "NOTFALL_REMINDER_SCHEDULE must use mon@HH:MM;tue@HH:MM entries"
            ) from exc
        if weekday in schedule:
            raise ValueError(f"Duplicate Notfall reminder weekday: {day_text}")
        schedule[weekday] = hour
    if not schedule:
        raise ValueError("NOTFALL_REMINDER_SCHEDULE needs at least one weekday")
    return schedule


def load_settings() -> Settings:
    load_dotenv()
    lead = int(os.getenv("NOTFALL_REMINDER_LEAD_MINUTES", "10"))
    if not 1 <= lead <= 60:
        raise ValueError("NOTFALL_REMINDER_LEAD_MINUTES must be between 1 and 60")
    second_lead = int(os.getenv("NOTFALL_REMINDER_SECOND_LEAD_MINUTES", "2"))
    if not 1 <= second_lead < lead:
        raise ValueError(
            "NOTFALL_REMINDER_SECOND_LEAD_MINUTES must be positive and earlier than the first reminder"
        )
    cutoff = os.getenv("NOTFALL_REMINDER_UNTIL", "").strip()
    return Settings(
        token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        schedule=parse_schedule(
            os.getenv("NOTFALL_REMINDER_SCHEDULE", DEFAULT_SCHEDULE)
        ),
        lead_minutes=lead,
        until=date.fromisoformat(cutoff) if cutoff else None,
        state_file=Path(
            os.getenv(
                "NOTFALL_REMINDER_STATE_FILE", "monitor/notfall/reminders.state.json"
            )
        ),
        log_file=Path(
            os.getenv("NOTFALL_REMINDER_LOG_FILE", "monitor/notfall/reminder.log")
        ),
        second_lead_minutes=second_lead,
    )


def reminders_from(start: date, settings: Settings, days: int = 14) -> list[Reminder]:
    reminders: list[Reminder] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        if settings.until is not None and day > settings.until:
            break
        release_time = settings.schedule.get(day.weekday())
        if release_time is None:
            continue
        release_at = datetime.combine(day, release_time, tzinfo=BERLIN)
        leads = [settings.lead_minutes]
        if settings.second_lead_minutes is not None:
            leads.append(settings.second_lead_minutes)
        for lead in leads:
            reminders.append(
                Reminder(
                    release_at - timedelta(minutes=lead),
                    "before",
                    release_at,
                    lead,
                )
            )
        reminders.append(Reminder(release_at, "release", release_at))
    return sorted(reminders, key=lambda item: item.at)


def delivery_deadline(reminder: Reminder) -> datetime:
    if reminder.kind == "before":
        return reminder.release_at
    return reminder.release_at + RELEASE_DELIVERY_WINDOW


def reminder_message(reminder: Reminder, lead_minutes: int) -> str:
    release = reminder.release_at.strftime("%d.%m.%Y %H:%M")
    if reminder.kind == "before":
        opening = (
            "KVR | Notfall randevu hatırlatması\n"
            f"{reminder.lead_minutes or lead_minutes} dakika öncesi uyarısı; "
            f"açılış {release} (Berlin)."
        )
    else:
        opening = f"KVR | Notfall randevu saati\nResmî açılış: {release} (Berlin)."
    return (
        f"{opening}\n"
        f"Hizmet: {SERVICE_NAME}\n"
        "Uygunluk durumunu resmî sayfada kontrol et. "
        "Bu mesaj boş randevu bulunduğu anlamına gelmez.\n"
        f"Randevu sayfası: {BOOKING_URL}\n"
        f"Hizmet bilgisi: {SERVICE_URL}"
    )


def read_sent(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("sent"), dict):
        raise ValueError(f"Invalid Notfall reminder state: {path}")
    return payload["sent"]


def write_sent(path: Path, sent: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps({"sent": sent}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def send_telegram(settings: Settings, message: str) -> None:
    """Send a message with the already configured bot, without logging its token."""
    fields = urlencode({"chat_id": settings.chat_id, "text": message}).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{settings.token}/sendMessage", data=fields
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Telegram gönderimi başarısız ({type(exc).__name__}).") from None
    if not payload.get("ok"):
        raise RuntimeError("Telegram bildirimi reddedildi.")


def configure_logging(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        path, maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), file_handler],
        force=True,
    )


def acquire_lock(state_file: Path) -> Path:
    lock = state_file.with_suffix(state_file.suffix + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            "Notfall hatırlatıcısı zaten çalışıyor olabilir; aynı anda ikinci kez başlatılmadı."
        ) from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return lock


async def run(settings: Settings) -> None:
    if not settings.token or not settings.chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    configure_logging(settings.log_file)
    lock = acquire_lock(settings.state_file)
    try:
        sent = read_sent(settings.state_file)
        logger.info("Notfall hatırlatıcısı başladı; saat dilimi Europe/Berlin.")
        while True:
            now = datetime.now(BERLIN)
            events = reminders_from(now.date(), settings)
            eligible = [
                item
                for item in events
                if item.at <= now < delivery_deadline(item)
                and item.key not in sent
                and not any(
                    later.release_at == item.release_at
                    and later.at > item.at
                    and later.key in sent
                    for later in events
                )
            ]
            if eligible:
                # After an outage, send only the newest still useful reminder.
                item = max(eligible, key=lambda entry: entry.at)
                message = reminder_message(item, settings.lead_minutes)
                try:
                    await asyncio.to_thread(send_telegram, settings, message)
                except RuntimeError as exc:
                    logger.error("%s", exc)
                    await asyncio.sleep(20)
                    continue
                else:
                    sent[item.key] = datetime.now(BERLIN).isoformat()
                    write_sent(settings.state_file, sent)
                    logger.info(
                        "Telegram gönderildi | %s | %s",
                        item.key,
                        item.release_at.strftime("%d.%m.%Y %H:%M"),
                    )
                    continue
            future = next((item for item in events if item.at > now), None)
            if future is None:
                logger.info("Notfall hatırlatma bitiş tarihi geçti; program kapanıyor.")
                return
            delay = min(60.0, max(0.5, (future.at - datetime.now(BERLIN)).total_seconds()))
            await asyncio.sleep(delay)
    finally:
        lock.unlink(missing_ok=True)


def print_status(settings: Settings) -> None:
    now = datetime.now(BERLIN)
    sent = read_sent(settings.state_file)
    events = reminders_from(now.date(), settings)
    upcoming = [item for item in events if item.at >= now][:6]
    print("KVR öğrenci/mezun Notfall hatırlatıcısı | Europe/Berlin")
    print("Durum dosyası:", settings.state_file)
    print("Günlük:", settings.log_file)
    print("Bugün gönderilen:", sum(key.startswith(now.date().isoformat()) for key in sent))
    for item in upcoming:
        label = (
            f"{item.lead_minutes} dk önce"
            if item.kind == "before"
            else "Açılış hatırlatması"
        )
        print(f"{label}: {item.at:%d.%m.%Y %H:%M}")
    if not upcoming:
        print("Planlı yeni hatırlatma yok.")


def main() -> None:
    # Windows terminals can otherwise use cp1252 and reject Turkish log text.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Show upcoming reminders without sending")
    args = parser.parse_args()
    settings = load_settings()
    if args.status:
        print_status(settings)
        return
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        logger.info("Notfall hatırlatıcısı durduruldu.")


if __name__ == "__main__":
    main()
