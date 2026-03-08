# OpenClaw VPS Setup Guide

**Last updated:** 2026-03-07
**Purpose:** Recreate the full OpenClaw agent platform on a new VPS from scratch.

---

## Table of Contents

1. [Overview](#overview)
2. [VPS Requirements](#vps-requirements)
3. [Architecture](#architecture)
4. [Step 1: VPS Base Setup](#step-1-vps-base-setup)
5. [Step 2: Docker & OpenClaw Container](#step-2-docker--openclaw-container)
6. [Step 3: Environment Variables (.env)](#step-3-environment-variables-env)
7. [Step 4: Gateway Configuration (openclaw.json)](#step-4-gateway-configuration-openclawjson)
8. [Step 5: Agents Setup](#step-5-agents-setup)
9. [Step 6: Skills Installation](#step-6-skills-installation)
10. [Step 7: Cron Jobs](#step-7-cron-jobs)
11. [Step 8: WhatsApp Setup](#step-8-whatsapp-setup)
12. [Step 9: Gmail (gog) Setup](#step-9-gmail-gog-setup)
13. [Step 10: Strava Integration](#step-10-strava-integration)
14. [Step 11: Fitness Coach Setup](#step-11-fitness-coach-setup)
15. [Step 12: Local Mac Node Connection](#step-12-local-mac-node-connection)
16. [Step 13: Browser Relay (Optional)](#step-13-browser-relay-optional)
17. [Issues Encountered & Solutions](#issues-encountered--solutions)
18. [Maintenance & Debugging](#maintenance--debugging)
19. [File Tree Reference](#file-tree-reference)

---

## Overview

OpenClaw is an AI agent orchestration platform. This setup runs:

- **3 agents**: `main` (Jerry's assistant), `ca` (Chartered Accountant — expense tracking), `ea` (Reshma — Aditya's executive assistant)
- **5 cron jobs**: Daily fitness coach, daily expense processing, weekly fitness recap, bi-weekly expense summary, weekly deadline nagger
- **Integrations**: WhatsApp (primary), Gmail (via `gog` CLI), Strava (fitness data), Blinkit (grocery ordering via browser automation)
- **Gateway** runs on the VPS inside Docker, Mac connects as a node

---

## VPS Requirements

- **OS:** Ubuntu 24.04 LTS (tested on Noble Numbat, kernel 6.8.x)
- **RAM:** 4GB minimum (Docker image is ~6.5GB, needs room for Chromium headless)
- **Disk:** 20GB+ (Docker image ~2GB compressed, data grows with agent sessions)
- **Ports:** 62508 (Hostinger panel), 18789 (gateway, bind to 127.0.0.1 for SSH tunnel)
- **SSH access:** Root with key-based auth

---

## Architecture

```
Mac (local node "Jerry Mac")              VPS <NEW_IP> (remote gateway)
─────────────────────────────              ──────────────────────────────────────
/opt/homebrew/bin/openclaw                 Docker: openclaw-xtpo-openclaw-1
openclaw node run  ──SSH tunnel──────►     Port 18789 (gateway, LAN-bound)
                                           Port 62508 (Hostinger management)
                                           /data/.openclaw/agents/
                                           /data/.openclaw/workspace/
                                           /data/.openclaw/workspace-ca/
                                           /data/.openclaw/workspace-ea/
                                           /data/.openclaw/cron/jobs.json
```

---

## Step 1: VPS Base Setup

```bash
# SSH into new VPS
ssh root@<NEW_IP>

# Update system
apt update && apt upgrade -y

# Install Docker (if not pre-installed by Hostinger)
curl -fsSL https://get.docker.com | sh
systemctl enable docker && systemctl start docker

# Install Docker Compose plugin
apt install docker-compose-plugin -y

# Set up SSH key access (copy your Mac's public key)
# On Mac: ssh-copy-id -i ~/.ssh/id_ed25519.pub root@<NEW_IP>
```

---

## Step 2: Docker & OpenClaw Container

Create the directory structure:

```bash
mkdir -p /docker/openclaw-xtpo/data
cd /docker/openclaw-xtpo
```

Create `docker-compose.yml`:

```yaml
services:
  openclaw:
    image: "${OPENCLAW_IMAGE:?set OPENCLAW_IMAGE to a pinned tag or digest}"
    init: true
    ports:
      - "${PORT}:${PORT}"
      - "127.0.0.1:18789:18789"
    env_file:
      - .env
    restart: unless-stopped
    volumes:
      - ./data:/data
      - ./data/linuxbrew:/home/linuxbrew
      - ./server.mjs:/hostinger/server.mjs:ro
```

**Notes:**
- Port 18789 is bound to `127.0.0.1` — only accessible via SSH tunnel, not from the internet
- Pin the image to a tested tag or digest in `.env`; do not deploy from `latest`
- The `server.mjs` file is the Hostinger proxy/entrypoint that came with the image. It handles model routing, auth, and the management UI. You may need to copy it from the old VPS or extract it from the image
- The `data/linuxbrew` mount is for the Linuxbrew installation inside the container (where `gog` CLI lives)

### Getting server.mjs

The `server.mjs` file is a minified Express server provided by Hostinger. It's mounted read-only into the container. If you're using the same Hostinger OpenClaw image, it should come with the image. If not:

```bash
# Copy from old VPS before it expires
scp root@<OLD_IP>:/docker/openclaw-xtpo/server.mjs /docker/openclaw-xtpo/server.mjs
```

### Start the container

```bash
cd /docker/openclaw-xtpo
docker compose pull
docker compose up -d
```

---

## Step 3: Environment Variables (.env)

Create `/docker/openclaw-xtpo/.env`:

```bash
PORT=62508
TZ=Asia/Kolkata
OPENCLAW_GATEWAY_TOKEN=<GENERATE_NEW_TOKEN>
OPENCLAW_GATEWAY_PORT=18789
OPENAI_API_KEY=<YOUR_OPENAI_KEY>
XAI_API_KEY=<YOUR_XAI_KEY>
WHATSAPP_NUMBER=*
STRAVA_CLIENT_ID=<YOUR_STRAVA_CLIENT_ID>
STRAVA_CLIENT_SECRET=<YOUR_STRAVA_CLIENT_SECRET>
STRAVA_ACCESS_TOKEN=<YOUR_STRAVA_ACCESS_TOKEN>
STRAVA_REFRESH_TOKEN=<YOUR_STRAVA_REFRESH_TOKEN>
GOG_ACCOUNT=<your-gmail>@gmail.com
GOG_KEYRING_PASSWORD=<your-keyring-password>
```

**Generate a new gateway token:**
```bash
openssl rand -base64 24 | tr -d '/+=' | head -c 32
```

**API Keys needed:**
- `OPENAI_API_KEY` — For ChatGPT models (fallback)
- `XAI_API_KEY` — For Grok models (primary model)
- Anthropic and Google keys are configured via the Hostinger panel or gateway config, not .env
- `STRAVA_*` — From your Strava API app (see Step 10)

---

## Step 4: Gateway Configuration (openclaw.json)

After the container is running, configure the gateway. Run all commands as `-u node` inside the container.

```bash
# Shorthand for running commands
alias oc='docker exec -u node openclaw-xtpo-openclaw-1 openclaw'
```

The full `openclaw.json` lives at `/data/.openclaw/openclaw.json` inside the container. Key sections:

### Model Configuration

```bash
# Primary model for all agents
oc config set agents.defaults.model.primary "Grok 4.1 Fast"
oc config set agents.defaults.model.fallbacks '["ChatGPT 5.2", "Claude Sonnet 4.5", "Gemini 3 Flash Preview"]'
```

Model aliases (map provider/model IDs to friendly names):
```json
{
  "agents": {
    "defaults": {
      "models": {
        "xai/grok-4-1-fast": { "alias": "Grok 4.1 Fast" },
        "anthropic/claude-sonnet-4-5": { "alias": "Claude Sonnet 4.5" },
        "openai/gpt-5.2": { "alias": "ChatGPT 5.2" },
        "google/gemini-3-flash-preview": { "alias": "Gemini 3 Flash Preview" }
      },
      "maxConcurrent": 4,
      "subagents": { "maxConcurrent": 8 }
    }
  }
}
```

**Note:** Model names will change. Update aliases to match whatever models are current when you set this up.

### Gateway Auth

```bash
oc config set gateway.port 18789
oc config set gateway.mode local
oc config set gateway.bind lan
oc config set gateway.auth.mode token
oc config set gateway.auth.token "<YOUR_GATEWAY_TOKEN>"
oc config set gateway.controlUi.allowInsecureAuth false
oc config set gateway.controlUi.dangerouslyAllowHostHeaderOriginFallback false
oc config set gateway.trustedProxies '["172.18.0.0/16", "127.0.0.1/32"]'
```

### Browser (headless Chromium for Blinkit skill)

```bash
oc config set browser.headless true
oc config set browser.noSandbox false
```

Only flip `browser.noSandbox` to `true` if Chromium cannot start in your container with sandboxing enabled.

### WhatsApp Channel

```bash
oc config set channels.whatsapp.enabled true
oc config set channels.whatsapp.dmPolicy pairing
oc config set channels.whatsapp.allowFrom '["+91XXXXXXXXXX"]'
oc config set channels.whatsapp.groupPolicy allowlist
oc config set channels.whatsapp.ackReaction.emoji "👀"
oc config set channels.whatsapp.ackReaction.direct true
oc config set channels.whatsapp.ackReaction.group never
oc config set channels.whatsapp.debounceMs 0
oc config set channels.whatsapp.mediaMaxMb 50
```

### Messages

```bash
oc config set messages.ackReactionScope group-mentions
```

### Plugins

```bash
oc config set plugins.entries.whatsapp.enabled true
oc config set plugins.entries.discord.enabled true
oc config set plugins.entries.telegram.enabled true
oc config set plugins.entries.slack.enabled true
oc config set plugins.entries.nostr.enabled true
oc config set plugins.entries.googlechat.enabled true
oc config set plugins.entries.imessage.enabled false
oc config set plugins.entries.signal.enabled false
```

---

## Step 5: Agents Setup

### Agent Definitions

Three agents are defined in `openclaw.json` under `agents.list`:

```json
{
  "agents": {
    "list": [
      {
        "id": "main",
        "model": {
          "primary": "xai/grok-4-1-fast",
          "fallbacks": ["xai/grok-4-1-fast"]
        },
        "subagents": { "allowAgents": ["*"] }
      },
      {
        "id": "ca",
        "name": "ca",
        "workspace": "/data/.openclaw/workspace-ca",
        "agentDir": "/data/.openclaw/agents/ca/agent",
        "model": "xai/grok-4-1-fast"
      },
      {
        "id": "ea",
        "name": "ea",
        "workspace": "/data/.openclaw/workspace-ea",
        "agentDir": "/data/.openclaw/agents/ea/agent",
        "model": "xai/grok-4-1-fast",
        "identity": { "name": "Reshma", "emoji": "📋" }
      }
    ]
  }
}
```

### WhatsApp Bindings (route DMs to specific agents)

```json
{
  "bindings": [
    {
      "agentId": "ca",
      "match": { "channel": "whatsapp", "peer": { "kind": "direct", "id": "+91XXXXXXXXXX" } }
    },
    {
      "agentId": "ea",
      "match": { "channel": "whatsapp", "peer": { "kind": "direct", "id": "+91XXXXXXXXXX" } }
    }
  ]
}
```

This routes WhatsApp DMs from Shephali (+91XXXXXXXXXX) to the CA agent and from Aditya (+91XXXXXXXXXX) to the EA agent. All other DMs go to the main agent.

### Create Workspace Directories

```bash
docker exec -u node openclaw-xtpo-openclaw-1 bash -c '
  mkdir -p /data/.openclaw/workspace/skills
  mkdir -p /data/.openclaw/workspace/coach
  mkdir -p /data/.openclaw/workspace-ca/memory
  mkdir -p /data/.openclaw/workspace-ca/skills/expenses
  mkdir -p /data/.openclaw/workspace-ca/skills/gog
  mkdir -p /data/.openclaw/workspace-ea/memory
  mkdir -p /data/.openclaw/agents/main
  mkdir -p /data/.openclaw/agents/ca/agent
  mkdir -p /data/.openclaw/agents/ea/agent
  mkdir -p /data/.openclaw/credentials
'
```

---

## Step 6: Skills Installation

### 6a. Strava Skill (main agent workspace)

Located at `/data/.openclaw/workspace/skills/strava/`

Install from ClawhHub (if available):
```bash
docker exec -u node openclaw-xtpo-openclaw-1 openclaw skills install strava
```

Or manually create the files — see [Strava Integration](#step-10-strava-integration).

### 6b. Gmail Skill (gog)

Located at `/data/.openclaw/workspace/skills/gog/SKILL.md`

Create the SKILL.md describing gog CLI commands (search, get, thread get, labels list). The `gog` binary lives at `/data/linuxbrew/.linuxbrew/bin/gog` inside the container.

### 6c. Blinkit Skill (grocery ordering)

Located at `/data/.openclaw/workspace/skills/blinkit/`

Files to create:
- `SKILL.md` — Skill definition (grocery list management + ordering flow)
- `scripts/blinkit.js` — Playwright-based headless browser automation script
- `data/grocery-list.json` — Start with `[]`

The blinkit.js script uses Playwright (bundled with OpenClaw at `/data/.npm-global/lib/node_modules/openclaw/node_modules/playwright-core`) and system Chromium at `/usr/bin/chromium`.

**Important config in blinkit.js:**
- `SESSION_PATH = '/data/.openclaw/credentials/blinkit-session.json'` — Persists login cookies
- `CHROMIUM_PATH = '/usr/bin/chromium'` — System Chromium inside Docker
- `BLINKIT_LATITUDE` / `BLINKIT_LONGITUDE` env vars — set these at runtime instead of hardcoding personal delivery coordinates in the repo
- `USER_AGENT` — Chrome UA string for anti-bot bypass

### 6d. CA Agent Skills

The CA agent has its own workspace at `/data/.openclaw/workspace-ca/` with:

**`skills/expenses/SKILL.md`** — Full expense tracking workflow:
- CSV format: `date,amount,merchant,category,card,type,email_id,notes`
- Processing pipeline: Gmail search → thread expansion → parse script → categorise → append CSV
- Reporting format for WhatsApp summaries

**`skills/gog/SKILL.md`** — Same Gmail skill definition as main agent

**`scripts/parse-transaction.sh`** — Located at `/data/.openclaw/workspace-ca/scripts/parse-transaction.sh` (NOT inside skills/expenses/). Bash script that parses bank email bodies:
- Handles: IDFC FIRST Bank CC (debit + reversal), ICICI Bank CC, Axis Bank account (debit + credit)
- Input: email body via stdin
- Output: pipe-delimited `date|amount|merchant_raw|card_last4|type|bank`
- Exit 1 if unparseable (agent falls back to manual extraction)
- Uses `grep -P` (Perl regex) — requires GNU grep (available in Docker/Linux, not macOS default)

The cron job prompt references this as `scripts/parse-transaction.sh` which resolves relative to the CA workspace root (`/data/.openclaw/workspace-ca/`).

### 6e. CA Agent Memory Files

- `memory/SOUL.md` — CA persona, anti-hallucination protocol, expense categories
- `memory/MEMORY.md` — Merchant registry (maps merchant names to categories)
- `memory/expenses-YYYY-MM.csv` — Monthly expense CSVs
- `memory/processed-emails.txt` — One email ID per line (dedup)
- `memory/processing-log.txt` — Daily processing log
- `memory/last-summary-date.txt` — Date of last WhatsApp summary sent
- `memory/summary.py` — Helper script for generating summaries

### 6f. EA Agent Files

- `memory/tasks.json` — Task list with deadlines, status, reminders_sent
- `memory/SOUL.md` — Reshma persona (Marvel/Telugu movie quotes, escalation protocol)

The EA agent's SOUL.md defines Reshma as Aditya's exec assistant who:
- Tracks deadlines in tasks.json
- Sends WhatsApp reminders with urgency-matched quotes (Marvel + Telugu cinema)
- Escalates overdue items to Jerry via the main agent

---

## Step 7: Cron Jobs

### 7a. Daily Fitness Coach (06:30 IST, daily)

**Agent:** main | **Model:** Grok 4.1 Fast | **Timeout:** 150s

Runs `python3 /data/.openclaw/workspace/coach/coach_data.py --mode daily` to get preprocessed Strava + health data, then composes a Coach Matt Bennet style debrief and sends via WhatsApp to +91XXXXXXXXXX.

### 7b. CA Daily Expense Processing (06:30 IST, daily)

**Agent:** ca | **Model:** Grok 4.1 Fast | **Timeout:** 300s

Searches Gmail for transaction emails from last 3 days, expands threads, parses each email through `parse-transaction.sh`, categorises, appends to CSV. Does NOT send WhatsApp — silent processing.

### 7c. Weekly Fitness Recap (Sun 11:00 IST)

**Agent:** main | **Model:** Grok 4.1 Fast | **Timeout:** 180s

Runs `python3 /data/.openclaw/workspace/coach/coach_data.py --mode weekly` for 2-week comparison, composes weekly recap, sends via WhatsApp.

### 7d. CA Expense Summary (Mon+Sat 09:30 IST)

**Agent:** ca | **Model:** Grok 4.1 Fast | **Timeout:** 240s | **Delivery:** announce to WhatsApp +91XXXXXXXXXX

Generates expense summary from CSV, calculates category totals, sends formatted WhatsApp summary.

### 7e. EA Deadline Nag (Thu 13:00 IST)

**Agent:** ea | **Model:** Grok 4.1 Fast | **Timeout:** 120s

Reads tasks.json, calculates days until deadlines, sends urgency-appropriate reminders with Marvel/Telugu movie quotes. Escalates overdue items to Jerry.

### Creating Cron Jobs

Use the CLI to create each job:

```bash
docker exec -u node openclaw-xtpo-openclaw-1 openclaw cron create \
  --agent main \
  --name "Daily fitness coach debrief 06:30 IST" \
  --cron "30 6 * * *" \
  --tz "Asia/Calcutta" \
  --model "Grok 4.1 Fast" \
  --timeout 150 \
  --message '<prompt text>'
```

Or directly edit `/data/.openclaw/cron/jobs.json` (restart gateway after).

The full prompt text for each job is long — see the exported `news-digest-job.json` in this repo for an example format. The prompts are included in the appendix below.

---

## Step 8: WhatsApp Setup

WhatsApp pairing must be done fresh on each new VPS:

1. Start the container
2. Check logs for the WhatsApp pairing QR code or pairing code:
   ```bash
   docker logs openclaw-xtpo-openclaw-1 --since=5m | grep -i "pair\|whatsapp\|qr"
   ```
3. Pair with your WhatsApp account (scan QR or enter code on phone)
4. Credentials are stored in `/data/.openclaw/credentials/whatsapp/`

**Important:** WhatsApp sessions can break if you pair on too many devices. You may need to unpair the old VPS first.

Files to back up from old VPS:
- `/data/.openclaw/credentials/whatsapp/` — Session data (may not transfer between VPS)
- `/data/.openclaw/credentials/whatsapp-allowFrom.json` — Allowed senders
- `/data/.openclaw/credentials/whatsapp-pairing.json` — Pairing config

---

## Step 9: Gmail (gog) Setup

The `gog` CLI is installed via Linuxbrew inside the container at `/data/linuxbrew/.linuxbrew/bin/gog`.

### Google OAuth Project

- **GCP Project:** `openclaw-gmail-487313`
- **Client secret file:** `client_secret_*.json` — stored locally in `Open Claw/Open Claw/`, never committed
- OAuth consent screen must have Gmail API scopes approved (read, send, modify)
- Gmail account: `<your-gmail>@gmail.com`

### Setup on New VPS

1. Upload the client secret file to the container:
   ```bash
   docker cp client_secret_*.json openclaw-xtpo-openclaw-1:/tmp/
   ```

2. Run the OAuth flow (needs `-it` for interactive terminal):
   ```bash
   docker exec -it -u node \
     -e GOG_ACCOUNT=<your-gmail>@gmail.com \
     -e GOG_KEYRING_PASSWORD=<your-keyring-password> \
     openclaw-xtpo-openclaw-1 \
     /data/linuxbrew/.linuxbrew/bin/gog auth login --client-secret /tmp/client_secret_*.json
   ```
   This prints a URL. Open it in your browser, authorize with `<your-gmail>@gmail.com`, paste the authorization code back.

3. Test:
   ```bash
   docker exec -u node \
     -e GOG_ACCOUNT=<your-gmail>@gmail.com \
     -e GOG_KEYRING_PASSWORD=<your-keyring-password> \
     openclaw-xtpo-openclaw-1 \
     /data/linuxbrew/.linuxbrew/bin/gog gmail search "in:inbox" --plain
   ```

4. Clean up:
   ```bash
   docker exec -u node openclaw-xtpo-openclaw-1 rm /tmp/client_secret_*.json
   ```

### Where gog Stores Its State

After login, gog saves credentials to `/data/.config/gogcli/` inside the container:
- `credentials.json` — OAuth client_id + client_secret
- `keyring/token:*` — Encrypted OAuth tokens (encrypted with `GOG_KEYRING_PASSWORD`)

### Important Notes

- **GCP "Testing" mode kills tokens after 7 days.** Push the OAuth consent screen to "Production" (even for personal use) to get persistent refresh tokens. This was a silent failure on the first setup — the CA expense job just stopped working after a week with no error in cron logs, only `gog search failed` in the agent session.
- **`docker exec` doesn't inherit .env vars.** When running gog manually via `docker exec`, you must pass `-e GOG_ACCOUNT=... -e GOG_KEYRING_PASSWORD=...` explicitly. The .env vars only reach the main openclaw process, not ad-hoc exec commands.
- If tokens expire, the CA agent's daily expense processing fails silently. Check `memory/processing-log.txt` for gaps in processing dates.

---

## Step 10: Strava Integration

### Create Strava API App

1. Go to https://www.strava.com/settings/api
2. Create an app (callback: `http://localhost`)
3. Note Client ID and Client Secret

### Get Initial OAuth Tokens

Visit (replace CLIENT_ID):
```
https://www.strava.com/oauth/authorize?client_id=CLIENT_ID&response_type=code&redirect_uri=http://localhost&approval_prompt=force&scope=activity:read_all
```

Exchange the authorization code:
```bash
curl -X POST https://www.strava.com/oauth/token \
  -d client_id=YOUR_CLIENT_ID \
  -d client_secret=YOUR_CLIENT_SECRET \
  -d code=AUTHORIZATION_CODE \
  -d grant_type=authorization_code
```

### Token Storage

Tokens are stored at `/data/.openclaw/credentials/strava-tokens.json`:
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": 1234567890,
  "client_id": "...",
  "client_secret": "..."
}
```

The `strava_request.py` script handles automatic token refresh. It:
1. Checks if `expires_at` is within 120 seconds of now
2. If so, refreshes via the Strava OAuth endpoint
3. Saves the new tokens (Strava may rotate refresh tokens)
4. On 401 responses, also tries refreshing once

### Scripts

- `skills/strava/scripts/strava_get.sh` — Simple wrapper that calls strava_request.py
- `skills/strava/scripts/strava_request.py` — Full token management + API requests
- `skills/strava/scripts/refresh_token.sh` — Manual token refresh helper

---

## Step 11: Fitness Coach Setup

The fitness coach is at `/data/.openclaw/workspace/coach/` and consists of:

### coach_data.py (main preprocessing script)

A ~450-line Python script that:
1. Fetches Strava activities for the relevant period
2. Gets detailed activity data (splits, HR zones, descriptions)
3. Reads Apple Watch health CSVs (steps, HRV, RHR, weight, VO2max)
4. Fetches Swiggy food orders from Gmail (parses HTML emails)
5. Outputs compact JSON for the LLM to analyze

**Modes:**
- `--mode daily` — Yesterday's data + progression comparison
- `--mode weekly` — This week vs last week

**Dependencies:**
- Strava tokens at `/data/.openclaw/credentials/strava-tokens.json`
- `gog` CLI at `/data/linuxbrew/.linuxbrew/bin/gog`
- Python 3 with `zoneinfo` (standard library)
- No pip packages needed

### Health CSVs

These are manually maintained or synced from Apple Watch:
- `steps_log.csv` — `date_iso,steps`
- `hrv_log.csv` — `date_iso,hrv`
- `rhr_log.csv` — `date_iso,rhr`
- `weight_log.csv` — `date_iso,weight_kg,notes`
- `metrics_log.csv` — `date_iso,vo2max`

### Other files
- `log_weight.py` — Appends weight entries from chat messages ("weight 86.4")
- `strava_coach.py` — Old version of the coach script (superseded by coach_data.py, can be deleted)
- `state.json` — Tracks reported activity IDs to avoid duplicates
- `WEIGHT.md` — Instructions for weight logging
- `shephali_quote_log.txt` — Tracks motivational quotes sent (avoid repeats)

### HR Zone Config (in coach_data.py)
```python
MAX_HR = 185
ZONES = [
    ("Z1", 0, 111),    # Recovery
    ("Z2", 111, 130),   # Aerobic base
    ("Z3", 130, 148),   # Tempo
    ("Z4", 148, 167),   # Threshold
    ("Z5", 167, 235),   # VO2max
]
```

---

## Step 12: Local Mac Node Connection

### Install OpenClaw CLI on Mac

```bash
brew install openclaw-cli
# Or: npm install -g openclaw
```

### SSH Tunnel (LaunchAgent)

Create `~/Library/LaunchAgents/ai.openclaw.ssh-tunnel.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>ai.openclaw.ssh-tunnel</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/ssh</string>
    <string>-N</string>
    <string>-L</string>
    <string>18789:127.0.0.1:18789</string>
    <string>-i</string>
    <string>/Users/jerry/.ssh/id_ed25519</string>
    <string>-o</string><string>StrictHostKeyChecking=yes</string>
    <string>-o</string><string>PasswordAuthentication=no</string>
    <string>-o</string><string>ExitOnForwardFailure=yes</string>
    <string>-o</string><string>ServerAliveInterval=30</string>
    <string>-o</string><string>ServerAliveCountMax=3</string>
    <string>root@NEW_VPS_IP</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
</dict>
</plist>
```

**Update:** Replace `NEW_VPS_IP` with the new VPS IP. Also update the SSH key path if different.

```bash
launchctl load ~/Library/LaunchAgents/ai.openclaw.ssh-tunnel.plist
# Verify: lsof -iTCP:18789 -sTCP:LISTEN
```

### Node Host (LaunchAgent)

Create `~/Library/LaunchAgents/ai.openclaw.node.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>ai.openclaw.node</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/node</string>
    <string>/opt/homebrew/lib/node_modules/openclaw/dist/index.js</string>
    <string>node</string><string>run</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>18789</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>OPENCLAW_GATEWAY_TOKEN</key>
    <string>YOUR_GATEWAY_TOKEN</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key>
  <string>/Users/jerry/.openclaw/logs/node.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/jerry/.openclaw/logs/node.err.log</string>
</dict>
</plist>
```

**Important:** The exact Node.js and OpenClaw CLI paths change with brew versions. Find the correct paths:
```bash
which node           # e.g., /opt/homebrew/bin/node
which openclaw       # find the linked binary
readlink -f $(which openclaw)  # actual path to index.js
```

```bash
mkdir -p ~/.openclaw/logs
launchctl load ~/Library/LaunchAgents/ai.openclaw.node.plist
```

### Approve Device & Node on VPS

```bash
docker exec -u node openclaw-xtpo-openclaw-1 openclaw devices list
docker exec -u node openclaw-xtpo-openclaw-1 openclaw devices approve <device-id>
docker exec -u node openclaw-xtpo-openclaw-1 openclaw nodes list
docker exec -u node openclaw-xtpo-openclaw-1 openclaw nodes approve <node-id>
```

---

## Step 13: Browser Relay (Optional)

For controlling Chrome on your Mac from the VPS agent. This was implemented but dismantled. See `openclaw-browser-relay-setup.md` in this repo for the full guide.

Key points:
- Chrome extension at `~/.openclaw/browser/chrome-extension/` needs patching to send auth token
- Relay listens on port 18792 on Mac
- VPS config: `gateway.nodes.browser.mode=auto`, `browser.defaultProfile=chrome`
- Three files need patching: `background.js`, `options.html`, `options.js`

---

## Issues Encountered & Solutions

### 1. `docker exec` as root breaks file ownership

**Problem:** Running `docker exec openclaw-xtpo-openclaw-1 openclaw ...` (without `-u node`) creates files owned by root inside the container. The openclaw process runs as `node` user and can't read/write those files.

**Solution:** ALWAYS use `docker exec -u node openclaw-xtpo-openclaw-1 ...` for all openclaw commands.

### 2. WhatsApp message tool argument confusion

**Problem:** The cron job prompts initially used wrong argument names for the WhatsApp message tool. The agent would use `topic` instead of `target`, or include Discord-specific fields, causing messages to fail silently.

**Solution:** Be explicit in the cron prompt: `"CRITICAL: argument is 'target' NOT 'topic'. No Discord fields."` The exact message tool call is:
```
action: send
channel: whatsapp
target: +91XXXXXXXXXX
message: <text>
```

### 3. `gateway.controlUi.allowInsecureAuth` defaults to true

**Problem:** Some OpenClaw builds default `allowInsecureAuth` to `true`, which allows token auth over plain HTTP (not just HTTPS). This is a security risk — anyone intercepting traffic could steal the gateway token.

**Solution:** Always set `oc config set gateway.controlUi.allowInsecureAuth false` immediately after setup.

### 4. Chrome extension doesn't send auth token

**Problem:** The stock OpenClaw Chrome extension connects to the local relay WebSocket without sending an auth token. The relay requires one and rejects the connection.

**Solution:** Patch 3 files in the extension to add token storage and send it as `?token=` query parameter on the WebSocket URL. Browser WebSocket API doesn't support custom headers, so query params are the only option. Acceptable because the connection is loopback-only (127.0.0.1).

### 5. Gmail thread expansion missing transactions

**Problem:** Gmail groups multiple transaction emails into threads. The initial `gog gmail search` only returns one result per thread, so the CA agent was missing transactions (e.g., multiple Quest Travel charges grouped together).

**Solution:** Added thread expansion to the cron prompt: "If any search result shows [N msgs] in the THREAD column, you MUST expand that thread with `gog gmail thread get <threadId> --json` and process each message individually."

### 6. Agent uses stale context after many failed attempts

**Problem:** After many failed browser automation attempts in a single session, the agent starts answering from its accumulated context instead of calling tools. It hallucinates browser results.

**Solution:** Reset the session. Long-running sessions with many errors pollute the context. Use `sessionTarget: "isolated"` for cron jobs so each run gets a fresh session.

### 7. Browser relay port 18792 only opens on demand

**Problem:** After a gateway restart, the browser relay doesn't auto-start. The agent gets connection errors when trying to use the browser.

**Solution:** Run `openclaw browser start --profile chrome` on the VPS after each gateway restart to trigger the relay startup.

### 8. Relay rejects second WebSocket connection (409)

**Problem:** Only one extension WebSocket slot is available on the relay. If a zombie process is holding it, new connections get 409 Conflict.

**Solution:** Kill zombie processes: `lsof -iTCP:18792` on Mac, then kill the stale process.

### 9. Strava token expiry mid-run

**Problem:** The Strava access token expires every 6 hours. If a cron job runs when the token is expired, the API call fails.

**Solution:** The `strava_request.py` script handles this automatically — checks `expires_at` before each request and refreshes if within 120 seconds of expiry. On 401 responses, it also tries refreshing once. Strava may rotate refresh tokens on refresh, so always save the new tokens.

### 10. Parse script fails on new bank email formats

**Problem:** The `parse-transaction.sh` script only handles specific bank email formats (IDFC FIRST, ICICI, Axis). New bank emails or format changes cause parse failures.

**Solution:** The cron prompt has a fallback: "If the script fails (exit 1), read the raw email body yourself. Find the line containing 'INR' or 'Rs.' and QUOTE it verbatim, then extract the fields manually." The agent acts as a fallback parser.

### 11. Cron job delivery mode confusion

**Problem:** Setting `delivery.mode: "announce"` sends the agent's response via WhatsApp automatically. Setting `delivery.mode: "none"` means the agent must call the message tool itself. Getting this wrong means either double-sending or not sending at all.

**Solution:**
- For fitness coach jobs: `delivery.mode: "none"` — the prompt explicitly tells the agent to use the message tool, giving it control over formatting
- For expense summary: `delivery.mode: "announce"` to WhatsApp +91XXXXXXXXXX — the agent's response IS the summary
- For expense processing: `delivery.mode: "none"` — silent processing, no message sent

### 12. Indian date formatting in parse script

**Problem:** `date -d "02 FEB 2026"` works on Linux (GNU date) but not on macOS. The parse script runs inside Docker (Linux), so this is fine. But if you ever test locally on Mac, use `gdate` from coreutils.

### 13. Swiggy email HTML parsing in coach_data.py

**Problem:** Swiggy order confirmation emails are complex HTML. Extracting restaurant name, items, and order time required parsing messy HTML with regex after stripping tags.

**Solution:** The `parse_swiggy_email()` function in coach_data.py strips HTML tags, then walks through lines looking for specific patterns ("Restaurant", "Item Name", "Order placed at:", "Order Total:"). It also detects late-night orders (after 9 PM) for the coach to flag.

### 14. gog CLI not in PATH inside Docker

**Problem:** The `gog` binary is installed via Linuxbrew at `/data/linuxbrew/.linuxbrew/bin/gog`, which is not in the default PATH for the node user.

**Solution:** Always use the full path: `/data/linuxbrew/.linuxbrew/bin/gog`. In Python scripts, set it as a constant: `GOG_BIN = "/data/linuxbrew/.linuxbrew/bin/gog"`.

### 15. Expense CSV newline issues

**Problem:** Appending to CSVs and processed-emails.txt without proper newlines caused concatenated lines — email IDs ran together, CSV rows merged.

**Solution:** Added explicit rules in the cron prompt: "Each row MUST end with a newline character" and "Each ID MUST be on its own line. Never concatenate." Also, `echo` adds a trailing newline by default, but the agent sometimes used `printf` without `\n`.

---

## Maintenance & Debugging

### Common Commands

```bash
# SSH into VPS
ssh root@<VPS_IP>

# Shorthand
alias oc='docker exec -u node openclaw-xtpo-openclaw-1 openclaw'

# Gateway health
OPENCLAW_GATEWAY_TOKEN=<token> openclaw gateway health

# View live logs
docker logs openclaw-xtpo-openclaw-1 --since=5m -f

# Restart gateway
cd /docker/openclaw-xtpo && docker compose restart

# List cron jobs
docker exec -u node openclaw-xtpo-openclaw-1 openclaw cron list

# Run a cron job manually
docker exec -u node openclaw-xtpo-openclaw-1 openclaw cron run <job-id>

# Edit a cron job
docker exec -u node openclaw-xtpo-openclaw-1 openclaw cron edit <job-id> --cron "30 4 * * *" --message "..."

# Check node connection
docker exec -u node openclaw-xtpo-openclaw-1 openclaw nodes status

# Gmail search (inside container)
docker exec -u node \
  -e GOG_ACCOUNT=<your-gmail>@gmail.com \
  -e GOG_KEYRING_PASSWORD=<your-keyring-password> \
  openclaw-xtpo-openclaw-1 \
  /data/linuxbrew/.linuxbrew/bin/gog gmail search "in:inbox" --plain

# Strava test
docker exec -u node openclaw-xtpo-openclaw-1 \
  bash /data/.openclaw/workspace/skills/strava/scripts/strava_get.sh "/api/v3/athlete"
```

### Backup Critical Data

Before VPS expires, back up:

```bash
# From your Mac:
mkdir -p "$HOME/openclaw-backups/$(date +%Y-%m-%d)"
BACKUP_DIR="$HOME/openclaw-backups/$(date +%Y-%m-%d)"
scp -r root@<VPS_IP>:/docker/openclaw-xtpo/data/.openclaw/cron/ "$BACKUP_DIR/cron/"
scp -r root@<VPS_IP>:/docker/openclaw-xtpo/data/.openclaw/workspace/ "$BACKUP_DIR/workspace/"
scp -r root@<VPS_IP>:/docker/openclaw-xtpo/data/.openclaw/workspace-ca/ "$BACKUP_DIR/workspace-ca/"
scp -r root@<VPS_IP>:/docker/openclaw-xtpo/data/.openclaw/workspace-ea/ "$BACKUP_DIR/workspace-ea/"
scp -r root@<VPS_IP>:/docker/openclaw-xtpo/data/.openclaw/credentials/ "$BACKUP_DIR/credentials/"
scp root@<VPS_IP>:/docker/openclaw-xtpo/data/.openclaw/openclaw.json "$BACKUP_DIR/"
scp root@<VPS_IP>:/docker/openclaw-xtpo/.env "$BACKUP_DIR/"
scp root@<VPS_IP>:/docker/openclaw-xtpo/server.mjs "$BACKUP_DIR/"
scp root@<VPS_IP>:/docker/openclaw-xtpo/docker-compose.yml "$BACKUP_DIR/"
```

Keep backups outside the git repo and encrypt them at rest if they contain `.env`, OAuth state, or session files.

---

## File Tree Reference

```
/docker/openclaw-xtpo/                    # VPS host
├── docker-compose.yml
├── .env                                   # API keys, tokens, ports
├── server.mjs                             # Hostinger proxy (read-only mount)
└── data/                                  # Mounted as /data inside container
    ├── linuxbrew/                          # Linuxbrew (gog CLI lives here)
    ├── .config/
    │   └── gogcli/                        # gog CLI credentials (created after OAuth login)
    │       ├── credentials.json           # OAuth client_id + client_secret
    │       └── keyring/                   # Encrypted OAuth tokens
    └── .openclaw/
        ├── openclaw.json                  # Gateway + agent config
        ├── credentials/
        │   ├── strava-tokens.json
        │   ├── blinkit-session.json
        │   ├── whatsapp/                  # WhatsApp session
        │   ├── whatsapp-allowFrom.json
        │   └── whatsapp-pairing.json
        ├── cron/
        │   └── jobs.json                  # All cron job definitions
        ├── agents/
        │   ├── main/                      # Main agent sessions (.jsonl)
        │   ├── ca/agent/                  # CA agent dir
        │   └── ea/agent/                  # EA agent dir
        ├── workspace/                     # Main agent workspace
        │   ├── skills/
        │   │   ├── strava/
        │   │   │   ├── SKILL.md
        │   │   │   └── scripts/
        │   │   │       ├── strava_get.sh
        │   │   │       ├── strava_request.py
        │   │   │       └── refresh_token.sh
        │   │   ├── gog/
        │   │   │   └── SKILL.md
        │   │   └── blinkit/
        │   │       ├── SKILL.md
        │   │       ├── scripts/blinkit.js
        │   │       └── data/grocery-list.json
        │   └── coach/
        │       ├── coach_data.py          # Main preprocessing script
        │       ├── log_weight.py
        │       ├── WEIGHT.md
        │       ├── state.json
        │       ├── steps_log.csv
        │       ├── hrv_log.csv
        │       ├── rhr_log.csv
        │       ├── weight_log.csv
        │       └── metrics_log.csv
        ├── workspace-ca/                  # CA agent workspace
        │   ├── MEMORY.md                  # Merchant registry
        │   ├── scripts/
        │   │   └── parse-transaction.sh   # Bank email parser (IDFC/ICICI/Axis)
        │   ├── memory/
        │   │   ├── SOUL.md
        │   │   ├── expenses-YYYY-MM.csv
        │   │   ├── processed-emails.txt
        │   │   ├── processing-log.txt
        │   │   ├── last-summary-date.txt
        │   │   └── summary.py
        │   └── skills/
        │       ├── expenses/
        │       │   └── SKILL.md
        │       └── gog/
        │           └── SKILL.md
        └── workspace-ea/                  # EA agent workspace
            └── memory/
                ├── SOUL.md                # Reshma persona
                └── tasks.json             # Task tracking
```

---

## Appendix: Cron Job Prompts

The full prompt text for each cron job is lengthy. They are stored in `/data/.openclaw/cron/jobs.json`. Key patterns:

1. **Always end with "reply NO_REPLY"** — prevents the agent from sending extra messages
2. **Specify message tool arguments exactly** — `action: send, channel: whatsapp, target: +91XXXXXXXXXX`
3. **Use `sessionTarget: "isolated"`** — each cron run gets a clean session
4. **Set appropriate timeouts** — 150s for simple reports, 300s for email processing
5. **Specify the model in each job** — don't rely on defaults

### News Digest (not currently active, was removed)

Was a daily 10:00 IST job that fetched RSS feeds, HTML pages, and X/Twitter posts about AI/agents/marketing, filtered by relevance score, and sent a formatted digest via WhatsApp. Used model "Grok 4.1 Fast" with 180s timeout. The exported job definition is in `news-digest-job.json` in this repo.
