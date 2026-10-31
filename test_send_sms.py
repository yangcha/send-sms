"""
Unit tests for send_sms.py module.
"""

import json
import os
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import Mock, MagicMock, patch

from twilio.base.exceptions import TwilioRestException

from send_sms import (
    SMSSender,
    E164_PATTERN,
    load_recipients,
    resolve_send_time,
    build_parser,
)


class TestPhoneValidation(unittest.TestCase):
    """Test phone number validation."""

    def test_valid_phone_numbers(self):
        """Test that valid E.164 format numbers are accepted."""
        valid_numbers = [
            "+11234567890",     # US, 11 digits
            "+19876543210",
            "+442071838750",    # UK
            "+8613800138000",   # China
            "+12",              # minimum (country code + 1 digit)
            "+123456789012345",  # maximum (15 digits)
        ]
        for number in valid_numbers:
            with self.subTest(number=number):
                self.assertTrue(SMSSender.validate_phone(number))

    def test_invalid_phone_numbers(self):
        """Test that invalid phone numbers are rejected."""
        invalid_numbers = [
            "1234567890",          # Missing +
            "+1 123 456 7890",     # Contains spaces
            "+1-123-456-7890",     # Contains dashes
            "(123) 456-7890",      # Wrong format
            "+1123456789a",        # Contains letter
            "",                    # Empty string
            "phone",               # Text
            "+1",                  # Too short (country code only)
            "+",                   # Just a plus
            "+0123456789",         # Leading zero in country code
            "+1234567890123456",   # 16 digits (too long)
        ]
        for number in invalid_numbers:
            with self.subTest(number=number):
                self.assertFalse(SMSSender.validate_phone(number))

    def test_e164_pattern_directly(self):
        """Test the E164_PATTERN regex directly."""
        self.assertIsNotNone(E164_PATTERN.match("+11234567890"))
        self.assertIsNone(E164_PATTERN.match("1234567890"))


