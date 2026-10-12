from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import date

from property_cutover import (
    CutoverReceipt,
    CutoverRequest,
    InfraiDnsClient,
    InspectionReminder,
    MaintenanceRequest,
    TenantDocument,
    execute_cutover,
    execute_rollback,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cut over or restore a property hostname")
    parser.add_argument("--domain", default="example.com")
    parser.add_argument("--hostname", default="portal.example.com")
    parser.add_argument("--target-ip", default="203.0.113.42")
    parser.add_argument("--ttl", type=int, default=60)
    parser.add_argument("--rollback-receipt")
    args = parser.parse_args()

    api_key = os.environ["INFRAI_API_KEY"]
    client = InfraiDnsClient(api_key)
    if args.rollback_receipt:
        with open(args.rollback_receipt, encoding="utf-8") as handle:
            receipt = CutoverReceipt(**json.load(handle))
        execute_rollback(client, receipt)
        print(json.dumps({"restored": receipt.hostname, "content": receipt.previous_content}))
        return

    request = CutoverRequest(
        domain=args.domain,
        hostname=args.hostname,
        target_ipv4=args.target_ip,
        ttl=args.ttl,
        maintenance_requests=(MaintenanceRequest("MX-104", urgent=False, closed=True),),
        tenant_documents=(TenantDocument("TD-208", access_reviewed=True),),
        inspection_reminders=(
            InspectionReminder("IN-331", due_on=date(2026, 10, 1), acknowledged=True),
        ),
    )
    receipt = execute_cutover(client, request, date.today())
    print(json.dumps(asdict(receipt), indent=2))


if __name__ == "__main__":
    main()
