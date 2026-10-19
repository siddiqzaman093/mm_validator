# SAP S/4HANA Material Master Validator — Technical Specification

| | |
|---|---|
| **Solution** | SAP S/4HANA Material Master Validator ("MM Validator Tool") |
| **Repository** | `github.com/siddiqzaman093/mm_validator` |
| **Document version** | 1.0 |
| **Date** | 19 October 2026 |
| **Status** | Reflects `main` as of commit `9f7de05`, plus the §10.2 clean-ups applied alongside this document |
| **Owner** | Arete Global — SAP MM / Data Migration |
| **Companion artefact** | [`solution-architecture.svg`](solution-architecture.svg) |

---

## 1. Purpose and scope

### 1.1 Purpose

This document is the technical specification for the SAP S/4HANA Material Master Validator — a web application that performs offline data-quality validation of the **SAP S/4HANA Migration Cockpit "Product Master Creation"** template *before* it is loaded into SAP.

It is written for three audiences:

- **Solution architects and SAP leads** — sections 2, 3, 4, 9.
- **Developers maintaining or extending the tool** — sections 5, 6, 10, 11.
- **Operations / deployment** — sections 7, 8.

### 1.2 Scope

| In scope | Out of scope |
|---|---|
| Validation of the Migration Cockpit Product Master template (`.xls` / `.xlsx`) | Writing to, or reading from, any SAP system (no RFC/OData/BAPI connectivity) |
| A configuration-driven rule set sourced from a customer-maintained lookup workbook | Executing the migration load itself |
| Deterministic schema, cross-extension and reference-integrity rules | Correcting the data — the tool reports, it does not repair |
| LLM-assisted plausibility flags (advisory only) | Master data governance workflow / approvals |
| Multi-user web UI with roles, run history, usage and cost metering | Non-material objects (BP, customer, vendor, BOM) |

### 1.3 Design principles

1. **One engine, many front ends.** All validation logic lives in the `validator/` Python package. The FastAPI backend and the Streamlit app (`app.py`) both import it, so the checks cannot diverge between UIs.
2. **Deterministic first, AI last.** Every AI-assisted check is fronted by a deterministic pre-filter. Clear-cut good rows and clear-cut bad rows never reach a model; only genuinely ambiguous rows do. Business rules never depend on model output alone.
3. **Configuration over deployment.** Field types, per-material-type mandatory fields, plant → profit-center mappings and conditional business rules are read from a customer-maintained Excel lookup file on **every run**. Changing a rule needs no code change and no deployment.
4. **Bounded cost and bounded memory.** The tool runs on a 512 MB free-tier container and is expected to handle 60 000–100 000-row workbooks. Every stage — ingestion, findings storage, AI calls — has an explicit bound.
5. **Nothing is silently ignored.** A dependency rule the parser cannot read, an AI sample that was capped, an AI call that failed — each produces a visible finding rather than a silent gap in coverage.

---

## 2. Solution overview

### 2.1 Business problem

The SAP Migration Cockpit validates structure but gives little useful feedback on **data quality**. A 60 000-row Product Master load typically fails late, row by row, on issues that were knowable up front: missing mandatory fields for a given material type, price control inconsistent with the maintained price, alternative units of measure that are dimensionally impossible, plants that do not match the profit-center master, extension-sheet rows for materials that do not exist in Basic Data.

Each such failure costs a load cycle. On a typical project this is days of elapsed time per iteration.

### 2.2 Solution summary

The user uploads two workbooks:

1. the **Product Master Lookup File** (`.xlsx`) — the customer's configuration: authoritative SAP field types, a per-material-type mandatory-field matrix, plant → profit-center mappings, and plain-English conditional rules;
2. the **Product Master Creation** template (`.xls` / `.xlsx`) — the data to be migrated.

The server validates the data against roughly **100 rules in 27 categories**, scores overall migration readiness from 0 to 100, and returns findings grouped by category and by sheet, downloadable as HTML and CSV. Validation runs as a server-side background job, so a dropped connection, a closed laptop or a server restart does not lose the result.

### 2.3 Capability summary

| Capability | Detail |
|---|---|
| Schema validation | Mandatory / type / length / decimal places, per material type |
| Cross-extension consistency | MRP, procurement, costing, sales, production, QM, forecasting |
| Reference integrity | Extension rows must resolve to Basic Data; storage locations and forecasting must resolve to a maintained plant |
| Unit-of-measure validation | SAP + ISO UoM master, dimension classification, conversion plausibility, physical-amount plausibility |
| Lookup-driven validation | Material class, valuation type, plant → profit center |
| Configurable conditional rules | Customer-maintained, parsed deterministically |
| AI plausibility flags | Description ↔ material type, shelf life, pricing, base-UoM nature, Arabic ↔ English description |
| Readiness scoring | 0–100 with per-material blocked / warning accounting |
| Multi-user operation | JWT auth, two roles, run history, admin usage and cost dashboard |

---

## 3. Architecture

### 3.1 Logical architecture

See [`solution-architecture.svg`](solution-architecture.svg). Five tiers:

| Tier | Runs on | Responsibility |
|---|---|---|
| **Presentation** | Vercel (static CDN) | React SPA — upload, live progress, results, history, admin panels |
| **Application** | Render (uvicorn + FastAPI, single instance) | Authentication, authorisation, REST API, job orchestration |
| **Validation engine** | In-process, same container | `validator/` package — pure Python, no I/O beyond the workbooks and the AI calls |
| **Data** | Neon Postgres (SQLite fallback) | Job queue + results + usage log |
| **External** | Anthropic / OpenAI | LLM plausibility verdicts for ambiguous rows only |

### 3.2 Technology stack

| Layer | Technology | Version constraint |
|---|---|---|
| Front end | React, Vite, Tailwind CSS, react-router, axios | 18.3 / 5.3 / 3.4 / 6.24 / 1.7 |
| API | FastAPI, uvicorn (standard), python-multipart | ≥ 0.110 / ≥ 0.29 / ≥ 0.0.9 |
| Auth | python-jose (cryptography) — HS256 JWT | ≥ 3.3 |
| Persistence | SQLAlchemy Core, psycopg2-binary | ≥ 2.0 / ≥ 2.9 |
| Excel | xlrd (`.xls`), openpyxl (`.xlsx`) | ≥ 2.0 / ≥ 3.1 |
| AI SDKs | `anthropic`, `openai` | ≥ 0.40 / ≥ 1.40 |
| Runtime | Python | 3.12.8 (pinned in `render.yaml`) |
| Secondary UI | Streamlit, pandas | ≥ 1.30 / ≥ 2.0 |

> The validation engine itself depends only on `xlrd` + `openpyxl` (and the AI SDKs when AI is enabled). It has no framework dependency and is importable from any host.

### 3.3 Deployment topology

