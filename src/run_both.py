"""Run the independent driving-licence monitor and Notfall reminder in one terminal."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
BERLIN = ZoneInfo("Europe/Berlin")
logger = logging.getLogger("kvr_runner")


@dataclass
class Worker:
    label: str
    module: str
    state_file: Path
    process: subprocess.Popen[str] | None = None
    reader: threading.Thread | None = None
    retry_at: float | None = None
    started_at: float | None = None
    failures: int = 0
    finished: bool = False


def parse_start_at(value: str | None, now: datetime | None = None) -> datetime:
    now = now or datetime.now(BERLIN)
    if value is None:
        return now
    if re.fullmatch(r"\d{2}:\d{2}", value):
        try:
            hour, minute = map(int, value.split(":"))
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError as exc:
            raise ValueError("Saat HH:MM biçiminde olmalı (Münih saati).") from exc
        return target if target > now else target + timedelta(days=1)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", value):
        raise ValueError("Başlangıç YYYY-MM-DD HH:MM veya HH:MM biçiminde olmalı.")
    try:
        target = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Başlangıç YYYY-MM-DD HH:MM veya HH:MM biçiminde olmalı.") from exc
    if target.tzinfo is not None:
        raise ValueError("Başlangıcı saat dilimi eki olmadan Münih saatiyle gir.")
    target = target.replace(tzinfo=BERLIN)
    if target <= now:
        raise ValueError("Tarih ve saat geçmişte; yeni bir başlangıç gir.")
    return target


def configure_logging() -> None:
    path = ROOT / "monitor" / "runner.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(path, maxBytes=2_000_000, backupCount=2, encoding="utf-8"),
        ],
        force=True,
    )


def keep_windows_awake(enable: bool) -> None:
    if os.name != "nt":
        return
    state = 0x80000001 if enable else 0x80000000  # continuous + system required
    result = ctypes.windll.kernel32.SetThreadExecutionState(state)
    if not result and enable:
        logger.warning("Windows uyku engeli açılamadı; güç ayarlarını kontrol et.")


def remove_owned_lock(worker: Worker, pid: int) -> None:
    lock = worker.state_file.with_suffix(worker.state_file.suffix + ".lock")
    try:
        if lock.read_text(encoding="utf-8").strip() == str(pid):
            lock.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("[%s] Kilit temizlenemedi (%s).", worker.label, type(exc).__name__)


def relay_output(worker: Worker, process: subprocess.Popen[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[{worker.label}] {line.rstrip()}", flush=True)


def start_worker(worker: Worker) -> None:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", worker.module],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )
    worker.process = process
    worker.retry_at = None
    worker.started_at = time.monotonic()
    worker.reader = threading.Thread(target=relay_output, args=(worker, process), daemon=True)
    worker.reader.start()
    logger.info("[%s] Başladı (PID %s).", worker.label, process.pid)


def stop_workers(workers: list[Worker]) -> None:
    for worker in workers:
        process = worker.process
        if process is not None and process.poll() is None:
            process.terminate()
    for worker in workers:
        process = worker.process
        if process is None:
            continue
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        remove_owned_lock(worker, process.pid)
        if worker.reader is not None:
            worker.reader.join(timeout=1)


def run(start_at: datetime) -> None:
    configure_logging()
    load_dotenv(ROOT / ".env")
    workers = [
        Worker(
            "Ehliyet",
            "src.driver_license_monitor",
            ROOT / os.getenv("MONITOR_STATE_FILE", "monitor/booking.state.json"),
        ),
        Worker(
            "Notfall",
            "src.notfall_reminder",
            ROOT / os.getenv("NOTFALL_REMINDER_STATE_FILE", "monitor/notfall/reminders.state.json"),
        ),
    ]
    keep_windows_awake(True)
    try:
        remaining = (start_at - datetime.now(BERLIN)).total_seconds()
        if remaining > 0:
            logger.info("İki görev %s (Münih saati) başlayacak; bekleniyor.", start_at.strftime("%d.%m.%Y %H:%M"))
        while remaining > 0:
            time.sleep(min(30, remaining))
            remaining = (start_at - datetime.now(BERLIN)).total_seconds()
        for worker in workers:
            try:
                start_worker(worker)
            except OSError as exc:
                worker.finished = True
                logger.error("[%s] Başlatılamadı (%s); diğer görev çalışmaya devam ediyor.", worker.label, type(exc).__name__)
        while any(not worker.finished for worker in workers):
            for worker in workers:
                process = worker.process
                if process is not None:
                    code = process.poll()
                    if code is None:
                        continue
                    if worker.reader is not None:
                        worker.reader.join(timeout=1)
                    remove_owned_lock(worker, process.pid)
                    worker.process = None
                    if worker.label == "Ehliyet" and code == 2:
                        if worker.started_at is not None and time.monotonic() - worker.started_at >= 1800:
                            worker.failures = 0
                        worker.failures += 1
                        delay = min(900, 60 * 2 ** min(worker.failures - 1, 4))
                        worker.retry_at = time.monotonic() + delay
                        logger.warning("[Ehliyet] Bağlantı kesildi; %s saniye sonra yeniden denenecek. Notfall çalışmaya devam ediyor.", delay)
                    else:
                        worker.finished = True
                        logger.warning("[%s] Sona erdi (çıkış kodu %s). Diğer görev etkilenmedi.", worker.label, code)
                elif worker.retry_at is not None and time.monotonic() >= worker.retry_at:
                    start_worker(worker)
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Ctrl+C alındı; iki görev durduruluyor.")
    finally:
        stop_workers(workers)
        keep_windows_awake(False)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-at",
        metavar="ZAMAN",
        help='Münih saatiyle sonraki HH:MM veya "YYYY-MM-DD HH:MM"; yoksa hemen başlar',
    )
    parser.add_argument("--plan", action="store_true", help="Yalnızca başlangıç planını göster; çalıştırma")
    args = parser.parse_args()
    try:
        start_at = parse_start_at(args.start_at)
    except ValueError as exc:
        parser.error(str(exc))
    if args.plan:
        print(f"Başlangıç: {start_at:%d.%m.%Y %H:%M} (Europe/Berlin)")
        print("Birlikte: ehliyet izleyicisi + öğrenci/mezun Notfall hatırlatıcısı")
        return
    run(start_at)


if __name__ == "__main__":
    main()
