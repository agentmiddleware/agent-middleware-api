# Quickstart: from `git clone` to a verified receipt in about five minutes

In about five minutes, with no operator, no pre-shared key, and no bespoke
client, you will:

1. boot a real local trust plane with one command,
2. mint your own wallet-scoped credential,
3. invoke a real governed tool and hold its signed receipt,
4. deliberately try to get charged twice, and fail,
5. verify the receipt **offline**, then forge one and watch the verifier
   reject it.

If you have about ten more minutes after that, three follow-on sections
cover the rest of the loop: deliberately overspending your permit (and
getting a signed denial instead), getting denied by authority, and bringing
an off-the-shelf MCP client.

Every command below is exercised by CI against a freshly booted server
(`tests/test_quickstart_path.py`), so if this page and the code ever
disagree, the build breaks. If a step still surprises you, that is a
finding, please open an issue; that is exactly what
[docs/stranger-test.md](stranger-test.md) exists to catch.

## 0. Prerequisites (~1 minute)

Python 3.11+, `git`, `make`, `curl`, and [`uv`](https://docs.astral.sh/uv/):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Everything else (including all Python dependencies) is installed
automatically on first run.

## 1. Boot the trust plane (~1 minute)

```bash
git clone https://github.com/PetrefiedThunder/agent-middleware-api.git
cd agent-middleware-api
make quickstart
```

First boot resolves dependencies, generates an Ed25519 signing seed, and
persists it with the database under `data/quickstart/` (gitignored). Wait
for the banner:

```text
[quickstart] Trust plane is up: http://127.0.0.1:8000
```

Three things worth knowing about what just started:

- **Strict trust mode is on.** Governed calls need a signed permit and an
  idempotency key; there is no permissive fallback.
- **One governed tool is exposed**: `partner.notes.write`, which
  appends a note to a local JSONL file for **2 credits per call**. A real
  side effect you can watch land on disk, small on purpose.
- **The server binds loopback only**, because self-serve key minting is
  enabled. This posture is for a machine you control; production-like
  deployments refuse to boot with these flags set.

Leave the server running and do the rest **in a second terminal**, from the
repository root:

```bash
export API_URL=http://127.0.0.1:8000
```

## 2. Discover what is on offer (~30 seconds)

```bash
curl -s "$API_URL/.well-known/agent.json"
curl -s "$API_URL/mcp/tools.json"
```

The tools manifest lists exactly one invokable tool, `partner.notes.write`.
That is the tool for the rest of this page. Nothing needs to be brought,
registered, or configured.

## 3. Mint your own key (~30 seconds)

No credential is needed to get a credential. The quickstart server allows
self-provisioning:

```bash
PROVISION_JSON=$(
  curl -s -X POST "$API_URL/v1/dev-keys/self-provision" \
    -H "Content-Type: application/json" \
    -d '{"agent_id": "quickstart-stranger"}'
)

export AGENT_API_KEY=$(echo "$PROVISION_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["api_key"])')
export WALLET_ID=$(echo "$PROVISION_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["wallet_id"])')
export KEY_ID=$(echo "$PROVISION_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["key_id"])')
echo "wallet: $WALLET_ID  key: $KEY_ID"
```

You now hold a **wallet-scoped** key (never bootstrap-admin) bound to an
agent wallet holding 1000 synthetic dev credits. The key is shown once. This
route exists only in local environments: it answers 404 unless the server
opted in, and a production-like deployment refuses to boot with it enabled.
Details in [docs/static-dev-api-keys.md](static-dev-api-keys.md).

## 4. Issue yourself a permit (~1 minute)

A permit binds your wallet, your key, one allowed tool, a spend cap, and an
expiry, signed by the server and checked before any money moves.

Do the arithmetic before you issue it. The cap below is **7 credits** and
the tool costs **2 credits per call**: calls one, two, and three fit
(2, 4, 6 spent), and the fourth call would cross the cap at 8. So the
fourth call must be denied. Hold the plane to that prediction in the
overspend follow-on in step 8.

```bash
EXPIRES_AT=$(python3 -c 'from datetime import datetime,timezone,timedelta; print((datetime.now(timezone.utc)+timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))')

PERMIT_JSON=$(
  curl -s -X POST "$API_URL/v1/permits" \
    -H "X-API-Key: $AGENT_API_KEY" \
    -H "Idempotency-Key: quickstart-permit-1" \
    -H "Content-Type: application/json" \
    -d "{
      \"issuer_wallet_id\": \"$WALLET_ID\",
      \"subject_wallet_id\": \"$WALLET_ID\",
      \"subject_key_id\": \"$KEY_ID\",
      \"allowed_tools\": [\"partner.notes.write\"],
      \"scopes\": [\"tool:partner.notes.write:invoke\", \"billing:charge\"],
      \"max_credits\": 7,
      \"expires_at\": \"$EXPIRES_AT\"
    }"
)

export PERMIT_ID=$(echo "$PERMIT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["permit_id"])')
echo "permit: $PERMIT_ID"
```

Note who issued this: **you did, to yourself**. A wallet-scoped key may only
permit wallets it has authority over, its own or wallets it funds. Try
putting someone else's wallet in `subject_wallet_id` and you get a 403.

## 5. Invoke the governed tool (~30 seconds)

```bash
INVOKE_JSON=$(
  curl -s -X POST "$API_URL/mcp/messages" \
    -H "X-API-Key: $AGENT_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"jsonrpc\": \"2.0\", \"id\": \"call-1\", \"method\": \"tools/call\",
      \"params\": {
        \"name\": \"partner.notes.write\",
        \"arguments\": {\"text\": \"first governed note\"},
        \"mcpContext\": {
          \"wallet_id\": \"$WALLET_ID\",
          \"permit_id\": \"$PERMIT_ID\",
          \"idempotency_key\": \"quickstart-note-1\"
        }
      }
    }"
)

export RECEIPT_ID=$(echo "$INVOKE_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["receipt"]["receipt_id"])')
echo "$INVOKE_JSON" | python3 -m json.tool
```

The result carries a signed receipt: `outcome: success`,
`credits_charged: 2.00000000`, a `ledger_entry_id` tying it to the debit,
request and response hashes, and an Ed25519 signature. And the tool really
ran. The note is on disk:

```bash
cat data/dogfood_partner_notes.jsonl
```

## 6. Try to get charged twice (~1 minute)

Send the **exact same request again**, same idempotency key, same payload:

```bash
curl -s -X POST "$API_URL/mcp/messages" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\": \"2.0\", \"id\": \"call-1\", \"method\": \"tools/call\",
    \"params\": {
      \"name\": \"partner.notes.write\",
      \"arguments\": {\"text\": \"first governed note\"},
      \"mcpContext\": {
        \"wallet_id\": \"$WALLET_ID\",
        \"permit_id\": \"$PERMIT_ID\",
        \"idempotency_key\": \"quickstart-note-1\"
      }
    }
  }" | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]["receipt"]; print("receipt:", r["receipt_id"])'
```

Same `receipt_id` as step 5. Not a similar receipt, the same one, replayed.
The tool did not run a second time (check the notes file: still one note)
and the wallet was not debited again.

Now try the sharper attack: **same idempotency key, different payload**,
the retry that is actually a new request wearing an old key:

```bash
curl -s -X POST "$API_URL/mcp/messages" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\": \"2.0\", \"id\": \"call-x\", \"method\": \"tools/call\",
    \"params\": {
      \"name\": \"partner.notes.write\",
      \"arguments\": {\"text\": \"DIFFERENT text, same key\"},
      \"mcpContext\": {
        \"wallet_id\": \"$WALLET_ID\",
        \"permit_id\": \"$PERMIT_ID\",
        \"idempotency_key\": \"quickstart-note-1\"
      }
    }
  }" | python3 -m json.tool
```

Fail-closed: `idempotency_key_reused`. No execution, no charge, no silent
"probably the same" guess. One key means one operation, forever.

Confirm the ledger agrees, one funding entry, one debit:

```bash
curl -s "$API_URL/v1/billing/ledger/$WALLET_ID" -H "X-API-Key: $AGENT_API_KEY" | python3 -m json.tool
```

Then verify the tamper-evident audit chain behind those entries. Every
governed tool invocation appends a hash-linked audit event, and your own
key is enough to verify your wallet's chain (tamper evidence you cannot
use yourself protects no one):

