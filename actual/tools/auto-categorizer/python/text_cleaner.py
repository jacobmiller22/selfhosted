import re

# Common bank noise prefixes
PREFIX_PATTERNS = [
    r"^sq\s*\*\s*",             # Square payments (SQ * ...)
    r"^tst\s*\*\s*",            # Toast POS payments (TST* ...)
    r"^paypal\s*\*\s*",         # PayPal (PAYPAL * ...)
    r"^py\s*\*\s*",             # PayPal short (PY * ...)
    r"^sp\s*\*\s*",             # Shopify (SP * ...)
    r"^chk\s*card\s*",          # Check Card
    r"^debit\s*card\s*purchase\s*",
    r"^pos\s*purchase\s*",
    r"^recurring\s*payment\s*",
    r"^ach\s*withdrawal\s*",
    r"^direct\s*deposit\s*",
]

# Common bank noise suffixes (store numbers, phone numbers, state codes, dates)
SUFFIX_PATTERNS = [
    r"#\s*\d+",                 # #1234
    r"\b\d{3}-\d{3}-\d{4}\b",  # 800-123-4567
    r"\b[A-Z]{2}\s+\d{5}\b",    # CA 94102
    r"\b(ca|ny|tx|fl|wa|or|il|ma|nc|ga)\b", # State abbreviations
    r"\b\d{2}/\d{2}\b",        # 09/08 dates
]

def clean_payee_text(text: str) -> str:
    """Normalize raw bank payee string by removing POS prefixes, store IDs, and noise."""
    if not text or not isinstance(text, str):
        return ""

    cleaned = text.lower().strip()

    # Remove prefixes
    for pat in PREFIX_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # Remove suffixes / store IDs
    for pat in SUFFIX_PATTERNS:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)

    # Replace non-alphanumeric with spaces
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)

    # Collapse multiple whitespaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned or text.lower().strip()

if __name__ == "__main__":
    samples = [
        "SQ *STARBUCKS COFFEE #08492 SAN FRANCISCO CA",
        "TST* CHIPOTLE 1849 SAN FRANCISCO CA",
        "PAYPAL *NETFLIX.COM DIG 800-542-492",
        "DEBIT CARD PURCHASE - TRADER JOE'S #104 OAKLAND CA 09/02",
        "AMAZON.COM*8B9149A AMZN"
    ]
    print("--- Text Cleaning Verification ---")
    for s in samples:
        print(f"Raw:   '{s}'")
        print(f"Clean: '{clean_payee_text(s)}'\n")