```
Browser
  │  HTTPS
  ▼
Vercel ── static assets, SPA rewrite /(.*) → /index.html
  │  HTTPS (CORS allow-list + https://*.vercel.app)
  ▼
Render web service "mm-validator-api"
  ├── uvicorn main:app --app-dir backend        (1 process, 512 MB)
  ├── FastAPI request handlers (async)
  ├── job worker thread (1, daemon)
  └── validator/ engine (in-process)
       │                               │
       ▼                               ▼
  Neon Postgres                  Anthropic / OpenAI
```

Build and start commands run from the **repository root**, not from `backend/`, because the `validator/` package and `sample_data/SAP_UOM_All.xlsx` (loaded at import time) must be on the path:

```
buildCommand: pip install -r backend/requirements.txt
startCommand: uvicorn main:app --app-dir backend --host 0.0.0.0 --port $PORT
healthCheckPath: /api/health
```

`backend/main.py` prepends the project root to `sys.path` so the canonical root `validator/` package always wins over any local fork.

An alternative single-VM topology is supported (`deploy/` — Nginx + systemd on Ubuntu/EC2); see section 8.4.

### 3.4 Environments

| Environment | Front end | API | Database | AI |
|---|---|---|---|---|
| Local dev | `vite` on :3000, proxying `/api` → :8000 | `uvicorn --reload` on :8000 | SQLite `backend/data/usage.db` | Optional (env key) |
| Production | Vercel project | Render `mm-validator-api` | Neon Postgres via `DATABASE_URL` | OpenAI via `OPENAI_API_KEY` |

---

## 4. Functional specification

### 4.1 Roles and permissions

Two roles are carried in the JWT claim `role`.

| Capability | `user` | `admin` |
|---|:--:|:--:|
| Run a validation | ✔ | ✔ |
| View / re-open own past validations | ✔ | ✔ |
| Delete own job | ✔ | ✔ |
| View **all users'** validations (`?all=true`) | — | ✔ |
| Delete any user's job | — | ✔ |
| Usage Dashboard (`/api/admin/usage`) | — | ✔ |
| Currently-running panel (`/api/admin/active`) | — | ✔ |
| AI Configuration page | — | ✔ |

Login ids are e-mail addresses, matched case-insensitively, plus two built-in accounts (`admin`, `mm01`). The directory is a static list in `backend/auth.py`; each account's password comes from an environment variable derived from the mailbox name — `siddiq.uzzaman@arete-global.com` → `SIDDIQ_UZZAMAN_PASSWORD`.

> **Design note — fail-open on credentials.** A blank or missing password variable falls back to a development default rather than locking the account out. This is deliberate: a Render blueprint sync once blanked every password variable and locked all accounts out. It is a documented availability-over-strictness trade-off, and section 6.1 lists the compensating controls.

### 4.2 Input artefact 1 — Migration Cockpit template

Standard SAP Migration Cockpit "Product Master Creation" workbook. Per data sheet (0-based row indices):

| Row | Content |
|---|---|
| 0 | Title |
| 1 | Version / copyright |
| 2 | *(blank)* |
| 3 | SAP structure — `S_MARA`, `S_MARC`, `S_MARM`, `S_MBEW`, `S_MVKE`, … |
| 4 | SAP field codes — `PRODUCT`, `MTART`, `MEINS`, … |
| 5 | Format string, e.g. `ETE;80;0;C;80;0` |
| 6 | Group label |
| 7 | Long description (field name + help text + Type/Length) |
| 8+ | Data rows |

The **Field List** sheet (header at row 3, data from row 4) drives which sheets are loaded and supplies the fallback field specification:

| Column (0-based) | Content |
|---|---|
| 1 | Sheet name — `Basic Data (mandatory)`, `Plant Data (optional)`, …; blank means "same sheet as above" |
| 2 | Group name |
| 3 | Field description |
| 4 | Importance (contains "mandatory" → mandatory) |
| 5 | Type — Text / Number / Date / Time |
| 6 | Length |
| 7 | Decimal places |
| 8 | SAP structure |
| 9 | SAP field |

Sheets recognised by the cross-field rules: `Basic Data`, `Plant Data`, `Valuation Data`, `Distribution Chains`, `Alternative Units of Measure`, `Storage Locations`, `Forecasting Data`, `MRP Area`, `Inspection Setup Data`, `Class Data`, `Additional Descriptions`.

If the Field List sheet is absent, every sheet in the workbook is loaded and schema validation proceeds on whatever the lookup file defines.

### 4.3 Input artefact 2 — Product Master Lookup File

A customer-maintained `.xlsx` workbook. All four sheets are optional; each absent sheet simply disables its rules.

**`Field Types`** — authoritative field specification. Columns 0–8: Sheet Name, Group Name, Field Description, Type, Length, Decimal, **SAP Type**, **SAP Length**, **SAP Decimal**. Sheet and group names are forward-filled to emulate merged cells. The SAP columns are **priority 1** for validation; the template's own Field List is the priority-2 fallback.

**`Fields Entry`** — the per-material-type mandatory matrix. Row 1 holds sparse section (sheet) names, forward-filled; row 3 holds field names; data starts at row 4; column 0 is the material type (Z-code). Field columns begin at column index 3. An `X` marks the field mandatory for that material type.

Field names are joined between Fields Entry and Field List by a normalisation that lowercases, strips parentheticals and drops a leading `Material ` — then requires **exact** equality. (Fuzzy suffix matching was rejected: it over-matched, e.g. *Manufacturer Product Number* against *Product Number*.)

**`Plant-ProfitCenter`** — header row, then `Plant | Profit Center`. Numeric cells are normalised (`1000.0` → `1000`).

**`Dependencies`** — conditional business rules; see 4.6.

### 4.4 Validation pipeline

`validator/runner.py::run_validation()` executes six stages and reports progress after each.

| Stage | % | Action |
|---|---|---|
| 1 | 5 | Load the lookup workbook → field specs, mandatory matrix, plant→PC map, dependency rules |
| 2 | 15 | Open and stream the data workbook → `FieldSpec` map + `SheetData` per sheet |
| 3 | 25 | Build the `PRODUCT → MTART` map from Basic Data |
| 3 | 30–55 | Schema validation per sheet (progress interpolated across sheets) |
| 4 | 60 | Cross-field / cross-extension consistency |
| 5 | 75 | Lookup-driven checks + the configurable dependency engine |
| 6 | 85 | AI flags (pre-filter always; model calls only when AI is enabled) |
| — | 100 | Assemble `ValidationReport` |

**Mandatory-field resolution order** per row:

1. `PRODUCT` is always mandatory on every sheet — it is the key field.
2. If the row's material type is present in the Fields Entry matrix, the `X` marks for that material type decide.
3. Otherwise, the Field List *Importance* flag decides, and the finding message is suffixed `(Field List)` so the source is visible.

The material type for a row on a non-Basic-Data sheet is resolved from the row's own `MTART` cell if present, otherwise via the `PRODUCT → MTART` map built from Basic Data.

### 4.5 Rule catalogue

Approximately 100 distinct `rule_id` values across 27 categories. Every finding carries `severity`, `category`, `sheet`, `row`, `field`, `sap_field`, `material`, `value`, `rule_id` and `ai_generated`.

#### Schema (`schema_check.py`)

