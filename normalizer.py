"""Normalize noisy bank descriptors into stable merchant records."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from extractor import extract_statement


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = ROOT / "statement_rules.db"
OLLAMA_URL = "http://localhost:11434/api/generate"


class MerchantClassification(BaseModel):
    canonical_name: str = Field(min_length=1)
    category: str = Field(min_length=1)


FALLBACK_MAPPINGS: dict[str, tuple[str, str]] = {
    "blue bottle": ("Blue Bottle Coffee", "Dining"),
    "sharma groceries": ("Sharma Groceries", "Groceries"),
    "streamflix": ("Streamflix", "Subscriptions"),
    "adobe": ("Adobe Creative", "Subscriptions"),
    "cloudvault": ("CloudVault", "Subscriptions"),
    "fitpulse": ("FitPulse App", "Subscriptions"),
    "metro gym": ("Metro Gym", "Health & Fitness"),
    "ridenow": ("RideNow", "Transportation"),
    "greenleaf": ("GreenLeaf Market", "Groceries"),
    "quickfuel": ("QuickFuel Station", "Transportation"),
    "city electric": ("City Electric", "Utilities"),
    "bright mobile": ("Bright Mobile", "Utilities"),
    "cloud kitchen": ("Cloud Kitchen", "Dining"),
    "doordash": ("Cloud Kitchen", "Dining"),
    "book nook": ("Book Nook", "Shopping"),
    "harbor insurance": ("Harbor Insurance", "Insurance"),
    "oak pharmacy": ("Oak Pharmacy", "Healthcare"),
    "northstar airlines": ("Northstar Airlines", "Travel"),
    "acme payroll": ("Acme Payroll", "Income"),
}


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS merchant_rules (
            raw_pattern TEXT PRIMARY KEY,
            canonical_name TEXT,
            category TEXT,
            is_recurring INTEGER
        )
        """
    )
    connection.commit()
    return connection


