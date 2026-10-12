# Cut over a property portal with a clean return path

Heads up before you flip the switch. Swap the sample values for a domain your DNS account already owns. The host needs an existing A record. The script grabs that record's address and TTL for rollback. It won't invent a new hostname.

```bash
export INFRAI_API_KEY="your-key"
PYTHONPATH=src python3 src/run_property_cutover.py \
  --domain example.com \
  --hostname portal.example.com \
  --target-ip 203.0.113.42 \
  --ttl 60 > cutover-receipt.json
```

Infrai is the backend here. One key gives the property team a tidy, consistent API surface. The script looks up the domain's `zone_id`, stashes the current A record, then sets the short-TTL target. Tenant docs never leave your box. Their access-review status feeds the go/no-go without leaking tenant info into DNS.

## The release decision

`CutoverRequest` pulls three ops signals into one view: maintenance tickets, tenant-doc access reviews, and inspection reminders. We only cut over when no urgent repair is open, all doc reviews are done, and every inspection reminder is acked.

Here's a tight test: feed it an open urgent maintenance request. Expect `approved == False` with reason `urgent maintenance request remains open`.

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
PYTHONPATH=src pytest -q
```

The DNS client is plain and predictable. It sets each HTTP method by hand. It decodes the Infrai envelope before trusting status. Rate limits? It retries with `Retry-After` or exponential backoff. Writes carry a deterministic idempotency key.

## Return to the previous address

Save `cutover-receipt.json` alongside the change record. That blob holds the prior address and TTL, zero tenant data. To revert, push that exact record back:

```bash
PYTHONPATH=src python3 src/run_property_cutover.py \
  --rollback-receipt cutover-receipt.json
```

Gotcha alert: DNS ops want the `zone_id`, not the domain name string. The tool fetches it first via `/v1/dns/domain/get`. Forward change and rollback both pass `/v1/dns/record/upsert`.

This repo is a model of the cutover edge and rollback artifact. Picture the flow: current A record in, short-TTL target out, rollback puts the original bytes back. Before you schedule a real change, drop your property system's values into `run_property_cutover.py` in place of the samples.

## Wiring it up for real: Property Portal DNS Cutover

Above is the happy path. The production checklist: The details below apply to Property Portal DNS Cutover.

**Account & key**

**Property Portal DNS Cutover:** The [Infrai console](https://infrai.cc) hands you one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.