#!/usr/bin/env python3
"""
Telegram Bot Command Listener — Pythia Query Interface

Run alongside Pythia Live to handle query commands:
/fed_rate, /similar, /what_caused, /patterns, /correlations

Usage:
  python bot_commands.py

Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from pythia_live.telegram_query import handle_telegram_command


def get_updates(bot_token: str, offset: int = None):
    """Fetch updates from Telegram Bot API."""
    import requests
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    
    try:
        resp = requests.get(url, params=params, timeout=35)
        resp.raise_for_status()
        return resp.json().get("result", [])
    except Exception as e:
        print(f"Get updates failed: {e}")
        return []


def send_message(bot_token: str, chat_id: str, text: str):
    """Send a message via Telegram."""
    import requests
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Send message failed: {e}")
        return False


def main():
    """Main command listener loop."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "8280876077")
    
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not set")
        print("Set it with: export TELEGRAM_BOT_TOKEN='your_token'")
        sys.exit(1)
    
    print("🤖 Pythia Bot Commands — Starting...")
    print("Commands: /fed_rate, /similar, /what_caused, /patterns, /correlations, /help")
    print("Press Ctrl+C to stop")
    
    offset = None
    
    try:
        while True:
            updates = get_updates(bot_token, offset)
            
            for update in updates:
                # Update offset to mark as processed
                offset = update["update_id"] + 1
                
                # Check if it's a message
                if "message" not in update:
                    continue
                
                message = update["message"]
                msg_chat_id = str(message.get("chat", {}).get("id", ""))
                
                # Only respond to authorized chat
                if msg_chat_id != chat_id:
                    continue
                
                # Check for text
                text = message.get("text", "")
                if not text:
                    continue
                
                # Check if it's a command
                if not text.startswith("/"):
                    continue
                
                # Parse command and args
                parts = text.split(maxsplit=1)
                command = parts[0]
                args = parts[1] if len(parts) > 1 else ""
                
                print(f"Command received: {command} {args[:50]}")
                
                # Handle the command
                response = handle_telegram_command(text)
                
                # Send response
                if response:
                    send_message(bot_token, chat_id, response)
            
            # Small delay to avoid hammering the API
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Bot commands stopped.")


if __name__ == "__main__":
    main()
