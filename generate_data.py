"""Generate deterministic, synthetic monthly bank statements for testing."""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import LongTable, Paragraph, SimpleDocTemplate, Spacer, TableStyle


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "sample_data"
MONEY = Decimal("0.01")
SEED = 20261023


MERCHANTS = [
    ("Blue Bottle Coffee", "debit", (5, 18)),
    ("Sharma Groceries", "debit", (35, 125)),
    ("Streamflix", "debit", (15.49, 15.49)),
    ("Adobe Creative", "debit", (19.99, 19.99)),
    ("CloudVault", "debit", (29, 29)),
    ("FitPulse App Trial", "debit", (14.99, 14.99)),
    ("Metro Gym", "debit", (45, 45)),
    ("RideNow", "debit", (12, 48)),
    ("GreenLeaf Market", "debit", (25, 95)),
    ("QuickFuel Station", "debit", (35, 72)),
    ("City Electric", "debit", (60, 145)),
    ("Bright Mobile", "debit", (75, 95)),
    ("Cloud Kitchen", "debit", (18, 46)),
    ("Book Nook", "debit", (12, 38)),
    ("Harbor Insurance", "debit", (110, 110)),
    ("Oak Pharmacy", "debit", (8, 55)),
    ("Northstar Airlines", "debit", (90, 320)),
    ("Acme Payroll", "credit", (3200, 3200)),
]


def money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


def descriptor(merchant: str, rng: random.Random, sequence: int) -> str:
    ref = f"{rng.randint(1000, 9999)}"
    variants = {
        "Blue Bottle Coffee": f"POS DEBIT {ref} SQ *BLUE BOTTLE COFFEE",
        "Sharma Groceries": f"UPI/{rng.randint(100000, 999999)}/SHARMA GROCERIES",
        "Streamflix": f"ACH WEB STREAMFLIX INC {ref}",
        "Adobe Creative": f"ADOBE *CREATIVE CLOUD {ref}",
        "CloudVault": f"ORIG CO: CLOUDVAULT FREE TRIAL {ref}",
        "FitPulse App Trial": f"FITPULSE APP TRIAL AUTH {ref}",
        "Metro Gym": f"POS DEBIT {ref} METRO GYM MEMBERSHIP",
        "RideNow": f"RIDENOW MOBILITY TRIP {ref}",
        "GreenLeaf Market": f"GREENLEAF MARKET #{ref} POS",
        "QuickFuel Station": f"QUICKFUEL STATION {ref} CARD PURCHASE",
        "City Electric": f"ACH CITY ELECTRIC UTILITIES {ref}",
        "Bright Mobile": f"BRIGHT MOBILE AUTOPAY {ref}",
        "Cloud Kitchen": f"DOORDASH CLOUD KITCHEN ORDER {ref}",
        "Book Nook": f"BOOK NOOK ONLINE ORDER {ref}",
        "Harbor Insurance": f"ACH HARBOR INSURANCE PREMIUM {ref}",
        "Oak Pharmacy": f"OAK PHARMACY RX {ref}",
        "Northstar Airlines": f"NORTHSTAR AIRLINES E-TICKET {ref}",
        "Acme Payroll": f"ACME PAYROLL DIRECT DEP {ref}",
    }
    text = variants[merchant]
    if sequence % 4 == 0:
        text += " / CUSTOMER REF"
    return text


def make_transactions(month: str, rng: random.Random) -> list[dict]:
    year, month_number = map(int, month.split("-"))
    start = date(year, month_number, 2)
    rows: list[dict] = []

    # Keep the recurring and anomaly-bearing merchants visible in every month.
    required = [
        ("Acme Payroll", 1),
        ("Streamflix", 5),
        ("Adobe Creative", 7),
        ("CloudVault", 9),
        ("FitPulse App Trial", 11),
        ("Metro Gym", 13),
    ]
    for merchant, day in required:
        if merchant == "Streamflix":
            amount = 18.99 if month == "2026-10" else 15.49
        elif merchant == "Adobe Creative":
            amount = 22.99 if month == "2026-10" else 19.99
        elif merchant == "CloudVault":
            amount = 1.00 if month == "2026-08" else 29.00
        elif merchant == "FitPulse App Trial":
            amount = 0.00 if month == "2026-08" else 14.99
        elif merchant == "Metro Gym":
            amount = 45.00
        else:
            amount = 3250.00
        rows.append(
            {
                "date": start + timedelta(days=day),
                "description": descriptor(merchant, rng, len(rows)),
                "merchant": merchant,
                "debit": money(amount) if merchant != "Acme Payroll" else money(0),
                "credit": money(amount) if merchant == "Acme Payroll" else money(0),
                "reference": descriptor(merchant, rng, len(rows))[-4:],
            }
        )

    # The duplicate is deliberately same-day, same-amount, different reference.
    if month == "2026-10":
        duplicate_date = start + timedelta(days=13)
        for suffix in ("A", "B"):
            rows.append(
                {
                    "date": duplicate_date,
                    "description": f"POS DEBIT {rng.randint(1000, 9999)} METRO GYM MEMBERSHIP REF {suffix}",
                    "merchant": "Metro Gym",
                    "debit": money(45),
                    "credit": money(0),
                    "reference": suffix,
                }
            )

    ordinary_merchants = [merchant for merchant, _, _ in MERCHANTS if merchant not in {"Acme Payroll"}]
    while len(rows) < 44:
        merchant = rng.choice(ordinary_merchants)
        if merchant in {"Streamflix", "Adobe Creative", "CloudVault", "FitPulse App Trial", "Metro Gym"}:
            continue
        day = rng.randint(1, 27)
        low, high = next(item[2] for item in MERCHANTS if item[0] == merchant)
        amount = money(rng.uniform(float(low), float(high)))
        rows.append(
            {
                "date": date(year, month_number, day),
                "description": descriptor(merchant, rng, len(rows)),
                "merchant": merchant,
                "debit": amount,
                "credit": money(0),
                "reference": str(rng.randint(1000, 9999)),
            }
        )

    rows.sort(key=lambda row: (row["date"], row["description"]))
    for index, row in enumerate(rows):
        row["transaction_id"] = f"{month.replace('-', '')}-{index + 1:03d}"
    return rows


