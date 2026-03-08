---
name: gog
description: Read and search Gmail using the gog CLI (Google Workspace CLI)
homepage: https://github.com/steipete/gogcli
metadata: {"clawdbot":{"emoji":"📧","requires":{"bins":["gog"],"env":["GOG_ACCOUNT"]},"primaryEnv":"GOG_ACCOUNT"}}
---

# Gmail Skill (gog)

Read, search, and manage Gmail using the `gog` CLI tool.

## Available Commands

### Search emails
```bash
gog gmail search "in:inbox"
gog gmail search "from:someone@example.com"
gog gmail search "is:unread"
gog gmail search "subject:meeting after:2026/02/01"
gog gmail search "has:attachment"
```

### Read a specific message
```bash
gog gmail get <messageId>
```

### List messages in a thread
```bash
gog gmail thread get <threadId>
```

### List labels
```bash
gog gmail labels list
```

## Output Formats

- Default: human-readable table
- `--plain`: TSV format (good for parsing)
- `--json`: JSON output (good for detailed data)

## Gmail Search Syntax

Uses standard Gmail search operators:
- `from:` / `to:` / `cc:` / `bcc:` — by sender/recipient
- `subject:` — by subject line
- `is:unread` / `is:read` / `is:starred`
- `in:inbox` / `in:sent` / `in:trash` / `in:spam`
- `has:attachment`
- `after:YYYY/MM/DD` / `before:YYYY/MM/DD`
- `newer_than:2d` / `older_than:1w`
- `label:` — by label
- Combine with spaces (AND) or `OR`

## Tips

- The `GOG_ACCOUNT` env var is pre-configured — no need to pass `--account`
- Use `--plain` for machine-readable output
- Use `--json` for full message details including body
- Message IDs from search results can be passed to `gog gmail get`
