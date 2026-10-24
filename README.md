# BillAutopsy

*Cut open your bank statements. Find what's quietly bleeding your wallet.*

## What It Is & Why It Runs Locally

BillAutopsy is a local-first bank statement auditor for the messy reality of PDF exports. It reconstructs shattered multi-line PDF bank tables, normalizes noisy merchant descriptors, and checks balances down to the exact cent. It then looks for the leaks that are easiest to miss: silent subscription price creep and forgotten free-trial conversions.

Your bank statement contains sensitive information such as account numbers, balances, transaction history, and sometimes your home address. BillAutopsy processes those PDFs 100% locally on your machine instead of asking you to upload them to a public cloud server. The only network service is optional local Ollama, if you choose to enable it; the core workflow works offline.

## Do I Need to Install Heavy AI Models to Try It?

**No. Only Python 3.10+ is required.** The lightweight core dependencies in `requirements.txt` install in approximately 10 seconds and work 100% offline out of the box. You do not need Ollama, PyTorch, a GPU, or a downloaded model to run the demo.

Local Ollama (`gemma3:4b` or `qwen2.5:0.5b`) and `tabpfn` are optional plug-in upgrades. If they are not installed or available, BillAutopsy uses deterministic local fallback logic.

## Step-by-Step Setup Guide

### 1. Clone the repository

```bash
git clone https://github.com/Droid-Faizan/billautopsy.git
cd billautopsy
```

### 2. Create and activate a virtual environment

All platforms:

```bash
python -m venv .venv
```

Windows Command Prompt:

```bat
.\.venv\Scripts\activate.bat
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
source .venv/bin/activate
```

### 3. Install the lightweight requirements

```bash
pip install -r requirements.txt
```

### 4. Generate data and launch BillAutopsy

```bash
python generate_data.py
python app.py
```

Open <http://127.0.0.1:8000> in your browser.

## What to Test in 60 Seconds

1. **3-Month Offline Demo** — Click **Run 3-Month Demo (Offline)** to audit 132 transactions across 3 statements. The demo has a `$0.00` balance discrepancy and `$748.88/yr` in detected leaks.
2. **Live Drag-and-Drop PDF Upload** — Drag any statement PDF into the dashed dropzone. The balance banner, leak cards, and transaction table replace themselves dynamically with the newly uploaded file's results.
3. **Category Memory & Exports** — Change a merchant's category in the dropdown; the mapping is persisted in local SQLite. Then try **Download Clean CSV** or **Print / Save 1-Page Audit PDF** for the executive summary.

## Optional Open-Source AI Upgrades

These are optional; the default workflow remains offline and deterministic.

```bash
# Choose one local Ollama model:
ollama pull gemma3:4b
# or:
ollama pull qwen2.5:0.5b

# Optional tabular modeling upgrade:
pip install tabpfn
```

Ollama should be running locally when the normalizer uses it. If it is offline or times out, merchant normalization continues with the built-in regex and keyword mappings.

## Four-Stage Architecture

1. **Extract** — `extractor.py` uses pdfplumber to read balance headers and transaction tables, repair wrapped currency values, merge continuation lines, and verify cent-level reconciliation.
2. **Normalize** — `normalizer.py` cleans bank descriptor noise, remembers merchant rules in SQLite, and optionally asks local Ollama for unknown vendors before using deterministic fallback mappings.
3. **Audit** — `auditor.py` uses pandas features and optional TabPFN availability to detect duplicate charges, trial conversions, and subscription price creep.
4. **Present** — `app.py` serves the BillAutopsy dashboard, local PDF upload flow, category-rule persistence, CSV export, and printable executive report.

## Benchmark

Run `python evaluate.py` to regenerate this comparison on `sample_data/`.

| Metric | Naive Baseline | BillAutopsy |
|---|---:|---:|
| Balance Reconciliation Rate | 100.0% | 100.0% |
| Merchant Grouping Purity | 100.0% | 100.0% |
| Anomaly Detection Recall (Planted Leaks Caught) | 0.0% | 100.0% |
| False Alarms on Normal Variable Bills | 0 | 1 |
| Execution Time (seconds) | ~0.01 | ~0.38 |

The one BillAutopsy false alarm is the intentionally incidental two-day Harbor Insurance duplicate surfaced by the deterministic duplicate rule; all five planted ground-truth anomalies are caught.