def render_statement(month: str, transactions: list[dict], opening: Decimal, wrapped_ids: set[str]) -> tuple[Decimal, Decimal]:
    closing = opening
    total_debits = money(0)
    total_credits = money(0)
    for row in transactions:
        total_debits += row["debit"]
        total_credits += row["credit"]
        closing += row["credit"] - row["debit"]
        row["balance"] = closing

    output_path = OUTPUT_DIR / f"{month.replace('-', '_')}_statement.pdf"
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.2, leading=8.5, alignment=TA_LEFT)
    right = ParagraphStyle("Right", parent=body, alignment=TA_RIGHT)
    header = ParagraphStyle("Header", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=colors.HexColor("#15395b"))
    small = ParagraphStyle("Small", parent=body, fontSize=8.5, leading=11)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=0.38 * inch,
        leftMargin=0.38 * inch,
        topMargin=0.4 * inch,
        bottomMargin=0.4 * inch,
        title=f"StatementSloth {month}",
    )
    story = [
        Paragraph("StatementSloth Bank", header),
        Paragraph(f"Account ending in 4821 &nbsp;&nbsp; | &nbsp;&nbsp; Statement period: {month}", small),
        Spacer(1, 8),
    ]
    summary = [
        ["Opening Balance", "Total Debits", "Total Credits", "Closing Balance"],
        [f"${opening:,.2f}", f"${total_debits:,.2f}", f"${total_credits:,.2f}", f"${closing:,.2f}"],
    ]
    summary_table = LongTable(summary, colWidths=[1.7 * inch] * 4)
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dce8f2")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#15395b")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8ca6bb")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([summary_table, Spacer(1, 12)])

    data = [["Date", "Description", "Debit", "Credit", "Balance"]]
    for row in transactions:
        description = row["description"]
        if row["transaction_id"] in wrapped_ids:
            description = description.replace(" ", " ", 2) + "<br/>" + "BANK REF " + row["reference"]
        data.append(
            [
                row["date"].strftime("%m/%d/%Y"),
                Paragraph(description, body),
                Paragraph(f"${row['debit']:,.2f}" if row["debit"] else "-", right),
                Paragraph(f"${row['credit']:,.2f}" if row["credit"] else "-", right),
                Paragraph(f"${row['balance']:,.2f}", right),
            ]
        )
    table = LongTable(data, repeatRows=1, colWidths=[0.78 * inch, 3.55 * inch, 0.85 * inch, 0.85 * inch, 1.0 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#15395b")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#afbbc4")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7f9")]),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(table)
    doc.build(story)
    return total_debits, total_credits


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    months = ["2026-08", "2026-09", "2026-10"]
    opening = money("2500.00")
    ground_truth: dict = {
        "account": "Synthetic StatementSloth checking account ending in 4821",
        "months": {},
        "anomalies": [
            {
                "id": "streamflix-price-creep",
                "type": "silent_subscription_price_creep",
                "merchant": "Streamflix",
                "details": "Monthly charge rises from $15.49 in August and September to $18.99 in October.",
            },
            {
                "id": "adobe-creative-price-creep",
                "type": "silent_subscription_price_creep",
                "merchant": "Adobe Creative",
                "details": "Monthly charge rises from $19.99 in August and September to $22.99 in October.",
            },
            {
                "id": "cloudvault-trial-conversion",
                "type": "forgotten_free_trial_conversion",
                "merchant": "CloudVault",
                "details": "A $1.00 trial authorization in August is followed by $29.00 charges in September and October.",
            },
            {
                "id": "fitpulse-trial-conversion",
                "type": "forgotten_free_trial_conversion",
                "merchant": "FitPulse App Trial",
                "details": "A $0.00 trial authorization in August converts to $14.99 charges in September and October.",
            },
            {
                "id": "metro-gym-duplicate",
                "type": "duplicate_charge",
                "merchant": "Metro Gym",
                "details": "October contains two same-day $45.00 charges with different reference numbers.",
            },
        ],
    }

    for month in months:
        transactions = make_transactions(month, rng)
        wrapped_ids = {row["transaction_id"] for row in transactions[:11]}
        total_debits, total_credits = render_statement(month, transactions, opening, wrapped_ids)
        closing = money(opening + total_credits - total_debits)
        ground_truth["months"][month] = {
            "file": f"{month.replace('-', '_')}_statement.pdf",
            "transaction_count": len(transactions),
            "wrapped_description_count": len(wrapped_ids),
            "opening_balance": f"{opening:.2f}",
            "total_debits": f"{total_debits:.2f}",
            "total_credits": f"{total_credits:.2f}",
            "closing_balance": f"{closing:.2f}",
            "reconciles": opening + total_credits - total_debits == closing,
            "transactions": [
                {
                    "transaction_id": row["transaction_id"],
                    "date": row["date"].isoformat(),
                    "merchant": row["merchant"],
                    "description": row["description"],
                    "debit": f"{row['debit']:.2f}",
                    "credit": f"{row['credit']:.2f}",
                    "balance": f"{row['balance']:.2f}",
                    "reference": row["reference"],
                }
                for row in transactions
            ],
        }
        opening = closing

    (OUTPUT_DIR / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")
    print(f"Created {len(months)} PDF statements and ground_truth.json in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
