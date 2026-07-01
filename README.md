# SAP S/4HANA Material Master — Validator

Streamlit app that validates the **SAP Migration Cockpit "Product Master Creation"** template
(.xls / .xlsx) and produces a data-quality health report.

## What it checks

| Group | Examples |
|---|---|
| **Schema** (driven by *Field List* sheet) | Mandatory presence, Type (Text / Number / Date / Time), Length, Decimal places. |
| **Cross-extension consistency** | MRP type ↔ Controller / Reorder Point / Lot Size · Procurement type ↔ Purchasing Group / Production Scheduler · Plant Status valid-from · Profit Center ↔ Controlling Area · Reorder ≤ Maximum stock |
| **Costing & Accounting** (S_MBEW) | Valuation Class required · Price Control S/V coherence · Standard / Moving price > 0 · Currency presence · Stock × Price ≈ Total Value · Price Unit > 0 |
| **Sales** (S_MVKE) | Sales Org + Distribution Channel · Status valid-from · Item Cat Group ↔ Account Assignment · Min Order ≥ 0 |
| **Alternative UoM** (S_MARM) | Alt UoM ≠ Base UoM · Numerator/Denominator > 0 · No duplicate alt UoMs · GTIN length 8/12/13/14 · Length/Width/Height require Unit of Dimension |
| **References** | Every Product in extension sheets exists in *Basic Data* · Storage Loc / Forecasting refer to a maintained Plant |
| **AI warning flags** | Description vs Material Type · Missing Shelf Life on perishables · Pricing anomaly vs material type · Base UoM vs Product Nature |

## Token-saving design

Every AI flag has a deterministic **pre-filter**:

- Obvious mismatches and obvious good rows never reach the LLM.
- Only the *ambiguous* candidates are batched — typically <10 per file — into one
  Anthropic call per flag type.
- The system prompt is cached (`cache_control: ephemeral`) so subsequent batches
  are billed at cache-read rates.

## Run

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

Then open the printed local URL, drag-and-drop the template, and review the report.

## Use without AI

Untoggle **Enable AI warning flags** in the sidebar (or just leave the API key blank).
You still get every schema, cross-field, and rule-based AI prefilter check.

## Programmatic use

```python
from validator import run_validation
from validator.report import render_html

report = run_validation("Product Master Creation.xlsx", use_ai=True,
                        api_key="sk-ant-...")
print(report.counts())               # {'error': 4, 'warning': 12, 'info': 1}
open("report.html", "w").write(render_html(report))
```

## Web app (React + FastAPI)

A browser UI is provided as an alternative to Streamlit: a **React** front end
(`frontend/`) talking to a **FastAPI** back end (`backend/`) that calls the very
same `validator/` package — so the checks are identical to the Streamlit app,
including the lookup-file-driven validations.

```
React (Vite, :3000) ──/api proxy──▶ FastAPI (uvicorn, :8000) ──▶ validator/
```

### Run locally

**1 — Back end** (Python 3.11+):

```bash
pip install -r backend/requirements.txt
cd backend
# Override the insecure defaults before exposing this anywhere:
export MM_USERNAME=admin MM_PASSWORD='choose-a-strong-password'
export JWT_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')"
uvicorn main:app --reload --port 8000
```

**2 — Front end** (Node.js 18+):

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 (proxies /api → :8000)
```

Sign in with the `MM_USERNAME` / `MM_PASSWORD` you set above (defaults
`admin` / `admin123` if unset — **change these**). Then:

1. **Step 1** — upload `Product Master Lookup File.xlsx` (required).
2. **Step 2** — upload `Product Master Creation.xls` / `.xlsx`.
3. Optionally toggle **AI Warning Flags**, pick a provider (Anthropic or
   OpenAI) and paste an API key, then **Run Validation**.

Results show as KPI cards + findings (by category / by sheet / filterable
table) and download as HTML / JSON / CSV. **API keys are entered in the UI and
never stored or hardcoded.**

### Production build / deploy

`frontend/` builds to static files (`npm run build`) served by Nginx; the
FastAPI back end runs under systemd. `deploy/setup_ec2.sh`, `deploy/nginx.conf`
and `deploy/mmvalidator.service` automate an Ubuntu/EC2 deployment — set
`MM_PASSWORD` and `JWT_SECRET` in the service file before starting.

## Layout

```
mm_validator/
├── app.py                    # Streamlit UI
├── validator/                # Shared validation engine (used by BOTH UIs)
│   ├── __init__.py
│   ├── models.py             # Finding / ValidationReport / FieldSpec
│   ├── loader.py             # .xls + .xlsx unified reader
│   ├── schema_check.py       # Importance / Type / Length / Decimal
│   ├── uom.py                # Base UoM ↔ description nature
│   ├── cross_field.py        # S/4HANA cross-extension checks
│   ├── lookup_loader.py      # Reads the Master Lookup File
│   ├── lookup_checks.py      # Product-type & plant→profit-center checks
│   ├── ai_flags.py           # AI warning flags + pre-filters
│   ├── report.py             # HTML renderer
│   └── runner.py             # Orchestrator
├── backend/                  # FastAPI API (auth + /api/validate)
│   ├── main.py
│   └── auth.py
├── frontend/                 # React + Vite + Tailwind UI
│   └── src/
├── deploy/                   # Nginx + systemd + EC2 setup
├── sample_data/
│   ├── Product Master Creation.xls   # blank SAP template
│   ├── SAP_UOM_All.xlsx              # SAP UoM master (loaded by validator)
│   └── make_synthetic.py             # script to build a test fixture
└── requirements.txt
```