```bash
curl -s -X POST "$API_URL/v1/audit/verify-chain" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

`"valid": true` with a non-zero `checked_events` means the recorded history
hash-links end to end; an edited or deleted event would surface as
`"valid": false` with the broken link named in `broken_event_id`.

## 7. Verify the receipt offline (~1 minute)

So far you have trusted the plane's own word. Stop trusting it. Fetch the
portable receipt bundle and the public key set. Note the key set needs
**no credential at all**. Verify the signature yourself, offline:

```bash
curl -s "$API_URL/v1/receipts/$RECEIPT_ID/portable" \
  -H "X-API-Key: $AGENT_API_KEY" -o data/quickstart/receipt-bundle.json
curl -s "$API_URL/.well-known/trust-keys.json" -o data/quickstart/trust-keys.json

PYTHONPATH=b2a_sdk/src uv run --with-requirements requirements.txt \
  python -m b2a_sdk.verify_cli \
  --bundle data/quickstart/receipt-bundle.json \
  --keys data/quickstart/trust-keys.json
```

```text
VERIFIED  rcpt-...
  signed by   quickstart-local-ed25519
  tool        partner.notes.write
  outcome     success
  credits     2 charged of 2 authorized
```

The verifier is part of the published SDK and never imports the server.
That independence is the point. Now forge a receipt: take the bundle and
change one signed fact, claim the call was free:

```bash
python3 - <<'EOF'
import json
bundle = json.load(open("data/quickstart/receipt-bundle.json"))
forged = bundle["signing_input"].replace(
    '"credits_charged":"2"', '"credits_charged":"0"'
)
assert forged != bundle["signing_input"], "nothing changed, is this the success receipt?"
bundle["signing_input"] = forged
json.dump(bundle, open("data/quickstart/forged-receipt.json", "w"))
EOF

