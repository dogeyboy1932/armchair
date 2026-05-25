# CI/CD: GitHub → Fly + Netlify

Two workflows live in `.github/workflows/`:

| Workflow | Trigger | Effect |
|---|---|---|
| `deploy-fly.yml`     | Push to `main` touching backend or `public/`, or manual run | Builds the fat Fly image, rolls out, smoke-tests `/health` |
| `deploy-netlify.yml` | Push to `main` touching `public/`, or manual run            | Generates `config.js` pointing at the Fly backend, deploys to Netlify prod |

`public/` changes trigger **both** so the Fly-served fallback and the Netlify CDN stay in sync.

PDF uploads from the live site keep working without any pipeline involvement — they POST to the Fly backend which handles topic extraction, embedding, scoring, and graph update in the background.

---

## One-time setup (~5 min)

You need to add four secrets to **Settings → Secrets and variables → Actions** at
<https://github.com/dogeyboy1932/armchair/settings/secrets/actions>.

### 1. `FLY_API_TOKEN`

Already generated for you with `flyctl tokens create deploy --app siip-armchair-akhil`.
Paste the token value (the long `FlyV1 fm2_...` string) from the terminal output.

If you need to rotate it:
```bash
flyctl tokens create deploy --app siip-armchair-akhil --name "github-actions-deploy" --expiry 8760h
```

### 2. `NETLIFY_AUTH_TOKEN`

1. <https://app.netlify.com/user/applications#personal-access-tokens>
2. **New access token** → name it `github-actions` → copy the value.

### 3. `NETLIFY_SITE_ID`

After you've deployed once (locally via `bash deploy/free/03-deploy-netlify.sh`):
```bash
cd deploy/free/.netlify
cat state.json   # has the siteId field
```
Or, from the Netlify dashboard: **Site → Site configuration → Site details → Site ID**.

### 4. `SIIP_API_URL`

Just the Fly URL with no trailing slash:
```
https://siip-armchair-akhil.fly.dev
```

---

## Verifying the pipeline

After secrets are set, push any small change to `main`:

```bash
git commit --allow-empty -m "ci: trigger deploy" && git push
```

Then watch <https://github.com/dogeyboy1932/armchair/actions>. The `Deploy backend (Fly.io)` job takes ~3 min on incremental builds (longer first time, since it has to cache PyTorch + SciNCL layers). The Netlify job is ~30 s.

Both workflows have a **manual "Run workflow"** button on the Actions page, useful for redeploying without an actual code change.

---

## Daily usage

| You do | We do |
|---|---|
| `git push` backend changes | Workflow rebuilds Fly image + smoke-tests `/health` |
| `git push` `public/*.html` changes | Both workflows run, frontend updates on Netlify (~30s) and Fly fallback (~3min) |
| Upload a PDF in the UI | Live Fly machine ingests it directly — no pipeline involvement |
| Run a script manually | `flyctl ssh console --app siip-armchair-akhil -C "sh -c 'cd /app && python scripts/whatever.py'"` |

No more local SciNCL runs, no more manual `flyctl deploy`.
