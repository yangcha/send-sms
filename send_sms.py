"""
Send SMS messages in bulk via the Twilio API, immediately or scheduled.

Credentials are read from a JSON config file or from environment variables.
Recipients are read from a plain-text or CSV file (one number per line,
E.164 format). See the README for full usage.
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# E.164: a leading "+", a non-zero country-code digit, then up to 14 more
# digits (15 digits total maximum). Covers international numbers, not just US.
E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")

DEFAULT_TIMEZONE = "America/New_York"

# Twilio requires scheduled sends to be between 15 minutes and 35 days out.
MIN_SCHEDULE_LEAD = timedelta(minutes=15)
MAX_SCHEDULE_LEAD = timedelta(days=35)

logger = logging.getLogger("send_sms")


class SMSSender:
    """Twilio SMS sender with immediate and scheduled delivery support."""

    def __init__(
        self,
        config_path: Path | None = None,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        messaging_service_sid: str | None = None,
        from_number: str | None = None,
    ):
        """
        Initialize the SMS sender with Twilio credentials.

        Credentials may be passed directly, loaded from ``config_path``, or
        taken from the environment (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
        TWILIO_MESSAGING_SERVICE_SID, TWILIO_FROM_NUMBER). Explicit arguments
        win over the config file, which wins over the environment.

        Args:
            config_path: Path to a config.json file. If None and no explicit
                credentials are given, environment variables are used.
            account_sid: Twilio Account SID.
            auth_token: Twilio Auth Token.
            messaging_service_sid: Twilio Messaging Service SID (preferred).
            from_number: Sender phone number (E.164), used when no messaging
                service SID is supplied.
        """
        config: dict = {}
        if config_path is not None:
            config = self._load_config(config_path)

        self.account_sid = (
            account_sid or config.get("account_sid") or os.environ.get("TWILIO_ACCOUNT_SID")
        )
        self.auth_token = (
            auth_token or config.get("auth_token") or os.environ.get("TWILIO_AUTH_TOKEN")
        )
        self.messaging_service_sid = (
            messaging_service_sid
            or config.get("messaging_service_sid")
            or os.environ.get("TWILIO_MESSAGING_SERVICE_SID")
        )
        self.from_number = (
            from_number or config.get("from_number") or os.environ.get("TWILIO_FROM_NUMBER")
        )

        if not self.account_sid or not self.auth_token:
            raise ValueError(
                "Missing Twilio credentials: account_sid and auth_token are required. "
                "Provide a config.json or set TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN."
            )
        if not self.messaging_service_sid and not self.from_number:
            raise ValueError(
                "Missing sender: provide either messaging_service_sid or from_number."
            )

        self.client = Client(self.account_sid, self.auth_token)

    @staticmethod
    def _load_config(config_path: Path) -> dict:
        """Load Twilio credentials from a config.json file."""
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {config_path}\n"
                "Create a config.json with: account_sid, auth_token, "
                "and messaging_service_sid (or from_number)."
            )
        return json.loads(config_path.read_text())

    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Return True if ``phone`` is in E.164 format (e.g. +11234567890)."""
        return bool(E164_PATTERN.match(phone))

    def _sender_kwargs(self) -> dict:
        """Return the correct 'sender' keyword for the Twilio API call."""
        if self.messaging_service_sid:
            return {"messaging_service_sid": self.messaging_service_sid}
        return {"from_": self.from_number}

    def send(
        self,
        to: str,
        body: str,
        send_at: datetime | None = None,
        timezone: str = DEFAULT_TIMEZONE,
        dry_run: bool = False,
    ) -> dict:
        """
        Send one SMS message, optionally scheduled.

        Args:
            to: Recipient phone number in E.164 format.
            body: Message content.
            send_at: Local datetime to send the message. If None, the message
                is sent immediately.
            timezone: IANA timezone name for ``send_at`` (default
                America/New_York). Ignored when ``send_at`` is None.
            dry_run: If True, validate and report without calling Twilio.

        Returns:
            dict with message ``sid`` and ``status`` (or a dry-run placeholder).
        """
        if not self.validate_phone(to):
            raise ValueError(f"Invalid phone number format: {to}. Expected E.164 format (e.g. +11234567890).")

        create_kwargs = {"body": body, "to": to, **self._sender_kwargs()}

        if send_at is not None:
            scheduled_utc = self._to_utc(send_at, timezone)
            create_kwargs["send_at"] = scheduled_utc.isoformat(timespec="seconds").replace("+00:00", "Z")
            create_kwargs["schedule_type"] = "fixed"

        if dry_run:
            return {"sid": None, "status": "dry-run", "to": to}

        try:
            message = self.client.messages.create(**create_kwargs)
            return {"sid": message.sid, "status": message.status}
        except TwilioRestException as e:
            raise RuntimeError(f"Failed to send SMS: {e.msg}") from e

    @staticmethod
    def _to_utc(send_at: datetime, timezone: str) -> datetime:
        """Convert a naive/aware local datetime to UTC using ``timezone``."""
        try:
            local_tz = ZoneInfo(timezone)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"Unknown timezone: {timezone}") from e
        localized = send_at if send_at.tzinfo else send_at.replace(tzinfo=local_tz)
        return localized.astimezone(ZoneInfo("UTC"))

    def send_bulk(
        self,
        recipients: list[str],
        body: str,
        send_at: datetime | None = None,
        timezone: str = DEFAULT_TIMEZONE,
        dry_run: bool = False,
    ) -> list[dict]:
        """
        Send an SMS to multiple recipients.

        Returns a list of per-recipient result dicts. Each dict has at least
        ``phone`` and ``success``; successes also carry ``sid``/``status`` and
        failures carry ``error``. One bad number never stops the rest.
        """
        results = []
        for phone in recipients:
            try:
                result = self.send(
                    to=phone, body=body, send_at=send_at, timezone=timezone, dry_run=dry_run
                )
                result["phone"] = phone
                result["success"] = True
                results.append(result)
                verb = "Would schedule" if dry_run and send_at else "Would send" if dry_run else (
                    "Scheduled" if send_at else "Sent"
                )
                logger.info("✓ %s for %s", verb, phone)
            except (RuntimeError, ValueError) as e:
                results.append({"phone": phone, "success": False, "error": str(e)})
                logger.error("✗ Failed for %s: %s", phone, e)
        return results