PYTHONPATH=b2a_sdk/src uv run --with-requirements requirements.txt \
  python -m b2a_sdk.verify_cli \
  --bundle data/quickstart/forged-receipt.json \
  --keys data/quickstart/trust-keys.json
echo "exit code: $?"
```

The output reports the signature does not verify over the changed input,
exit code 1. The exit codes are meant to be branched on: `0` verified, `1`
well-formed but forged, `2` undetermined (for example an unknown key). A
verifier that conflates "forged" with "could not check" will eventually
raise a fraud alarm during a key-server outage.

That is the five minute core loop: authority before money, no double
charge on retry, and a receipt you verified yourself without trusting the
server. The next three sections are follow-ons for when you have about ten
more minutes.

## Follow-ons (about ten more minutes)

## 8. Overspend on purpose (~2 minutes)

Spend the rest of the permit. Notes two and three succeed:

```bash
for N in 2 3; do
  curl -s -X POST "$API_URL/mcp/messages" \
    -H "X-API-Key: $AGENT_API_KEY" \
    -H "Content-Type: application/json" \
    -d "{
      \"jsonrpc\": \"2.0\", \"id\": \"call-$N\", \"method\": \"tools/call\",
      \"params\": {
        \"name\": \"partner.notes.write\",
        \"arguments\": {\"text\": \"note $N\"},
        \"mcpContext\": {
          \"wallet_id\": \"$WALLET_ID\",
          \"permit_id\": \"$PERMIT_ID\",
          \"idempotency_key\": \"quickstart-note-$N\"
        }
      }
    }" | python3 -c 'import json,sys; r=json.load(sys.stdin)["result"]["receipt"]; print("charged:", r["credits_charged"], r["receipt_id"])'
done
```

Six of seven credits are now spent. The fourth call, the one step 4
predicted, needs 2 credits against 1 remaining:

```bash
curl -s -X POST "$API_URL/mcp/messages" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\": \"2.0\", \"id\": \"call-4\", \"method\": \"tools/call\",
    \"params\": {
      \"name\": \"partner.notes.write\",
      \"arguments\": {\"text\": \"note 4, should be denied\"},
      \"mcpContext\": {
        \"wallet_id\": \"$WALLET_ID\",
        \"permit_id\": \"$PERMIT_ID\",
        \"idempotency_key\": \"quickstart-note-4\"
      }
    }
  }" | python3 -m json.tool
