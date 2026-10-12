from datetime import date

from property_cutover import (
    CutoverRequest,
    InspectionReminder,
    MaintenanceRequest,
    TenantDocument,
    assess_readiness,
)


def test_open_urgent_maintenance_blocks_dns_cutover() -> None:
    request = CutoverRequest(
        domain="example.com",
        hostname="portal.example.com",
        target_ipv4="203.0.113.42",
        ttl=60,
        maintenance_requests=(MaintenanceRequest("MX-104", urgent=True, closed=False),),
        tenant_documents=(TenantDocument("TD-208", access_reviewed=True),),
        inspection_reminders=(
            InspectionReminder("IN-331", date(2026, 10, 1), acknowledged=True),
        ),
    )

    decision = assess_readiness(request, today=date(2026, 9, 21))

    assert decision.approved is False
    assert decision.reasons == ("urgent maintenance request remains open",)
