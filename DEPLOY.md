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
2. When prompted, set the secret env vars (marked "sync:false"):
   - `OPENAI_API_KEY` → your **new** OpenAI key
   - `MM_PASSWORD` → admin password
   - `MM01_PASSWORD` → mm01 password
   - `ALLOWED_ORIGINS` → leave blank for now (you'll set it in step 4)
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

| User | Password | Sees |
|---|---|---|
| `admin` | *(your `MM_PASSWORD`)* | Validator + Admin Activities (AI Configuration) |
| `mm01` | *(your `MM01_PASSWORD`)* | Validator only |

Upload the lookup file (Step 1) + a Product Master template (Step 2) and run.
Toggle **AI Warning Flags** to exercise the OpenAI path (uses the server key).

---

## Updating later

Push to `main` → **both** Vercel and Render auto-deploy from the same repo.
Changing an env var (key, password, origins) is done in the respective dashboard;
no code change or re-push needed.
