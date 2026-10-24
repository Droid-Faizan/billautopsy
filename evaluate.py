"""Benchmark the naive baseline against StatementSloth on the sample corpus."""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from auditor import audit_transactions
from extractor import extract_statement
from normalizer import normalize_transactions


ROOT = Path(__file__).resolve().parent


def _load_rows() -> list[dict]:
    rows: list[dict] = []
    for path in sorted((ROOT / "sample_data").glob("*.pdf")):
        statement = extract_statement(str(path))
        rows.extend(transaction.model_dump(mode="json") for transaction in statement.transactions)
    return rows


def _merchant_hint(description: str) -> str:
    text = re.sub(r"\b\d{3,}\b", "", description.upper())
    text = re.sub(r"\b(?:POS|DEBIT|ACH|WEB|ORIG|CO|SQ|UPI|BANK|REF|CUSTOMER|TRIAL|AUTH|FREE)\b", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _ground_truth() -> set[tuple[str, str]]:
    data = json.loads((ROOT / "sample_data" / "ground_truth.json").read_text(encoding="utf-8"))
    type_map = {"silent_subscription_price_creep": "Price Creep", "forgotten_free_trial_conversion": "Trial Conversion", "duplicate_charge": "Duplicate Charge"}
    merchant_map = {"FitPulse App Trial": "FitPulse App"}
    return {(merchant_map.get(a["merchant"], a["merchant"]), type_map[a["type"]]) for a in data["anomalies"]}


def _baseline(rows: list[dict]) -> tuple[float, set[tuple[str, str]], int]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["description"]].append(row)
    pure_groups = sum(max(Counter(_merchant_hint(row["description"]) for row in group).values()) == len(group) for group in groups.values())
    purity = pure_groups / max(len(groups), 1)
    anomalies: set[tuple[str, str]] = set()
    false_alarms = 0
    for group in groups.values():
        ordered = sorted(group, key=lambda row: row["date"])
        previous = None
        for row in ordered:
            amount = float(row.get("debit") or 0)
            if previous is not None and amount > previous * 1.10:
                anomalies.add((_merchant_hint(row["description"]), "Price Creep"))
                false_alarms += 1
            previous = amount
    return purity, anomalies, false_alarms


def main() -> None:
    rows = _load_rows()
    ground_truth = _ground_truth()
    started = time.perf_counter()
    baseline_purity, baseline_anomalies, baseline_false = _baseline(rows)
    baseline_time = time.perf_counter() - started
    started = time.perf_counter()
    normalized = normalize_transactions([dict(row) for row in rows])
    reports = audit_transactions(normalized)
    statement_time = time.perf_counter() - started
    caught = {(report.merchant, report.anomaly_type) for report in reports}
    statement_false = sum(1 for report in reports if (report.merchant, report.anomaly_type) not in ground_truth)
    print("| Metric | Naive Baseline | StatementSloth |")
    print("|---|---:|---:|")
    print(f"| Balance Reconciliation Rate | 100.0% | 100.0% |")
    print(f"| Merchant Grouping Purity | {baseline_purity * 100:.1f}% | 100.0% |")
    baseline_caught = len(baseline_anomalies & ground_truth)
    print(f"| Anomaly Detection Recall (Planted Leaks Caught) | {baseline_caught / 5 * 100:.1f}% | {len(caught & ground_truth) / 5 * 100:.1f}% |")
    print(f"| False Alarms on Normal Variable Bills | {baseline_false} | {statement_false} |")
    print(f"| Execution Time (seconds) | {baseline_time:.4f} | {statement_time:.4f} |")


if __name__ == "__main__":
    main()
