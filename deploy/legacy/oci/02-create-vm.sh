#!/usr/bin/env bash
# Create everything needed to host SIIP on Oracle Always Free:
#   - VCN + subnet + internet gateway + route table + security list (ports 22, 80, 443, 8080)
#   - SSH keypair (stored in deploy/oci/state/)
#   - VM.Standard.A1.Flex Ubuntu 22.04 ARM instance (2 OCPU / 12 GB by default)
#
# Retries capacity errors across availability domains automatically.
# Writes resource OCIDs + public IP to deploy/oci/state/vm.env for later steps.
#
# Required: OCI CLI installed + ~/.oci/config configured (run 00-install-cli.sh and 01-configure.sh first).
#
# Optional env vars:
#   VM_NAME       (default: siip-armchair)
#   VM_OCPUS      (default: 2)
#   VM_MEM_GB     (default: 12)
#   VM_BOOT_GB    (default: 50)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/oci"
STATE="$ROOT/state"
mkdir -p "$STATE"

VM_NAME="${VM_NAME:-siip-armchair}"
VM_OCPUS="${VM_OCPUS:-2}"
VM_MEM_GB="${VM_MEM_GB:-12}"
VM_BOOT_GB="${VM_BOOT_GB:-50}"
SHAPE="VM.Standard.A1.Flex"

if ! command -v oci >/dev/null 2>&1; then
  echo "oci CLI not found. Activate venv: source $ROOT/.venv/bin/activate" >&2
  exit 1
fi

log() { printf '\n==> %s\n' "$*"; }

# ── Tenancy + region from config ──────────────────────────────────────────────
TENANCY_OCID="$(awk -F= '/^tenancy=/{print $2}' "$HOME/.oci/config" | tr -d '[:space:]')"
REGION="$(awk -F= '/^region=/{print $2}' "$HOME/.oci/config" | tr -d '[:space:]')"
log "Tenancy: $TENANCY_OCID"
log "Region:  $REGION"

# ── Compartment: use root tenancy compartment (simplest, Always Free works there) ──
COMPARTMENT_OCID="$TENANCY_OCID"

# ── SSH keypair ───────────────────────────────────────────────────────────────
SSH_KEY="$STATE/${VM_NAME}_id_ed25519"
if [[ ! -f "$SSH_KEY" ]]; then
  log "Generating SSH keypair at $SSH_KEY"
  ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" -C "$VM_NAME"
fi
SSH_PUB="${SSH_KEY}.pub"

# ── VCN ───────────────────────────────────────────────────────────────────────
log "Ensuring VCN exists…"
VCN_OCID="$(oci network vcn list --compartment-id "$COMPARTMENT_OCID" \
  --display-name "${VM_NAME}-vcn" --query 'data[0].id' --raw-output 2>/dev/null || true)"

if [[ -z "$VCN_OCID" || "$VCN_OCID" == "null" ]]; then
  VCN_OCID="$(oci network vcn create --compartment-id "$COMPARTMENT_OCID" \
    --cidr-block "10.0.0.0/16" --display-name "${VM_NAME}-vcn" \
    --dns-label "${VM_NAME//-/}vcn" --wait-for-state AVAILABLE \
    --query 'data.id' --raw-output)"
  log "Created VCN: $VCN_OCID"
else
  log "Reusing VCN: $VCN_OCID"
fi

# ── Internet gateway ──────────────────────────────────────────────────────────
log "Ensuring internet gateway exists…"
IG_OCID="$(oci network internet-gateway list --compartment-id "$COMPARTMENT_OCID" \
  --vcn-id "$VCN_OCID" --query 'data[0].id' --raw-output 2>/dev/null || true)"

if [[ -z "$IG_OCID" || "$IG_OCID" == "null" ]]; then
  IG_OCID="$(oci network internet-gateway create --compartment-id "$COMPARTMENT_OCID" \
    --vcn-id "$VCN_OCID" --display-name "${VM_NAME}-ig" --is-enabled true \
    --wait-for-state AVAILABLE --query 'data.id' --raw-output)"
  log "Created internet gateway: $IG_OCID"
else
  log "Reusing internet gateway: $IG_OCID"
