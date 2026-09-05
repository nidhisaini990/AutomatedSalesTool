from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Protocol


@dataclass(frozen=True)
class DiscoveredPerson:
    source_record_id: str
    first_name: str
    last_name: str
    email: str
    company: str
    job_title: str
    website: str


class DiscoveryProvider(Protocol):
    source_name: str

    def discover(self, query: str, limit: int) -> list[DiscoveredPerson]: ...


class EnrichmentProvider(Protocol):
    source_name: str

    def enrich(self, email: str, company: str) -> dict: ...


class EmailProvider(Protocol):
    source_name: str

    def send(self, *, to: str, subject: str, body: str) -> str: ...


class MockDiscoveryProvider:
    source_name = "mock-discovery"
    _people = (
        ("Ada", "Lovelace", "VP Engineering"),
        ("Grace", "Hopper", "CTO"),
        ("Alan", "Turing", "Head of Data"),
        ("Katherine", "Johnson", "Director of Operations"),
        ("Margaret", "Hamilton", "Product Lead"),
    )

    def discover(self, query: str, limit: int) -> list[DiscoveredPerson]:
        slug = "-".join(query.lower().split())[:40] or "prospects"
        company = f"{query.strip().title()} Labs"
        return [
            DiscoveredPerson(
                source_record_id=f"{slug}-{index + 1}",
                first_name=first,
                last_name=last,
                email=f"{first.lower()}.{last.lower()}@{slug}.example.test",
                company=company,
                job_title=title,
                website=f"https://{slug}.example.test",
            )
            for index, (first, last, title) in enumerate(self._people[:limit])
        ]


class MockEnrichmentProvider:
    source_name = "mock-enrichment"

    def enrich(self, email: str, company: str) -> dict:
        domain = email.split("@", maxsplit=1)[-1]
        return {
            "company_domain": domain,
            "employee_range": "51-200",
            "industry": "Software",
            "summary": f"Mock enrichment for {company}; no external data was requested.",
        }


class MockEmailProvider:
    source_name = "mock-email"

    def send(self, *, to: str, subject: str, body: str) -> str:
        digest = sha256(f"{to}|{subject}|{body}".encode()).hexdigest()[:16]
        return f"mock-email-{digest}"


def provenance_event(provider: str, query: str | None = None) -> dict:
    event = {
        "provider": provider,
        "mock": True,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "notice": "Mock data only; no external provider was called.",
    }
    if query is not None:
        event["query"] = query
    return event
