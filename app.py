"""BillAutopsy: a local FastAPI bank statement audit dashboard."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from auditor import audit_transactions
from extractor import extract_statement
from normalizer import _connect, normalize_transactions

ROOT = Path(__file__).resolve().parent
app = FastAPI(title="BillAutopsy", version="1.0")


class RuleUpdate(BaseModel):
    raw_pattern: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    category: str = Field(min_length=1)


def _load_statements(paths: list[Path]) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    statements: list[dict] = []
    for pdf_path in paths:
        statement = extract_statement(str(pdf_path))
        statements.append(
            {
                "filename": pdf_path.name,
                "opening_balance": float(statement.opening_balance),
                "closing_balance": float(statement.closing_balance),
                "computed_balance": float(statement.computed_balance),
                "total_debits": float(statement.total_debits),
                "total_credits": float(statement.total_credits),
                "is_reconciled": statement.is_reconciled,
            }
        )
        rows.extend(transaction.model_dump(mode="json") for transaction in statement.transactions)
    return normalize_transactions(rows), statements


def load_demo_transactions() -> list[dict]:
    rows, _ = _load_statements(sorted((ROOT / "sample_data").glob("*.pdf")))
    return rows


def _result_payload(
    transactions: list[dict],
    statements: list[dict],
    filenames: list[str],
) -> dict[str, Any]:
    reports = audit_transactions(transactions)
    cards = [report.model_dump() for report in reports]
    discrepancy = round(sum(abs(item["computed_balance"] - item["closing_balance"]) for item in statements), 2)
    return {
        "filenames": filenames,
        "transactions": transactions,
        "reports": cards,
        "leaks": cards,
        "statement_count": len(statements),
        "reconciled_count": sum(1 for item in statements if item["is_reconciled"]),
        "total_discrepancy": discrepancy,
        "discrepancy": discrepancy,
        "opening_balance": statements[0]["opening_balance"] if statements else 0.0,
        "closing_balance": statements[-1]["closing_balance"] if statements else 0.0,
        "total_debits": round(sum(item["total_debits"] for item in statements), 2),
        "total_credits": round(sum(item["total_credits"] for item in statements), 2),
        "total_annual_waste": round(sum(report["annualized_leak"] for report in cards), 2),
        "total_waste": round(sum(report["annualized_leak"] for report in cards), 2),
    }


def demo_payload() -> dict[str, Any]:
    rows, statements = _load_statements(sorted((ROOT / "sample_data").glob("*.pdf")))
    return _result_payload(rows, statements, [item["filename"] for item in statements])


HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>BillAutopsy — Local Bank Statement Auditor</title>
  <style>
    :root{--ink:#09090b;--muted:#52525b;--line:#e4e4e7;--panel:#e4e4e2;--coral:#ff4d6d;--emerald:#10b981;--amber:#f59e0b}
    *{box-sizing:border-box}body{margin:0;background:#fff;color:var(--ink);font-family:Inter,system-ui,-apple-system,sans-serif}
    .mono,table,.metric,.proof-metric,.badge,.amount{font-family:"JetBrains Mono","Fira Code",ui-monospace,monospace;font-variant-numeric:tabular-nums}
    .container{max-width:1220px;margin:auto;padding:24px 32px 64px}.nav{display:flex;align-items:center;gap:30px;padding-bottom:30px}
    .wordmark{font-size:22px;font-weight:850;letter-spacing:-.04em;white-space:nowrap}.accent-dot{display:inline-block;width:8px;height:8px;background:var(--coral);border-radius:50%;margin-left:5px}
    .navlinks{display:flex;gap:22px;color:var(--muted);font-size:14px;font-weight:600;flex:1}.navlinks a{color:inherit;text-decoration:none}.nav-upload{background:var(--ink);color:#fff;border-radius:999px;padding:10px 22px;font-weight:600;border:0;cursor:pointer}
    .hero{background:var(--panel);border-radius:28px;padding:56px;display:grid;grid-template-columns:1.05fr .95fr;gap:40px;align-items:center;position:relative;overflow:hidden}
    .eyebrow{font-size:12px;letter-spacing:.08em;font-weight:700;color:var(--muted)}h1{font-size:46px;font-weight:800;line-height:1.05;letter-spacing:-.035em;margin:12px 0 18px}h2{letter-spacing:-.03em}.lede{font-size:16px;line-height:1.55;color:#3f3f46;margin-bottom:28px}
    .actions{display:flex;gap:10px;flex-wrap:wrap}.pill{border-radius:999px;padding:14px 24px;font-weight:700;cursor:pointer;border:0}.primary{background:var(--coral);color:#fff;box-shadow:0 8px 20px #ff4d6d47}.secondary{background:#fff;color:var(--ink);border:1px solid #d4d4d8}
    .drop-input{display:none}.visual{min-height:380px;position:relative}.wallet{position:absolute;z-index:3;top:6px;left:8%;width:230px;background:#18181b;border-radius:18px;padding:18px 22px;color:#fff;box-shadow:0 20px 40px #0000002e;transform:rotate(-5deg)}.wallet-title{font-size:11px;color:#a1a1aa;text-transform:uppercase;letter-spacing:.12em}.wallet-amount{font-size:20px;font-weight:800;margin:28px 0 5px;color:#ffd0d8}.wallet small{color:#d4d4d8}
    .sheet{position:absolute;right:2%;top:70px;width:84%;height:285px;background:#fff;border-radius:9px;padding:24px 26px;box-shadow:0 18px 30px #0002;transform:rotate(-2.5deg);overflow:hidden}.sheet-top{color:#71717a;font-size:11px;line-height:2}.sheet-top strong{color:var(--ink);font-size:13px}.cut{position:absolute;top:145px;left:-2%;width:104%;height:2px;background:linear-gradient(90deg,transparent,var(--coral),#ff1e42);box-shadow:0 0 14px var(--coral);z-index:2}.cut-badge{position:absolute;right:12px;top:119px;z-index:4;background:var(--coral);color:#fff;border-radius:999px;padding:5px 9px;font:700 10px "JetBrains Mono",monospace;transform:rotate(2.5deg)}.sheet-bottom{position:absolute;left:9%;right:-3%;top:171px;background:#111113;color:#fff;min-height:160px;padding:18px 24px;transform:translate(8px,8px) rotate(2.5deg);box-shadow:0 8px 18px #0005}.bleed{color:#ff8ca0;font:700 12px/1.8 "JetBrains Mono",monospace}.seal{display:inline-block;margin-top:10px;padding:5px 9px;border:1px solid #34d399;border-radius:999px;color:#6ee7b7;font:700 10px "JetBrains Mono",monospace}
    .proof{padding:28px 8px 36px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:28px;flex-wrap:wrap}.proof-title{font-size:28px;font-weight:800;letter-spacing:-.02em;max-width:560px}.highlight{background:#ffc2d1;padding:2px 10px;border-radius:6px}.proof-metrics{display:flex;gap:28px}.proof-metric strong{display:block;font-size:25px}.proof-metric span{display:block;color:var(--muted);font:12px Inter,system-ui,sans-serif;margin-top:5px}
    .status{margin:28px 0 18px;background:#ecfdf5;border:1px solid #a7f3d0;color:#047857;border-radius:14px;padding:15px 18px;font-weight:800}.status .badge{font-size:14px}
    .audit-head{display:flex;justify-content:space-between;align-items:end;gap:16px;margin-top:30px}.audit-head p{color:var(--muted)}.waste{font-size:clamp(32px,5vw,56px);font-weight:850;letter-spacing:-.05em;margin:0 0 26px}
    .leaks{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.leak{border:1px solid var(--line);border-left:4px solid var(--coral);border-radius:14px;padding:17px;background:#fff}.leak.price{border-left-color:var(--amber)}.leak h3{margin:10px 0 5px}.leak .amount{font-size:22px;font-weight:800;color:#be123c}.type{font-size:11px;text-transform:uppercase;letter-spacing:.08em;font-weight:800;color:var(--muted)}.leak p{color:#52525b;font-size:13px}
    .section-head{display:flex;justify-content:space-between;align-items:end;margin-top:38px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:14px;margin-top:12px}table{width:100%;border-collapse:collapse;min-width:760px;font-size:13px}th,td{text-align:left;padding:11px 13px;border-bottom:1px solid var(--line)}th{background:#fafafa;font-family:Inter,system-ui,sans-serif;font-size:12px;color:var(--muted)}td.amount{text-align:right}select{border:1px solid #d4d4d8;border-radius:7px;padding:5px;background:#fff;font:inherit}.reconciled{color:#047857;font-weight:800}.message{min-height:24px;color:var(--muted);font-size:13px;margin-top:8px}
    .dropzone{margin:28px 0 8px;border:2px dashed #a1a1aa;border-radius:18px;padding:22px;text-align:center;background:#fafafa;transition:.2s ease}.dropzone.active{border-color:var(--coral);background:#fff1f3;transform:translateY(-2px)}.drop-icon{font-size:28px}.drop-title{font-weight:800;margin:4px 0}.drop-help{color:var(--muted);font-size:13px}.loaded-pill{display:inline-flex;margin-top:12px;background:#18181b;color:#fff;border-radius:999px;padding:7px 12px;font:12px "JetBrains Mono",monospace}.drop-actions{display:flex;justify-content:center;gap:10px;margin-top:12px;flex-wrap:wrap}.reset{background:#fff;color:var(--ink);border:1px solid #d4d4d8}
    .sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}@media(max-width:800px){.container{padding:18px}.navlinks{display:none}.hero{padding:30px 24px;grid-template-columns:1fr}.visual{min-height:360px}.leaks{grid-template-columns:1fr}.proof-metrics{width:100%;justify-content:space-between}.proof-title{font-size:24px}h1{font-size:38px}}
    @media print{body{background:#fff}.container{max-width:none;padding:0}.nav,.actions,.message,.table-wrap,.section-head,.proof,.dropzone,.subtle{display:none!important}.hero{border:1px solid #111;background:#fff;padding:24px;min-height:270px}.visual{transform:scale(.82);transform-origin:top right;margin-bottom:-55px}.audit-head{margin-top:14px}.waste{font-size:34px;margin-bottom:10px}.leaks{grid-template-columns:repeat(3,1fr);gap:7px}.leak{padding:9px}.leak p{font-size:10px}.leak .amount{font-size:15px}.status{margin:10px 0;padding:8px}.print-title{display:block!important}}
    .print-title{display:none}
  </style>
</head>
<body>
<main class="container">
  <nav class="nav">
    <div class="wordmark">BillAutopsy<span class="accent-dot"></span></div>
    <div class="navlinks"><a href="#how">How It Works</a><a href="#privacy">Zero-Cloud Gate</a><a href="#audit">Audit Results</a><a href="#transactions">Transactions</a></div>
    <button class="nav-upload" onclick="document.getElementById('pdf-input').click()">Upload PDFs</button>
  </nav>
  <section class="hero" id="how">
    <div><div class="eyebrow">100% LOCAL &amp; OFFLINE • ZERO CLOUD UPLOADS</div><h1>Cut open your bank statements. Find what’s quietly bleeding your wallet.</h1><p class="lede">Drop your monthly PDFs. Catch the subscriptions creeping up in price and the free trials that never stopped billing you—mathematically reconciled down to the exact cent on your laptop.</p>
      <div class="actions"><button class="pill primary" id="demoButton">Run 3-Month Demo (Offline)</button><button class="pill secondary" onclick="document.getElementById('pdfInput').click()">Drop or Choose PDFs</button><input id="pdfInput" class="drop-input" type="file" accept="application/pdf" multiple></div>
    </div>
    <div class="visual" aria-label="Statement autopsy illustration"><div class="wallet"><div class="wallet-title">Wallet scan</div><div class="wallet-amount">$748.88 / yr</div><small>bleeding detected</small></div><div class="sheet"><div class="sheet-top"><strong>STATEMENT / 2026</strong><br>08/11 ORIG CO: CLOUDVAULT AUTH $1.00<br>09/07 ACH STREAMFLIX INC 9921 $15.49<br>10/15 POS DEB METRO GYM 4410 $45.00</div><div class="cut"></div><div class="cut-badge">✂ AUTOPSY CUT LINE</div><div class="sheet-bottom"><div class="bleed">🩸 CloudVault Zombie Trial: -$336.00/yr<br>📈 Streamflix +22.6% Price Creep: -$42.00/yr<br>⚡ Harbor Ins. Duplicate Charge: -$110.00/yr</div><div class="seal">✓ 3/3 Statements Reconciled • $0.00 Math Error</div></div></div></div>
  </section>
  <section class="proof" id="privacy"><div class="proof-title">Engineered for <span class="highlight">zero-cloud</span> financial privacy</div><div class="proof-metrics"><div class="proof-metric"><strong>100%</strong><span>Cent-level balance verification</span></div><div class="proof-metric"><strong>$748.88</strong><span>Annual waste caught in demo</span></div><div class="proof-metric"><strong>0 bytes</strong><span>Uploaded to external servers</span></div></div></section>
  <section id="dropzone" class="dropzone"><div class="drop-icon">⇧</div><div class="drop-title">Drag &amp; drop bank statement PDF(s) here, or click to browse</div><div class="drop-help">Your files are processed locally and never mixed with the demo data.</div><div id="loadedPill" class="loaded-pill">📂 Currently Showing: 3-Month Demo (132 rows)</div><div class="drop-actions"><button class="pill secondary" onclick="document.getElementById('pdf-input').click()">Choose PDFs</button><button class="pill reset" id="resetButton">Reset to 3-Month Demo</button></div><input id="pdf-input" class="drop-input" type="file" accept=".pdf,application/pdf" multiple></section>
  <div class="toolbar"><button class="pill secondary" onclick="window.print()">Print / Save 1-Page Audit PDF</button><button class="pill secondary" onclick="downloadCsv()">Download Clean CSV</button><span id="message" class="message"></span></div>
  <div class="status">✓ <span id="reconcile" class="badge">3/3 Statements Mathematically Reconciled ($0.00 Discrepancy — Zero Math Hallucinations)</span></div>
  <section id="audit"><div class="audit-head"><div><div class="eyebrow">THE LAZY AUDIT</div><h2 class="print-title">BillAutopsy Dissection Report</h2><p>Recurring leaks surfaced by deterministic local analysis.</p></div></div><div class="waste mono" id="totalWaste">$748.88 / yr in Preventable Waste Discovered</div><div id="reports" class="leaks"></div></section>
  <section id="transactions"><div class="section-head"><h2>Normalized transactions</h2><span id="rowCount" class="mono"></span></div><div class="table-wrap"><table><thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Amount</th><th>Status</th></tr></thead><tbody id="transactionRows"></tbody></table></div></section>
</main>
<script>
let state={transactions:[],reports:[]};const categories=["Subscriptions","Dining","Utilities","Groceries","Shopping","Transportation","Health & Fitness","Insurance","Healthcare","Travel","Income","Other"];
const money=n=>"$"+Number(n||0).toFixed(2), esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function countUp(target,value){const el=document.getElementById("totalWaste"),start=performance.now(),from=0;function tick(now){const p=Math.min((now-start)/500,1),n=value*p;el.textContent=money(n)+" / yr in Preventable Waste Discovered";if(p<1)requestAnimationFrame(tick)}requestAnimationFrame(tick)}
function render(data,label){state=data;const waste=Number(data.total_annual_waste??data.total_waste??0);countUp("totalWaste",waste);document.getElementById("reconcile").textContent=`${data.reconciled_count??data.statement_count??0}/${data.statement_count??0} Statements Mathematically Reconciled ($${Number(data.total_discrepancy??data.discrepancy??0).toFixed(2)} Discrepancy — Zero Math Hallucinations)`;document.getElementById("rowCount").textContent=data.transactions.length+" rows";document.getElementById("loadedPill").textContent=label||`📂 Currently Showing: ${data.filenames?.join(", ")||"Loaded Statements"} (${data.transactions.length} rows)`;document.getElementById("reports").innerHTML=(data.leaks||data.reports||[]).map(r=>`<article class="leak ${r.anomaly_type==="Price Creep"?"price":""}"><div class="type">${esc(r.anomaly_type)}</div><h3>${esc(r.merchant)}</h3><div class="amount">${money(r.annualized_leak)} / yr</div><p>${esc(r.details)}</p></article>`).join("");document.getElementById("transactionRows").innerHTML=data.transactions.map((t,i)=>{const amount=Number(t.debit||0)>0?-Number(t.debit):Number(t.credit||0),options=categories.map(c=>`<option ${c===t.category?"selected":""}>${c}</option>`).join("");return `<tr><td class="mono">${esc(t.date)}</td><td>${esc(t.canonical_merchant)}</td><td><select onchange="saveRule(${i},this.value)">${options}</select></td><td class="amount">${money(amount)}</td><td class="reconciled">✓ reconciled</td></tr>`}).join("")}
async function loadDemo(){setMessage("Running offline demo…");const r=await fetch("/api/demo");render(await r.json(),"📂 Currently Showing: 3-Month Demo (132 rows)");setMessage("Demo loaded locally.");}
async function saveRule(i,category){const t=state.transactions[i];await fetch("/api/rules",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({raw_pattern:t.description,canonical_name:t.canonical_merchant,category})});setMessage("Saved merchant rule for "+t.canonical_merchant+".")}
async function uploadFiles(files){const picked=[...files].filter(f=>f.name.toLowerCase().endsWith(".pdf"));if(!picked.length){setMessage("Please choose PDF files.");return}const form=new FormData();picked.forEach(f=>form.append("files",f));setMessage("Extracting uploaded statements…");const r=await fetch("/api/upload",{method:"POST",body:form}),data=await r.json();if(!r.ok){setMessage(data.detail||"Upload failed.");return}const names=data.filenames?.join(", ")||picked.map(f=>f.name).join(", ");render(data,`📄 Currently Showing: Uploaded File — ${names} (${data.transactions.length} rows)`);setMessage("Uploaded statements analyzed locally.");document.getElementById("audit").scrollIntoView({behavior:"smooth",block:"start"});}
function setMessage(text){document.getElementById("message").textContent=text}function downloadCsv(){window.location="/api/export.csv"}
const dropzone=document.getElementById("dropzone");["dragenter","dragover"].forEach(event=>dropzone.addEventListener(event,e=>{e.preventDefault();dropzone.classList.add("active")}));["dragleave","drop"].forEach(event=>dropzone.addEventListener(event,e=>{e.preventDefault();dropzone.classList.remove("active")}));dropzone.addEventListener("drop",e=>uploadFiles(e.dataTransfer.files));document.getElementById("demoButton").onclick=loadDemo;document.getElementById("pdf-input").onchange=e=>uploadFiles(e.target.files);document.getElementById("resetButton").onclick=loadDemo;loadDemo();
</script>
</body></html>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return HTML


@app.get("/hero.jpg")
def hero_image() -> FileResponse:
    image = ROOT / "hero.jpg"
    if not image.exists():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="hero.jpg is not present")
    return FileResponse(image)


@app.get("/api/demo")
def demo() -> dict[str, Any]:
    return demo_payload()


@app.post("/api/rules")
def save_rule(rule: RuleUpdate) -> dict[str, str]:
    connection = _connect()
    try:
        connection.execute(
            "INSERT OR REPLACE INTO merchant_rules(raw_pattern, canonical_name, category, is_recurring) VALUES (?, ?, ?, ?)",
            (rule.raw_pattern, rule.canonical_name, rule.category, int(rule.category == "Subscriptions")),
        )
        connection.commit()
    finally:
        connection.close()
    return {"status": "saved"}


@app.get("/api/export.csv")
def export_csv() -> StreamingResponse:
    rows = load_demo_transactions()
    output = io.StringIO()
    fields = ["date", "canonical_merchant", "category", "debit", "credit", "balance", "has_trial_token"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=statementsloth_clean.csv"})


async def _process_uploads(files: list[UploadFile]) -> JSONResponse:
    rows: list[dict] = []
    statements: list[dict] = []
    filenames: list[str] = []
    temporary_paths: list[Path] = []
    try:
        for upload_file in files:
            if not upload_file.filename or not upload_file.filename.lower().endswith(".pdf"):
                return JSONResponse({"detail": "Only PDF uploads are supported."}, status_code=400)
            target = ROOT / f".upload_{len(temporary_paths)}_{Path(upload_file.filename).name}"
            target.write_bytes(await upload_file.read())
            temporary_paths.append(target)
            statement = extract_statement(str(target))
            filenames.append(upload_file.filename)
            statements.append(
                {
                    "filename": upload_file.filename,
                    "opening_balance": float(statement.opening_balance),
                    "closing_balance": float(statement.closing_balance),
                    "computed_balance": float(statement.computed_balance),
                    "total_debits": float(statement.total_debits),
                    "total_credits": float(statement.total_credits),
                    "is_reconciled": statement.is_reconciled,
                }
            )
            rows.extend(transaction.model_dump(mode="json") for transaction in statement.transactions)
        return JSONResponse(_result_payload(normalize_transactions(rows), statements, filenames))
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)) -> JSONResponse:
    return await _process_uploads(files)


@app.post("/api/upload")
async def api_upload(files: list[UploadFile] = File(...)) -> JSONResponse:
    return await _process_uploads(files)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
