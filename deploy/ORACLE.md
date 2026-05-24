# Deploy SIIP on Oracle Cloud (Free)

**Repo:** https://github.com/dogeyboy1932/armchair  
**Cost:** $0/month (Oracle Always Free tier)  
**Time:** ~20 minutes hands-on + ~20 minutes automated setup

---

## What you do vs what the scripts do

| Step | Who does it |
|------|-------------|
| Create Oracle account + VM in the web console | **You** (~15 min, one time) |
| Open port 8080 in Oracle firewall | **You** (~2 min, one time) |
| SSH into the VM | **You** (~1 min) |
| Paste one install command | **You** (~10 seconds) |
| Install Docker | Script |
| Generate passwords, create `.env` | Script |
| Open Linux firewall (UFW + iptables) | Script |
| Add swap if RAM < 12 GB | Script |
| Start Postgres, Neo4j, Milvus, backend | Script |
| Seed 33 courses + build graph | Script |
| Print your public URL | Script |

After setup, your link looks like: **`http://YOUR_ORACLE_IP:8080`**

---

## Prerequisites

- A credit/debit card (Oracle uses it for identity verification — stays at **$0** on Always Free)
- An SSH client (Terminal on Mac/Linux; [PuTTY](https://www.putty.org/) on Windows)
- This repo is public — no GitHub token needed on the server

---

## Part 1 — Create the Oracle VM (web console)

### 1.1 Sign up

1. Go to https://cloud.oracle.com
2. Click **Start for free**
3. Complete registration (pick any home region — see note below)

> **Region tip:** Always Free ARM instances run out of capacity in popular regions (e.g. `us-ashburn-1`, `us-phoenix-1`). If creation fails with **"Out of host capacity"**, try another region such as `uk-london-1`, `eu-frankfurt-1`, or `ap-tokyo-1`.

### 1.2 Create the VM

1. Open the **☰ menu** → **Compute** → **Instances**
2. Click **Create instance**
3. Configure:

| Setting | Value |
|---------|-------|
| **Name** | `armchair-prod` |
| **Image** | **Ubuntu 22.04** (Canonical) |
| **Shape** | **Ampere** → **VM.Standard.A1.Flex** |
| **OCPUs** | **2** (minimum; 4 is fine) |
| **Memory (GB)** | **12** (minimum; 24 is fine) |
| **Boot volume** | 50 GB (default is fine) |

4. **Networking** — click **Edit** and set:
   - **Public IPv4 address:** **Yes** ← required (without this you cannot SSH from your laptop or share a link)
   - Leave other defaults (creates a VCN + subnet automatically)
5. **SSH keys** — choose one:
   - **Generate a key pair for me** → download the private key (`ssh-key-*.key`) and save it somewhere safe
   - Or paste your existing public key
6. Click **Create**
7. Wait until **State** = **Running** (green)
8. Copy the **Public IP address** (e.g. `132.145.xxx.xxx`)

### 1.3 Open port 8080 (Oracle cloud firewall)

Oracle blocks all ports except 22 by default. You must add a rule:

1. On the instance page, click the **Subnet** link (under Instance details → Primary VNIC)
2. Click the **Security list** link for that subnet
3. Click **Add ingress rules**
4. Fill in:

| Field | Value |
|-------|-------|
| Source CIDR | `0.0.0.0/0` |
| IP Protocol | TCP |
| Destination port range | `8080` |
| Description | `SIIP app` |

5. Click **Add ingress rules**

> **Optional (for HTTPS later):** repeat with ports `80` and `443`.

The install script also opens the Linux-level firewall automatically. Both layers are required on Oracle.

---

## Part 2 — Install (one command)

### 2.1 SSH into the VM

**Mac / Linux:**

```bash
chmod 400 ~/Downloads/ssh-key-YYYY-MM-DD.key   # your downloaded key
ssh -i ~/Downloads/ssh-key-YYYY-MM-DD.key ubuntu@YOUR_ORACLE_IP
```

**Windows (PuTTY):** load the `.key` or `.ppk` file under Connection → SSH → Auth.

Default username is **`ubuntu`**.

### 2.2 Run the installer

Paste this single command on the server:

```bash
curl -fsSL https://raw.githubusercontent.com/dogeyboy1932/armchair/main/deploy/oracle-install.sh | bash
```

That's it. Go get coffee — first run takes **20–40 minutes** (Docker images + SciNCL model download + data seeding).

#### Optional: include Gemini API key for pre-generated explanations

```bash
GEMINI_API_KEY=your-key-here curl -fsSL https://raw.githubusercontent.com/dogeyboy1932/armchair/main/deploy/oracle-install.sh | bash
```

Without this, the app still works — users paste their own key via the **⚙ API Key** button in the UI.

### What the installer prints when done

```
✓ Live at: http://132.145.xxx.xxx:8080
```

Open that URL in any browser and share it with your team.

---

## Part 3 — Verify

On the server:

```bash
curl http://127.0.0.1:8080/health
# {"status":"ok"}
```

In a browser:

- **Graph view:** `http://YOUR_ORACLE_IP:8080`
- **Upload page:** `http://YOUR_ORACLE_IP:8080/upload`
- **API docs:** `http://YOUR_ORACLE_IP:8080/docs`

---

## Part 4 — Optional HTTPS with a custom domain

1. Buy or use a domain you control
2. Add a DNS **A record**: `armchair.yourdomain.com` → your Oracle public IP
3. Add ingress rules for ports **80** and **443** (same steps as 1.3)
4. On the server:

```bash
cd ~/armchair
SIIP_DOMAIN=armchair.yourdomain.com ./deploy/bootstrap.sh
```

Caddy is installed automatically and provisions a free TLS certificate.

---

## Part 5 — Day-to-day commands

All commands run on the server from `~/armchair`:

```bash
cd ~/armchair
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# Check all containers
$COMPOSE ps

# Follow backend logs
$COMPOSE logs -f backend

# Pull latest code and restart
git pull origin main
$COMPOSE up -d --build

# Re-run bootstrap (safe — skips seed if data exists)
./deploy/bootstrap.sh

# Stop everything (VM still runs, app is down)
$COMPOSE down

# Start again
$COMPOSE up -d
```

---

## Part 6 — Troubleshooting

### "Out of host capacity" for VM.Standard.A1.Flex (most common)

Oracle's free ARM VMs are popular — **AD-1 is often full**. Fix in this order:

#### Fix 1 — Change availability domain (try first)

On the **Create instance** page, under **Placement**:

| Setting | Change to |
|---------|-----------|
| **Availability domain** | **AD-2** (if that fails, try **AD-3**) |
| **Fault domain** | **Let Oracle choose** (leave as-is) |

Click **Create** again. Stay on shape `VM.Standard.A1.Flex`.

#### Fix 2 — Use minimum shape to squeeze in

| Setting | Value |
|---------|-------|
| **OCPUs** | **1** |
| **Memory** | **6 GB** |

The install script adds 4 GB swap — 6 GB RAM works, just slower on first boot.

#### Fix 3 — Retry at off-peak hours

Capacity frees up randomly. Retry early morning US time (5–8 AM ET).

#### Fix 4 — Different home region (last resort)

Always Free ARM capacity is per region. If your home region stays full (`us-ashburn-1` and `us-phoenix-1` are worst), you'd need a **new Oracle account** with a different home region (`uk-london-1`, `eu-frankfurt-1`, `ap-osaka-1`). You cannot change home region on an existing account.

#### If ARM never works — free fallback (no VM)

Run locally and expose via Cloudflare Tunnel ($0):

```bash
cloudflared tunnel --url http://localhost:8080
```

Share the `https://....trycloudflare.com` link. Your laptop must stay on.

---

### Wrong networking: Public IPv4 = No

If the review page shows **Public IPv4 address: No**, you cannot SSH from home or share a public link.

**Fix:** Edit **Networking** → **Assign a public IPv4 address** → **Yes** → Create again.

---
### Install script fails on Docker

```bash
cd ~/armchair
sudo ./deploy/bootstrap.sh
```

### Page won't load in browser but health check works on server

Port 8080 isn't open in Oracle's **Security List** (Part 1.3). The Linux firewall is handled by the script; the Oracle console rule is not.

### Backend unhealthy / Milvus won't start

Milvus is slow on first boot. Wait 5 minutes, then:

```bash
cd ~/armchair
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs milvus
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart backend
```

### Out of memory during seed

The script adds 4 GB swap automatically on machines with < 12 GB RAM. If seed still fails:

```bash
free -h   # confirm swap is active
cd ~/armchair
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend python scripts/seed.py
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend python scripts/build_graph.py
```

### UI loads but API calls fail

Make sure you're on the latest code (API URL fix):

```bash
cd ~/armchair && git pull origin main && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Re-install from scratch

```bash
cd ~
rm -rf armchair
curl -fsSL https://raw.githubusercontent.com/dogeyboy1932/armchair/main/deploy/oracle-install.sh | bash
```

Database volumes are removed with the repo folder only if you also run:

```bash
docker volume ls | grep siip   # list volumes
docker compose -f ~/armchair/docker-compose.yml down -v   # ⚠ deletes all data
```

---

## Part 7 — Cost & limits

| Item | Cost |
|------|------|
| VM.Standard.A1.Flex (Always Free) | **$0/month** |
| 200 GB block storage (Always Free) | **$0/month** |
| 10 TB outbound data/month (Always Free) | **$0/month** |
| Stopping the VM | Still free (storage only) |

**Always Free limits:** up to 4 OCPUs + 24 GB RAM total across all Always Free ARM instances in your tenancy.

---

## Quick reference

```
Oracle console:  https://cloud.oracle.com
Repo:            https://github.com/dogeyboy1932/armchair
Install command: curl -fsSL https://raw.githubusercontent.com/dogeyboy1932/armchair/main/deploy/oracle-install.sh | bash
App URL:         http://YOUR_ORACLE_IP:8080
Health check:    http://YOUR_ORACLE_IP:8080/health
```

---

## Architecture on the server

```
Internet
   │
   ▼
Oracle Security List (port 8080)  ← you configure once in console
   │
   ▼
Ubuntu VM
   ├── bootstrap.sh opens UFW + iptables
   └── Docker Compose
         ├── backend (FastAPI + UI)  :8080
         ├── postgres
         ├── neo4j
         ├── milvus + etcd + minio
         └── (DB ports NOT exposed publicly)
```

Frontend and backend are served together — no separate Netlify or CDN needed.