| Rule id | Severity | Check |
|---|---|---|
| `SCHEMA_MANDATORY` | ERROR | Mandatory field empty (source per 4.4) |
| `SCHEMA_TYPE_NUMBER` | ERROR | Value is not numeric where Number is expected |
| `SCHEMA_TYPE_DATE` | ERROR | Not `YYYY-MM-DD`, `YYYYMMDD` or `DD.MM.YYYY` |
| `SCHEMA_TYPE_TIME` | ERROR | Not `HH:MM[:SS]` or `HHMMSS` |
| `SCHEMA_LENGTH_TEXT` | ERROR | Text longer than the effective length |
| `SCHEMA_LENGTH_NUM` | ERROR | More digits than the effective length |
| `SCHEMA_DECIMAL` | WARNING | More decimal places than allowed |

#### Cross-extension (`cross_field.py`)

| Category | Rule ids | Representative check |
|---|---|---|
| `Cross/Key` | `X_KEY_PLANT`, `X_KEY_VAL`, `X_KEY_SALES`, `X_KEY_ALTUOM`, `X_KEY_SLOC`, `X_KEY_MRPA`, `X_KEY_QM` | Sheet-specific key fields present (plant, valuation area, sales org/channel, alt UoM, storage location, MRP area, inspection type) |
| `Cross/MRP` | `X_MRP_CONTROLLER_REQUIRED`, `X_MRP_REORDER_POINT`, `X_MRP_LOT_SIZE`, `X_MRP_MAX_LT_REORDER`, `X_MRP_ND_INCONSISTENT`, `X_MRPA_CONTROLLER`, `X_AVAIL_CHECK_RECOMMENDED` | MRP type ↔ controller / reorder point / lot size; reorder point ≤ maximum stock; `ND` coherence |
| `Cross/Costing` | `X_VAL_CLASS_REQUIRED`, `X_PRICE_CTRL_VALUE`, `X_STD_PRICE_REQUIRED`, `X_MOV_PRICE_REQUIRED`, `X_MOV_PRICE_IGNORED`, `X_VAL_INCONSISTENT`, `X_CURRENCY_MISSING`, `X_PRICE_UNIT_POSITIVE`, `X_CO_AREA_REQUIRED` | Valuation class required; price control `S`/`V` coherence with standard vs moving price; stock × price ≈ total value; price unit > 0; profit center ↔ controlling area |
| `Cross/Sales` | `X_SALES_ORG`, `X_SALES_STATUS_VALID`, `X_SALES_MIN_ORDER_NEG` | Sales org + distribution channel; status valid-from; minimum order ≥ 0 |
| `Cross/AltUoM` | `X_ALT_EQ_BASE`, `X_ALT_CONV_INVALID`, `X_ALT_DUPLICATE`, `X_ALT_GTIN_LEN`, `X_ALT_GTIN_DUP`, `X_ALT_DIM_UNIT` | Alt UoM ≠ base UoM; numerator/denominator > 0; no duplicate alt UoM; GTIN length 8/12/13/14; L/W/H require a unit of dimension |
| `Cross/Reference` | `X_PRODUCT_NOT_IN_BASIC`, `X_SLOC_PLANT_MISSING`, `X_FCST_PLANT_MISSING` | Every extension row resolves to Basic Data; storage location / forecasting resolve to a maintained plant |
| `Cross/Status`, `Cross/Purchasing`, `Cross/Production`, `Cross/QM`, `Cross/Forecast` | `X_STATUS_VALID_FROM`, `X_PUR_GROUP_REQUIRED`, `X_PROD_ROUNDING_NEG`, `X_QM_TYPE`, `X_FCST_PERIODS` | Plant status valid-from; procurement type ↔ purchasing group; non-negative rounding value; inspection type; forecast periods |
| `Duplicate/*` | `X_DUP_PRODUCT_NUMBER` (ERROR), `X_DUP_DESCRIPTION` (WARNING) | Duplicate product numbers; near-duplicate descriptions at ≥ 75 % token similarity after pack-size tokens (`500G`, `1.5KG`, `750ML`) are stripped |
| `Cross/UoM` | `X_BASE_UOM_INVALID_SAP` | Base UoM is not a recognised SAP or ISO code; the message names the recognised code to use |

#### Unit-of-measure conversion (`uom_conversion.py`, `uom_data.py`)

The SAP UoM master (`sample_data/SAP_UOM_All.xlsx`) is loaded once at import and classifies each code into a dimension: mass, volume, length, area, time, count, packaging, mole, energy, pressure, temperature, proportion, density, speed, force, power, other. ISO codes are the primary key; SAP internal codes are the fallback.

| Rule id | Severity | Check |
|---|---|---|
| `X_ALT_INVALID_UOM_CODE` | ERROR | Code not in the SAP/ISO master |
| `X_ALT_IMPOSSIBLE_DIM` | ERROR | Dimensionally impossible pair (mass↔length, volume↔time, …) |
| `X_ALT_MAGNITUDE_ERROR` | ERROR | Known conversion with the wrong order of magnitude |
| `X_ALT_CROSS_DIM` | WARNING | Legitimate but density/catch-weight-dependent pair (mass↔volume, mass↔count, …) |
| `X_ALT_IMPLAUSIBLE_RATIO`, `X_ALT_IMPLAUSIBLE_CROSS_RATIO` | WARNING | Same- or cross-dimension ratio outside plausible bounds |
| `X_ALT_RATIO_ONE` | WARNING | Trivial 1:1 same-dimension conversion |
| `X_ALT_MTART_DIM` | WARNING | Dimension inconsistent with the material type |
| `X_ALT_MTART_PREFERRED` | INFO | A different UoM is conventional for this material type |

SAP conversion semantics: `UMREN` alternative units = `UMREZ` base units; `alt_per_base = UMREN / UMREZ`.

#### Physical-amount plausibility (`plausibility.py`, category `Cross/UoM Amounts`)

Validates the *amounts* (weights, volumes, dimensions) rather than the conversion ratios, using unit→SI factor tables: `X_QTY_NEGATIVE`, `X_QTY_WEIGHT_UNIT_MISSING`, `X_QTY_VOL_UNIT_MISSING`, `X_QTY_DIM_UNIT_MISSING`, `X_QTY_NET_GT_GROSS`, `X_QTY_PLACEHOLDER` (999999, 12345 …), `X_QTY_WEIGHT_TINY` / `_HUGE`, `X_QTY_VOLUME_TINY` / `_HUGE`, `X_QTY_BASE_MASS_MISMATCH`, `X_QTY_BASE_VOL_MISMATCH`, `X_QTY_VOL_GT_BOX` (declared volume exceeds the L×W×H bounding box), `X_QTY_DENSITY_HIGH` / `_LOW`.

#### Lookup-driven (`lookup_checks.py`)

