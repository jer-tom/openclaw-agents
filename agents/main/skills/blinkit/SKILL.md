---
name: blinkit
description: Track grocery needs and place orders on Blinkit. Use when the user mentions groceries, grocery list, Blinkit, or wants to order food/household items for delivery.
metadata: {"openclaw":{"emoji":"\uD83D\uDED2","requires":{"bins":["node"]}}}
---

# Blinkit Grocery Skill

You manage a grocery list and place orders on Blinkit via headless browser automation.

## Grocery List

The list is stored at `{baseDir}/data/grocery-list.json` as a JSON array:

```json
[
  { "name": "Toned Milk 500ml", "qty": 2, "brand": "Amul", "notes": "get double toned if unavailable" }
]
```

Only `name` and `qty` are required. `brand` and `notes` are optional hints.

**Operations** (you read/write the file directly via exec):
- **Add**: append to the array, merge if item already exists (bump qty)
- **Remove**: filter out by name (fuzzy match is fine)
- **View**: read and summarize as a clean list
- **Clear**: write `[]` after confirming with the user

## Blinkit Ordering

### CLI Reference

All commands via: `node {baseDir}/scripts/blinkit.js <command> [args]`

All output is JSON on stdout. Errors on stderr.

| Command | Description |
|---|---|
| `check-login` | Check session validity. Returns `{"loggedIn": true/false}` |
| `login <phone>` | Start login. OTP will be sent to the phone. |
| `otp <code>` | Enter OTP to complete login. |
| `search <query>` | Search products. Returns `{count, results: [{index, id, name, price}]}` |
| `prepare-order '<json>'` | **Main command.** Takes `[{name, qty}]`, searches each item, adds best match to cart, returns cart summary. |
| `cart` | View current cart contents. |
| `clear-cart` | Remove all items from cart. |
| `place-order` | Checkout with default address + first saved UPI. Triggers UPI collect request. |

### Ordering Flow

When the user says "order my groceries" or similar:

1. Read `{baseDir}/data/grocery-list.json`
2. If empty, tell the user and ask what they need
3. Run: `node {baseDir}/scripts/blinkit.js prepare-order '<items-json>'`
   - Pass the grocery list items as `[{"name":"...", "qty":N}]` (use `brand` as part of `name` if present, e.g. "Amul Toned Milk 500ml")
4. Parse the response. Show the user:
   - What was found vs not found
   - Matched product names and prices
   - Cart total (from cartSummary)
5. **Ask the user for confirmation before proceeding**
6. On confirmation: `node {baseDir}/scripts/blinkit.js place-order`
7. Tell the user to approve the UPI payment on their phone
8. After ordering, ask if they want to clear the grocery list

### Error Handling

- `{"error": "store_closed"}` → Tell the user the store is closed, suggest trying later
- `{"loggedIn": false}` → Session expired. Ask the user for their phone number, run `login`, then `otp`
- Items with `"status": "not_found"` → Tell the user which items weren't found, offer alternatives via `search`

### Important Notes

- **Never place an order without explicit user confirmation** of the cart summary
- The `place-order` command selects the first saved address and first saved UPI automatically
- The user must approve the UPI PIN on their phone — the script triggers the payment request but cannot complete it
- Sessions persist across runs. Re-login is only needed if cookies expire (rare)
- If the user wants to search without ordering, use `search` directly
- Set `BLINKIT_LATITUDE` and `BLINKIT_LONGITUDE` in the environment before running the script. Do not hardcode personal delivery coordinates in the repo.
- Leave Chromium sandboxing enabled by default. Only set `BLINKIT_DISABLE_SANDBOX=1` if your container environment cannot run Chromium with its sandbox.