def load_recipients(path: Path) -> list[str]:
    """
    Read recipient phone numbers from a text or CSV file.

    Rules: one number per line; the first column is used for CSV rows; blank
    lines and lines starting with ``#`` are ignored; duplicates are removed
    while preserving order.
    """
    recipients: list[str] = []
    seen: set[str] = set()
    with path.open(newline="") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            value = row[0].strip()
            if not value or value.startswith("#"):
                continue
            if value not in seen:
                seen.add(value)
                recipients.append(value)
    return recipients


def resolve_send_time(args: argparse.Namespace) -> datetime | None:
    """Turn the mutually exclusive time flags into a local ``send_at`` (or None)."""
    if args.now:
        return None
    if args.in_minutes is not None:
        return datetime.now() + timedelta(minutes=args.in_minutes)
    # args.at is guaranteed by the argument parser at this point.
    try:
        return datetime.fromisoformat(args.at)
    except ValueError as e:
        raise SystemExit(f"Invalid --at datetime '{args.at}'. Use ISO format, e.g. 2026-01-30T10:00:00.") from e


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Send SMS messages in bulk via Twilio, immediately or scheduled.",
    )
    parser.add_argument(
        "phone_numbers",
        type=Path,
        help="Path to a text/CSV file of recipient numbers (E.164 format, one per line).",
    )

    body_group = parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("-b", "--body", help="Message text to send.")
    body_group.add_argument(
        "--body-file", type=Path, help="Path to a file whose contents are the message text."
    )

    time_group = parser.add_mutually_exclusive_group(required=True)
    time_group.add_argument("--at", help="Local send time in ISO format, e.g. 2026-01-30T10:00:00.")
    time_group.add_argument("--in-minutes", type=int, help="Schedule N minutes from now.")
    time_group.add_argument("--now", action="store_true", help="Send immediately (no scheduling).")

    parser.add_argument(
        "--timezone", "--tz", default=DEFAULT_TIMEZONE, dest="timezone",
        help=f"IANA timezone for scheduled sends (default: {DEFAULT_TIMEZONE}).",
    )
    parser.add_argument(
        "-c", "--config", type=Path, default=None,
        help="Path to config.json. If omitted, credentials are read from the environment.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate and print the plan without contacting Twilio.",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip the confirmation prompt.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging.",
    )
    return parser


