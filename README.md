# Hyderabad Gold Rate Teller

A small, honest pipeline that fetches the daily **22K and 24K gold rates
for Hyderabad, India** from
[Goodreturns](https://www.goodreturns.in/gold-rates/hyderabad.html), stores
history for both purities, calculates day-over-day change independently
for each, and publishes it two ways:

- **Telegram** — a daily message to your phone.
- **A mobile-first website** — hosted free on GitHub Pages, updated
  automatically every day, no manual steps once set up.

**Source: Goodreturns only.** This project intentionally does not use IBJA,
MCX, Malabar Gold, Tanishq, Kalyan, Joyalukkas, or generic "India gold rate"
sources. It is not an official government or IBJA rate — it is Goodreturns'
published retail gold rate for Hyderabad.

If Goodreturns is unreachable or its page structure changes enough that the
22K rate can't be confidently identified, the pipeline **fails loudly and
changes nothing** — it never invents a rate, and it never overwrites the
last known-good published data with a guess.

## Project overview / architecture

```
Goodreturns (website)
        │  HTTP GET + BeautifulSoup parse (no JS execution needed)
        ▼
app/scraper.py            -- fetch + parse, raises on failure, never fabricates
        │
        ├─────────────────────────────┐
        ▼                              ▼
app/main.py (run.py)          scripts/update_gold_rate_data.py
  - console output               - reads previous rate from web/data/gold_rates.json
  - local SQLite history         - writes web/data/gold_rates.json (source of truth
    (gold_rates.db,                 for the public site's history)
    local machine only)            - also updates the local SQLite db (best-effort)
  - Telegram notification        - sends Telegram notification
        │                              │
        │                              ▼
        │                     Git commit + push (GitHub Actions, daily)
        │                              │
        │                              ▼
        │                     GitHub Pages deployment (GitHub Actions)
        │                              │
        ▼                              ▼
  Your phone (Telegram)        https://<username>.github.io/hyderabad-gold-rate-teller/
                                (a phone browser, bookmarked)
```

There are two entry points that both reuse the same scraper/calculator/
telegram code, for two different jobs:

- **`run.py`** — the original CLI tool (Phase 1). Prints the rate, stores it
  in local SQLite, sends Telegram. Unchanged by Phase 2.
- **`scripts/update_gold_rate_data.py`** — the pipeline used by GitHub
  Actions. Fetches the current rate **and** Goodreturns' own "Gold Rate in
  Hyderabad for Last 10 Days (1 gram)" table in the same request, merges
  both into the *previously committed* `web/data/gold_rates.json` (because
  GitHub Actions checks out a fresh copy of the repo every run — nothing
  persists on the runner between runs, so the committed JSON file itself is
  the durable historical record for the public site), computes change
  against the most recent *actually available* previous date (never an
  assumed "yesterday"), writes the updated JSON, and sends Telegram. It
  also updates local SQLite for parity, but that's incidental on a CI
  runner.

```
hyderabad-gold-rate-teller/
│
├── app/
│   ├── scraper.py          # HTTP fetch + BeautifulSoup parsing of Goodreturns
│   ├── calculator.py       # price-for-N-grams, change %, INR formatting
│   ├── database.py         # SQLite storage (local history, insert/upsert, queries)
│   ├── telegram_bot.py     # Telegram Bot API message builder + sender
│   ├── data_export.py      # builds/validates/writes web/data/gold_rates.json
│   └── main.py             # CLI pipeline: fetch -> store -> compare -> notify
│
├── scripts/
│   └── update_gold_rate_data.py   # pipeline used by the daily GitHub Actions job
│
├── web/                     # static site published via GitHub Pages
│   ├── index.html
│   ├── style.css
│   ├── app.js               # fetches ./data/gold_rates.json, renders dashboard + chart
│   └── data/
│       └── gold_rates.json  # generated/updated file; this is what the site reads
│
├── .github/workflows/
│   ├── daily-gold-rate.yml  # scheduled: fetch, validate, update JSON, commit, notify
│   └── deploy-pages.yml     # deploys web/ to GitHub Pages
│
├── tests/
│   ├── fixtures/hyderabad_live_sample.html   # real saved page, for tests
│   ├── test_scraper.py
│   ├── test_calculator.py
│   ├── test_telegram_bot.py
│   └── test_data_export.py
│
├── run.py                   # `python run.py` — manual/local CLI entry point
├── requirements.txt
├── .env.example
└── gold_rates.db            # created on first local run (not committed)
```

**Why HTTP + BeautifulSoup and not Playwright/a browser?** The Goodreturns
Hyderabad page server-renders the gold rate directly into the initial HTML
response (`<span id="22K-price">₹14,015</span>` inside a price card, with
the date in `<span id="metal-price-date">`). This was verified by fetching
the live page and inspecting the raw response before writing any parsing
code — no JavaScript execution is required.

**Why no frontend framework?** `web/` is plain HTML/CSS/JS with zero
build step and zero external script dependency — the history chart is a
small hand-drawn inline SVG rather than pulling in a charting library, which
keeps the page tiny and fast on mobile data connections.

## Requirements

- Windows 10/11 (for local development) — the deployed pipeline itself runs
  on GitHub's Linux runners, no Windows machine required to keep it going.
- Python 3.14 locally (`requests`, `beautifulsoup4`, `python-dotenv` all
  install cleanly on it). GitHub Actions uses Python 3.13, which is more
  broadly pre-cached on hosted runners; both versions are tested against
  the same test suite.
- A GitHub account and a repository (this one:
  [msuryavardhan/hyderabad-gold-rate-teller](https://github.com/msuryavardhan/hyderabad-gold-rate-teller)).
- (Optional) A Telegram bot + chat ID, for notifications.

## Local setup

```bash
cd F:\Gold_Rate_Teller
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

- `py -3.14 -m venv .venv` creates an isolated virtual environment.
- `.venv\Scripts\activate` activates it (PowerShell: `.venv\Scripts\Activate.ps1`).
- `pip install -r requirements.txt` installs exactly `requests`,
  `beautifulsoup4`, and `python-dotenv` — nothing else.

### Configuration (`.env`)

```bash
copy .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Only for Telegram notifications | Token from @BotFather |
| `TELEGRAM_CHAT_ID` | Only for Telegram notifications | Numeric chat ID to send the message to |

`.env` is listed in `.gitignore` and must never be committed. Without it,
the app still fetches/prints/stores/publishes the rate — it just logs a
warning and skips the Telegram step.

## Running locally

Console + local SQLite history (original Phase 1 behaviour, unchanged):

```bash
python run.py
```

Full Phase 2 pipeline — the same thing GitHub Actions runs daily, i.e. also
updates `web/data/gold_rates.json`:

```bash
python scripts/update_gold_rate_data.py
```

### Viewing the dashboard locally

The frontend must be served over HTTP (not opened as a `file://` URL,
since `fetch()` for the JSON file won't work from disk in most browsers):

```bash
python -m http.server 8000 --directory web
```

Then open **http://localhost:8000** in a browser. Run
`python scripts/update_gold_rate_data.py` first (or at least once) so
`web/data/gold_rates.json` exists with real data.

## Running tests

```bash
python -m unittest discover -s tests -v
```

96 tests, all passing, using Python's built-in `unittest` (no extra test
framework installed). Covers:

- Parsing the real, saved Goodreturns HTML and price-string edge cases,
  for **both 22K and 24K** independently (each has its own price card and
  its own column in the "Last 10 Days" table -- column position is found
  via the table header, not hardcoded)
- 8g/10g calculation and change % / absolute calculation, incl. "no
  previous rate", for both purities, with an explicit check that 22K and
  24K changes are never conflated
- Missing 22K/24K card / malformed price / completely invalid HTML
- 24K unavailable-but-22K-still-succeeds handling (never fabricates a 24K
  value, never fails the whole scrape over it)
- Telegram message formatting, including the additive 24K section
- **JSON export**: valid payload shape for both purities, non-positive/
  invalid rate rejected (prevents ever publishing bad data), history
  upsert/sort/trim/merge (never deletes an already-collected date),
  finding the correct previous rate for change calculation, corrupt/
  missing existing-file handling, and atomic write behaviour

## GitHub setup

This project is already pushed to
[github.com/msuryavardhan/hyderabad-gold-rate-teller](https://github.com/msuryavardhan/hyderabad-gold-rate-teller).
To do this yourself on a new repo:

1. Create an empty repository on GitHub (no README/license/gitignore —
   this project already has its own).
2. `git remote add origin https://github.com/<you>/<repo>.git`
3. `git push -u origin master`

## GitHub Secrets (for Telegram)

The daily workflow reads `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from
**GitHub Actions Secrets** — never from a file in the repo.

1. On GitHub, go to the repository → **Settings** → **Secrets and
   variables** → **Actions**.
2. Click **New repository secret**.
3. Name: `TELEGRAM_BOT_TOKEN`. Value: your bot's token (see below for how
   to obtain it). Save.
4. Repeat for `TELEGRAM_CHAT_ID`.

*(This README never shows or asks for the actual secret values — only
where to obtain and where to paste them.)*

### Creating a Telegram bot

1. Open Telegram and message **@BotFather**.
2. Send `/newbot` and follow the prompts (name + a username ending in `bot`).
3. BotFather replies with a token — this is your `TELEGRAM_BOT_TOKEN`.
4. Send your new bot at least one message (e.g. "hi") — bots can't message
   a user first.

### Getting your Telegram chat ID

1. After messaging your bot, open in a browser (replace `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
2. Look for `"chat":{"id": 123456789, ...}` — that number is your
   `TELEGRAM_CHAT_ID`.
3. If the response is empty, message your bot again and refresh.

If the secrets are not set, the pipeline still runs and still publishes the
website — it just logs a warning and skips the Telegram step.

## GitHub Pages

The site deploys via the `deploy-pages.yml` workflow (GitHub's official
"deploy from Actions" method), not from a branch. **One manual, one-time
setting** is required because a repository's Pages source can't be flipped
to "GitHub Actions" through a normal git push — only through repository
Settings:

> **On GitHub: Settings → Pages → Build and deployment → Source → select
> "GitHub Actions".** That's the only click needed. After that, every
> future deploy happens automatically.

Once that's set, the site is served from the `web/` folder at:

**https://msuryavardhan.github.io/hyderabad-gold-rate-teller/**

(the username is taken from this repository's own GitHub path — replace it
if you fork this under a different account).

## GitHub Actions (daily schedule)

`.github/workflows/daily-gold-rate.yml` runs on a cron schedule:

```yaml
schedule:
  - cron: "30 3 * * *"
```

GitHub Actions cron always runs in **UTC**. India Standard Time is a fixed
UTC+5:30 offset (no daylight saving), so:

**09:00 IST = 03:30 UTC** → `cron: "30 3 * * *"`.

You can also trigger it manually any time from the **Actions** tab →
"Daily Gold Rate Update" → **Run workflow** (useful for testing without
waiting for 9 AM).

Each run:

1. Checks out the repo, sets up Python 3.13, installs dependencies.
2. Runs the existing test suite.
3. Runs `scripts/update_gold_rate_data.py`, which fetches Goodreturns,
   validates today's 22K rate **and** its "Last 10 Days" historical table,
   merges both into the existing history, and writes
   `web/data/gold_rates.json`.
4. **If step 3 fails for any reason** (no internet, Goodreturns down, HTML
   structure changed, today's rate or the historical table can't be
   confidently parsed) **the job stops there** — no commit, no push, no
   fake data or fake history, and the site keeps showing the last
   successfully published rate.
5. If step 3 succeeds, commits and pushes `web/data/gold_rates.json` only
   if it actually changed.
6. That push (or a manual `web/` edit) triggers `deploy-pages.yml`, which
   republishes the site.

## Mobile access

Once GitHub Pages is enabled (see above):

1. On your phone, open **https://msuryavardhan.github.io/hyderabad-gold-rate-teller/**
   in any browser (Safari on iPhone, Chrome on Android).
2. **iPhone (Safari):** tap the Share icon → "Add to Home Screen" for an
   app-like icon, or just add it to Bookmarks/Favorites.
3. **Android (Chrome):** tap the ⋮ menu → "Add to Home screen", or "Add
   bookmark" from the same menu.
4. The page re-fetches its data every time you open it (with cache-busting,
   so you always see the latest published rate, not a stale cached copy).

## Failure behavior

If Goodreturns is unreachable, blocks the request, or changes its page
structure so the 22K rate can't be confidently identified:

- **Locally (`run.py` / `scripts/update_gold_rate_data.py`):** the script
  prints/logs a clear error and exits with a non-zero status. No database
  write, no JSON write, no Telegram message, no fabricated rate.
- **GitHub Actions:** the "Fetch..." step fails, the job is marked failed
  (visible in the Actions tab and, if you've enabled it, GitHub's own
  failed-workflow email), and every later step (commit/push/deploy) is
  skipped automatically.
- **The website:** keeps showing the last successfully published rate and
  its real `updated_at` timestamp — it will never silently show a wrong or
  invented number, and a stale-but-real rate is always distinguishable
  because the dashboard displays the actual last-fetched date/time.

## Windows Task Scheduler (optional local alternative)

You don't need this if GitHub Actions is set up — it's only useful if you
also want a local console run / local Telegram ping independent of GitHub.

1. Open **Task Scheduler** → **Create Task...**.
2. **General**: name it "Hyderabad Gold Rate Teller"; optionally "Run
   whether user is logged on or not".
3. **Triggers** → New → Daily, start time **09:00:00**.
4. **Actions** → New:
   - Program/script: `F:\Gold_Rate_Teller\.venv\Scripts\python.exe`
   - Add arguments: `run.py`
   - Start in: `F:\Gold_Rate_Teller`
5. **Settings**: check "Run task as soon as possible after a scheduled
   start is missed".

This still only runs while your PC is on — which is exactly why the
GitHub Actions pipeline above exists as the primary, always-on path.

## Troubleshooting

- **"Could not connect to ... (no internet or host unreachable)"** — check
  network connectivity; nothing is fabricated.
- **"No gold price cards found"** / **"none matched a 22K label"** —
  Goodreturns changed their HTML; re-inspect the live page and update the
  selectors in `app/scraper.py::parse_hyderabad_22k`.
- **"Multiple conflicting 22K rate values found"** — the page had
  disagreeing 22K prices; the app refuses to guess.
- **Telegram notification not sent** — check the secrets/`.env` values, and
  that you've messaged your bot at least once.
- **Dashboard shows "Couldn't load the latest rate"** — usually means
  `web/data/gold_rates.json` doesn't exist yet (run
  `scripts/update_gold_rate_data.py` once) or the page is being opened via
  `file://` instead of a local HTTP server.
- **Site not updating after a workflow run** — confirm GitHub Pages'
  source is set to "GitHub Actions" (Settings → Pages); check the
  "Deploy Pages" workflow run in the Actions tab for errors.
- **`ModuleNotFoundError`** — activate the virtual environment
  (`.venv\Scripts\activate`) or call `.venv\Scripts\python.exe` directly.

## Limitations

- Goodreturns is a third-party website; its HTML structure can change at
  any time without notice, which may require updating `app/scraper.py`.
- Goodreturns does not publish an intraday "last updated" time — only a
  date — so "Updated"/"Last fetched" reflects this pipeline's own fetch
  time.
- This is **not** an official/IBJA/government gold rate.
- On its very first successful run, the pipeline also reads Goodreturns'
  own "Gold Rate in Hyderabad for Last 10 Days (1 gram)" table, so
  `web/data/gold_rates.json` typically starts with up to ~10 real days of
  history immediately, not just one. From then on, each daily run extends
  it further and never deletes an earlier date — but nothing before
  whatever Goodreturns' own 10-day table showed on first run is backfilled
  or fabricated.
- GitHub Actions' free-tier scheduled workflows can occasionally run a few
  minutes late during high platform load; this is a GitHub-side behaviour,
  not something this project controls.

## Attribution

Gold rate data: [Goodreturns](https://www.goodreturns.in/gold-rates/hyderabad.html).
This project is not affiliated with or endorsed by Goodreturns.