class TestConfigLoading(unittest.TestCase):
    """Test configuration file loading."""

    def test_load_valid_config(self):
        """Test loading a valid config file."""
        config_data = {
            "account_sid": "test_sid",
            "auth_token": "test_token",
            "messaging_service_sid": "test_msg_sid"
        }

        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(config_data, f)
            temp_path = Path(f.name)

        try:
            sender = SMSSender(config_path=temp_path)
            self.assertEqual(sender.account_sid, "test_sid")
            self.assertEqual(sender.auth_token, "test_token")
            self.assertEqual(sender.messaging_service_sid, "test_msg_sid")
        finally:
            temp_path.unlink()

    def test_load_config_file_not_found(self):
        """Test that FileNotFoundError is raised when config doesn't exist."""
        non_existent_path = Path("non_existent_config.json")
        with self.assertRaises(FileNotFoundError) as context:
            SMSSender(config_path=non_existent_path)
        self.assertIn("Config file not found", str(context.exception))

    def test_load_config_invalid_json(self):
        """Test that invalid JSON raises an error."""
        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write("invalid json content {")
            temp_path = Path(f.name)

        try:
            with self.assertRaises(json.JSONDecodeError):
                SMSSender(config_path=temp_path)
        finally:
            temp_path.unlink()

    def test_explicit_credentials(self):
        """Test constructing with explicit keyword credentials."""
        sender = SMSSender(
            account_sid="sid",
            auth_token="token",
            messaging_service_sid="msg",
        )
        self.assertEqual(sender.account_sid, "sid")
        self.assertEqual(sender.messaging_service_sid, "msg")

    def test_from_number_as_sender(self):
        """Test that from_number is accepted when no messaging service is set."""
        sender = SMSSender(
            account_sid="sid",
            auth_token="token",
            from_number="+11234567890",
        )
        self.assertEqual(sender.from_number, "+11234567890")
        self.assertEqual(sender._sender_kwargs(), {"from_": "+11234567890"})

    def test_missing_credentials_raises(self):
        """Test that missing account_sid/auth_token raises ValueError."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as context:
                SMSSender(messaging_service_sid="msg")
            self.assertIn("Missing Twilio credentials", str(context.exception))

    def test_missing_sender_raises(self):
        """Test that missing both sender options raises ValueError."""
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError) as context:
                SMSSender(account_sid="sid", auth_token="token")
            self.assertIn("Missing sender", str(context.exception))

    def test_credentials_from_environment(self):
        """Test that credentials are read from environment variables."""
        env = {
            "TWILIO_ACCOUNT_SID": "env_sid",
            "TWILIO_AUTH_TOKEN": "env_token",
            "TWILIO_MESSAGING_SERVICE_SID": "env_msg",
        }
        with patch.dict(os.environ, env, clear=True):
            sender = SMSSender()
            self.assertEqual(sender.account_sid, "env_sid")
            self.assertEqual(sender.messaging_service_sid, "env_msg")


class TestSMSSending(unittest.TestCase):
    """Test SMS sending functionality."""

    def setUp(self):
        """Set up test fixtures with mocked Twilio client."""
        self.config_data = {
            "account_sid": "test_sid",
            "auth_token": "test_token",
            "messaging_service_sid": "test_msg_sid"
        }

        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.config_data, f)
            self.temp_config_path = Path(f.name)

        # Mock the Twilio Client
        self.mock_client_patcher = patch('send_sms.Client')
        self.mock_client_class = self.mock_client_patcher.start()
        self.mock_client = MagicMock()
        self.mock_client_class.return_value = self.mock_client

        self.sender = SMSSender(config_path=self.temp_config_path)

    def tearDown(self):
        """Clean up test fixtures."""
        self.mock_client_patcher.stop()
        self.temp_config_path.unlink()

    def test_send_valid_message(self):
        """Test sending a valid scheduled SMS message."""
        mock_message = Mock()
        mock_message.sid = "SM123456"
        mock_message.status = "scheduled"
        self.mock_client.messages.create.return_value = mock_message

        send_at = datetime(2026, 2, 1, 10, 0, 0)
        result = self.sender.send(
            to="+11234567890",
            body="Test message",
            send_at=send_at,
            timezone="America/New_York"
        )

        self.assertEqual(result["sid"], "SM123456")
        self.assertEqual(result["status"], "scheduled")
        self.mock_client.messages.create.assert_called_once()

        call_kwargs = self.mock_client.messages.create.call_args[1]
        self.assertEqual(call_kwargs["to"], "+11234567890")
        self.assertEqual(call_kwargs["body"], "Test message")
        self.assertEqual(call_kwargs["messaging_service_sid"], "test_msg_sid")
        self.assertEqual(call_kwargs["schedule_type"], "fixed")
        self.assertIn("send_at", call_kwargs)

    def test_send_immediate_message(self):
        """Test that send_at=None sends immediately without scheduling kwargs."""
        mock_message = Mock()
        mock_message.sid = "SM999"
        mock_message.status = "queued"
        self.mock_client.messages.create.return_value = mock_message

        result = self.sender.send(to="+11234567890", body="Now", send_at=None)

        self.assertEqual(result["status"], "queued")
        call_kwargs = self.mock_client.messages.create.call_args[1]
        self.assertNotIn("send_at", call_kwargs)
        self.assertNotIn("schedule_type", call_kwargs)

    def test_dry_run_does_not_call_twilio(self):
        """Test that dry_run validates without calling the API."""
        result = self.sender.send(
            to="+11234567890", body="Test", send_at=None, dry_run=True
        )
        self.assertEqual(result["status"], "dry-run")
        self.mock_client.messages.create.assert_not_called()

    def test_dry_run_still_validates_phone(self):
        """Test that dry_run still rejects invalid numbers."""
        with self.assertRaises(ValueError):
            self.sender.send(to="bad", body="Test", dry_run=True)

    def test_send_invalid_phone_number(self):
        """Test that sending to invalid phone number raises ValueError."""
        send_at = datetime(2026, 2, 1, 10, 0, 0)

        with self.assertRaises(ValueError) as context:
            self.sender.send(
                to="1234567890",  # Invalid format
                body="Test message",
                send_at=send_at
            )
        self.assertIn("Invalid phone number format", str(context.exception))

    def test_send_invalid_timezone(self):
        """Test that an unknown timezone raises ValueError."""
        send_at = datetime(2026, 2, 1, 10, 0, 0)
        with self.assertRaises(ValueError) as context:
            self.sender.send(
                to="+11234567890", body="Test", send_at=send_at, timezone="Mars/Olympus"
            )
        self.assertIn("Unknown timezone", str(context.exception))

    def test_send_twilio_exception(self):
        """Test that Twilio API errors are handled properly."""
        self.mock_client.messages.create.side_effect = TwilioRestException(
            status=400,
            uri="/Messages",
            msg="Invalid phone number"
        )

        send_at = datetime(2026, 2, 1, 10, 0, 0)

        with self.assertRaises(RuntimeError) as context:
            self.sender.send(
                to="+11234567890",
                body="Test message",
                send_at=send_at
            )
        self.assertIn("Failed to send SMS", str(context.exception))

    def test_send_with_different_timezone(self):
        """Test sending with different timezone."""
        mock_message = Mock()
        mock_message.sid = "SM123456"
        mock_message.status = "scheduled"
        self.mock_client.messages.create.return_value = mock_message

        send_at = datetime(2026, 2, 1, 10, 0, 0)
        result = self.sender.send(
            to="+11234567890",
            body="Test message",
            send_at=send_at,
            timezone="America/Los_Angeles"
        )

        self.assertEqual(result["sid"], "SM123456")
        self.mock_client.messages.create.assert_called_once()


class TestBulkSending(unittest.TestCase):
    """Test bulk SMS sending functionality."""

    def setUp(self):
        """Set up test fixtures with mocked Twilio client."""
        self.config_data = {
            "account_sid": "test_sid",
            "auth_token": "test_token",
            "messaging_service_sid": "test_msg_sid"
        }

        with NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(self.config_data, f)
            self.temp_config_path = Path(f.name)

        # Mock the Twilio Client
        self.mock_client_patcher = patch('send_sms.Client')
        self.mock_client_class = self.mock_client_patcher.start()
        self.mock_client = MagicMock()
        self.mock_client_class.return_value = self.mock_client

        self.sender = SMSSender(config_path=self.temp_config_path)

    def tearDown(self):
        """Clean up test fixtures."""
        self.mock_client_patcher.stop()
        self.temp_config_path.unlink()

    def test_send_bulk_all_success(self):
        """Test bulk sending when all messages succeed."""
        mock_message = Mock()
        mock_message.sid = "SM123456"
        mock_message.status = "scheduled"
        self.mock_client.messages.create.return_value = mock_message

        recipients = ["+11234567890", "+10987654321", "+11111111111"]
        send_at = datetime(2026, 2, 1, 10, 0, 0)

        results = self.sender.send_bulk(
            recipients=recipients,
            body="Bulk test message",
            send_at=send_at
        )

        self.assertEqual(len(results), 3)
        for i, result in enumerate(results):
            self.assertTrue(result["success"])
            self.assertEqual(result["phone"], recipients[i])
            self.assertEqual(result["sid"], "SM123456")
            self.assertEqual(result["status"], "scheduled")

    def test_send_bulk_partial_failure(self):
        """Test bulk sending with some failures."""
        mock_message = Mock()
        mock_message.sid = "SM123456"
        mock_message.status = "scheduled"

        self.mock_client.messages.create.side_effect = [
            mock_message,
            TwilioRestException(status=400, uri="/Messages", msg="Invalid number"),
            mock_message,
        ]

        recipients = ["+11234567890", "+10987654321", "+11111111111"]
        send_at = datetime(2026, 2, 1, 10, 0, 0)

        results = self.sender.send_bulk(
            recipients=recipients,
            body="Bulk test message",
            send_at=send_at
        )

        self.assertEqual(len(results), 3)
        self.assertTrue(results[0]["success"])
        self.assertFalse(results[1]["success"])
        self.assertIn("error", results[1])
        self.assertTrue(results[2]["success"])

    def test_send_bulk_invalid_phone_in_list(self):
        """Test bulk sending with invalid phone number in list."""
        mock_message = Mock()
        mock_message.sid = "SM123456"
        mock_message.status = "scheduled"
        self.mock_client.messages.create.return_value = mock_message

        recipients = ["+11234567890", "invalid_number", "+11111111111"]
        send_at = datetime(2026, 2, 1, 10, 0, 0)

        results = self.sender.send_bulk(
            recipients=recipients,
            body="Bulk test message",
            send_at=send_at
        )

        self.assertEqual(len(results), 3)
        self.assertTrue(results[0]["success"])
        self.assertFalse(results[1]["success"])
        self.assertIn("Invalid phone number format", results[1]["error"])
        self.assertTrue(results[2]["success"])

    def test_send_bulk_empty_recipients(self):
        """Test bulk sending with empty recipient list."""
        send_at = datetime(2026, 2, 1, 10, 0, 0)

        results = self.sender.send_bulk(
            recipients=[],
            body="Bulk test message",
            send_at=send_at
        )

        self.assertEqual(len(results), 0)
        self.mock_client.messages.create.assert_not_called()

    def test_send_bulk_dry_run(self):
        """Test that bulk dry-run validates without calling Twilio."""
        recipients = ["+11234567890", "+10987654321"]
        results = self.sender.send_bulk(
            recipients=recipients, body="Test", send_at=None, dry_run=True
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r["success"] for r in results))
        self.mock_client.messages.create.assert_not_called()


class TestLoadRecipients(unittest.TestCase):
    """Test reading recipients from a file."""

    def _write(self, content: str) -> Path:
        with NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(content)
            return Path(f.name)

    def test_basic_list(self):
        """Test a simple one-per-line list."""
        path = self._write("+11234567890\n+10987654321\n")
        try:
            self.assertEqual(
                load_recipients(path), ["+11234567890", "+10987654321"]
            )
        finally:
            path.unlink()

    def test_blanks_comments_and_duplicates(self):
        """Test that blanks, comments, and duplicates are handled."""
        path = self._write(
            "+11234567890\n\n# a comment\n+11234567890\n  +10987654321  \n"
        )
        try:
            self.assertEqual(
                load_recipients(path), ["+11234567890", "+10987654321"]
            )
        finally:
            path.unlink()

    def test_csv_first_column(self):
        """Test that only the first CSV column is used."""
        path = self._write("+11234567890,Alice\n+10987654321,Bob\n")
        try:
            self.assertEqual(
                load_recipients(path), ["+11234567890", "+10987654321"]
            )
        finally:
            path.unlink()


class TestResolveSendTime(unittest.TestCase):
    """Test resolving the CLI time flags into a datetime."""

    def _args(self, argv):
        return build_parser().parse_args(argv)

    def test_now_returns_none(self):
        """--now resolves to None (immediate send)."""
        args = self._args(["nums.txt", "-b", "hi", "--now"])
        self.assertIsNone(resolve_send_time(args))

    def test_in_minutes(self):
        """--in-minutes resolves to a datetime."""
        args = self._args(["nums.txt", "-b", "hi", "--in-minutes", "30"])
        result = resolve_send_time(args)
        self.assertIsInstance(result, datetime)

    def test_at_iso(self):
        """--at parses an ISO datetime string."""
        args = self._args(["nums.txt", "-b", "hi", "--at", "2026-01-30T10:00:00"])
        self.assertEqual(resolve_send_time(args), datetime(2026, 1, 30, 10, 0, 0))

    def test_at_invalid(self):
        """An invalid --at value exits the program."""
        args = self._args(["nums.txt", "-b", "hi", "--at", "not-a-date"])
        with self.assertRaises(SystemExit):
            resolve_send_time(args)


if __name__ == "__main__":
    unittest.main()
