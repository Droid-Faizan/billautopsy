# BillAutopsy

**Cut open your bank statements. Find what’s quietly bleeding your wallet.**

BillAutopsy is a local-first bank statement auditor. It extracts PDF tables, normalizes noisy merchant descriptors, and audits recurring charges without sending statements to an external server.

## Four-stage architecture

1. **Extract** — `extractor.py` uses pdfplumber to read balance headers and transaction tables, merging wrapped descriptions and checking cent-level reconciliation.
2. **Normalize** — `normalizer.py` cleans bank descriptor noise, remembers merchant rules in SQLite, and optionally asks local Ollama for unknown vendors before using deterministic fallback mappings.
3. **Audit** — `auditor.py` uses pandas features and optional TabPFN availability to detect duplicate charges, trial conversions, and subscription price creep.
4. **Present** — `app.py` serves the BillAutopsy dashboard, local PDF upload flow, category-rule persistence, CSV export, and printable executive report.

## 60-second local quickstart

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python generate_data.py
python app.py
```

Open <http://127.0.0.1:8000>. Click **Run 3-Month Demo (Offline)** or upload PDF statements. All processing stays on the local machine; Ollama is optional and the normalizer always has a deterministic fallback.

## Benchmark

Run `python evaluate.py` to regenerate this comparison on `sample_data/`.

| Metric | Naive Baseline | StatementSloth |
|---|---:|---:|
| Balance Reconciliation Rate | 100.0% | 100.0% |
| Merchant Grouping Purity | 100.0% | 100.0% |
| Anomaly Detection Recall (Planted Leaks Caught) | 0.0% | 100.0% |
| False Alarms on Normal Variable Bills | 0 | 1 |
| Execution Time (seconds) | ~0.01 | ~0.38 |

The one StatementSloth false alarm is the intentionally incidental two-day Harbor Insurance duplicate surfaced by the deterministic duplicate rule; the five planted ground-truth anomalies are all caught.
