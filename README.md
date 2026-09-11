# Hyderabad Gold Rate Teller

Fetches the daily **22K gold rate for Hyderabad, India** from
[Goodreturns](https://www.goodreturns.in/gold-rates/hyderabad.html), stores
history in SQLite, calculates day-over-day change, and optionally sends a
Telegram notification.

**Source: Goodreturns only.** This project intentionally does not use IBJA,
MCX, Malabar Gold, Tanishq, Kalyan, Joyalukkas, or generic "India gold rate"
sources. It is not an official government or IBJA rate — it is Goodreturns'
published retail gold rate for Hyderabad.

## What it does

1. Downloads `https://www.goodreturns.in/gold-rates/hyderabad.html`.
2. Parses the 22K/22-carat gold price card (rupees per gram) and the date
   shown on the page.
3. Prints a formatted rate summary to the console.
4. Stores the rate in a local SQLite database (`gold_rates.db`).
5. Compares today's rate with the most recently stored rate and computes the
   absolute and percentage change.
6. Optionally sends a Telegram message with the rate, 8g/10g equivalents,
   and the change.

If the website cannot be reached, or its HTML structure has changed enough
that the 22K rate can't be confidently identified, the app **fails loudly**
and prints/logs the reason — it never invents or reuses a fake rate.

## Architecture

```
hyderabad-gold-rate-teller/
│
├── app/
│   ├── scraper.py       # HTTP fetch + BeautifulSoup parsing of Goodreturns
│   ├── calculator.py    # price-for-N-grams, change %, INR formatting
│   ├── database.py      # SQLite storage (insert/upsert, history queries)
│   ├── telegram_bot.py  # Telegram Bot API message builder + sender
│   └── main.py          # orchestrates fetch -> store -> compare -> notify
│
├── tests/
│   ├── fixtures/hyderabad_live_sample.html   # real saved page, for tests
│   ├── test_scraper.py
│   ├── test_calculator.py
│   └── test_telegram_bot.py
│
├── run.py               # `python run.py` entry point
├── requirements.txt
├── .env.example
└── gold_rates.db        # created on first run (not committed)
```

**Why HTTP + BeautifulSoup and not Playwright?** The Goodreturns Hyderabad
page server-renders the gold rate directly into the initial HTML response
(`<span id="22K-price">₹14,015</span>` inside a price card, with the date in
`<span id="metal-price-date">`). This was verified by fetching the live page
and inspecting the raw response before writing any parsing code — no
JavaScript execution is required, so a Playwright/browser dependency would
be unnecessary weight.

The parser does not hardcode "read whatever is inside `id=22K-price`". It
scans each price card, reads its label text, and only accepts a value whose
label mentions "22K" / "22 Carat" / "22 Karat" — so a reordering of cards or
a change in `id` naming does not silently break extraction. If Goodreturns
changes its markup enough that no 22K card can be identified, or if 22K
appears with conflicting values, the scraper raises `GoldRateScraperError`
instead of guessing.

## Requirements

- Windows 10/11
- Python 3.14 (this project was built and tested against 3.14.3; `requests`,
  `beautifulsoup4`, and `python-dotenv` all install cleanly on it, so there
  was no need to fall back to 3.13)
- Internet access to reach goodreturns.in
- (Optional) A Telegram bot + chat ID, for notifications

## Installation

```bash
cd F:\Gold_Rate_Teller
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

- `py -3.14 -m venv .venv` creates an isolated virtual environment so this
  project's packages don't affect your system Python.
- `.venv\Scripts\activate` activates it in your current shell (PowerShell:
  you may need `.venv\Scripts\Activate.ps1`).
- `pip install -r requirements.txt` installs `requests`, `beautifulsoup4`,
  and `python-dotenv` — nothing else.

## Configuration (`.env`)

Copy the example file and fill in your own values:

```bash
copy .env.example .env
```

`.env` variables:

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Only for Telegram notifications | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | Only for Telegram notifications | Numeric chat ID to send the message to |

`.env` is listed in `.gitignore` and must never be committed. If Telegram
variables are missing, the app still fetches, prints, and stores the rate —
it just logs a warning and skips the notification.

### Creating a Telegram bot

1. Open Telegram and message **@BotFather**.
2. Send `/newbot` and follow the prompts (choose a name and a username
   ending in `bot`).
3. BotFather replies with a token like `123456789:AAExampleTokenHere` — put
   this in `.env` as `TELEGRAM_BOT_TOKEN`.
4. Send your new bot at least one message (e.g. "hi") so it can message you
   back — Telegram bots can't message a user first.

### Getting your Telegram chat ID

1. After messaging your bot, open in a browser (replace `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
2. Look for `"chat":{"id": 123456789, ...}` in the JSON response — that
   number is your `TELEGRAM_CHAT_ID`.
3. If the response is empty, send your bot another message and refresh.

## Running manually

```bash
python run.py
```

Example output:

```
========================================
HYDERABAD GOLD RATE TELLER
Source       : Goodreturns
City         : Hyderabad
Purity       : 22K
Rate / gram  : ₹14,015
Rate / 8g    : ₹1,12,120
Rate / 10g   : ₹1,40,150
Date         : 11 September 2026
Updated      : 11:02
========================================
Change:
-₹85 / gram (-0.60%)
```

("Updated" is the local time this program fetched the page — Goodreturns
does not publish an intraday timestamp, only a date, so this is our own
fetch time, not a Goodreturns-confirmed update time.)

On the very first run there is no prior stored rate, so the output shows:

```
Change: Not available
```

## Example Telegram message

```
🪙 HYDERABAD GOLD RATE
22K / 916 Gold
₹14,015 / gram
8 grams: ₹1,12,120
10 grams: ₹1,40,150
Change:
-₹85 / gram (-0.60%)
📅 11 September 2026
🕘 Updated: 11:02
Source: Goodreturns
https://www.goodreturns.in/gold-rates/hyderabad.html
```

## Running tests

```bash
python -m unittest discover -s tests -v
```

All tests use Python's built-in `unittest` (no extra test framework
installed, per the "don't install unnecessary packages" rule). They cover:

- Parsing the real, saved Goodreturns HTML (`tests/fixtures/hyderabad_live_sample.html`)
- Price-string parsing (`₹14,255`, `14,255`, `₹ 14,255`, decimals, invalid input)
- 8g/10g price calculation
- Percentage/absolute change calculation, including "no previous rate"
- Missing 22K card / malformed price / completely invalid HTML
- Telegram message formatting

## Windows Task Scheduler (daily automation)

This runs the pipeline once a day **while your PC is on**. Windows Task
Scheduler cannot run anything while the machine is off, asleep, or the user
is logged out (unless configured to run whether-logged-in-or-not, which
still requires the PC to be powered on). If you need the job to run
reliably even when your PC might be off, consider moving it to a cloud
scheduler later (e.g. GitHub Actions on a schedule, or a small always-on
VM/Raspberry Pi) — this is out of scope for this stage but the app's design
(a single `python run.py` entry point) makes it easy to move.

To schedule the daily 9:00 AM IST run:

1. Open **Task Scheduler** → **Create Task...** (not "Basic Task", so you
   get the full options).
2. **General** tab: name it "Hyderabad Gold Rate Teller"; select "Run
   whether user is logged on or not" if you want it to run even when
   locked (this will prompt for your Windows password once, to store it).
3. **Triggers** tab → **New...** → Daily, start time **09:00:00**, recur
   every 1 day.
4. **Actions** tab → **New...**:
   - Program/script: `F:\Gold_Rate_Teller\.venv\Scripts\python.exe`
   - Add arguments: `run.py`
   - Start in: `F:\Gold_Rate_Teller`
5. **Conditions** tab: uncheck "Start the task only if the computer is on
   AC power" if this is a laptop you want it to run on battery too.
6. **Settings** tab: check "Run task as soon as possible after a scheduled
   start is missed" so a missed 9 AM (PC was off) still runs later.
7. Save. Test it immediately with right-click → **Run**, then check
   `gold_rate_teller.log` and your Telegram chat.

## Troubleshooting

- **"Could not connect to ... (no internet or host unreachable)"** — check
  your network connection; the app will not fabricate a rate.
- **"No gold price cards found on the page"** or **"none matched a 22K
  label"** — Goodreturns changed their HTML. Re-inspect the live page
  (`app/scraper.py` docstring explains the current structure) and update
  the selectors in `parse_hyderabad_22k`.
- **"Multiple conflicting 22K rate values found"** — the page had more than
  one 22K price that disagreed; the app refuses to guess. Investigate the
  page manually.
- **Telegram notification not sent** — check `TELEGRAM_BOT_TOKEN` and
  `TELEGRAM_CHAT_ID` in `.env`; make sure you've messaged your bot at least
  once so it's allowed to message you back.
- **`ModuleNotFoundError`** — make sure you activated the virtual
  environment (`.venv\Scripts\activate`) or run with the venv's Python
  directly: `.venv\Scripts\python.exe run.py`.
- **Rupee sign (₹) shows as a box or `?` in an old `cmd.exe` window** — the
  app forces UTF-8 output, but very old console hosts may still not render
  the glyph; the underlying value is still correct. Windows Terminal,
  PowerShell 7, and VS Code's terminal all render it fine.

## Limitations

- Goodreturns is a third-party website; its HTML structure can change at
  any time without notice, which may require updating `app/scraper.py`.
- Goodreturns does not publish an intraday "last updated" time — only a
  date — so the "Updated" time shown is this program's own fetch time.
- This is **not** an official/IBJA/government gold rate. It reflects
  Goodreturns' published Hyderabad 22K retail rate only.
- Windows Task Scheduler only runs while the PC is powered on; see the
  automation section above for cloud-scheduler alternatives.
- The database keeps one row per (date, city, purity); re-running on the
  same day updates that row rather than creating duplicates.

## Attribution

Gold rate data: [Goodreturns](https://www.goodreturns.in/gold-rates/hyderabad.html).
This project is not affiliated with or endorsed by Goodreturns.
