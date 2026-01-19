"""
Send SMS via Twilio API with scheduling support.
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

# E.164 format: + followed by 11 digits
E164_PATTERN = re.compile(r"^\+\d{11}$")


class SMSSender:
    """Twilio SMS sender with scheduling support."""

    def __init__(self, config_path: Path | None = None):
        """
        Initialize SMS sender with Twilio credentials.

        Args:
            config_path: Path to config.json file (default: config.json in script directory)
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.json"

        config = self._load_config(config_path)
        self.account_sid = config["account_sid"]
        self.auth_token = config["auth_token"]
        self.messaging_service_sid = config["messaging_service_sid"]
        self.client = Client(self.account_sid, self.auth_token)

    @staticmethod
    def _load_config(config_path: Path) -> dict:
        """Load Twilio credentials from config.json file."""
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {config_path}\n"
                "Create a config.json with: account_sid, auth_token, messaging_service_sid"
            )
        return json.loads(config_path.read_text())

    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate phone number is in E.164 format (+11 digits)."""
        return bool(E164_PATTERN.match(phone))

    def send(
        self,
        to: str,
        body: str,
        send_at: datetime,
        timezone: str = "America/New_York",
    ) -> dict:
        """
        Send a scheduled SMS message.

        Args:
            to: Recipient phone number (E.164 format for US. numbers)
            body: Message content
            send_at: Local datetime to send the message
            timezone: Timezone for send_at (default: America/New_York)

        Returns:
            dict with message sid and status
        """
        if not self.validate_phone(to):
            raise ValueError(f"Invalid phone number format: {to}. Expected E.164 format.")

        local_tz = ZoneInfo(timezone)
        scheduled_utc = send_at.replace(tzinfo=local_tz).astimezone(ZoneInfo("UTC"))

        try:
            message = self.client.messages.create(
                body=body,
                messaging_service_sid=self.messaging_service_sid,
                send_at=scheduled_utc.isoformat(timespec='seconds').replace('+00:00', 'Z'),
                schedule_type="fixed",
                to=to,
            )
            return {"sid": message.sid, "status": message.status}
        except TwilioRestException as e:
            raise RuntimeError(f"Failed to send SMS: {e.msg}") from e

    def send_bulk(
        self,
        recipients: list[str],
        body: str,
        send_at: datetime,
        timezone: str = "America/New_York",
    ) -> list[dict]:
        """
        Send scheduled SMS to multiple phone numbers.

        Args:
            recipients: List of recipient phone numbers (E.164 format)
            body: Message content
            send_at: Local datetime to send the messages
            timezone: Timezone for send_at (default: America/New_York)

        Returns:
            List of dicts with send results for each number
        """
        message_results = []
        for phone in recipients:
            try:
                result = self.send(to=phone, body=body, send_at=send_at, timezone=timezone)
                result["phone"] = phone
                result["success"] = True
                message_results.append(result)
                print(f"✓ Scheduled for {phone}")
            except (RuntimeError, ValueError) as e:
                message_results.append({"phone": phone, "success": False, "error": str(e)})
                print(f"✗ Failed for {phone}: {e}")
        return message_results


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Send scheduled SMS via Twilio")
    arg_parser.add_argument(
        "phone_numbers",
        type=Path,
        help="List of phone numbers to send to (E.164 format)"
    )
    args = arg_parser.parse_args()

    # List of phone numbers to send to
    try:
        numbers_text = args.phone_numbers.read_text()
    except FileNotFoundError as exc:
        print(f"Phone numbers file not found: {args.phone_numbers}")
        raise SystemExit(1) from exc
    except OSError as e:
        print(f"Could not read phone numbers file {args.phone_numbers}: {e}")
        raise SystemExit(1) from e

    phone_numbers = [line.strip() for line in numbers_text.splitlines() if line.strip()]
    phone_numbers = list(set(phone_numbers))  # Remove duplicates if any
    print(f"Loaded {len(phone_numbers)} unique phone numbers.")
    input("Press Enter to continue..., or Ctrl+C to abort.")

    # Schedule message 6 minutes from now
    #scheduled_time = datetime.now() + timedelta(minutes=6)
    scheduled_time = datetime(2026, 1, 30, 10, 0, 0)  # Example fixed time
    print(f"Scheduling message to be sent at {scheduled_time} local time.")
    print(f"Sending to {len(phone_numbers)} recipients...\n")

    sender = SMSSender()
    results = sender.send_bulk(
        recipients=phone_numbers,
        body="Hello! This is a scheduled message. Text STOP to unsubscribe",
        send_at=scheduled_time,
    )

    # Summary
    successful = sum(1 for r in results if r["success"])
    print(f"\nComplete: {successful}/{len(phone_numbers)} messages scheduled")