| Rule id | Severity | Check |
|---|---|---|
| `LKP_PRODUCT_TYPE_MISSING` | ERROR | Material type not present in the lookup Fields Entry matrix |
| `LKP_MATERIAL_CLASS_MISMATCH` | ERROR | Class Data class ≠ lookup value |
| `LKP_VALUATION_TYPE_MISMATCH` | ERROR | Valuation Data `BWTAR` ≠ lookup value |
| `LKP_PLANT_NOT_IN_LOOKUP` | ERROR | Plant absent from the Plant-ProfitCenter sheet |
| `LKP_PROFIT_CENTER_EMPTY` | WARNING | Profit center not maintained on Plant Data |
| `LKP_PROFIT_CENTER_MISMATCH` | ERROR | Profit center ≠ the plant's expected value |

A blank Material Class or Valuation Type in the lookup means "applies to all" — no comparison is made and no finding raised.

### 4.6 Configurable dependency rules

`dependencies.py` lets key users maintain conditional business rules on the lookup `Dependencies` sheet. The sheet is re-read on every run, so a rule change takes effect immediately with no deployment.

**Sheet layout** — header row, then per row: column A trigger field name, column B trigger value, columns C–G up to five free-text conditions. Each non-empty condition cell becomes one rule.

**Example**

| Product type | Value | Dependency 1 |
|---|---|---|
| Product type | `ZDEV` | `Valuation class should be one of: Z002 - Z015` |

**Grammar** (case-insensitive, quotes optional, `not` negates any form):

```
<field> should [not] start with <value>
<field> should [not] end with <value>
<field> should [not] contain <value>
<field> should [not] be one of [the following][:] v1 - v2 - v3      (also , or ;)
<field> should [not] be empty
<field> should be maintained | filled                                (≡ should not be empty)
<field> should [not] be [equal to] <value>
```

**Deliberate parser constraints**

- Interpretation is a **deterministic template parser**, never a model. Business rules must not depend on model guesswork.
- The bare-equality fallback rejects values longer than 40 characters or more than 3 words. Otherwise a rule phrased in an unsupported way ("should be consistent with …") would silently become an equality check and flood the report with false errors.
- Field names resolve against the template's Field List descriptions using the same normalisation as the Fields Entry join. On ambiguity (e.g. *Valuation Class* exists on both Basic Data and Valuation Data) the column that actually contains data wins; a remaining tie prefers Basic Data.
- Conditions on a different sheet from the trigger are joined per material via `PRODUCT`. A material with no matching target row is itself a violation.

**Outputs per rule**

| Rule id | Severity | Meaning |
|---|---|---|
| `LKP_DEPENDENCY` | ERROR | A material violates the rule |
| `LKP_DEPENDENCY_INFO` | INFO | One transparency line per rule: how it was interpreted, how many materials the trigger matched, how many violations |
| `LKP_DEPENDENCY_UNPARSED` | WARNING | The condition could not be parsed, or a field name was not found — the message lists the supported phrasings |

The INFO transparency line is the reason the report-sampling algorithm (5.6) is round-robin per `rule_id`: a plain errors-first cut would bury these lines exactly when rules fire heavily.

### 4.7 AI-assisted plausibility flags

Five flags, each with a deterministic pre-filter in `ai_flags.py`:

| Flag | Pre-filter emits directly | Sent to the model |
|---|---|---|
| `desc_mtart` | `AI_DESC_MTART_FORBIDDEN` (WARNING) when the description contains a forbidden term for that material type | Descriptions that neither clearly match nor clearly contradict |
| `shelf_life` | `AI_SHELF_LIFE_MISSING` (WARNING) when a regex over ~50 perishable patterns matches and shelf life is blank | Ambiguous descriptions |
| `pricing` | `AI_PRICE_NEGATIVE` (ERROR), `AI_PRICE_ZERO`, `AI_PRICE_DIEN_ZERO`, `AI_PRICE_UNBW_NONZERO` (WARNING) | Prices outside the material type's expected band but not provably wrong |
| `uom_nature` | `UOM_NATURE_MISMATCH` (WARNING) — used directly only when AI is **off** | Base UoM ↔ product-nature mismatches, for confirmation |
| `arabic_desc` | `AI_AR_NOT_ARABIC`, `AI_AR_SAME_AS_EN` (WARNING) | Arabic descriptions that are plausibly a translation, for semantic equivalence |

`MTART_EXPECTATIONS` holds, per SAP material type (`ROH`, `HALB`, `FERT`, `HAWA`, `VERP`, `DIEN`, `UNBW`, `NLAG`, `LEIH`), the expected terms, forbidden terms, expected price range and whether perishability is plausible.

**Cost and latency envelope.** A 60 000-row workbook could otherwise queue thousands of candidates → hundreds of sequential calls → 15–40 minutes and real token cost per run. Four bounds apply:

1. **Deduplication** — candidates whose payload is identical except for the material number collapse into one question; the verdict fans back out to every duplicate row.
2. **Sampling** — at most `AI_MAX_CANDIDATES_PER_FLAG` (default 250) distinct cases per flag, chosen with a fixed seed (42) so re-running the same file samples the same rows. When sampling occurs, an `AI_SAMPLE_CAPPED` INFO finding states how many distinct cases existed and how many rows were not individually reviewed — the report never overstates coverage.
3. **Chunking** — 25 items per call, `max_tokens = 1500`.
4. **Parallelism** — `AI_PARALLEL_CALLS` (default 4) worker threads.

The Anthropic path marks the system prompt `cache_control: ephemeral`, so repeat batches are billed at cache-read rates. The model is instructed to be conservative and to return strict JSON (`{"results":[{"id","issue","severity","reason"}]}`); markdown fences and trailing prose are tolerated by `_safe_json`.

**Degradation.** A failed call produces `AI_CALL_FAILED` (INFO), unparseable output produces `AI_PARSE_ERROR` (INFO), and a missing key produces `AI_SKIPPED_NO_KEY` (INFO) per candidate. AI never blocks a validation, and AI findings are always tagged `ai_generated: true`.

### 4.8 Readiness score

`ValidationReport.readiness()` returns a 0–100 score computed **per material**, not per finding, so one bad material with forty findings does not look like forty bad materials.

```
blocked    = distinct materials with ≥ 1 ERROR
warn_only  = distinct materials with warnings but no error
score      = 100 × (total − blocked − 0.3 × warn_only) / total
score     −= min(25, 5 × file_level_errors)       # findings with no material key
score     −= min(10, 1 × file_level_warnings)     # e.g. missing sheet or column
score      = clamp(round(score), 0, 100)
```

| Score | Label | Band |
|---|---|---|
| ≥ 90 | Ready to load | green |
| 70–89 | Nearly ready | amber |
| 40–69 | Needs attention | orange |
| < 40 | Not ready | red |

`total_materials` is the count of **distinct** `PRODUCT` values across all sheets, falling back to the Basic Data row count when the PRODUCT column is absent entirely. A file with no materials scores 0 / "No data".

### 4.9 Outputs

| Output | Produced by | Notes |
|---|---|---|
| Report JSON | `ValidationReport.to_dict()` | Sampled findings + **true** totals per category and per sheet |
| HTML report | `report.py::render_html()` | Self-contained dark-theme document, embedded in the JSON as `html_report` |
| Findings CSV | `jobs.py` | **Complete**, never sampled; gzipped at rest; served with `utf-8-sig` so Excel renders Arabic correctly |
| KPI cards | Front end | Readiness score headline, error/warning/info counts, materials, rows, duration, AI tokens |

