#!/bin/bash
# parse-transaction.sh — Extract transaction fields from bank email body text
# Input: email body text via stdin (pipe from gog gmail get <id> --json | jq -r .body)
# Output: pipe-delimited line: date|amount|merchant_raw|card_last4|type|bank
# Exit 1 if unable to parse
# Handles: IDFC FIRST Bank CC, ICICI Bank CC, Axis Bank account (debit+credit)

set -euo pipefail

BODY=$(cat)

# Normalise: strip \r, collapse whitespace across lines
BODY_CLEAN=$(echo "$BODY" | tr '\r' ' ' | tr '\n' ' ' | sed 's/  */ /g')

# ─── IDFC FIRST Bank Credit Card (debit) ───
# "INR 210.04 spent on your IDFC FIRST BANK Credit Card ending XX9178 at UBER INDIA SYSTE PVT LTD on 02 FEB 2026"
if echo "$BODY_CLEAN" | grep -qiP 'INR\s+[\d,.]+\s+spent\s+on\s+your\s+IDFC'; then
    AMOUNT=$(echo "$BODY_CLEAN" | grep -oP 'INR\s+\K[\d,.]+(?=\s+spent)' | head -1 | tr -d ',')
    CARD=$(echo "$BODY_CLEAN" | grep -oP 'Card ending\s+\K[A-Z0-9]+' | head -1)
    MERCHANT=$(echo "$BODY_CLEAN" | grep -oP 'at\s+\K[^o]+(?=\s+on\s+\d{2}\s+[A-Z]{3}\s+\d{4})' | head -1 | sed 's/\s*$//')
    DATE_RAW=$(echo "$BODY_CLEAN" | grep -oP 'on\s+\K\d{2}\s+[A-Z]{3}\s+\d{4}' | head -1)
    # Convert "02 FEB 2026" to "2026-02-02"
    if [ -n "$DATE_RAW" ]; then
        DATE=$(date -d "$DATE_RAW" '+%Y-%m-%d' 2>/dev/null || echo "$DATE_RAW")
    fi
    if [ -n "$AMOUNT" ] && [ -n "$MERCHANT" ]; then
        echo "${DATE:-unknown}|${AMOUNT}|${MERCHANT}|${CARD:-unknown}|debit|IDFC"
        exit 0
    fi
fi

# ─── IDFC FIRST Bank Credit Card (reversal) ───
# "Transaction of INR 443.18 done at UBER INDIA ... on 07 FEB 2026 has been reversed"
if echo "$BODY_CLEAN" | grep -qiP 'INR\s+[\d,.]+\s+done\s+at\s+.*has\s+been\s+reversed'; then
    AMOUNT=$(echo "$BODY_CLEAN" | grep -oP 'INR\s+\K[\d,.]+(?=\s+done\s+at)' | head -1 | tr -d ',')
    MERCHANT=$(echo "$BODY_CLEAN" | grep -oP 'done\s+at\s+\K[^o]+(?=\s+on\s+\d{2}\s+[A-Z]{3}\s+\d{4})' | head -1 | sed 's/\s*$//')
    CARD=$(echo "$BODY_CLEAN" | grep -oP 'Card ending\s+\K[A-Z0-9]+' | head -1)
    DATE_RAW=$(echo "$BODY_CLEAN" | grep -oP 'on\s+\K\d{2}\s+[A-Z]{3}\s+\d{4}' | head -1)
    if [ -n "$DATE_RAW" ]; then
        DATE=$(date -d "$DATE_RAW" '+%Y-%m-%d' 2>/dev/null || echo "$DATE_RAW")
    fi
    if [ -n "$AMOUNT" ] && [ -n "$MERCHANT" ]; then
        echo "${DATE:-unknown}|${AMOUNT}|${MERCHANT}|${CARD:-unknown}|reversal|IDFC"
        exit 0
    fi
fi

