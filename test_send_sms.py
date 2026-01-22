"""
Unit tests for send_sms.py module.
"""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import Mock, MagicMock, patch

from twilio.base.exceptions import TwilioRestException

from send_sms import SMSSender, E164_PATTERN


class TestPhoneValidation(unittest.TestCase):
    """Test phone number validation."""

    def test_valid_phone_numbers(self):
        """Test that valid E.164 format numbers are accepted."""
        valid_numbers = [
            "+11234567890",
            "+19876543210",
            "+10000000000",
            "+19999999999",
        ]
        for number in valid_numbers:
            with self.subTest(number=number):
                self.assertTrue(SMSSender.validate_phone(number))

    def test_invalid_phone_numbers(self):
        """Test that invalid phone numbers are rejected."""
        invalid_numbers = [
            "1234567890",  # Missing +
            "+1234567890",  # Only 10 digits
            "+123456789012",  # 12 digits
            "+1 123 456 7890",  # Contains spaces
            "+1-123-456-7890",  # Contains dashes
            "(123) 456-7890",  # Wrong format
            "+1123456789a",  # Contains letter
            "",  # Empty string
            "phone",  # Text
            "+1",  # Too short
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
        """Test sending a valid SMS message."""
        # Mock the message creation
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

        # Verify the call arguments
        call_kwargs = self.mock_client.messages.create.call_args[1]
        self.assertEqual(call_kwargs["to"], "+11234567890")
        self.assertEqual(call_kwargs["body"], "Test message")
        self.assertEqual(call_kwargs["messaging_service_sid"], "test_msg_sid")
        self.assertEqual(call_kwargs["schedule_type"], "fixed")
        self.assertIn("send_at", call_kwargs)

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

    def test_send_twilio_exception(self):
        """Test that Twilio API errors are handled properly."""
        # Mock Twilio raising an exception
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
        # First call succeeds, second fails, third succeeds
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


if __name__ == "__main__":
    unittest.main()