CSV columns: `severity, ai_generated, category, sheet, material, row, field, sap_field, value, message, rule_id`.

---

## 5. Technical design

### 5.1 Data model

Both tables live in the same database (`DATABASE_URL`, else SQLite at `backend/data/usage.db`) and are created with `metadata.create_all()` at import.

#### `validation_jobs` (`backend/jobs.py`)

| Column | Type | Notes |
|---|---|---|
| `id` | String(32) PK | `uuid4().hex` |
| `username`, `role` | String | indexed on `username` |
| `file_name` | String(255) | truncated |
| `use_ai`, `provider`, `model` | Boolean / String | request parameters |
| `status` | String(16), indexed | `queued` \| `running` \| `done` \| `failed` |
| `created_at` (indexed), `started_at`, `finished_at` | DateTime | naive UTC |
| `progress_pct`, `progress_stage`, `ai_done`, `ai_total` | Integer / String(255) | throttled writes |
| `input_file`, `lookup_file` | LargeBinary | **cleared on completion** |
| `result_json_gz`, `csv_gz` | LargeBinary | gzip level 6 |
| `readiness_score`, `errors`, `warnings`, `infos`, `findings_total`, `rows_total`, `materials_total` | Integer | summary KPIs |
| `ai_calls`, `input_tokens`, `output_tokens`, `duration_ms` | Integer | metering |
| `error` | String(1000) | failure message |

#### `usage_sessions` (`backend/usage_log.py`)

One row per completed or failed validation: `username`, `role`, `started_at` (indexed, naive UTC), `file_name`, `materials`, `errors`, `warnings`, `infos`, `ai_used`, `provider`, `model`, `ai_calls`, `input_tokens`, `output_tokens`, `cost_usd`, `duration_ms`, `readiness_score`, `status`, `error`.

`_ensure_columns()` performs a micro-migration for `readiness_score`, since `create_all()` does not alter existing tables. It is wrapped in a bare `except` — a failed migration must not block startup.

**Timestamp convention.** All timestamps are stored as **naive UTC** (`datetime.now(timezone.utc).replace(tzinfo=None)`) so comparisons behave identically on SQLite and Postgres. The API serialises them with `.isoformat()`; the front end appends `Z` when no offset is present.

### 5.2 API contract

Base path `/api`. All endpoints except `/api/health` and `/api/auth/login` require `Authorization: Bearer <jwt>`.

| Method | Path | Request | Response | Errors |
|---|---|---|---|---|
| `GET` | `/api/health` | — | `{"status":"ok"}` | — |
| `POST` | `/api/auth/login` | form: `username`, `password` | `{access_token, token_type, username, role, name}` | 401 |
| `POST` | `/api/jobs` | multipart: `file`, `lookup_file?`, `use_ai`, `provider`, `model` | `{job_id}` | 422 bad extension / provider · 413 > 25 MB · 429 queue cap |
| `GET` | `/api/jobs` | `?all=true` (admin only) | `{jobs:[summary]}` — ≤ 50, newest first | 401 |
| `GET` | `/api/jobs/{id}` | — | job summary + live progress | 403 · 404 |
| `GET` | `/api/jobs/{id}/result` | — | report JSON (`application/json`) | 403 · 404 if running/failed/expired |
| `GET` | `/api/jobs/{id}/csv` | — | `text/csv` attachment | 403 · 404 |
| `DELETE` | `/api/jobs/{id}` | — | `{deleted: id}` | 403 · 404 · **409 if running** |
| `GET` | `/api/admin/usage` | `?days=30` (`≤0` = all) | `{days, storage, totals, per_user, sessions}` | 403 |
| `GET` | `/api/admin/active` | — | `{runs:[…]}` sorted by elapsed desc | 403 |

Authorisation on a job: the caller must own it **or** be an admin (`_authorize_job`). A job summary returned to the client overlays the live in-memory progress for the currently running job, which is fresher than the last throttled database write.

**Upload validation.** `file` must end `.xls` or `.xlsx`; `lookup_file` must end `.xlsx`. Each is size-checked after reading, against `MAX_UPLOAD_MB` (default 25) → HTTP 413 with a human-readable message.

**CORS.** `ALLOWED_ORIGINS` is a comma-separated allow-list; blank or unset falls back to `["*"]` so a wiped variable cannot take the app down. An additional `allow_origin_regex` of `https://.*\.vercel\.app` admits every Vercel preview and branch deployment, which a fixed origin list would miss.

### 5.3 Job lifecycle and concurrency

```
submit_job()                     _worker_loop()                        _run_job()
    │                                 │                                     │
    ├─ retention sweep (>30d, done/failed)                                  │
    ├─ per-user cap check (3) ──429                                         │
    ├─ INSERT status='queued' + input blobs                                 │
    └─ _wakeups.put(job_id) ────────► get() ──────────────────────────────► _claim_job()
                                                                            │  UPDATE … WHERE status='queued'
                                                                            │  rowcount == 0 → return (lost the race, or deleted)
                                                                            ├─ run_validation(…) with progress callbacks
                                                                            ├─ gzip result JSON + full CSV
                                                                            ├─ UPDATE status='done', clear input blobs
                                                                            └─ log_session(...)
```

**Why a single worker thread.** Peak memory for a 100 000-row workbook is roughly 200 MB against a 512 MB container. Two concurrent large files would OOM the instance, so jobs are processed strictly sequentially.

**Why the queue is the database.** The `status` column *is* the queue; the in-process `queue.Queue` only wakes the worker. Consequences:

- a dropped connection or closed browser cannot lose a result — the user re-opens it from Past Validations;
- `recover_stuck_jobs()` at startup re-queues everything left `queued` or `running` by a previous process (Render restarts free-tier services routinely). Input blobs are retained in the row until the job finishes, so a crashed run can always re-run. A row whose inputs were already cleared is failed cleanly;
- `_claim_job()`'s `UPDATE … WHERE id = ? AND status = 'queued'` makes the claim first-wins, so duplicate workers (e.g. `uvicorn --workers 2`) or duplicate re-queues cannot double-execute a job.

**Deleting.** Deleting a `queued` job cancels it — the worker's atomic claim finds no queued row and drops the wake-up. A `running` job is refused with 409: the validation would keep occupying the worker with nowhere to write its result.

**Progress.** Database progress writes are throttled to at most one every 2 seconds, and every write is best-effort (a failed progress write must never fail the job). The `active_jobs` dict always holds the current value and backs the admin panel without a query. The front end polls `/api/jobs/{id}` every 2.5 seconds.

**Retention.** Finished jobs older than `JOB_RETENTION_DAYS` (default 30) are deleted inside the submission transaction. No background sweeper is needed.

### 5.4 Memory and performance design

A 60 000-row workbook stored as one dict per cell needs gigabytes. Three decisions keep it inside 512 MB:

