from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized.count("@") != 1 or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("A valid email address is required")
        return normalized


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class WorkspaceOut(APIModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime


class DiscoverRequest(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    limit: int = Field(default=5, ge=1, le=25)


class LeadOut(APIModel):
    id: str
    workspace_id: str
    first_name: str
    last_name: str
    email: str
    company: str
    job_title: str
    website: str | None
    status: str
    source: str
    source_record_id: str
    provenance: list
    enrichment: dict
    score: int
    score_explanation: list
    suppressed_at: datetime | None
    suppression_reason: str | None
    created_at: datetime
    updated_at: datetime


class DiscoveryOut(BaseModel):
    mock: bool = True
    provider: str
    message: str
    created: int
    existing: int
    leads: list[LeadOut]


class EnrichmentOut(BaseModel):
    mock: bool = True
    provider: str
    lead: LeadOut


class SuppressRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=300)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    lead_ids: list[str] = Field(min_length=1, max_length=200)
    subject: str = Field(default="A quick idea for {{company}}", min_length=2, max_length=250)
    body: str = Field(
        default="Hi {{first_name}}, I have an idea that may help {{company}}.", min_length=2
    )


class CampaignOut(APIModel):
    id: str
    workspace_id: str
    name: str
    subject: str
    body: str
    status: str
    created_at: datetime
    updated_at: datetime


class CampaignCreateOut(BaseModel):
    campaign: CampaignOut
    queued: int
    suppressed: int


class DispatchOut(BaseModel):
    mock: bool = True
    sent: int
    suppressed: int
    skipped: int


class ReplyCreate(BaseModel):
    lead_id: str
    text: str = Field(min_length=1, max_length=10_000)
    campaign_id: str | None = None


class ReplyOut(APIModel):
    id: str
    workspace_id: str
    lead_id: str
    campaign_id: str | None
    text: str
    classification: str
    confidence: int
    classification_reason: str
    created_at: datetime
    updated_at: datetime


class ReplyCreateOut(BaseModel):
    reply: ReplyOut
    followup_id: str | None = None
    lead_suppressed: bool


class FollowUpCreate(BaseModel):
    lead_id: str
    scheduled_for: datetime
    reason: str = Field(min_length=2, max_length=300)


class FollowUpOut(APIModel):
    id: str
    workspace_id: str
    lead_id: str
    reply_id: str | None
    scheduled_for: datetime
    reason: str
    status: str
    created_at: datetime
    updated_at: datetime
