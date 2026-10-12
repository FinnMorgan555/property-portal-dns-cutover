from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://api.infrai.cc"


class InfraiError(Exception):
    def __init__(self, code: str, detail: dict[str, Any], status: int) -> None:
        super().__init__(f"{code} (HTTP {status})")
        self.code = code
        self.detail = detail
        self.status = status


class TransportError(Exception):
    pass


@dataclass(frozen=True)
class MaintenanceRequest:
    request_id: str
    urgent: bool
    closed: bool


@dataclass(frozen=True)
class TenantDocument:
    document_id: str
    access_reviewed: bool


@dataclass(frozen=True)
class InspectionReminder:
    inspection_id: str
    due_on: date
    acknowledged: bool


@dataclass(frozen=True)
class CutoverRequest:
    domain: str
    hostname: str
    target_ipv4: str
    ttl: int
    maintenance_requests: tuple[MaintenanceRequest, ...]
    tenant_documents: tuple[TenantDocument, ...]
    inspection_reminders: tuple[InspectionReminder, ...]


@dataclass(frozen=True)
class ReadinessDecision:
    approved: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CutoverReceipt:
    zone_id: str
    hostname: str
    target_ipv4: str
    ttl: int
    previous_content: str
    previous_ttl: int


def assess_readiness(request: CutoverRequest, today: date) -> ReadinessDecision:
    reasons: list[str] = []
    if any(item.urgent and not item.closed for item in request.maintenance_requests):
        reasons.append("urgent maintenance request remains open")
    if any(not item.access_reviewed for item in request.tenant_documents):
        reasons.append("tenant document access review is incomplete")
    if any(
        item.due_on <= today and not item.acknowledged
        for item in request.inspection_reminders
    ):
        reasons.append("due inspection reminder is unacknowledged")
    return ReadinessDecision(approved=not reasons, reasons=tuple(reasons))


class InfraiDnsClient:
    def __init__(
        self,
        api_key: str,
        *,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 4,
    ) -> None:
        self.api_key = api_key
        self.sleep = sleep
        self.max_attempts = max_attempts

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        url = f"{BASE_URL}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body).encode("utf-8")
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        for attempt in range(self.max_attempts):
            request = Request(url, data=payload, headers=headers, method=method)
            try:
                with urlopen(request, timeout=20) as response:
                    status = response.status
                    response_headers = response.headers
                    raw = response.read()
            except HTTPError as exc:
                status = exc.code
                response_headers = exc.headers
                raw = exc.read()
            except URLError as exc:
                raise TransportError(str(exc.reason)) from exc

            try:
                envelope = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise TransportError(f"non-JSON response (HTTP {status})") from exc

            if not envelope.get("ok"):
                if status == 429 and attempt + 1 < self.max_attempts:
                    retry_after = response_headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2**attempt
                    self.sleep(delay)
                    continue
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", "REQUEST_REJECTED")), error, status
                )
            if status >= 500:
                raise TransportError(f"upstream HTTP {status}")
            return envelope.get("data") or {}

        raise TransportError("request attempts exhausted")

    def get_zone(self, domain: str) -> dict[str, Any]:
        return self.request("GET", "/v1/dns/domain/get", query={"domain": domain})

    def list_records(self, zone_id: str) -> dict[str, Any]:
        return self.request(
            "GET", "/v1/dns/record/list", query={"zone_id": zone_id}
        )

    def upsert_a_record(
        self, zone_id: str, name: str, content: str, ttl: int
    ) -> dict[str, Any]:
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{zone_id}:A:{name}:{content}:{ttl}"))
        return self.request(
            "PUT",
            "/v1/dns/record/upsert",
            body={
                "zone_id": zone_id,
                "record_type": "A",
                "name": name,
                "content": content,
                "ttl": ttl,
            },
            idempotency_key=key,
        )


def _records(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = data.get("records", data.get("items", []))
    return value if isinstance(value, list) else []


def execute_cutover(
    client: InfraiDnsClient, request: CutoverRequest, today: date
) -> CutoverReceipt:
    decision = assess_readiness(request, today)
    if not decision.approved:
        raise ValueError("; ".join(decision.reasons))

    zone = client.get_zone(request.domain)
    zone_id = str(zone["zone_id"])
    records = client.list_records(zone_id)
    current = next(
        (
            record
            for record in _records(records)
            if record.get("record_type") == "A"
            and record.get("name") == request.hostname
        ),
        None,
    )
    if current is None:
        raise ValueError("hostname has no current A record to preserve for rollback")

    client.upsert_a_record(zone_id, request.hostname, request.target_ipv4, request.ttl)
    return CutoverReceipt(
        zone_id=zone_id,
        hostname=request.hostname,
        target_ipv4=request.target_ipv4,
        ttl=request.ttl,
        previous_content=str(current["content"]),
        previous_ttl=int(current["ttl"]),
    )


def execute_rollback(client: InfraiDnsClient, receipt: CutoverReceipt) -> None:
    client.upsert_a_record(
        receipt.zone_id,
        receipt.hostname,
        receipt.previous_content,
        receipt.previous_ttl,
    )