1. **Streaming readers.** `openpyxl` in `read_only=True, data_only=True` mode for `.xlsx`; `xlrd` for `.xls`. Both are hidden behind a `_Book` wrapper that exposes only sheet names and a sequential row iterator. Each sheet is read in exactly one pass.
2. **Compact row storage.** `models.py` defines `Row` and `Cells` with `__slots__`. A row holds a value tuple plus a reference to a **per-sheet shared** `keymap` (`sap_field → index`). Only mapped columns are retained. `Cells` is a lazy mapping view that reconstructs a `Cell` on access, so the check modules keep their original `row["_cells"].get(field)["value"]` API unchanged.
3. **Cell types.** `.xls` rows carry real `xlrd` cell types (dates are plain floats there and are otherwise indistinguishable from numbers). `.xlsx` rows carry `None` and types are derived from the Python value. Integer-valued floats are normalised to `int` on load, guarded on `XL_CELL_NUMBER` so dates are never truncated — this is what stops material numbers rendering as `1054.0`.

Findings themselves are the other growth axis; see 5.6.

### 5.5 Front-end architecture

| Concern | Implementation |
|---|---|
| Routing | `react-router-dom` with `ProtectedRoute` (authenticated) and `AdminRoute` (role check) wrappers around a shared `Layout` |
| State | React local state + `AuthContext`; no global store |
| Session | JWT in `sessionStorage` under `mm_validator_session`, mirrored in a module-level variable. Deliberately **not** `localStorage`: the session should not survive a browser restart. The token expires after 8 hours |
| Auth transport | axios request interceptor adds the bearer header; a response interceptor clears the session and redirects to `/login` on any 401 **except** from `/api/auth/login` itself (a wrong password must not look like an expiry) |
| Job resumption | The active `job_id` is kept in `sessionStorage` under `mm_validator_active_job`, so a refresh re-attaches to the running job instead of losing it |
| Cold starts | `pingHealth()` on mount and every 10 minutes keeps the free-tier backend awake, so "Run Validation" does not pay a cold start |
| Elapsed time | Computed from the job's `created_at`, not a local timer, so it stays correct across refreshes |
| Large results | A banner appears when `findings_truncated` is true, pointing at the Downloads tab for the complete CSV |
| CSV download | Fetches the server-side complete CSV via `job_id`; falls back to a client-side build from the (sampled) list only if that is gone |
| Hosting | SPA rewrite `/(.*) → /index.html` in `vercel.json`; `VITE_API_URL` points at the Render service (blank locally, where Vite proxies `/api` → `:8000`) |

### 5.6 Report sampling

Tens of thousands of findings shipped as JSON stall the browser. `ValidationReport.to_dict()` therefore ships a **sample**, with two invariants:

- counts, readiness and the per-category / per-sheet totals are always computed from the **full** list;
- the complete detail is always available as the server-side CSV.

Sampling (`top_findings`) is: group by category → within each category group by `rule_id` → sort each rule group most-severe first → take round-robin across rule groups up to `SAMPLES_PER_GROUP` (200) per category → global cap `MAX_FINDINGS_JSON` (5 000).

The round-robin is the point: a plain errors-first cut would let one high-volume rule bury every other rule in its category, including the dependency engine's INFO transparency lines. Sampling per rule guarantees that **every rule that fired is represented on screen**.

`findings_truncated`, `findings_total`, `samples_per_group`, `category_counts` and `sheet_counts` let the UI list every group with its true totals while showing only samples of the rows. `samples_per_group` is published so the front end never holds a second, drifting copy of the per-category sample size: `ResultsView` uses it as the row ceiling for an expanded group on a sampled report, and falls back to its own render guard on an unsampled one.

### 5.7 Configuration reference

| Variable | Default | Effect |
|---|---|---|
| `JWT_SECRET` | insecure placeholder | HS256 signing key — **must** be set in production (`generateValue: true` in `render.yaml`) |
| `MM_PASSWORD` | `admin123` | Built-in `admin` account |
| `MM01_PASSWORD` | `password123` | Built-in `mm01` account |
| `<MAILBOX>_PASSWORD` | `password123` | Per named user, e.g. `SIDDIQ_UZZAMAN_PASSWORD` |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS allow-list |
| `DATABASE_URL` | SQLite file | Postgres URL; `postgres://` is normalised to `postgresql://` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | — | Server-side AI key, selected by `provider` |
| `AI_PRICING_JSON` | — | Per-model price overrides, e.g. `{"gpt-5.4":[1.25,10.0]}` |
| `MAX_UPLOAD_MB` | `25` | Upload size limit |
| `JOB_RETENTION_DAYS` | `30` | Finished-job retention |
| `MAX_ACTIVE_JOBS_PER_USER` | `3` | Queued + running cap per user |
| `AI_MAX_CANDIDATES_PER_FLAG` | `250` | Distinct cases sampled per flag |
| `AI_PARALLEL_CALLS` | `4` | Concurrent AI calls |
| `PYTHON_VERSION` | `3.12.8` | Render runtime |

> **Operational warning.** Secrets are intentionally **not** declared in `render.yaml`. A blueprint sync manages — and can wipe — every variable listed in the blueprint; this once blanked all passwords and locked every account out. Secrets are managed only in the Render dashboard, where blueprint syncs never touch them.

---

## 6. Non-functional characteristics

### 6.1 Security

| Control | Implementation |
|---|---|
| Authentication | OAuth2 password flow → HS256 JWT, 8-hour expiry, `sub` / `role` / `name` claims |
| Password comparison | `secrets.compare_digest` — constant time |
| Authorisation | FastAPI dependencies `get_current_user` / `require_admin`; per-job ownership check |
| Transport | HTTPS end to end (Vercel and Render terminate TLS) |
| CORS | Explicit allow-list plus a Vercel-deployment regex |
| Secret handling | AI key and all passwords live only in backend environment variables; the key is never sent to the browser, and the client may omit it entirely |
| Session storage | `sessionStorage` (tab-scoped), not `localStorage`; cleared on any 401 |
| Upload hardening | Extension allow-list, 25 MB cap, size checked before the bytes reach the database |
| Resource abuse | Per-user queue cap (3) → HTTP 429 |
| CSV injection | `csv_safe()` prefixes a quote onto workbook-controlled values beginning `=`, `+`, `-`, `@`, tab or CR, so an exported CSV cannot execute a formula in Excel. The front-end fallback path applies the same rule |
| Data lifetime | Input workbooks are cleared from the database the moment a job finishes; results expire after 30 days |

**Known weaknesses, accepted deliberately**

1. *Passwords are compared in plaintext against environment variables* — no hashing, no salt. Acceptable for a small internal named-user directory; a move to hashed credentials in the database is the natural next step if the user base grows.
2. *Blank password variables fall back to a development default* — availability was chosen over strictness after a blueprint sync locked every account out. Compensating control: set every `*_PASSWORD` variable explicitly in the Render dashboard and verify after any blueprint sync.
3. *`ALLOWED_ORIGINS` falls back to `*`* — same rationale. With `allow_credentials=True` this is permissive; set the variable explicitly in production.
4. *No rate limiting on `/api/auth/login`* — brute force is bounded only by the per-user job cap, which does not apply to login.

