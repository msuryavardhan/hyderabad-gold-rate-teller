"""Entry point: `python run.py`

Fetches today's Hyderabad 22K gold rate from Goodreturns, prints it,
stores it, compares it with the previous rate, and sends a Telegram
notification (if TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are configured).
"""

import sys

from app.main import run, setup_logging

if __name__ == "__main__":
    setup_logging()
    sys.exit(run())