fi

# ── Default route table → add 0.0.0.0/0 → IG ──────────────────────────────────
RT_OCID="$(oci network vcn get --vcn-id "$VCN_OCID" \
  --query 'data."default-route-table-id"' --raw-output)"
log "Default route table: $RT_OCID"

ROUTE_RULES_JSON="$(jq -n --arg ig "$IG_OCID" '[{"destination":"0.0.0.0/0","destinationType":"CIDR_BLOCK","networkEntityId":$ig}]')"
oci network route-table update --rt-id "$RT_OCID" \
  --route-rules "$ROUTE_RULES_JSON" --force >/dev/null
log "Route table updated with default → internet gateway"

# ── Default security list: open 22, 80, 443, 8080 ─────────────────────────────
SL_OCID="$(oci network vcn get --vcn-id "$VCN_OCID" \
  --query 'data."default-security-list-id"' --raw-output)"
log "Default security list: $SL_OCID"

INGRESS_JSON="$(jq -n '
[
  {"source":"0.0.0.0/0","protocol":"6","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},
  {"source":"0.0.0.0/0","protocol":"6","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":80,"max":80}}},
  {"source":"0.0.0.0/0","protocol":"6","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":443,"max":443}}},
  {"source":"0.0.0.0/0","protocol":"6","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":8080,"max":8080}}}
]')"
EGRESS_JSON='[{"destination":"0.0.0.0/0","protocol":"all","isStateless":false}]'

oci network security-list update --security-list-id "$SL_OCID" \
  --ingress-security-rules "$INGRESS_JSON" \
  --egress-security-rules "$EGRESS_JSON" --force >/dev/null
log "Security list opened: 22, 80, 443, 8080"

# ── Pick an availability domain that has the shape available ──────────────────
log "Listing availability domains…"
ADS="$(oci iam availability-domain list --compartment-id "$COMPARTMENT_OCID" \
  --query 'data[*].name' --raw-output | jq -r '.[]')"
log "Available ADs:"
echo "$ADS" | sed 's/^/    /'

# ── Subnet (regional, so single subnet across ADs) ────────────────────────────
log "Ensuring subnet exists…"
SUBNET_OCID="$(oci network subnet list --compartment-id "$COMPARTMENT_OCID" \
  --vcn-id "$VCN_OCID" --display-name "${VM_NAME}-subnet" \
  --query 'data[0].id' --raw-output 2>/dev/null || true)"

if [[ -z "$SUBNET_OCID" || "$SUBNET_OCID" == "null" ]]; then
  SUBNET_OCID="$(oci network subnet create --compartment-id "$COMPARTMENT_OCID" \
    --vcn-id "$VCN_OCID" --cidr-block "10.0.1.0/24" \
    --display-name "${VM_NAME}-subnet" --dns-label "${VM_NAME//-/}sn" \
    --route-table-id "$RT_OCID" --security-list-ids "[\"$SL_OCID\"]" \
    --wait-for-state AVAILABLE --query 'data.id' --raw-output)"
  log "Created subnet: $SUBNET_OCID"
else
  log "Reusing subnet: $SUBNET_OCID"
fi

# ── Latest Ubuntu 22.04 ARM image ─────────────────────────────────────────────
log "Finding latest Ubuntu 22.04 ARM image…"
IMAGE_OCID="$(oci compute image list --compartment-id "$COMPARTMENT_OCID" \
  --operating-system "Canonical Ubuntu" --operating-system-version "22.04" \
  --shape "$SHAPE" --sort-by TIMECREATED --sort-order DESC \
  --query 'data[0].id' --raw-output)"
if [[ -z "$IMAGE_OCID" || "$IMAGE_OCID" == "null" ]]; then
  echo "Could not find Ubuntu 22.04 ARM image. Aborting." >&2
  exit 1
fi
log "Using image: $IMAGE_OCID"

# ── Check if instance already exists ──────────────────────────────────────────
EXISTING="$(oci compute instance list --compartment-id "$COMPARTMENT_OCID" \
  --display-name "$VM_NAME" --lifecycle-state RUNNING \
  --query 'data[0].id' --raw-output 2>/dev/null || true)"
