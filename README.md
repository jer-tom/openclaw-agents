# OpenClaw Agents — Multi-Agent AI Platform

A production multi-agent system built on [OpenClaw](https://openclaw.ai), running 3 autonomous agents with 5 scheduled cron jobs and 4 integrations. Deployed on a VPS inside Docker, with a local Mac node for browser automation.

## What This Does

I built a personal AI operations layer that handles fitness coaching, expense tracking, executive assistance, grocery ordering, and news curation — all running autonomously on scheduled cron jobs, communicating via WhatsApp.

```
Mac (local node)                       VPS (remote gateway)
─────────────────                      ──────────────────────────────
openclaw node run  ───SSH tunnel───►   Docker: openclaw container
Chrome extension   (relay :18792)      Port 18789 (gateway)
                                       ├── agents/main/  (Jerry's assistant)
                                       ├── agents/ca/    (Chartered Accountant)
                                       └── agents/ea/    (Executive Assistant)
```

## Agents

### Main Agent — Fitness Coach + News Curator
- **Daily fitness debrief** (6:30 AM IST): Pulls Strava activities, Apple Watch health metrics, and Swiggy food orders via Gmail. Analyzes HR zones, pace progression, and nutrition. Sends a Coach Matt Bennet-style report via WhatsApp.
- **Weekly fitness recap** (Sun 11:00 AM): Two-week comparison with zone distribution, strength progression, and weight trend analysis.
- **News digest** (10:00 AM): Fetches RSS feeds, scans HTML pages, and searches X/Twitter for AI/agents/marketing updates. Filters by relevance score. Friday edition is a deep-dive.
- **Blinkit grocery ordering**: Playwright-based browser automation for headless grocery ordering with cart management and UPI payment.

### CA Agent — Chartered Accountant
- **Daily expense processing** (6:30 AM, silent): Searches Gmail for bank transaction emails (IDFC, ICICI, Axis Bank), parses amounts/merchants via bash script with LLM fallback, categorizes, and appends to monthly CSV.
- **Bi-weekly expense summary** (Mon + Sat 9:30 AM): Generates category breakdowns, top merchants, flags anomalies (>₹10K, reversals, late-night), sends formatted WhatsApp report.
- **Anti-hallucination protocol**: Every number must come from the email text. Agent must quote the source line before recording. Never fabricates transactions.

### EA Agent — Reshma (Executive Assistant)
- **Weekly deadline nagger** (Thu 1:00 PM): Reads task list, calculates days until deadlines, sends urgency-matched WhatsApp reminders with Marvel and Telugu movie quotes.
- **Escalation protocol**: Overdue tasks get escalated to the main agent, which notifies a secondary contact.
- **Travel planning**: Builds complete itineraries with flights, hotels, transport, and budget estimates.

## Cron Jobs

| Job | Schedule | Agent | What It Does |
|-----|----------|-------|-------------|
| Fitness coach debrief | Daily 6:30 AM IST | main | Strava + health + food → WhatsApp report |
| Expense processing | Daily 6:30 AM IST | ca | Gmail → parse → categorize → CSV |
| Weekly fitness recap | Sun 11:00 AM IST | main | 2-week comparison → WhatsApp |
| Expense summary | Mon+Sat 9:30 AM IST | ca | CSV → category totals → WhatsApp |
| Deadline nagger | Thu 1:00 PM IST | ea | tasks.json → urgency reminders → WhatsApp |

## Key Scripts

### `agents/main/coach/coach_data.py` (450+ lines)
Preprocessing pipeline that:
1. Fetches Strava activities with detailed splits and HR zone analysis
2. Reads Apple Watch CSVs (steps, HRV, RHR, weight, VO2max)
3. Parses Swiggy food order emails from Gmail (extracts items, prices, late-night flags)
4. Outputs compact JSON for the LLM to analyze
5. Handles Strava OAuth token refresh automatically

### `agents/ca/scripts/parse-transaction.sh`
Bash script that parses bank email bodies from 3 Indian banks:
- IDFC FIRST Bank credit card (debit + reversal)
- ICICI Bank credit card
- Axis Bank account (debit + credit via UPI)

Outputs pipe-delimited fields. Exits 1 on unparseable emails so the LLM agent can fall back to manual extraction.

### `agents/main/skills/blinkit/scripts/blinkit.js` (550 lines)
Playwright headless browser automation for Blinkit grocery delivery:
- Session management with cookie persistence
- Product search and cart management
- Multi-item order preparation from JSON grocery list
- UPI payment flow (triggers collect request)
- Anti-bot detection bypass (webdriver flag hiding, geolocation spoofing)

### `agents/main/skills/strava/scripts/strava_request.py`
Strava API client with automatic OAuth token refresh:
- Checks token expiry before each request
- Refreshes on 401 responses (handles token rotation)
- Persists updated tokens to disk with secure permissions

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Platform | [OpenClaw](https://openclaw.ai) (agent orchestration) |
| LLM | Grok 4.1 Fast (primary), Claude Sonnet 4.5 / GPT-5.2 (fallback) |
| Infrastructure | Docker on Ubuntu 24.04 VPS, SSH tunnel to Mac |
| Messaging | WhatsApp (via OpenClaw channel plugin) |
| Fitness data | Strava API + Apple Watch CSVs |
| Email | Gmail via `gog` CLI (Google Workspace CLI) |
| Browser automation | Playwright (headless Chromium) |
| Grocery delivery | Blinkit (via Playwright) |
| Scheduling | OpenClaw cron (5 jobs, IST timezone) |
| Languages | Python, Bash, JavaScript/Node.js |

## Integrations

- **WhatsApp**: Primary delivery channel for all reports and reminders. Agents use the OpenClaw message tool to send formatted messages. DMs are routed to specific agents based on sender phone number.
- **Strava**: OAuth2 with automatic token refresh. Fetches activities, detailed splits with per-km HR zones, and historical data for progression tracking.
- **Gmail**: Transaction email parsing for expense tracking, Swiggy order extraction for nutrition analysis. Uses `gog` CLI with encrypted OAuth tokens.
- **Blinkit**: Headless Playwright automation with session persistence, anti-bot detection bypass, and full ordering flow including UPI payment.

## Repo Structure

```
├── agents/
│   ├── main/
│   │   ├── coach/           # Fitness coaching scripts
│   │   │   ├── coach_data.py    # 450-line Strava + health + food preprocessor
│   │   │   ├── strava_coach.py  # Earlier version of coach report
│   │   │   ├── log_weight.py    # Weight logging from chat
│   │   │   └── WEIGHT.md
│   │   └── skills/
│   │       ├── strava/      # Strava API skill + token management
│   │       ├── gog/         # Gmail skill definition
│   │       └── blinkit/     # Grocery ordering (Playwright automation)
│   ├── ca/
│   │   ├── skills/expenses/ # Expense tracking workflow
│   │   ├── scripts/         # Bank email parser (IDFC/ICICI/Axis)
│   │   └── persona/         # CA agent personality + anti-hallucination rules
│   └── ea/
│       └── persona/         # Reshma EA persona (Marvel/Telugu quotes)
├── cron/
│   ├── jobs.json            # All 5 cron job definitions with full prompts
│   └── news-digest-job.json # News curator job (exported)
├── docs/
│   ├── vps-setup-guide.md   # Full VPS setup from scratch
│   └── browser-relay-setup.md # Chrome extension relay implementation
└── config/
    ├── docker-compose.yml
    ├── env.example          # Environment variable template
    └── openclaw.example.json # Gateway configuration template
```

## Setup

See [`docs/vps-setup-guide.md`](docs/vps-setup-guide.md) for the complete setup guide including:
- VPS provisioning and Docker setup
- Agent configuration and workspace creation
- Integration setup (WhatsApp, Gmail, Strava)
- Cron job creation
- Local Mac node connection
- 15 documented issues and their solutions

## Lessons Learned

**Prompt engineering is system design.** Each cron job prompt is essentially a program — specifying exact tool calls, argument names, output formats, and error handling. Getting the WhatsApp message tool arguments right (`target` not `topic`) took multiple iterations.

**LLM agents need anti-hallucination guardrails.** The CA agent's expense tracking required explicit rules: "quote the source line before recording," "process one email at a time," "never fabricate transactions." Without these, the agent would confidently invent transaction amounts.

**Gmail thread expansion is a silent failure mode.** Gmail groups transaction emails into threads. Without explicit thread expansion in the cron prompt, the agent silently missed transactions. The fix was a prompt-level instruction, not a code change.

**Token management is the unglamorous backbone.** Strava tokens expire every 6 hours. Gmail OAuth tokens expire in 7 days if the GCP project is in "Testing" mode. Both failures are silent — the cron job runs, the API call fails, and no report gets sent. Automatic token refresh and persistent storage solved this.

**Browser automation is fragile but powerful.** The Blinkit grocery script handles anti-bot detection, session persistence, and dynamic page elements. It works — until the site redesigns. The Chrome extension relay for remote browser control was the most complex piece (3-file patch, SSH tunnel, WebSocket auth).

---

Built by [Jerry](https://github.com/jer-tom) using [OpenClaw](https://openclaw.ai).
