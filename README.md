# Munich Appointment Bot

Telegram bot that monitors Munich city appointment system and notifies users when appointments become available.

![screenshot](DOCS/bot-screenshot.png)

## Features

- **Multi-service subscriptions** - Track multiple appointment types simultaneously
- **Automated booking** - Book appointments directly through the bot
- **Date range filtering** - Only get notified for appointments in your preferred timeframe
- **Real-time notifications** - Get instant alerts when appointments become available

## Quick Start

```bash
# Setup
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN

# Install dependencies
uv pip install --system -r pyproject.toml

# Initialize database
python3 -c "from database import init_database; init_database()"

# Run
python3 telegram_bot.py
```

## Configuration

Required:
- `TELEGRAM_BOT_TOKEN` - Get from @BotFather

Optional:
- `ADMIN_TELEGRAM_ID` - For health alerts

## Official driver-licence appointment monitor

The dedicated monitor follows the public Munich appointment page in a browser and
checks the service **Umschreibung eines ausländischen Führerscheins**. It reads the
visible date and time list and does not call the repository's CAPTCHA-solving API
flow. If the official page presents a CAPTCHA or access check, it stops and reports
that condition without attempting to solve it.

Use this dedicated monitor for the driving-licence exchange workflow. The older
general-purpose Telegram bot still uses its separate API-based checker.

1. Copy `.env.example` to `.env`. Create a Telegram bot with `@BotFather` (`/newbot`)
   and put its token in `TELEGRAM_BOT_TOKEN`. Send `/start` to your bot, then run
   `.\.venv\Scripts\python.exe -m src.driver_license_monitor --telegram-chat-id`
   to find your chat ID. Put it in `TELEGRAM_CHAT_ID`, then verify delivery with
   `.\.venv\Scripts\python.exe -m src.driver_license_monitor --test-telegram`.
2. In Python 3.11+, install `playwright` and `python-dotenv`, then run
   `python -m playwright install chromium` once. The dedicated monitor sends
   notifications through Telegram's HTTPS API without another package.
3. On Windows, run a one-time read-only check with
   `.\.venv\Scripts\python.exe -m src.driver_license_monitor --once`.
4. Run continuous monitor-only mode with
   `.\.venv\Scripts\python.exe -m src.driver_license_monitor`.
   Until Telegram is configured, use
   `.\.venv\Scripts\python.exe -m src.driver_license_monitor --local-only`;
   matching-slot alerts then appear only in the terminal and `monitor.log`.
5. Stop it with `Ctrl+C`. Keep Windows awake and connected to the internet.

One Chromium browser stays open while monitoring. Every check reloads the official
page in the same tab, chooses the service, presses Weiter, and reads the dates and
times from the page DOM; it does not take or analyze screenshots. If no matching
slot is visible, it waits and repeats. In monitor-only mode it continues after a
match and sends Telegram alerts for newly seen or reappearing matching times.
The first scan sends one message listing matching slots that have not previously
been alerted, plus any that disappeared in a prior scan and have returned.
Each later scan sends at most one message listing all newly seen or reappearing
matching slots. A slot is alerted again only after `ALERT_COOLDOWN_MINUTES`
(default 30) have passed since its last alert; this survives restarts.
Continuous visibility in later scans does not create repeated alerts. The same
readable Turkish alert appears in the terminal and on Telegram when configured.
`MONITOR_SCHEDULE`
defines weekday and weekend intervals in Berlin local time; the minimum gap between
check starts is 120 seconds. The scheduler recalculates after each scan and handles
the October clock change. If a scan lasts longer than the scheduled interval, the
next scan starts when it finishes and the overrun is logged.
If the page says **Aktuell ist kein Termin verfügbar**, that scan records zero slots
and waits for the next scheduled check.

`APPOINTMENT_WINDOWS` entries are checked in order. The default October range accepts
any time. The November morning range accepts 07:00–08:40 and takes the earliest time
on the earliest day. The November evening range accepts 16:00–23:59 and takes the
latest time on the earliest day. The 21–24 November fallback accepts any time.
Past dates are excluded. Add `#latest` to a range to choose its latest time;
`#earliest` is optional. Update the initial 2026 dates as needed.

The ignored `monitor/` directory contains `slot_events.json` (each distinct
date/time's first and last sighting, reappearance and alert counts, last alert,
current visibility and
preference match), `metrics.jsonl` (one record per scan with stage durations,
total duration and the schedule), `monitor.log` (readable terminal messages),
and `booking.state.json` (reservation status). The log rotates at 5 MB and keeps
three backups. In a second PowerShell window, follow live messages with
`Get-Content .\monitor\monitor.log -Wait -Tail 30`.

`metrics.jsonl` contains
one JSON record per scan with stage durations, total duration, scheduled interval,
actual start-to-start gap, and any overrun. These files are local and ignored by Git. Run
`.\.venv\Scripts\python.exe -m src.driver_license_monitor --report` to see first
sightings by Berlin hour, reappearances, counts for morning and afternoon windows,
and average / maximum scan duration. A first sighting is the first time the monitor observed a
slot, not proof of its exact publication time. Observe for 24–48 hours before
changing the schedule based on the data.

Run `.\.venv\Scripts\python.exe -m src.driver_license_monitor --status` for the
last scan and local reservation status. It shows the selected slot, submit time,
and an estimated 60-minute email activation deadline after a successful request.
The monitor cannot see whether you clicked the activation link in your email.

Automatic booking is off by default. To enable it, fill in the four
`BOOKING_*` fields and explicitly set `AUTO_BOOK_ENABLED=true`. The monitor selects
one matching slot, fills those details, presses Weiter, then presses the final
booking button (currently labelled **Termin reservieren**) only when exactly one
recognized button appears on the overview. It notifies Telegram after the site
confirms the request; immediately before submitting, it checks the electronic-
communication consent checkbox explicitly requested by the user. You activate the
emailed link yourself within 60 minutes. If the final button or consent control is missing or
ambiguous, it stops without submitting and asks you to review the official site.
A local state file prevents a duplicate attempt. Clear
`monitor/booking.state.json` only after verifying that no reservation is
pending. Keep `.env` private; it contains personal data
and credentials.

## Bot Commands

- `/start` - Register and get started
- `/menu` - Show main menu
- `/subscribe` - Browse and subscribe to services
- `/myservices` - Manage your subscriptions
- `/setdates <start> <end>` - Set date range (YYYY-MM-DD)
- `/status` - View your settings
- `/stats` - View bot statistics
- `/stop` - Unsubscribe from all

## Architecture

Built with modern Python patterns:
- **Type-safe** - Pydantic models and dataclasses throughout
- **ORM** - SQLModel with repository pattern
- **Validated config** - Fails fast on startup errors
- **Background monitoring** - Continuous appointment checking with health monitoring

See `CLAUDE.md` for detailed architecture documentation.
