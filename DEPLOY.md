# Deploying the SAP MM Validator (Vercel + Render)

The app has two parts:

- **Frontend** (`frontend/`) — React/Vite static site → **Vercel**
- **Backend** (`backend/` + `validator/`) — FastAPI → **Render**

The React app talks to the API via `VITE_API_URL`. The OpenAI key lives **only**
on the backend (env var `OPENAI_API_KEY`) — it is never in the frontend bundle.

---

## 0. Before you start — rotate the OpenAI key ⚠️

The old key was previously embedded in source, so treat it as compromised:

1. In the OpenAI dashboard → **API keys**, **revoke** the old key.
2. **Create a new key.** You'll paste it into Render in step 2 (never into the code).

---

## 1. Push to GitHub

From the project root:

```bash
git init
git add .
git commit -m "SAP MM Validator — web app"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

`.gitignore` already excludes `node_modules/`, build output, and any real `.env`
files. (The `.env.example` files are committed on purpose.)

---

## 2. Deploy the backend on Render

1. Render dashboard → **New → Blueprint** → connect your GitHub repo.
   Render reads **`render.yaml`** and provisions the `mm-validator-api` web service.
2. Set the secret env vars **manually in the dashboard** (service →
   **Environment** → Add Environment Variable). They are deliberately NOT
   declared in `render.yaml` — blueprint syncs manage (and can wipe) whatever
   is listed there, so secrets live only in the dashboard where syncs never
   touch them:
   - `OPENAI_API_KEY` → your **new** OpenAI key
   - `MM_PASSWORD` → built-in admin password
   - `MM01_PASSWORD` → mm01 password
   - `SIDDIQ_UZZAMAN_PASSWORD`, `ISMAIL_SHAIK_PASSWORD`, `MOHAMED_OMRAN_PASSWORD`,
     `MOHAMED_OSAMA_PASSWORD`, `YAHYA_OMAR_PASSWORD`, `MOHAMED_ELEWA_PASSWORD`,
     `ABDELAZIZ_NASSAR_PASSWORD`, `ABDELRHAMAN_OSAMA_PASSWORD` → passwords for the
     named users (login id = their e-mail address; any password left unset/blank
     falls back to the dev default `password123` — set them all in production)
   - `ALLOWED_ORIGINS` → leave blank for now (you'll set it in step 4)
   - `DATABASE_URL` → *optional but recommended* — a Postgres URL for the usage
     log (see "Usage log & admin dashboard" below). Without it the log lives in
     a local SQLite file that **resets on every deploy/restart** (Render's free
     tier has an ephemeral filesystem).
   - `AI_PRICING_JSON` → *optional* — override per-model token prices used for
     the cost column, e.g. `{"gpt-5.4": [1.25, 10.0]}` (USD per 1M input/output
     tokens).
   - `JWT_SECRET` is auto-generated; `PYTHON_VERSION` is preset.
3. Click **Apply** / **Create**. Wait for the first deploy to go green.
4. Copy the service URL, e.g. `https://mm-validator-api.onrender.com`.
   Verify it: opening `…/api/health` should return `{"status":"ok"}`.

> Free-tier note: Render spins the service down when idle, so the **first**
> request after a while takes ~30–50s to wake up. Subsequent requests are fast.

---

## 3. Deploy the frontend on Vercel

1. Vercel dashboard → **Add New → Project** → import the same GitHub repo.
2. Set **Root Directory** = `frontend` (click *Edit* next to the repo root).
   Framework preset auto-detects **Vite** (build `npm run build`, output `dist`).
3. Add an **Environment Variable**:
   - `VITE_API_URL` = your Render URL from step 2 (e.g. `https://mm-validator-api.onrender.com`)
4. **Deploy.** Copy the resulting URL, e.g. `https://mm-validator.vercel.app`.

---

## 4. Connect the two (CORS)

1. Back in **Render** → your service → **Environment**:
   - Set `ALLOWED_ORIGINS` = your Vercel URL (e.g. `https://mm-validator.vercel.app`)
   - (Add your custom domain too, comma-separated, if you have one.)
2. Save — Render redeploys automatically.

---

## 5. Test

Open the Vercel URL and sign in:

Login ids are e-mail addresses (case doesn't matter). Roles:

| User | Role | Sees |
|---|---|---|
| `siddiq.uzzaman@arete-global.com` (Siddiq Zaman) | Admin | Validator + Admin Activities (AI Configuration, Usage Dashboard) |
| `admin` (built-in) | Admin | Same as above |
| `ismail.shaik@`, `mohamed.omran@`, `mohamed.osama@`, `yahya.omar@`, `mohamed.elewa@`, `abdelaziz.nassar@`, `abdelrhaman.osama@arete-global.com` | Non-Admin | Validator only |
| `mm01` (built-in) | Non-Admin | Validator only |

Upload the lookup file (Step 1) + a Product Master template (Step 2) and run.
Toggle **AI-Enabled Validations** to exercise the OpenAI path (uses the server key).

---

## Usage log & admin dashboard

Every validation run is logged (user, date/time, materials validated, AI calls,
tokens in/out, estimated cost, duration, status). The `admin` user sees it under
**Admin Activities → Usage Dashboard**, with per-user totals, a session log and
CSV export.

**Storage:** by default the log is a SQLite file inside the service — fine for
local use, but on Render's free tier the filesystem is ephemeral, so the log
resets on every deploy/restart. To make it permanent, create a **free Postgres**
database (any of these works):

- [Neon](https://neon.tech) — free serverless Postgres
- [Supabase](https://supabase.com) — free Postgres
- Render's own Postgres (free instance expires after 30 days)

Copy its connection string into the `DATABASE_URL` env var on Render and
redeploy — the table is created automatically on startup. No other change needed.

**Cost estimates** use built-in per-model prices (Claude Haiku 4.5 = $1/$5 per
1M tokens, etc.). Verify the OpenAI `gpt-5.4` rate against openai.com/pricing
and override via `AI_PRICING_JSON` if it drifts.

---

## Keeping the backend awake (free tier)

Render's free plan sleeps the service after ~15 min idle, so the first request
then cold-starts (~30–50s). Two layers mitigate this:

- **Built in:** the app pings `/api/health` when it loads and every 10 min while
  open, so the server is usually warm by the time someone clicks *Run Validation*
  during an active session.
- **24/7 (optional):** add a free uptime monitor — e.g. **UptimeRobot** or
  **cron-job.org** — that GETs `https://<your-backend>.onrender.com/api/health`
  every 10 minutes. That keeps it from ever sleeping. (Or upgrade the Render
  instance to a paid, always-on plan.)

## Updating later

Push to `main` → **both** Vercel and Render auto-deploy from the same repo.
Changing an env var (key, password, origins) is done in the respective dashboard;
no code change or re-push needed.
