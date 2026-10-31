# Bulk Send SMS

Send SMS messages in bulk via the [Twilio](https://www.twilio.com/) API —
immediately or scheduled for a future time.

[![Python application](https://github.com/yangcha/send-sms/actions/workflows/python-app.yml/badge.svg)](https://github.com/yangcha/send-sms/actions/workflows/python-app.yml)

## Features

- Immediate or scheduled delivery (`--now`, `--at`, `--in-minutes`)
- Bulk sending to many recipients from a text or CSV file
- International E.164 phone-number validation
- Automatic duplicate removal (order preserved)
- Per-recipient status reporting; one bad number never stops the rest
- `--dry-run` to preview exactly what would be sent, with no API calls
- Credentials from a config file **or** environment variables
- Send via a Messaging Service SID or a single `from` number

## Requirements

- Python 3.10+
- A Twilio account with a Messaging Service (or a sending phone number)

## Installation

```bash
pip install -r requirements.txt
```

For development (linters and tests):

```bash
pip install -r requirements-dev.txt
```

## Configuration

Credentials can be supplied two ways. Explicit config wins over the environment.

### Option 1 — `config.json`

Create `config.json` in the project root:

```json
{
    "account_sid": "your_account_sid",
    "auth_token": "your_auth_token",
    "messaging_service_sid": "your_messaging_service_sid"
}
```

You can use `"from_number": "+11234567890"` instead of
`messaging_service_sid` if you send from a single number.

Pass it with `--config path/to/config.json` (defaults to looking at the
environment if omitted).

### Option 2 — environment variables

```bash
export TWILIO_ACCOUNT_SID=your_account_sid
export TWILIO_AUTH_TOKEN=your_auth_token
export TWILIO_MESSAGING_SERVICE_SID=your_messaging_service_sid
# or, instead of the messaging service SID:
# export TWILIO_FROM_NUMBER=+11234567890
```

Get these values from [twilio.com/console](https://www.twilio.com/console).
`config.json` is git-ignored so your credentials are never committed.

## Usage

1. Create a recipients file (one number per line, E.164 format). Blank lines
   and lines starting with `#` are ignored, and for CSV rows only the first
   column is used:

   ```text
   +11234567890
   +10987654321
   # a comment
   +442071838750,Optional label ignored
   ```

2. Run the script.

   Preview without sending (recommended first):

   ```bash
   python send_sms.py recipients.txt --body "Hello!" --now --dry-run
   ```

   Send immediately:

   ```bash
   python send_sms.py recipients.txt --body "Hello! Text STOP to unsubscribe." --now
   ```

   Schedule for a specific local time:

   ```bash
   python send_sms.py recipients.txt --body "Reminder!" --at 2026-01-30T10:00:00 --tz America/New_York
   ```

   Schedule a number of minutes from now, skipping the confirmation prompt:

   ```bash
   python send_sms.py recipients.txt --body "Starting soon" --in-minutes 30 --yes
   ```

   Read the message body from a file:

   ```bash
   python send_sms.py recipients.txt --body-file message.txt --now
   ```

### Options

| Option | Description |
| --- | --- |
| `phone_numbers` | Path to the recipients file (positional, required). |
| `-b`, `--body` | Message text. |
| `--body-file` | Read the message text from a file (alternative to `--body`). |
| `--now` | Send immediately. |
| `--at` | Local send time in ISO format, e.g. `2026-01-30T10:00:00`. |
| `--in-minutes` | Schedule N minutes from now. |
| `--timezone`, `--tz` | IANA timezone for scheduled sends (default `America/New_York`). |
| `-c`, `--config` | Path to `config.json` (defaults to environment variables). |
| `--dry-run` | Validate and print the plan without contacting Twilio. |
| `-y`, `--yes` | Skip the confirmation prompt. |
| `-v`, `--verbose` | Enable debug logging. |

Exactly one of `--body`/`--body-file` and one of `--now`/`--at`/`--in-minutes`
are required.

## Scheduling notes

Twilio requires scheduled messages to be between **15 minutes and 35 days**
in the future, and scheduling requires a Messaging Service. The script warns
if your chosen time falls outside that window.

## Phone number format

Numbers must be in [E.164 format](https://www.twilio.com/docs/glossary/what-e164):
a `+`, the country code, then the subscriber number, up to 15 digits total
(e.g. `+11234567890`).

## Programmatic use

```python
from datetime import datetime
from send_sms import SMSSender

sender = SMSSender()  # reads credentials from the environment
sender.send_bulk(
    recipients=["+11234567890", "+10987654321"],
    body="Hello!",
    send_at=datetime(2026, 1, 30, 10, 0, 0),  # or None to send immediately
    timezone="America/New_York",
)
```

## Development

Run the test suite and linters the same way CI does:

```bash
pytest
flake8 .
pylint $(git ls-files '*.py')
```

## License

BSD 2-Clause — see [LICENSE](LICENSE).
