# Oracle Cloud deploy (CLI-driven)

End-to-end automation: from "I have Oracle credentials" to "https://my-app.com is live."

## Prerequisites (one-time, manual)

You must do these in the Oracle web console because they can't be automated:

1. **Create an Oracle Cloud account** at https://cloud.oracle.com (pick a non-Ashburn home region — see ORACLE.md).
2. **Generate an API key** under your profile → API Keys → Add API Key → Generate.
3. **Download the private key** (`oci_api_key.pem`) and note its absolute path.
4. **Copy the configuration preview** — it contains your `tenancy`, `user`, `fingerprint`, `region`.

## Running

```bash
cp deploy/oci/credentials.env.example deploy/oci/credentials.env
# Edit credentials.env with the values from step 4 + key path from step 3

deploy/oci/deploy.sh
```

That's it. The orchestrator:

1. Installs OCI CLI into a local venv (no sudo).
2. Writes `~/.oci/config` and copies your key.
3. Creates VCN, subnet, internet gateway, route table, security list (ports 22, 80, 443, 8080).
4. Generates an SSH keypair (stored in `state/`).
5. Launches a VM.Standard.A1.Flex Ubuntu 22.04 instance (2 OCPU / 12 GB) — retries across availability domains if capacity is unavailable.
6. SSHes in, runs `oracle-install.sh`, waits for `/health` to return 200.
7. Prints the live URL.

Total time: 30-50 minutes (mostly downloading Docker images + the SciNCL model on first boot).

## File layout

| File | Purpose |
|------|---------|
| `00-install-cli.sh` | Installs OCI CLI into `deploy/oci/.venv` (no sudo). |
| `01-configure.sh` | Writes `~/.oci/config` from env vars. |
| `02-create-vm.sh` | Creates all networking + launches VM with capacity retry. |
| `03-deploy-app.sh` | SSHes in and runs the SIIP installer. |
| `deploy.sh` | Runs all of the above in order. |
| `credentials.env.example` | Template for the 5 required values. |
| `state/vm.env` | Created by 02-create-vm.sh — VM OCID, public IP, SSH key path. |
| `state/<vm>_id_ed25519` | Generated SSH private key for the VM. |

## Running steps individually

```bash
# Step 1: install CLI (once)
deploy/oci/00-install-cli.sh
source deploy/oci/.venv/bin/activate

# Step 2: configure credentials (once)
set -a; source deploy/oci/credentials.env; set +a
deploy/oci/01-configure.sh

# Step 3: create the VM (re-runs are idempotent — reuses existing VCN/instance)
deploy/oci/02-create-vm.sh

# Step 4: deploy the app (re-runs pull latest code on the server)
deploy/oci/03-deploy-app.sh
```

## Common issues

**"All availability domains were out of capacity"** — Always Free ARM is heavily contested. Either re-run in 30 min, or fall back to a smaller shape: `VM_OCPUS=1 VM_MEM_GB=6 deploy/oci/02-create-vm.sh`.

**SSH hangs after launch** — Cloud-init takes 30-90s after the instance reports RUNNING. The deploy script already waits, but if you SSH manually, give it a minute.

**Health check fails** — First boot pulls ~4 GB of Docker images and downloads the 420 MB SciNCL model. Give it 5-10 min, then re-run `deploy/oci/03-deploy-app.sh`.

## Tearing down (delete everything)

```bash
source deploy/oci/.venv/bin/activate
source deploy/oci/state/vm.env

# Terminate VM
oci compute instance terminate --instance-id "$INSTANCE_OCID" --force --wait-for-state TERMINATED

# Delete VCN (will also delete subnet, IG, route table if no other dependencies)
oci network vcn delete --vcn-id "$VCN_OCID" --force --wait-for-state TERMINATED

rm -rf deploy/oci/state
```