```

`permit_budget_exceeded`, with the arithmetic in `details`
(`required_credits: 2.0`, `remaining_credits: 1.0`). Read the denial
receipt closely: `credits_charged: "0"` and `ledger_entry_id: null`. The
denial is **signed evidence that carries no charge**: authority ran out
before money moved, and you can prove it. The tool did not run (the notes
file still has three notes), and the ledger still shows exactly three
debits.

## 9. Get denied by authority (follow-on, ~1 minute)

A permit is not a session token. It names the tools it allows. Issue a
second permit that allows a *different* tool, then try to use it for
`partner.notes.write`:

```bash
DENY_PERMIT_JSON=$(
  curl -s -X POST "$API_URL/v1/permits" \
    -H "X-API-Key: $AGENT_API_KEY" \
    -H "Idempotency-Key: quickstart-permit-2" \
    -H "Content-Type: application/json" \
    -d "{
      \"issuer_wallet_id\": \"$WALLET_ID\",
      \"subject_wallet_id\": \"$WALLET_ID\",
      \"subject_key_id\": \"$KEY_ID\",
      \"allowed_tools\": [\"some.other.tool\"],
      \"scopes\": [\"tool:some.other.tool:invoke\", \"billing:charge\"],
      \"max_credits\": 7,
      \"expires_at\": \"$EXPIRES_AT\"
    }"
)
DENY_PERMIT_ID=$(echo "$DENY_PERMIT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["permit_id"])')

curl -s -X POST "$API_URL/mcp/messages" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"jsonrpc\": \"2.0\", \"id\": \"deny-1\", \"method\": \"tools/call\",
    \"params\": {
      \"name\": \"partner.notes.write\",
      \"arguments\": {\"text\": \"should be denied\"},
      \"mcpContext\": {
        \"wallet_id\": \"$WALLET_ID\",
        \"permit_id\": \"$DENY_PERMIT_ID\",
        \"idempotency_key\": \"quickstart-denied-1\"
      }
    }
  }" | python3 -m json.tool
```

`permit_tool_not_allowed`, again with a **signed denial receipt** and no
ledger linkage. Denial receipts verify offline exactly like success
receipts. Fetch `/v1/receipts/{that_receipt_id}/portable` and run the
verifier again if you want the proof.

## 10. Bring an off-the-shelf MCP client (follow-on)

Everything above used raw JSON-RPC so you could see each moving part. The
same server also speaks standard MCP (Streamable HTTP, official SDK) at
`POST $API_URL/mcp`. Point MCP Inspector or any standards-compliant client
at it with your `X-API-Key` header. Standard clients cannot send permit
context, so the server mints a bounded, single-tool, short-lived permit per
call from your wallet; pass an `Idempotency-Key` header (or the
`io.agentmiddleware/idempotency_key` entry in `params._meta`) to make retries
safe. The key must be a non-blank string of at most 128 characters; a key
that is present but unusable is refused before anything is minted or charged,
and a call with no key at all is a new charged operation every time.
`tests/test_minimal_path_e2e.py` drives exactly this with the official
Python SDK client.

## Starting over

State persists across restarts (`make quickstart` resumes where you left
off). For a clean slate, new database, new signing key, all minted keys
and receipts gone, and the notes file emptied:

```bash
make quickstart QUICKSTART_ARGS="--reset"
```

Reset before repeating the walkthrough: idempotency is forever, so
re-running step 5 against old state replays the *original* receipt instead
of executing again (correct behavior, but not the fresh run you wanted),
and the note counts in steps 6 and 8 assume the notes file starts empty.

## What you just proved, and what you did not

The five minute core loop drove four checks a stranger is asked to run in
[docs/stranger-test.md](stranger-test.md): a governed call needs authority
before money, a retry cannot double-charge, a receipt verifies offline, and
a forged one fails. The follow-ons add the fifth check, a permit cap
contains overspend, plus authority denial and the standards-compliant MCP
path. What this page does **not** prove: production posture (real keys are
operator-issued and rotated,
[docs/key-management.md](key-management.md)), real settlement (these credits
are synthetic), or remote-upstream failure semantics. For what happens when
a metered call dies mid-flight, including the deliberately unfixable
`delivery_uncertain` state, read
[docs/failure-semantics.md](failure-semantics.md). A receipt proves what
happened, never what did not
([SECURITY_LIMITATIONS.md](../SECURITY_LIMITATIONS.md)).

Where to go next:

- **Run the stranger test properly**, hand this page to someone who has
  never seen the repo and record where they get stuck:
  [docs/stranger-test.md](stranger-test.md).
- **Operate it like an operator**, bootstrap keys, sponsor/agent wallet
  hierarchies, policies, and audit-chain verification:
  [docs/golden-path.md](golden-path.md).
- **Bring one real tool**, swap the dogfood tool for one upstream MCP tool
  behind the same governance:
  [docs/partner-first-tool-runbook.md](partner-first-tool-runbook.md).
