# OpenClaw Browser Relay — Implementation Guide

**Date:** 2026-02-22
**Status:** Implemented & tested (then dismantled — see notes at bottom)

---

## What This Does

Lets the AI agent running on a remote VPS (Hostinger Docker container) control tabs in your local Chrome browser. The agent can see pages, click, type, navigate — all routed securely through an SSH tunnel and a local relay.

---

## Architecture

```
VPS (<VPS_IP>)
└── Docker: openclaw-xtpo-openclaw-1
    └── Gateway on port 63362 (internal)
        Proxied to port 18789 by server.cjs
        Port 18789 mapped to host

Mac (local)
├── SSH Tunnel (LaunchAgent: ai.openclaw.ssh-tunnel)
│   └── localhost:18789 ──SSH──▶ VPS:18789 ──▶ container:63362
│
├── Node Host (LaunchAgent: ai.openclaw.node)
│   ├── Connects to gateway via tunnel on 18789
│   ├── Starts browser relay on localhost:18792
│   └── Proxies browser commands from gateway to relay
│
├── Chrome Extension (OpenClaw Browser Relay)
│   ├── Options page: set port=18792, token=<gateway_token>
│   ├── Click toolbar icon on a tab → badge shows ON
│   └── WebSocket to localhost:18792/extension?token=<token>
│
└── Chrome Browser
    └── Attached tab (badge ON) ← controlled by agent
```

---

## Components

### 1. VPS Gateway

- **Host:** `<VPS_IP>`
- **Container:** `openclaw-xtpo-openclaw-1`
- **Docker Compose:** `/docker/openclaw-xtpo/docker-compose.yml`
- **Port mapping:** `18789:18789` (SSH tunnel entry) + internal gateway on 63362
- **Auth token:** `<YOUR_GATEWAY_TOKEN>`

### 2. SSH Tunnel (Mac LaunchAgent)

**File:** `~/Library/LaunchAgents/ai.openclaw.ssh-tunnel.plist`

```xml
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
  <string>root@<VPS_IP></string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>10</integer>
```

**Load:** `launchctl load ~/Library/LaunchAgents/ai.openclaw.ssh-tunnel.plist`

### 3. Node Host (Mac LaunchAgent)

**File:** `~/Library/LaunchAgents/ai.openclaw.node.plist`

Key settings:
```xml
<key>ProgramArguments</key>
<array>
  <string>/opt/homebrew/Cellar/node/25.6.1/bin/node</string>
  <string>/opt/homebrew/Cellar/openclaw-cli/2026.2.19-2/libexec/lib/node_modules/openclaw/dist/index.js</string>
  <string>node</string><string>run</string>
  <string>--host</string><string>127.0.0.1</string>
  <string>--port</string><string>18789</string>
</array>
<key>EnvironmentVariables</key>
<dict>
  <key>OPENCLAW_GATEWAY_TOKEN</key>
  <string><YOUR_GATEWAY_TOKEN></string>
</dict>
```

**Load:** `launchctl load ~/Library/LaunchAgents/ai.openclaw.node.plist`

**Logs:** `~/.openclaw/logs/node.log` / `node.err.log`

### 4. Chrome Extension (Patched)

**Location:** `~/.openclaw/browser/chrome-extension/`

The stock extension does **not** send an auth token with its WebSocket connection to the relay. The relay requires one. Three files were patched:

#### `background.js` — Added token auth

```js
// Added these two functions:
async function getRelayToken() {
  const stored = await chrome.storage.local.get(['relayToken'])
  return stored.relayToken || ''
}

// Modified ensureRelayConnection() to use token:
const port = await getRelayPort()
const token = await getRelayToken()
const wsUrl = token
  ? `ws://127.0.0.1:${port}/extension?token=${encodeURIComponent(token)}`
  : `ws://127.0.0.1:${port}/extension`
```

#### `options.html` — Added token input field

```html
<div class="card">
  <h2>Gateway token</h2>
  <label for="token">Token</label>
  <div class="row">
    <input id="token" type="password" autocomplete="off" style="width: 280px" />
    <button id="save-token" type="button">Save</button>
  </div>
  <div class="hint">
    Required for relay authentication. Find it in <code>~/.openclaw/openclaw.json</code>
    → <code>gateway.auth.token</code>, or run <code>openclaw config get gateway.auth.token</code>.
  </div>
</div>
```

#### `options.js` — Added token load/save

```js
async function load() {
  const stored = await chrome.storage.local.get(['relayPort', 'relayToken'])
  document.getElementById('port').value = String(clampPort(stored.relayPort))
  document.getElementById('token').value = stored.relayToken || ''
  // ...
}

async function saveToken() {
  const token = (document.getElementById('token').value || '').trim()
  await chrome.storage.local.set({ relayToken: token })
}

document.getElementById('save-token').addEventListener('click', () => void saveToken())
```

#### Loading the extension

1. Open Chrome → `chrome://extensions/`
2. Enable **Developer mode**
3. Click **Load unpacked** → select `~/.openclaw/browser/chrome-extension/`
4. Open the extension **Options** page
5. Set Port: `18792`
6. Set Token: (paste gateway auth token)
7. Click Save for each

### 5. VPS Gateway Config (key settings)

```json
{
  "browser": {
    "defaultProfile": "chrome"
  },
  "gateway": {
    "controlUi": { "allowInsecureAuth": false },
    "nodes": { "browser": { "mode": "auto" } }
  }
}
```