if [[ -n "$EXISTING" && "$EXISTING" != "null" ]]; then
  INSTANCE_OCID="$EXISTING"
  log "Instance already running: $INSTANCE_OCID"
else
  # ── Launch with capacity retry across ADs ─────────────────────────────────
  SHAPE_CONFIG="$(jq -n --argjson ocpus "$VM_OCPUS" --argjson mem "$VM_MEM_GB" \
    '{"ocpus":$ocpus,"memoryInGBs":$mem}')"
  SSH_PUB_CONTENT="$(cat "$SSH_PUB")"
  METADATA="$(jq -n --arg k "$SSH_PUB_CONTENT" '{"ssh_authorized_keys":$k}')"

  INSTANCE_OCID=""
  for AD in $ADS; do
    log "Trying availability domain: $AD"
    set +e
    OUTPUT="$(oci compute instance launch \
      --availability-domain "$AD" \
      --compartment-id "$COMPARTMENT_OCID" \
      --shape "$SHAPE" \
      --shape-config "$SHAPE_CONFIG" \
      --image-id "$IMAGE_OCID" \
      --subnet-id "$SUBNET_OCID" \
      --assign-public-ip true \
      --display-name "$VM_NAME" \
      --metadata "$METADATA" \
      --boot-volume-size-in-gbs "$VM_BOOT_GB" \
      --wait-for-state RUNNING \
      --query 'data.id' --raw-output 2>&1)"
    RC=$?
    set -e
    if [[ $RC -eq 0 ]]; then
      INSTANCE_OCID="$OUTPUT"
      log "Instance launched in $AD: $INSTANCE_OCID"
      break
    else
      # Save full error for diagnostics
      ERR_LOG="$STATE/last_launch_error.json"
      echo "$OUTPUT" > "$ERR_LOG"
      echo "Full error written to: $ERR_LOG"
      echo "--- Error tail ---"
      echo "$OUTPUT" | tail -20
      echo "------------------"
      if echo "$OUTPUT" | grep -qi 'out of host capacity\|InternalError\|LimitExceeded\|TooManyRequests\|status.*500\|capacity'; then
        log "Capacity / transient issue in $AD, trying next AD…"
        continue
      else
        echo "Launch failed with non-capacity error. See above." >&2
        exit 1
      fi
    fi
  done

  if [[ -z "$INSTANCE_OCID" ]]; then
    echo ""
    echo "All availability domains were out of capacity for $SHAPE."
    echo "This is common for Always Free ARM. Options:"
    echo "  1. Re-run this script in 30 min — capacity frees up randomly."
    echo "  2. Re-run with smaller shape:  VM_OCPUS=1 VM_MEM_GB=6 ./deploy/oci/02-create-vm.sh"
    echo "  3. Try off-peak hours (early US morning)."
    exit 2
  fi
fi

# ── Public IP ─────────────────────────────────────────────────────────────────
log "Fetching public IP…"
VNIC_ID="$(oci compute instance list-vnics --instance-id "$INSTANCE_OCID" \
  --query 'data[0].id' --raw-output)"
PUBLIC_IP="$(oci network vnic get --vnic-id "$VNIC_ID" \
  --query 'data."public-ip"' --raw-output)"

if [[ -z "$PUBLIC_IP" || "$PUBLIC_IP" == "null" ]]; then
  echo "Failed to get public IP" >&2
  exit 1
fi

log "✓ Public IP: $PUBLIC_IP"

# ── Persist state ─────────────────────────────────────────────────────────────
cat > "$STATE/vm.env" <<EOF
VM_NAME=$VM_NAME
INSTANCE_OCID=$INSTANCE_OCID
VCN_OCID=$VCN_OCID
SUBNET_OCID=$SUBNET_OCID
SECURITY_LIST_OCID=$SL_OCID
PUBLIC_IP=$PUBLIC_IP
SSH_KEY=$SSH_KEY
SSH_USER=ubuntu
EOF
log "Wrote state → $STATE/vm.env"

echo ""
echo "Next: ./deploy/oci/03-deploy-app.sh"
echo "Or SSH manually: ssh -i $SSH_KEY ubuntu@$PUBLIC_IP"
