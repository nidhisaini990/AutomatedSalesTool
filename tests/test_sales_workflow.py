import pytest


def auth_headers(client, email: str) -> dict:
    response = client.post(
        "/api/auth/register", json={"email": email, "password": "correct-horse-battery"}
    )
    assert response.status_code == 201
    return {"Authorization": "Bear" + "er " + response.json()["access_token"]}


def create_workspace(client, headers: dict, name: str = "Acme") -> str:
    response = client.post("/api/workspaces", headers=headers, json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def test_workspace_isolation_and_mock_discovery_provenance(client):
    homepage = client.get("/")
    assert homepage.status_code == 200
    assert "AI Sales Agent MVP" in homepage.text

    owner_headers = auth_headers(client, "owner@example.test")
    workspace_id = create_workspace(client, owner_headers)

    discovered = client.post(
        f"/api/workspaces/{workspace_id}/discover",
        headers=owner_headers,
        json={"query": "B2B SaaS", "limit": 2},
    )
    assert discovered.status_code == 200
    payload = discovered.json()
    assert payload["mock"] is True
    assert payload["created"] == 2
    assert payload["leads"][0]["source"] == "mock-discovery"
    assert payload["leads"][0]["provenance"][0]["mock"] is True
    assert payload["leads"][0]["score"] > 0
    assert payload["leads"][0]["score_explanation"]

    other_headers = auth_headers(client, "other@example.test")
    denied = client.get(f"/api/workspaces/{workspace_id}/leads", headers=other_headers)
    assert denied.status_code == 404


def test_csv_import_preserves_internal_provenance_and_normalizes_deduplication(client):
    headers = auth_headers(client, "importer@example.test")
    workspace_id = create_workspace(client, headers)
    csv_data = (
        "first_name,last_name,email,company,job_title,website,confidence\n"
        "Ada,Lovelace, ADA@EXAMPLE.COM ,Example,CTO,HTTPS://Example.COM/team,86\n"
        "Duplicate,Ada,ada@example.com,Example,CTO,https://example.com,77\n"
        "Grace,Hopper,grace@another.example,Another,VP Engineering,,92\n"
    )
    imported = client.post(
        f"/api/workspaces/{workspace_id}/leads/import",
        headers=headers,
        data={
            "source_url": "https://intranet.example.test/approved/leads.csv",
            "query": "B2B SaaS",
            "icp": "Engineering leaders",
        },
        files={"file": ("leads.csv", csv_data, "text/csv")},
    )

    assert imported.status_code == 200
    payload = imported.json()
    assert payload["provider"] == "internal-csv"
    assert (payload["created"], payload["existing"]) == (2, 1)
    assert len(payload["leads"]) == 2
    ada = payload["leads"][0]
    assert ada["email"] == "ada@example.com"
    assert ada["confidence"] == 86
    assert ada["provenance"][0] == {
        "provider": "internal-csv",
        "source_url": "https://intranet.example.test/approved/leads.csv",
        "source_record_id": ada["source_record_id"],
        "normalized_email": "ada@example.com",
        "normalized_domain": "example.com",
        "confidence": 86,
        "row_number": 2,
        "query": "B2B SaaS",
        "icp": "Engineering leaders",
        "approved_internal_source": True,
    }

    repeated = client.post(
        f"/api/workspaces/{workspace_id}/leads/import",
        headers=headers,
        data={"source_url": "https://intranet.example.test/approved/leads.csv"},
        files={"file": ("leads.csv", csv_data, "text/csv")},
    )
    assert repeated.status_code == 200
    assert (repeated.json()["created"], repeated.json()["existing"]) == (0, 3)


def test_csv_import_rejects_invalid_data_without_creating_leads(client):
    headers = auth_headers(client, "invalid-import@example.test")
    workspace_id = create_workspace(client, headers)
    response = client.post(
        f"/api/workspaces/{workspace_id}/leads/import",
        headers=headers,
        data={"source_url": "ftp://intranet.example.test/leads.csv"},
        files={"file": ("leads.csv", "email\nnot-an-email\n", "text/csv")},
    )
    assert response.status_code == 422
    assert client.get(f"/api/workspaces/{workspace_id}/leads", headers=headers).json() == []

    ragged = client.post(
        f"/api/workspaces/{workspace_id}/leads/import",
        headers=headers,
        data={"source_url": "https://intranet.example.test/leads.csv"},
        files={"file": ("leads.csv", "email\nvalid@example.test,unexpected\n", "text/csv")},
    )
    assert ragged.status_code == 422
    assert client.get(f"/api/workspaces/{workspace_id}/leads", headers=headers).json() == []


def test_suppression_is_enforced_and_replies_schedule_followups(client):
    headers = auth_headers(client, "sales@example.test")
    workspace_id = create_workspace(client, headers)
    discovery = client.post(
        f"/api/workspaces/{workspace_id}/discover",
        headers=headers,
        json={"query": "analytics", "limit": 2},
    ).json()
    first, second = discovery["leads"]

    enriched = client.post(
        f"/api/workspaces/{workspace_id}/leads/{first['id']}/enrich", headers=headers
    )
    assert enriched.status_code == 200
    assert enriched.json()["lead"]["score"] >= first["score"]
    assert enriched.json()["lead"]["provenance"][-1]["provider"] == "mock-enrichment"

    suppressed = client.post(
        f"/api/workspaces/{workspace_id}/leads/{first['id']}/suppress",
        headers=headers,
        json={"reason": "Requested no outreach"},
    )
    assert suppressed.status_code == 200

    campaign = client.post(
        f"/api/workspaces/{workspace_id}/campaigns",
        headers=headers,
        json={"name": "September", "lead_ids": [first["id"], second["id"]]},
    )
    assert campaign.status_code == 201
    assert campaign.json()["queued"] == 1
    assert campaign.json()["suppressed"] == 1

    dispatch = client.post(
        f"/api/workspaces/{workspace_id}/campaigns/{campaign.json()['campaign']['id']}/dispatch",
        headers=headers,
    )
    assert dispatch.status_code == 200
    assert dispatch.json() == {"mock": True, "sent": 1, "suppressed": 0, "skipped": 1}

    reply = client.post(
        f"/api/workspaces/{workspace_id}/replies",
        headers=headers,
        json={"lead_id": second["id"], "text": "Sounds good, let's talk."},
    )
    assert reply.status_code == 200
    assert reply.json()["reply"]["classification"] == "interested"
    assert reply.json()["followup_id"]

    opt_out = client.post(
        f"/api/workspaces/{workspace_id}/replies",
        headers=headers,
        json={"lead_id": second["id"], "text": "Please unsubscribe me."},
    )
    assert opt_out.status_code == 200
    assert opt_out.json()["lead_suppressed"] is True


def test_campaign_is_workspace_isolated_and_reply_intent_is_specific(client):
    owner_headers = auth_headers(client, "campaign-owner@example.test")
    workspace_id = create_workspace(client, owner_headers)
    lead = client.post(
        f"/api/workspaces/{workspace_id}/discover",
        headers=owner_headers,
        json={"query": "software", "limit": 1},
    ).json()["leads"][0]
    campaign = client.post(
        f"/api/workspaces/{workspace_id}/campaigns",
        headers=owner_headers,
        json={"name": "Review me", "lead_ids": [lead["id"]]},
    ).json()["campaign"]

    detail = client.get(
        f"/api/workspaces/{workspace_id}/campaigns/{campaign['id']}", headers=owner_headers
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == campaign["id"]

    reply = client.post(
        f"/api/workspaces/{workspace_id}/replies",
        headers=owner_headers,
        json={"lead_id": lead["id"], "text": "Can you send pricing?"},
    )
    assert reply.status_code == 200
    assert reply.json()["reply"]["classification"] == "pricing_requested"
    assert reply.json()["followup_id"]

    outsider_headers = auth_headers(client, "campaign-outsider@example.test")
    denied = client.get(
        f"/api/workspaces/{workspace_id}/campaigns/{campaign['id']}", headers=outsider_headers
    )
    assert denied.status_code == 404


def test_production_configuration_rejects_insecure_defaults(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "ENVIRONMENT", "production")
    monkeypatch.setattr(config, "DATABASE_URL", "sqlite:///./sales_agent.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        config.validate_runtime_config()


def test_health_reports_database_and_response_is_hardened(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