Set via CLI (run inside Docker as node user):
```bash
docker exec -u node openclaw-xtpo-openclaw-1 openclaw config set gateway.nodes.browser.mode auto
docker exec -u node openclaw-xtpo-openclaw-1 openclaw config set gateway.controlUi.allowInsecureAuth false
docker exec -u node openclaw-xtpo-openclaw-1 openclaw config set browser.defaultProfile chrome
```

### 6. Browser Profile on Mac

**`~/.openclaw/openclaw.json`** (Mac-side):
```json
{
  "browser": {
    "defaultProfile": "chrome",
    "profiles": {
      "chrome": {
        "cdpUrl": "http://127.0.0.1:18792",
        "driver": "extension",
        "color": "#00AA00"
      }
    }
  }
}
```

Created via:
```bash
openclaw browser create-profile --name chrome --driver extension \
  --cdp-url http://127.0.0.1:18792 --color '#00AA00'
```

---

## Setup Order (from scratch)

1. **SSH key access** to VPS as root (key: `~/.ssh/id_ed25519`)
2. **Create SSH tunnel LaunchAgent** → load it → verify `lsof -iTCP:18789`
3. **Generate node host LaunchAgent** via `openclaw node install` (or manually) → load it
4. **Approve the device** on VPS: `openclaw devices list` then `openclaw devices approve <id>`
5. **Approve the node** on VPS: `openclaw nodes list` → `openclaw nodes approve <id>`
6. **Start the relay**: `openclaw browser start --profile chrome` (on VPS, triggers node host to open port 18792)
7. **Patch the Chrome extension** (3 files above)
8. **Load extension** in Chrome developer mode
9. **Enter token** in extension Options page
10. **Click extension icon** on any tab → badge turns ON
11. **Verify**: `openclaw browser tabs --profile chrome` on VPS → should show the tab
12. **Set VPS config**: `gateway.nodes.browser.mode=auto`, `browser.defaultProfile=chrome`

---

## Key Debugging Commands

```bash
# VPS: Check node connection
docker exec -u node openclaw-xtpo-openclaw-1 openclaw nodes status

# VPS: List tabs (via node host relay)
docker exec -u node openclaw-xtpo-openclaw-1 openclaw browser tabs --profile chrome

# VPS: List browser profiles
docker exec -u node openclaw-xtpo-openclaw-1 openclaw browser profiles

# Mac: Check relay is listening
lsof -iTCP:18792 -sTCP:LISTEN

# Mac: Check SSH tunnel
lsof -iTCP:18789 -sTCP:LISTEN

# Mac: Test relay auth
curl -v http://127.0.0.1:18792/
# Expect 200 OK

# Mac: Check node host process
ps aux | grep "openclaw.*node run"
```

---

## Ports Reference

| Port  | Where  | Purpose                              |
|-------|--------|--------------------------------------|
| 63362 | VPS    | Gateway WebSocket (inside Docker)    |
| 18789 | VPS    | Gateway mapped to host (SSH entry)   |
| 18789 | Mac    | SSH tunnel local end → VPS:18789     |
| 18792 | Mac    | Node host browser relay (extension connects here) |

---

## Gotchas & Lessons Learned

- **Relay requires auth token** — stock extension sends none; must patch `background.js` to append `?token=` to WebSocket URL. Browser WebSocket API doesn't support custom headers.
- **`?token=` is acceptable security** — connection is loopback-only (127.0.0.1), token already sits in plaintext on disk, and the relay itself was designed to accept this.
- **`gateway.controlUi.allowInsecureAuth`** — defaults to `true` in some builds; set to `false` immediately. Allows token auth over plain HTTP otherwise (CRITICAL finding).
- **`openclaw nodes status` vs `nodes list`** — `status` shows if a node is connected; `list` may show 0 even when connected.
- **`isRemote: false` is normal for extension profiles** — the `--driver extension` flag enforces loopback CDP, so `isRemote` is always false. Routing through node host is controlled separately by `gateway.nodes.browser.mode: auto`.
- **Relay port 18792 only opens on demand** — after gateway restart, run `openclaw browser start --profile chrome` to trigger relay startup; it doesn't auto-start.
- **Only one extension WebSocket slot** — relay rejects second connection with 409. Kill any zombie processes holding it (`lsof -iTCP:18792`).
- **Agent session context pollution** — after many failed browser attempts, agent answers from stale memory instead of calling the tool. Reset the session.
- **`docker exec` as root breaks file ownership** — always use `-u node` when running openclaw commands inside the container.
- **VPS `create-profile` CLI** — profiles created via CLI on VPS go into Mac's `~/.openclaw/openclaw.json` (because CLI connects through the gateway tunnel to the node). VPS-side profiles are created locally.

---

## Dismantled

This relay was set up and tested, then dismantled on 2026-02-22. To restore, follow the Setup Order above.

Files to restore/recreate:
- `~/Library/LaunchAgents/ai.openclaw.ssh-tunnel.plist`
- `~/Library/LaunchAgents/ai.openclaw.node.plist`
- `~/.openclaw/browser/chrome-extension/background.js` (3 patches)
- `~/.openclaw/browser/chrome-extension/options.html` (token field)
- `~/.openclaw/browser/chrome-extension/options.js` (token save/load)
- VPS gateway config: `gateway.nodes.browser.mode`, `browser.defaultProfile`
