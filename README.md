# Bulk Send SMS

Send scheduled SMS messages via Twilio API.

## Setup

1. Install dependencies:
   ```bash
   pip install twilio
   ```

2. Create `config.json` in the project root:
   ```json
   {
       "account_sid": "your_account_sid",
       "auth_token": "your_auth_token",
       "messaging_service_sid": "your_messaging_service_sid"
   }
   ```

   Get these values from [twilio.com/console](https://twilio.com/console).

## Usage

1. Create a text file with phone numbers (one per line, E.164 format):
   ```
   +11234567890
   +10987654321
   ```

2. Run the script:
   ```bash
   python send_sms.py phone_numbers.txt
   ```

3. Edit `scheduled_time` and `body` in the script as needed.

## Phone Number Format

Numbers must be in E.164 format: `+` followed by 11 digits (e.g., `+11234567890`).

## Features

- Scheduled SMS delivery
- Bulk sending to multiple recipients
- Phone number validation
- Duplicate removal
- Error handling with per-recipient status