def clean_merchant_string(desc: str) -> str:
    """Remove bank boilerplate, references, terminal IDs, and formatting noise."""
    text = re.sub(r"<br\s*/?>", " ", desc, flags=re.IGNORECASE)
    text = re.sub(r"\bBANK REF\b.*$", " ", text, flags=re.IGNORECASE)
    text = text.replace("*", " ")
    text = re.sub(r"\b(?:POS\s+DEBIT|ACH\s+WEB|ORIG\s+CO:|DEBIT|CREDIT)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:CARD PURCHASE|MEMBERSHIP|AUTOPAY|ONLINE ORDER|E-TICKET|RX)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:AUTH|TRIAL|SUB)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCUSTOMER\s+REF\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:SQ|UPI|ORIG|CO)\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{3,}\b", " ", text)
    text = re.sub(r"\bREF\s*[A-Z]\b", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[/#:-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -")
    aliases = (
        (r"\bBLUE\s+BOTTLE(?:\s+COFFEE)?\b.*", "BLUE BOTTLE COFFEE"),
        (r"\bSHARMA\s+GROCERIES\b.*", "SHARMA GROCERIES"),
        (r"\bSTREAMFLIX(?:\s+INC)?\b.*", "STREAMFLIX"),
        (r"\bADOBE(?:\s+CREATIVE)?(?:\s+CLOUD)?\b.*", "ADOBE"),
        (r"\bCLOUDVAULT\b.*", "CLOUDVAULT"),
        (r"\bFITPULSE(?:\s+APP)?\b.*", "FITPULSE"),
        (r"\bMETRO\s+GYM\b.*", "METRO GYM"),
        (r"\bRIDENOW\b.*", "RIDENOW"),
        (r"\bGREENLEAF\s+MARKET\b.*", "GREENLEAF MARKET"),
        (r"\bQUICKFUEL\s+STATION\b.*", "QUICKFUEL STATION"),
        (r"\bCITY\s+ELECTRIC\b.*", "CITY ELECTRIC"),
        (r"\bBRIGHT\s+MOBILE\b.*", "BRIGHT MOBILE"),
        (r"\b(?:DOORDASH\s+)?CLOUD\s+KITCHEN\b.*", "CLOUD KITCHEN"),
        (r"\bBOOK\s+NOOK\b.*", "BOOK NOOK"),
        (r"\bHARBOR\s+INSURANCE\b.*", "HARBOR INSURANCE"),
        (r"\bOAK\s+PHARMACY\b.*", "OAK PHARMACY"),
        (r"\bNORTHSTAR\s+AIRLINES\b.*", "NORTHSTAR AIRLINES"),
        (r"\bACME\s+PAYROLL\b.*", "ACME PAYROLL"),
    )
    for pattern, replacement in aliases:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return replacement
    return text


def _fallback_classification(cleaned: str) -> MerchantClassification:
    lowered = cleaned.lower()
    for keyword, (canonical, category) in FALLBACK_MAPPINGS.items():
        if keyword in lowered:
            return MerchantClassification(canonical_name=canonical, category=category)
    return MerchantClassification(canonical_name=cleaned.title() or "Unknown Merchant", category="Other")


def _ollama_classification(cleaned: str) -> MerchantClassification | None:
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
    prompt = (
        "Classify this bank merchant descriptor. Return JSON only with exactly "
        '{"canonical_name":"...","category":"..."}; use concise merchant names and categories '
        f"such as Subscriptions, Dining, Utilities, Groceries, Shopping, or Other. Descriptor: {cleaned}"
    )
    try:
        response = httpx.post(
            OLLAMA_URL,
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=3.0,
        )
        response.raise_for_status()
        payload = response.json()
        raw = payload.get("response", payload)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        return MerchantClassification.model_validate(parsed)
    except (httpx.HTTPError, OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _remember_rule(
    connection: sqlite3.Connection,
    raw_pattern: str,
    classification: MerchantClassification,
) -> None:
    is_recurring = int(classification.category in {"Subscriptions", "Utilities", "Insurance", "Income"})
    connection.execute(
        """
        INSERT OR REPLACE INTO merchant_rules
            (raw_pattern, canonical_name, category, is_recurring)
        VALUES (?, ?, ?, ?)
        """,
        (raw_pattern, classification.canonical_name, classification.category, is_recurring),
    )


def normalize_transactions(transactions: list[dict]) -> list[dict]:
    """Attach canonical merchant metadata, using SQLite, Ollama, then regex fallback."""
    connection = _connect()
    cache: dict[str, MerchantClassification] = {}
    try:
        for transaction in transactions:
            raw_description = str(transaction.get("description", ""))
            cleaned = clean_merchant_string(raw_description)
            if cleaned in cache:
                classification = cache[cleaned]
            else:
                row = connection.execute(
                    "SELECT canonical_name, category FROM merchant_rules WHERE raw_pattern = ?",
                    (cleaned,),
                ).fetchone()
                if row:
                    classification = MerchantClassification(canonical_name=row[0], category=row[1])
                else:
                    classification = _ollama_classification(cleaned) or _fallback_classification(cleaned)
                    _remember_rule(connection, cleaned, classification)
                    connection.commit()
                cache[cleaned] = classification

            transaction["canonical_merchant"] = classification.canonical_name
            transaction["category"] = classification.category
            transaction["has_trial_token"] = bool(
                re.search(r"\b(?:TRIAL|FREE\s+TRIAL|AUTH)\b", raw_description, re.IGNORECASE)
            )
    finally:
        connection.close()
    return transactions


def main() -> None:
    sample_dir = ROOT / "sample_data"
    transactions: list[dict] = []
    for pdf_path in sorted(sample_dir.glob("*.pdf")):
        statement = extract_statement(str(pdf_path))
        transactions.extend(transaction.model_dump(mode="json") for transaction in statement.transactions)

    normalized = normalize_transactions(transactions)
    merchants = Counter((item["canonical_merchant"], item["category"]) for item in normalized)
    print(f"Total Transactions: {len(normalized)} | Unique Merchants Identified: {len({name for name, _ in merchants})}")
    print("Merchant | Category | Transactions")
    print("-" * 48)
    for (merchant, category), count in merchants.most_common(10):
        print(f"{merchant} | {category} | {count}")


if __name__ == "__main__":
    main()
