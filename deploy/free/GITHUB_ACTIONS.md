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

## One-time setup (~2 min)

**If Actions shows "All jobs have failed"**, the usual cause is a missing
`FLY_API_TOKEN` secret. The deploy step fails before the Docker build starts.

### Option A — automated (recommended)

```bash
flyctl auth login          # if not already
gh auth login              # GitHub CLI: https://cli.github.com/
bash deploy/free/setup-github-actions.sh
```

This creates a Fly deploy token and stores it in GitHub Actions secrets.

### Option B — manual

1. ```bash
   flyctl tokens create deploy --app siip-armchair-akhil --name github-actions --expiry 8760h
   ```
2. Copy the `FlyV1 fm2_...` line.
3. GitHub → [Settings → Secrets → Actions](https://github.com/dogeyboy1932/armchair/settings/secrets/actions)
   - Name: `FLY_API_TOKEN`
   - Value: paste the token

---

## Daily usage

| You do | What happens |
|---|---|
| Edit code/CSS locally, `git push origin main` | GitHub Actions deploys to Fly (~5–15 min first build, ~3 min after) |
| Run `uvicorn` after `link-local-env.sh` | Same Supabase + Aura as production |
| Upload a PDF on the live site | Fly ingests into shared cloud DBs; local sees it on refresh |
| Run a maintenance script | Prefer Fly: `flyctl ssh console --app siip-armchair-akhil -C "sh -c 'cd /app && python scripts/…'"` |

---

## Verify the pipeline

After the secret is set:

```bash
git commit --allow-empty -m "ci: trigger deploy" && git push origin main
```

Watch <https://github.com/dogeyboy1932/armchair/actions>. A green run means
`https://siip-armchair-akhil.fly.dev` is serving the latest `main` commit.

Manual deploy (bypasses GitHub, same result):

```bash
bash deploy/free/02-deploy-fly.sh
```