### 6.2 Performance and capacity

| Dimension | Figure |
|---|---|
| Target workbook size | 60 000–100 000 rows |
| Peak memory per job | ≈ 200 MB (container limit 512 MB) |
| Deterministic validation, 60 k rows | ≈ 1–2 minutes |
| With AI enabled | + 1–3 minutes typical, bounded by the 250-case-per-flag sample and 4-way parallelism |
| Concurrency | 1 job at a time, globally; others queue |
| Upload limit | 25 MB per file (real Migration Cockpit workbooks are ≈ 2 MB) |
| Findings in the JSON payload | ≤ 5 000 (≤ 200 per category, round-robin per rule) |
| Findings in the CSV | unlimited — a 6.6 MB CSV gzips to well under 1 MB |
| Job list page | 50 most recent |
| Usage dashboard | 500 most recent sessions |

### 6.3 Availability and recovery

| Scenario | Behaviour |
|---|---|
| Browser closed / network dropped mid-run | Job continues server-side; the result is in Past Validations |
| Page refreshed mid-run | The SPA re-attaches via the `job_id` in `sessionStorage` |
| Backend restarts mid-run | `recover_stuck_jobs()` re-queues the job from the retained input blobs on startup |
| Backend restarts after completion | No impact — results are in the database |
| AI provider unavailable | Validation completes; an INFO finding records the failure |
| Lookup file absent or unreadable | Loaders return empty structures; lookup-driven rules are skipped; schema validation falls back to the template Field List |
| `DATABASE_URL` unset | Falls back to SQLite — **ephemeral on Render's free tier**, so history resets on each deploy |
| Free-tier cold start | Mitigated by the SPA's 10-minute health ping |

### 6.4 Cost model

`usage_log.py` estimates USD cost per session from token counts, using a per-model table of (input, output) prices per million tokens:

| Model | Input | Output |
|---|---|---|
| `claude-haiku-4-5` | 1.00 | 5.00 |
| `claude-sonnet-4-6` / `claude-sonnet-5` | 3.00 | 15.00 |
| `claude-opus-4-8` | 5.00 | 25.00 |
| `gpt-5.4` | 1.25 | 10.00 |
| `gpt-4o` | 2.50 | 10.00 |
| `gpt-4o-mini` | 0.15 | 0.60 |

Unknown model ids resolve by prefix (so dated ids such as `claude-haiku-4-5-20251001` still price correctly) and otherwise cost 0.00. `AI_PRICING_JSON` overrides or extends the table without a code change; a malformed override is ignored rather than breaking validation.

> These are the rates hard-coded in the repository. Verify them against current provider pricing and override via `AI_PRICING_JSON` where they have drifted.

### 6.5 Observability

- **Usage Dashboard** (admin) — sessions, materials validated, AI calls, tokens, estimated cost, per-user aggregates, last-active timestamps, and whether the log store is durable.
- **Currently Running** (admin) — live view of the job in flight: user, file, AI on/off, elapsed seconds, stage, percentage, AI items done/total.
- **Per-job record** — every run leaves a `validation_jobs` row and a `usage_sessions` row, including failures (`status='error'` with the message).
- **Health** — `/api/health` backs Render's health check and the SPA keep-alive.

There is no structured application log shipping, metrics endpoint or alerting. See section 10.

---

## 7. Testing

`backend/tests/` under pytest. `conftest.py` points the shared engine at a throwaway SQLite file **before** any backend module is imported, because `usage_log` creates the engine at import time.

| File | Covers |
|---|---|
| `test_dependencies.py` | Condition grammar (parametrised accept/reject), the rejection of over-long bare-equality phrasings, field resolution preferring populated columns, same-sheet and cross-sheet rules, missing-target-row violations, and that unparseable conditions and unknown field names are reported rather than dropped |
| `test_hardening.py` | Atomic job claim under concurrency, claim on a deleted job, per-user queue cap, upload size limit, job ownership enforcement, `csv_safe` formula-injection neutralisation, delete removing row and blobs |
| `test_sampling.py` | Every `rule_id` survives sampling, counts and totals still cover everything, small reports ship whole |

```bash
pip install -r backend/requirements-dev.txt
python -m pytest backend/tests -q      # run from the repository root
```

The suite covers the concurrency, security and sampling invariants — the parts where a regression is silent. It does **not** cover the SAP rule modules end-to-end against golden workbooks; see section 10.

---

## 8. Deployment and operations

### 8.1 Backend (Render)

1. Render → **New → Blueprint** → connect the repository. `render.yaml` provisions `mm-validator-api`.
2. Add secrets **in the dashboard** (service → Environment), never in the blueprint: `OPENAI_API_KEY`, `MM_PASSWORD`, `MM01_PASSWORD`, every `<MAILBOX>_PASSWORD`, `DATABASE_URL`, `ALLOWED_ORIGINS`.
3. `JWT_SECRET` is generated once by Render (`generateValue: true`).
4. Verify `GET /api/health` returns `{"status":"ok"}`.

### 8.2 Front end (Vercel)

1. Import the repository, root directory `frontend/`.
2. Set `VITE_API_URL` to the Render service URL.
3. Deploy, then set `ALLOWED_ORIGINS` on Render to the Vercel production URL and redeploy the API.

### 8.3 Database (Neon)

Create a free Postgres instance and set `DATABASE_URL` on Render. Without it the usage log and job store use SQLite inside the container, which **resets on every deploy or restart**. `storage_info()` surfaces this on the admin dashboard (`durable: false` plus an explanatory note).

### 8.4 Single-VM alternative

`deploy/` contains `setup_ec2.sh`, `nginx.conf` and `mmvalidator.service` for an Ubuntu/EC2 deployment: the front end is built to static files served by Nginx, the backend runs under systemd. Set `MM_PASSWORD` and `JWT_SECRET` in the unit file before starting.

### 8.5 Runbook

| Symptom | Likely cause | Action |
|---|---|---|
| Every account rejected after a deploy | Blueprint sync blanked the password variables | Re-enter them in the Render dashboard; confirm they are not declared in `render.yaml` |
| Browser blocked by CORS | `ALLOWED_ORIGINS` does not include the front-end origin | Add the origin (Vercel preview URLs are already covered by the regex) |
| Usage history empty after a deploy | `DATABASE_URL` unset — SQLite is ephemeral | Set `DATABASE_URL` to the Neon URL |
| Job stuck in `queued` | Worker thread died, or the process restarted | Restart the service: `recover_stuck_jobs()` re-queues from the retained inputs |
| HTTP 429 on submit | User already has 3 unfinished jobs | Wait, or delete a queued job |
| HTTP 409 on delete | The job is running | Wait for it to finish |
| AI findings missing | No key configured, or AI toggle off | Check `OPENAI_API_KEY`; look for `AI_SKIPPED_NO_KEY` / `AI_CALL_FAILED` INFO findings |
| Report shows fewer rows than the CSV | Expected — the JSON payload is sampled | Use the Downloads tab for the complete CSV |

