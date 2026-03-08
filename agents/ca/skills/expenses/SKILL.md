---
name: expenses
description: Track, categorise, and report on personal expenses from transaction emails
---

# Expense Tracking Skill

## CSV Format

All expenses are stored in `memory/expenses-YYYY-MM.csv` with this header:

```
date,amount,merchant,category,card,type,email_id,notes
```

- `date`: YYYY-MM-DD
- `amount`: Decimal number, no commas (e.g., 6718.84)
- `merchant`: Cleaned merchant name (e.g., "Uber" not "UBER INDIA SYSTE PVT LTD")
- `category`: One of: Rent, Utilities, Apparel, Amazon, Swiggy/Zomato, Essentials, Travel, Fitness, Investments, Miscellaneous
- `card`: Card/account identifier (e.g., XX9178, XX3009, XX7701)
- `type`: debit, credit, or reversal
- `email_id`: Gmail message ID (for dedup)
- `notes`: Optional (e.g., "Reversal of 02-Feb Uber charge")

## Processing Pipeline

**CRITICAL: Process ONE email at a time. Never batch.**

### Step 0: Search Gmail
```
gog gmail search "subject:(transaction OR payment OR debited OR credited OR UPI OR spent OR charged OR debit) newer_than:3d" --plain --max 100
```
This returns a TSV list. The THREAD column shows `[N msgs]` when a thread has multiple messages.
Collect ALL email IDs you need to process (see Step 0b for threads).

### Step 0b: Expand threads
For each search result where THREAD shows `[N msgs]` (N > 1):
```
gog gmail thread get <threadId> --json
```
This returns `{ "thread": { "messages": [ { "id": "...", ... }, ... ] } }`.
Extract all message IDs from the thread. Each message is a separate transaction.
Add all these message IDs to your processing queue.

**This is critical.** Without this step, you will miss transactions that Gmail groups
into the same thread (e.g., multiple Quest Travel charges in one thread).

### Step 1: Check if already processed
For each email ID in your queue:
```
grep -q "<email_id>" memory/processed-emails.txt && echo "SKIP" || echo "NEW"
```
Skip any IDs already in processed-emails.txt.

### Step 2: Get email body
```
gog gmail get <email_id> --json
```
Do not interpolate the raw `body` into shell quotes.

### Step 3: Run parse script
```
gog gmail get <email_id> --json \
  | python3 -c 'import json, sys; sys.stdout.write(json.load(sys.stdin).get("body", ""))' \
  | bash scripts/parse-transaction.sh
```
Output format: `date|amount|merchant_raw|card_last4|type|bank`

### Step 4: If script fails (exit 1), extract manually
Read the email body yourself. Find the line with "INR" or "Rs." and QUOTE it verbatim.
Then extract: date, amount, merchant, card, type.

### Step 5: Clean merchant name
- Strip suffixes like "PVT LTD", "PRIVATE LIMITED", "INDIA SYSTE"
- For UPI transactions (Transaction Info: UPI/P2M/.../MERCHANT or UPI/P2A/.../NAME), extract the last meaningful segment
- Check MEMORY.md merchant registry first
- If unknown merchant, search the web to identify what they sell

### Step 6: Categorise
Use the categories from SOUL.md. Rules:
- Uber, Ola, auto = Miscellaneous
- Swiggy, Zomato = Swiggy/Zomato (only orders placed THROUGH the app, not direct UPI to restaurants)
- Amazon = Amazon
- Airbnb, MakeMyTrip, Quest Travel, hotels, airlines = Travel
- Instamart, BigBasket, grocery, Urban Company, salon, Q Mart = Essentials
- Groww, Zerodha, mutual fund = Investments
- Jawved, Aaniya = Rent
- MyGate, ACT Fibernet, Atria Convergence, Netflix, Hotstar, electricity = Utilities
- Clothing brands = Apparel
- Yoga, pilates, gym = Fitness
- If unsure after web search, mark as Miscellaneous and add a note "UNCATEGORISED - ask Jerry"

### Step 7: Append to CSV
Append exactly ONE row to `memory/expenses-YYYY-MM.csv` (use the transaction date's month).
If the CSV file doesn't exist, create it with the header row first.
**CRITICAL:** Each row MUST end with a newline character.

### Step 8: Mark as processed
Append the email ID on its own line:
```
echo "<email_id>" >> memory/processed-emails.txt
```
**CRITICAL:** Each ID MUST be on its own line. Never concatenate.

### Step 9: Update merchant registry
If this is a new merchant, add it to MEMORY.md merchant registry table.

### Step 10: Verify (after ALL emails done)
Re-read the CSV. Count total rows (minus header). Report:
"Processed N new emails, CSV now has M total rows."

## Reporting Format (for WhatsApp summaries)

Use WhatsApp formatting. NO markdown tables (WhatsApp doesn't render them).

```
*Expense Update — [start_date] to [end_date]*

*By Category:*
• Miscellaneous: ₹X,XXX (N txns)
• Travel: ₹X,XXX (N txns)
• [etc, sorted by amount descending, skip categories with 0]

*Top Merchants:*
• [Merchant]: ₹X,XXX (N txns)
• [up to 5 merchants]

*Flagged:*
• [Any reversals, credits, uncategorised, or anomalies]

*Period Total: ₹XX,XXX (N transactions)*
*Month-to-date: ₹XX,XXX*
```

Use Indian numbering (₹1,00,000.00). Show your arithmetic.

## Anomaly Flags

Flag these to Jerry:
- Transactions > ₹10,000
- Duplicate amounts to same merchant within 24 hours
- Reversals/refunds
- Merchants marked "UNCATEGORISED"
- Transactions between midnight and 5 AM

## Error Handling

- If an email cannot be parsed by the script AND you cannot extract manually, log it:
  `echo "FAILED:<email_id>:<reason>" >> memory/processing-log.txt`
  Do NOT skip silently. Do NOT invent data.
- If the CSV file is corrupted or has wrong column count, stop and alert Jerry.
