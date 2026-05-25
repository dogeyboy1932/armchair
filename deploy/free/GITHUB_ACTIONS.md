# CI/CD: GitHub → Fly

## The model

- **Shared cloud data:** Supabase (Postgres + pgvector) and Neo4j Aura. Local
  dev uses the same instances via `bash deploy/free/link-local-env.sh`.
- **Code deploys on push:** every commit to `main` triggers a Fly redeploy
  (API + UI + SciNCL in one image).
- **Data from the live site:** PDF uploads on production write directly to the
  shared cloud DBs. No git push needed; local dev sees them immediately.

| Workflow | Trigger | Effect |
|---|---|---|
| `deploy-fly.yml` | Any push to `main`, or manual run | Rebuild Fly image, roll out, smoke-test `/health` |

Live URL: **https://siip-armchair-akhil.fly.dev**

---

## One-time setup (~1 min)

Add **one** secret at
<https://github.com/dogeyboy1932/armchair/settings/secrets/actions>:

### `FLY_API_TOKEN`

```bash
flyctl tokens create deploy --app siip-armchair-akhil --name "github-actions-deploy" --expiry 8760h
```

Paste the `FlyV1 fm2_...` value as the secret.

---

## Daily usage

| You do | What happens |
|---|---|
| Edit code/CSS locally, `git push origin main` | GitHub Actions deploys to Fly (~3 min) |
| Run `uvicorn` after `link-local-env.sh` | Same Supabase + Aura as production |
| Upload a PDF on the live site | Fly ingests into shared cloud DBs; local sees it on refresh |
| Run a maintenance script | Prefer Fly: `flyctl ssh console --app siip-armchair-akhil -C "sh -c 'cd /app && python scripts/…'"` |

---

## Verify the pipeline

```bash
git commit --allow-empty -m "ci: trigger deploy" && git push origin main
```

Watch <https://github.com/dogeyboy1932/armchair/actions>.