class SendSmsError(Exception):
    """Raised for user-facing input/configuration problems in the CLI."""


def _resolve_body(args: argparse.Namespace) -> str:
    """Resolve the message body from --body or --body-file."""
    if args.body_file is not None:
        try:
            body = args.body_file.read_text().strip()
        except OSError as e:
            raise SendSmsError(f"Could not read body file {args.body_file}: {e}") from e
    else:
        body = args.body
    if not body:
        raise SendSmsError("Message body is empty.")
    return body


def _resolve_recipients(path: Path) -> list[str]:
    """Load recipients from a file, raising SendSmsError on any problem."""
    try:
        recipients = load_recipients(path)
    except FileNotFoundError as e:
        raise SendSmsError(f"Phone numbers file not found: {path}") from e
    except OSError as e:
        raise SendSmsError(f"Could not read phone numbers file {path}: {e}") from e
    if not recipients:
        raise SendSmsError(f"No phone numbers found in {path}.")
    return recipients


def _log_plan(recipients: list[str], send_at: datetime | None, timezone: str, body: str) -> None:
    """Print a summary of what will be sent."""
    logger.info("Loaded %d unique phone number(s).", len(recipients))
    if send_at is None:
        logger.info("Delivery: immediately.")
    else:
        logger.info("Delivery: %s (%s).", send_at.isoformat(timespec="seconds"), timezone)
        lead = send_at - datetime.now()
        if lead < MIN_SCHEDULE_LEAD:
            logger.warning("Scheduled time is less than 15 minutes out; Twilio may reject it.")
        elif lead > MAX_SCHEDULE_LEAD:
            logger.warning("Scheduled time is more than 35 days out; Twilio may reject it.")
    logger.info("Message: %s", body)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point. Returns a process exit code."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    try:
        body = _resolve_body(args)
        recipients = _resolve_recipients(args.phone_numbers)
    except SendSmsError as e:
        logger.error("%s", e)
        return 1

    send_at = resolve_send_time(args)

    # Report the plan.
    _log_plan(recipients, send_at, args.timezone, body)

    if args.dry_run:
        logger.info("[dry-run] No messages will be sent.")

    # Confirm (unless suppressed or dry-run).
    if not args.yes and not args.dry_run:
        try:
            input("Press Enter to continue, or Ctrl+C to abort... ")
        except (KeyboardInterrupt, EOFError):
            logger.info("\nAborted.")
            return 130

    try:
        sender = SMSSender(config_path=args.config)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        logger.error("Configuration error: %s", e)
        return 1

    results = sender.send_bulk(
        recipients=recipients,
        body=body,
        send_at=send_at,
        timezone=args.timezone,
        dry_run=args.dry_run,
    )

    successful = sum(1 for r in results if r["success"])
    logger.info("\nComplete: %d/%d message(s) %s.", successful, len(results),
                "validated" if args.dry_run else "accepted by Twilio")
    return 0 if successful == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
