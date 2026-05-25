# CI/CD: GitHub → Fly

One workflow lives in `.github/workflows/`:

| Workflow | Trigger | Effect |
|---|---|---|
| `deploy-fly.yml` | Push to `main` touching backend or `public/`, or manual run | Builds the fat Fly image (API + UI + SciNCL), rolls out, smoke-tests `/health` |

The Fly machine serves the UI from the same origin as the API, so a single
deploy ships both the frontend and the backend at once.

PDF uploads from the live site keep working without any pipeline involvement —
they POST to the same Fly backend, which handles topic extraction, embedding,
scoring, and graph update in the background.

---

## One-time setup (~1 min)

You need to add **one** secret to **Settings → Secrets and variables → Actions** at
<https://github.com/dogeyboy1932/armchair/settings/secrets/actions>.

### `FLY_API_TOKEN`

Already generated for you with `flyctl tokens create deploy --app siip-armchair-akhil`.
Paste the token value (the long `FlyV1 fm2_...` string) from the terminal output.

If you need to rotate it:
```bash
flyctl tokens create deploy --app siip-armchair-akhil --name "github-actions-deploy" --expiry 8760h
```

---

## Verifying the pipeline

After the secret is set, push any small change to `main`:

```bash
git commit --allow-empty -m "ci: trigger deploy" && git push
```

Then watch <https://github.com/dogeyboy1932/armchair/actions>. The
`Deploy backend (Fly.io)` job takes ~3 min on incremental builds (longer first
time, since it has to cache PyTorch + SciNCL layers).

The workflow has a **manual "Run workflow"** button on the Actions page, useful
for redeploying without an actual code change.

---

## Daily usage

| You do | We do |
|---|---|
| `git push` backend or `public/` changes | Workflow rebuilds Fly image + smoke-tests `/health` |
| Upload a PDF in the UI | Live Fly machine ingests it directly — no pipeline involvement |
| Run a script manually | `flyctl ssh console --app siip-armchair-akhil -C "sh -c 'cd /app && python scripts/whatever.py'"` |

No more local SciNCL runs, no more manual `flyctl deploy`.