---

## 9. Extension points

| To change | Edit | Deployment needed |
|---|---|---|
| Field types, lengths, decimals | Lookup `Field Types` sheet | No |
| Mandatory fields per material type | Lookup `Fields Entry` sheet | No |
| Plant → profit center | Lookup `Plant-ProfitCenter` sheet | No |
| Conditional business rules | Lookup `Dependencies` sheet | No |
| A new deterministic rule | Add a `check_*` function in `cross_field.py` and register it in `run_cross_checks()` | Yes |
| A new AI flag | Add a `prefilter_*` function + a `FLAG_INSTRUCTIONS` entry + mappings in `_friendly_flag` / `_field_for_flag` / `_sap_for_flag` | Yes |
| A new AI provider | Add a `_call_<provider>` returning `(text, in_tokens, out_tokens, error)` and extend the dispatch | Yes |
| Model / pricing | `aiConfig.js` (display) + `_DEFAULT_PRICING` or `AI_PRICING_JSON` | Pricing: no |
| Readiness weighting | `ValidationReport.readiness()` | Yes |

---

## 10. Known limitations and backlog

### 10.1 Functional

1. **The engine never writes to SAP.** Findings must be corrected in the workbook by hand. A correction-proposal export (suggested value per finding) is the obvious next increment.
2. **AI coverage is sampled, not exhaustive**, above 250 distinct cases per flag. This is stated in the report, but on very large files the AI flags are indicative rather than complete.
3. **Dependency rules support a fixed grammar** of six condition forms with a single trigger field and value. Multi-condition triggers (`A = X AND B = Y`) are not expressible.
4. **No Arabic/RTL support in the UI itself** — Arabic data is validated and exported correctly (`utf-8-sig`), but the interface is English only.

### 10.2 Technical debt

1. **Plaintext password comparison** and the fail-open credential/CORS defaults (6.1).
2. **No login rate limiting.**
3. **No structured logging or metrics** — the usage tables are the only operational record; broad `except Exception: pass` blocks in the progress, logging and migration paths are intentional for robustness but silent.
4. **Rule coverage is not tested against golden workbooks** — the SAP rule modules have no end-to-end regression fixtures, so a behaviour change in a `cross_field` rule would not be caught by CI.
5. **Single worker caps throughput.** The correct scaling move is a larger instance plus a worker count derived from memory, not naive horizontal scaling — though the atomic claim already makes multi-worker safe from a correctness standpoint.

### 10.2.1 Resolved alongside this document

| Item | Resolution |
|---|---|
| Dead client code — `api.js::validateFile()` posting to the removed `/api/validate` endpoint | Deleted |
| Display-cap mismatch — a hard-coded `300` in the UI against the engine's `SAMPLES_PER_GROUP = 200` | The engine now publishes `samples_per_group`; `ResultsView` derives the per-group row cap from it and passes it to both group views, so the banner can no longer overstate what the user will see |

### 10.3 Suggested next increments

| Priority | Item |
|---|---|
| High | Golden-workbook regression fixtures for the rule modules |
| High | Hashed credentials in the database + login rate limiting |
| Medium | Correction-proposal export (suggested value per finding) |
| Medium | Structured logging + an error-rate alert on `usage_sessions.status='error'` |
| Low | Multi-condition dependency triggers |
| Low | Per-project rule profiles (several lookup files, selectable at run time) |

---

## 11. Appendix A — repository layout

```
mm_validator/
├── app.py                      Streamlit UI (secondary front end)
├── validator/                  VALIDATION ENGINE — shared by both UIs
│   ├── models.py               Finding / FieldSpec / SheetData / Row / ValidationReport
│   ├── loader.py               .xls + .xlsx streaming reader, compact row storage
│   ├── lookup_loader.py        Lookup workbook → 5 configuration structures
│   ├── schema_check.py         Mandatory / type / length / decimal
│   ├── cross_field.py          Cross-extension consistency (orchestrates the UoM modules)
│   ├── plausibility.py         Physical-amount plausibility
│   ├── uom_conversion.py       Alternative-UoM conversion validation
│   ├── uom_data.py             SAP/ISO UoM master loader + dimension classification
│   ├── uom.py                  Base UoM ↔ description nature
│   ├── lookup_checks.py        Product type, material class, valuation type, profit center
│   ├── dependencies.py         Configurable conditional-rule engine
│   ├── ai_flags.py             Pre-filters + batched LLM calls
│   ├── report.py               HTML renderer
│   └── runner.py               Six-stage orchestrator
├── backend/                    FASTAPI APPLICATION TIER
│   ├── main.py                 Routes, CORS, auth dependencies, upload gate
│   ├── auth.py                 Directory, password resolution, JWT issue/verify
│   ├── jobs.py                 Job table, queue, single worker, recovery, retention
│   ├── usage_log.py            Usage table, cost model, dashboard aggregation
│   └── tests/                  pytest: dependencies · hardening · sampling
├── frontend/                   REACT SPA
│   └── src/
│       ├── pages/              Login · Validator · Validations · AiConfig · UsageDashboard · About
│       ├── components/         Layout · Sidebar · KPICards · ValidationProgress ·
│       │                       ResultsView · FindingsByCategory / BySheet / Table · SeverityBadge
│       ├── contexts/           AuthContext
│       ├── api.js              axios client, session handling, interceptors
│       └── aiConfig.js         Provider/model display constants (no key)
├── sample_data/                Blank template, lookup file, SAP_UOM_All.xlsx, synthetic fixture builder
├── deploy/                     Nginx + systemd + EC2 setup (single-VM alternative)
├── docs/                       This specification and the architecture diagram
├── render.yaml                 Render blueprint (secrets deliberately excluded)
└── zmm_create_invoice_po.abap  Unrelated ABAP utility kept in the repository
```

## 12. Appendix B — glossary

| Term | Meaning |
|---|---|
| **Migration Cockpit** | SAP S/4HANA tool that loads staged data via standard migration objects |
| **Product Master Creation** | The Migration Cockpit template for material master data |
| **MTART** | SAP material type (`ROH`, `HALB`, `FERT`, `HAWA`, `VERP`, `DIEN`, `UNBW`, `NLAG`, `LEIH`, and Z-codes) |
| **S_MARA / S_MARC / S_MARM / S_MBEW / S_MVKE** | SAP structures for general, plant, alternative-UoM, valuation and sales material data |
| **MEINS / UMREZ / UMREN** | Base unit of measure; conversion denominator; conversion numerator |
| **Extension sheet** | Any sheet other than Basic Data, carrying org-level data for a material |
| **Finding** | One rule violation: severity, category, sheet, row, field, material, value, `rule_id` |
| **Readiness score** | 0–100 per-material measure of how loadable the file is (4.8) |
| **Pre-filter** | Deterministic logic deciding whether a row is clearly fine, clearly wrong, or genuinely ambiguous — only the last reaches a model |
| **Blocked material** | A material with at least one ERROR finding |