# ─── ICICI Bank Credit Card ───
# "Credit Card XX3009 has been used for a transaction of INR 6,718.84 on Feb 02, 2026 at 08:34:40. Info: ATRIA CONVERGENCE TECH"
if echo "$BODY_CLEAN" | grep -qiP 'Credit Card\s+XX\d+\s+has been used'; then
    CARD=$(echo "$BODY_CLEAN" | grep -oP 'Credit Card\s+\KXX\d+' | head -1)
    AMOUNT=$(echo "$BODY_CLEAN" | grep -oP 'transaction of INR\s+\K[\d,.]+' | head -1 | tr -d ',')
    DATE_RAW=$(echo "$BODY_CLEAN" | grep -oP 'on\s+\K[A-Z][a-z]{2}\s+\d{2},\s+\d{4}' | head -1)
    MERCHANT=$(echo "$BODY_CLEAN" | grep -oP 'Info:\s*\K[^.]+' | head -1 | sed 's/\s*$//')
    if [ -n "$DATE_RAW" ]; then
        DATE=$(date -d "$DATE_RAW" '+%Y-%m-%d' 2>/dev/null || echo "$DATE_RAW")
    fi
    if [ -n "$AMOUNT" ] && [ -n "$MERCHANT" ]; then
        echo "${DATE:-unknown}|${AMOUNT}|${MERCHANT}|${CARD:-unknown}|debit|ICICI"
        exit 0
    fi
fi

# ─── Axis Bank Account (debit) ───
# "Amount Debited: INR 170.00 / Account Number: XX7701 / Transaction Info: UPI/P2M/.../Q MART RETAIL LIMIT"
if echo "$BODY_CLEAN" | grep -qiP 'Amount\s+Debited:\s*INR'; then
    AMOUNT=$(echo "$BODY_CLEAN" | grep -oP 'Amount\s+Debited:\s*INR\s+\K[\d,.]+' | head -1 | tr -d ',')
    CARD=$(echo "$BODY_CLEAN" | grep -oP 'Account Number:\s*\KXX\d+' | head -1)
    # Date from "DD-MM-YYYY" at top of email or Date & Time field
    DATE_RAW=$(echo "$BODY_CLEAN" | grep -oP '\d{2}-\d{2}-\d{4}' | head -1)
    if [ -n "$DATE_RAW" ]; then
        # Convert DD-MM-YYYY to YYYY-MM-DD
        DAY=$(echo "$DATE_RAW" | cut -d- -f1)
        MON=$(echo "$DATE_RAW" | cut -d- -f2)
        YEAR=$(echo "$DATE_RAW" | cut -d- -f3)
        DATE="${YEAR}-${MON}-${DAY}"
    fi
    # Transaction Info: UPI/P2M/604574454938/Q MART RETAIL LIMIT
    MERCHANT=$(echo "$BODY_CLEAN" | grep -oP 'Transaction Info:\s*\K[^\n]+' | head -1 | sed 's/\s*If this.*//' | sed 's/\s*$//')
    if [ -n "$AMOUNT" ] && [ -n "$MERCHANT" ]; then
        echo "${DATE:-unknown}|${AMOUNT}|${MERCHANT}|${CARD:-unknown}|debit|AXIS"
        exit 0
    fi
fi

# ─── Axis Bank Account (credit) ───
# "Amount Credited: INR 80.00 / Account Number: XX7701 / Transaction Info: UPI/P2A/.../MITALI M/SBIN/UPI"
if echo "$BODY_CLEAN" | grep -qiP 'Amount\s+Credited:\s*INR'; then
    AMOUNT=$(echo "$BODY_CLEAN" | grep -oP 'Amount\s+Credited:\s*INR\s+\K[\d,.]+' | head -1 | tr -d ',')
    CARD=$(echo "$BODY_CLEAN" | grep -oP 'Account Number:\s*\KXX\d+' | head -1)
    DATE_RAW=$(echo "$BODY_CLEAN" | grep -oP '\d{2}-\d{2}-\d{4}' | head -1)
    if [ -n "$DATE_RAW" ]; then
        DAY=$(echo "$DATE_RAW" | cut -d- -f1)
        MON=$(echo "$DATE_RAW" | cut -d- -f2)
        YEAR=$(echo "$DATE_RAW" | cut -d- -f3)
        DATE="${YEAR}-${MON}-${DAY}"
    fi
    MERCHANT=$(echo "$BODY_CLEAN" | grep -oP 'Transaction Info:\s*\K[^\n]+' | head -1 | sed 's/\s*Feel free.*//' | sed 's/\s*$//')
    if [ -n "$AMOUNT" ] && [ -n "$MERCHANT" ]; then
        echo "${DATE:-unknown}|${AMOUNT}|${MERCHANT}|${CARD:-unknown}|credit|AXIS"
        exit 0
    fi
fi

# ─── Fallback: Could not parse ───
echo "PARSE_FAILED: Could not extract transaction from email body" >&2
exit 1
