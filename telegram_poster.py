# telegram_poster.py
import json
import os
import requests


class TelegramPoster:
    def __init__(self) -> None:
        self.bot_token = os.getenv("DEVOTIONAL_BOT_TOKEN")
        self.group_id = os.getenv("DEVOTIONAL_GROUP_ID")
        if not self.bot_token:
            print("Warning: DEVOTIONAL_BOT_TOKEN not set in environment")
        if not self.group_id:
            print("Warning: DEVOTIONAL_GROUP_ID not set in environment")

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.group_id)

    def post_devotion(
        self,
        message_id: str,
        subject: str,
        verse: str,
        reflection: str,
        prayer: str,
        silent: bool = False,
    ) -> bool:
        if not self.is_configured():
            print(
                "Error: Telegram not configured. Set DEVOTIONAL_BOT_TOKEN and DEVOTIONAL_GROUP_ID"
            )
            return False

        # subject, verse, reflection, prayer are already HTML-escaped/converted by caller
        parts = []
        if message_id:
            parts.append(f"<code>message id: {subject and ''}{message_id}</code>")
        if subject:
            parts.append(f"<b>{subject}</b>")
        if verse:
            parts.append("<i>Verse:</i>")
            parts.append(verse)
        if reflection:
            parts.append("<i>Reflection:</i>")
            parts.append(reflection)
        if prayer:
            parts.append("<i>Prayer:</i>")
            parts.append(prayer)

        # Blank line between sections -> Telegram supports \n\n in HTML mode, preserved as new lines
        message = "\n\n".join(parts).strip()

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.group_id,
            "text": message,
            "parse_mode": "HTML",  # HTML mode
            "disable_notification": silent,
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            result = response.json()
            if result.get("ok"):
                return True
            print(f"Telegram error: {result.get('description', 'Unknown error')}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"Network error posting to Telegram: {e}")
            return False
        except json.JSONDecodeError:
            print("Invalid response from Telegram API")
            return False
