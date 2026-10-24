"""Extract and validate synthetic bank statements."""

from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pdfplumber
from pydantic import BaseModel, ConfigDict, Field


MONEY = Decimal("0.01")
HEADER_PATTERN = re.compile(
    r"Opening\s+Balance.*?Total\s+Debits.*?Total\s+Credits.*?Closing\s+Balance\s+"
    r"\$?([\d,]+\.\d{2})\s+\$?([\d,]+\.\d{2})\s+\$?([\d,]+\.\d{2})\s+\$?([\d,]+\.\d{2})",
    re.IGNORECASE,
)
PII_PATTERN = re.compile(r"(?<!\d)\d{10,16}(?!\d)")
DATE_PATTERN = r"(?:\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})"
AMOUNT_TOKEN = r"(?:\$?[\d,]+\.\d{2}|[-—])"


class Transaction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str
    description: str
    debit: Decimal = Field(default=Decimal("0.00"))
    credit: Decimal = Field(default=Decimal("0.00"))
    balance: Decimal


class Statement(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    transactions: list[Transaction]
    opening_balance: Decimal
    closing_balance: Decimal
    computed_balance: Decimal
    total_debits: Decimal
    total_credits: Decimal
    is_reconciled: bool


def redact_pii(text: str) -> str:
    """Mask account/card numbers containing 10 to 16 consecutive digits."""
    return PII_PATTERN.sub("XXXX-XXXX", text)


def _amount(value: Any) -> Decimal:
    cleaned = re.sub(r"(\d[\d,]*\.)\s+(\d{2})", r"\1\2", str(value or ""))
    match = re.search(r"-?\d[\d,]*(?:\.\d{1,2})?", cleaned.replace("$", ""))
    if not match:
        return Decimal("0.00")
    return Decimal(match.group(0).replace(",", "")).quantize(MONEY, rounding=ROUND_HALF_UP)


def _clean_cell(value: Any) -> str:
    return _normalize_number_breaks(str(value or "")).strip()


def _normalize_number_breaks(text: str) -> str:
    return re.sub(r"(\$?\d[\d,]*\.)\s+(\d{2})\b", r"\1\2", str(text))


def _header_values(pdf: pdfplumber.PDF) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    text = _normalize_number_breaks("\n".join(page.extract_text() or "" for page in pdf.pages))
    match = HEADER_PATTERN.search(text)
    if match:
        return tuple(_amount(group) for group in match.groups())  # type: ignore[return-value]

    def labeled_amount(label: str) -> Decimal | None:
        found = re.search(rf"{label}\s*(?:[:\-]?\s*)({AMOUNT_TOKEN})", text, re.IGNORECASE)
        return _amount(found.group(1)) if found else None

    values = (
        labeled_amount(r"Opening\s+Balance"),
        labeled_amount(r"Total\s+Debits"),
        labeled_amount(r"Total\s+Credits"),
        labeled_amount(r"Closing\s+Balance"),
    )
    return tuple(value if value is not None else Decimal("0.00") for value in values)  # type: ignore[return-value]


def _append_row(extracted: list[dict[str, str]], row: dict[str, str]) -> None:
    if not row["date"]:
        if extracted and row["description"]:
            extracted[-1]["description"] = f"{extracted[-1]['description']} {row['description']}".strip()
        return
    extracted.append(row)


def _transaction_rows(pdf: pdfplumber.PDF) -> list[Transaction]:
    extracted: list[dict[str, str]] = []
    for page in pdf.pages:
        for table in page.extract_tables() or []:
            if not table:
                continue
            header_index = next(
                (
                    index
                    for index, row in enumerate(table[:3])
                    if len(row) >= 5
                    and "date" in _clean_cell(row[0]).lower()
                    and "description" in _clean_cell(row[1]).lower()
                    and "balance" in _clean_cell(row[4]).lower()
                ),
                None,
            )
            if header_index is None:
                continue
            for raw_row in table[header_index + 1 :]:
                cells = list(raw_row) + [""] * (5 - len(raw_row))
                date_text, description, debit, credit, balance = (_clean_cell(cell) for cell in cells[:5])
                if re.fullmatch(DATE_PATTERN, date_text):
                    _append_row(extracted, {"date": date_text, "description": description, "debit": debit, "credit": credit, "balance": balance})
                elif description:
                    _append_row(extracted, {"date": "", "description": description, "debit": "", "credit": "", "balance": ""})

    if extracted:
        valid_date = re.compile(r"^(?:\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})$")
        extracted = [
            row
            for row in extracted
            if valid_date.fullmatch(row.get("date", "").strip())
            and re.search(r"\d", row.get("balance", ""))
        ]
        return [
            Transaction(
                date=row["date"],
                description=redact_pii(row["description"]),
                debit=_amount(row["debit"]),
                credit=_amount(row["credit"]),
                balance=_amount(row["balance"]),
            )
            for row in extracted
        ]

    # Some bank PDFs have no detectable table geometry. Parse the text rows and
    # merge continuation lines until the next date-prefixed transaction.
    for page in pdf.pages:
        for raw_line in (page.extract_text() or "").splitlines():
            line = _normalize_number_breaks(raw_line).strip()
            match = re.match(
                rf"^({DATE_PATTERN})\s+(.+?)\s+({AMOUNT_TOKEN})\s+({AMOUNT_TOKEN})\s+({AMOUNT_TOKEN})\s*$",
                line,
            )
            if match:
                _append_row(
                    extracted,
                    {
                        "date": match.group(1),
                        "description": match.group(2),
                        "debit": match.group(3),
                        "credit": match.group(4),
                        "balance": match.group(5),
                    },
                )
            elif extracted and line and not re.search(r"^(?:Date|Opening Balance|Closing Balance|Total )", line, re.IGNORECASE):
                extracted[-1]["description"] = f"{extracted[-1]['description']} {line}".strip()

    return [
        Transaction(
            date=row["date"],
            description=redact_pii(row["description"]),
            debit=_amount(row["debit"]),
            credit=_amount(row["credit"]),
            balance=_amount(row["balance"]),
        )
        for row in extracted
    ]


def extract_statement(pdf_path: str) -> Statement:
    """Extract a PDF statement and perform an exact cent-level reconciliation."""
    with pdfplumber.open(pdf_path) as pdf:
        opening, header_debits, header_credits, closing = _header_values(pdf)
        transactions = _transaction_rows(pdf)

    if not transactions:
        raise ValueError(f"No transaction rows found in {pdf_path}")
    total_debits = sum((transaction.debit for transaction in transactions), Decimal("0.00")).quantize(MONEY)
    total_credits = sum((transaction.credit for transaction in transactions), Decimal("0.00")).quantize(MONEY)
    if opening == Decimal("0.00") and transactions:
        first = transactions[0]
        opening = (first.balance - first.credit + first.debit).quantize(MONEY)
    if closing == Decimal("0.00") and transactions:
        closing = transactions[-1].balance.quantize(MONEY)
    computed = (opening + total_credits - total_debits).quantize(MONEY, rounding=ROUND_HALF_UP)
    closing = closing.quantize(MONEY, rounding=ROUND_HALF_UP)
    # Header totals are parsed above as a second integrity signal, while the
    # reconciliation itself is intentionally based on extracted transaction rows.
    if header_debits not in {Decimal("0.00"), total_debits} or header_credits not in {Decimal("0.00"), total_credits}:
        raise ValueError(
            f"Transaction totals do not match statement header in {pdf_path}: "
            f"debits {total_debits} vs {header_debits}, credits {total_credits} vs {header_credits}"
        )
    return Statement(
        transactions=transactions,
        opening_balance=opening,
        closing_balance=closing,
        computed_balance=computed,
        total_debits=total_debits,
        total_credits=total_credits,
        is_reconciled=round(computed, 2) == round(closing, 2),
    )


def _summary_row(filename: str, statement: Statement) -> str:
    return (
        f"{filename} | {len(statement.transactions):>4} | "
        f"${statement.opening_balance:>10,.2f} | ${statement.total_debits:>10,.2f} | "
        f"${statement.total_credits:>10,.2f} | ${statement.closing_balance:>10,.2f} | "
        f"{'Yes' if statement.is_reconciled else 'No'}"
    )


def main() -> None:
    sample_dir = Path(__file__).resolve().parent / "sample_data"
    pdf_paths = sorted(sample_dir.glob("*.pdf"))
    if not pdf_paths:
        raise FileNotFoundError(f"No PDFs found in {sample_dir}")

    print("Filename | Rows Extracted | Opening | Debits | Credits | Closing | Reconciled?")
    print("-" * 106)
    for pdf_path in pdf_paths:
        statement = extract_statement(str(pdf_path))
        assert statement.is_reconciled, f"{pdf_path.name} did not reconcile"
        print(_summary_row(pdf_path.name, statement))


if __name__ == "__main__":
    main()
