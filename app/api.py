from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Campaign,
    CampaignRecipient,
    FollowUp,
    Lead,
    Membership,
    Reply,
    User,
    Workspace,
    utcnow,
)
from app.providers import (
    MockDiscoveryProvider,
    MockEmailProvider,
    MockEnrichmentProvider,
    provenance_event,
)
from app.schemas import (
    CampaignCreate,
    CampaignCreateOut,
    CampaignOut,
    DiscoverRequest,
    DiscoveryOut,
    DispatchOut,
    EnrichmentOut,
    FollowUpCreate,
    FollowUpOut,
    LeadOut,
    ReplyCreate,
    ReplyCreateOut,
    ReplyOut,
    SuppressRequest,
    TokenOut,
    UserCredentials,
    WorkspaceCreate,
    WorkspaceOut,
)
from app.scoring import classify_reply, score_lead
from app.security import create_access_token, decode_access_token, hash_password, verify_password

router = APIRouter(prefix="/api")
bearer = HTTPBearer()
discovery_provider = MockDiscoveryProvider()
enrichment_provider = MockEnrichmentProvider()
email_provider = MockEmailProvider()


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(credentials.credentials)
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def workspace_for_user(workspace_id: str, user: User, db: Session) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.workspace_id == workspace_id, Membership.user_id == user.id
        )
    )
    if workspace is None or membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def lead_for_workspace(lead_id: str, workspace: Workspace, db: Session) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None or lead.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.post("/auth/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(payload: UserCredentials, db: Session = Depends(get_db)) -> TokenOut:
    if db.scalar(select(User).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="An account with that email already exists")
    user = User(email=payload.email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    return TokenOut(access_token=create_access_token(user.id))


@router.post("/auth/login", response_model=TokenOut)
def login(payload: UserCredentials, db: Session = Depends(get_db)) -> TokenOut:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenOut(access_token=create_access_token(user.id))


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": user.id, "email": user.email}


@router.post("/workspaces", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Workspace:
    workspace = Workspace(name=payload.name.strip())
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[Workspace]:
    return list(
        db.scalars(
            select(Workspace)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user.id)
            .order_by(Workspace.created_at.desc())
        )
    )


@router.post("/workspaces/{workspace_id}/discover", response_model=DiscoveryOut)
def discover_leads(
    workspace_id: str,
    payload: DiscoverRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DiscoveryOut:
    workspace_for_user(workspace_id, user, db)
    leads: list[Lead] = []
    created = 0
    existing = 0
    for person in discovery_provider.discover(payload.query, payload.limit):
        lead = db.scalar(
            select(Lead).where(
                Lead.workspace_id == workspace_id,
                Lead.source == discovery_provider.source_name,
                Lead.source_record_id == person.source_record_id,
            )
        )
        if lead is None:
            lead = Lead(
                workspace_id=workspace_id,
                first_name=person.first_name,
                last_name=person.last_name,
                email=person.email,
                company=person.company,
                job_title=person.job_title,
                website=person.website,
                source=discovery_provider.source_name,
                source_record_id=person.source_record_id,
                provenance=[
                    {
                        **provenance_event(discovery_provider.source_name, payload.query),
                        "source_record_id": person.source_record_id,
                    }
                ],
            )
            lead.score, lead.score_explanation = score_lead(lead)
            db.add(lead)
            created += 1
        else:
            existing += 1
        leads.append(lead)
    db.commit()
    for lead in leads:
        db.refresh(lead)
    return DiscoveryOut(
        provider=discovery_provider.source_name,
        message="Mock results are generated locally; no external discovery provider was called.",
        created=created,
        existing=existing,
        leads=leads,
    )


@router.get("/workspaces/{workspace_id}/leads", response_model=list[LeadOut])
def list_leads(
    workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[Lead]:
    workspace_for_user(workspace_id, user, db)
    return list(
        db.scalars(
            select(Lead)
            .where(Lead.workspace_id == workspace_id)
            .order_by(Lead.score.desc(), Lead.created_at.desc())
        )
    )


@router.get("/workspaces/{workspace_id}/leads/{lead_id}", response_model=LeadOut)
def get_lead(
    workspace_id: str,
    lead_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Lead:
    workspace = workspace_for_user(workspace_id, user, db)
    return lead_for_workspace(lead_id, workspace, db)


@router.post("/workspaces/{workspace_id}/leads/{lead_id}/enrich", response_model=EnrichmentOut)
def enrich_lead(
    workspace_id: str,
    lead_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> EnrichmentOut:
    workspace = workspace_for_user(workspace_id, user, db)
    lead = lead_for_workspace(lead_id, workspace, db)
    lead.enrichment = enrichment_provider.enrich(lead.email, lead.company)
    lead.provenance = [
        *lead.provenance,
        {**provenance_event(enrichment_provider.source_name), "lead_email": lead.email},
    ]
    lead.score, lead.score_explanation = score_lead(lead)
    db.commit()
    db.refresh(lead)
    return EnrichmentOut(provider=enrichment_provider.source_name, lead=lead)


@router.post("/workspaces/{workspace_id}/leads/{lead_id}/score", response_model=LeadOut)
def rescore_lead(
    workspace_id: str,
    lead_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Lead:
    workspace = workspace_for_user(workspace_id, user, db)
    lead = lead_for_workspace(lead_id, workspace, db)
    lead.score, lead.score_explanation = score_lead(lead)
    db.commit()
    db.refresh(lead)
    return lead


@router.post("/workspaces/{workspace_id}/leads/{lead_id}/suppress", response_model=LeadOut)
def suppress_lead(
    workspace_id: str,
    lead_id: str,
    payload: SuppressRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Lead:
    workspace = workspace_for_user(workspace_id, user, db)
    lead = lead_for_workspace(lead_id, workspace, db)
    lead.suppressed_at = utcnow()
    lead.suppression_reason = payload.reason.strip()
    db.commit()
    db.refresh(lead)
    return lead


@router.post(
    "/workspaces/{workspace_id}/campaigns",
    response_model=CampaignCreateOut,
    status_code=status.HTTP_201_CREATED,
)
def create_campaign(
    workspace_id: str,
    payload: CampaignCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CampaignCreateOut:
    workspace_for_user(workspace_id, user, db)
    lead_ids = list(dict.fromkeys(payload.lead_ids))
    leads = list(
        db.scalars(
            select(Lead).where(Lead.workspace_id == workspace_id, Lead.id.in_(lead_ids))
        )
    )
    if len(leads) != len(lead_ids):
        raise HTTPException(status_code=404, detail="One or more leads were not found")

    campaign = Campaign(
        workspace_id=workspace_id,
        name=payload.name.strip(),
        subject=payload.subject,
        body=payload.body,
        status="ready",
    )
    db.add(campaign)
    db.flush()
    queued = 0
    suppressed = 0
    for lead in leads:
        recipient_status = "suppressed" if lead.suppressed_at else "pending"
        db.add(
            CampaignRecipient(
                campaign_id=campaign.id, lead_id=lead.id, status=recipient_status
            )
        )
        if recipient_status == "pending":
            queued += 1
        else:
            suppressed += 1
    db.commit()
    db.refresh(campaign)
    return CampaignCreateOut(campaign=campaign, queued=queued, suppressed=suppressed)


@router.get("/workspaces/{workspace_id}/campaigns", response_model=list[CampaignOut])
def list_campaigns(
    workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[Campaign]:
    workspace_for_user(workspace_id, user, db)
    return list(
        db.scalars(
            select(Campaign)
            .where(Campaign.workspace_id == workspace_id)
            .order_by(Campaign.created_at.desc())
        )
    )


@router.post("/workspaces/{workspace_id}/campaigns/{campaign_id}/dispatch", response_model=DispatchOut)
def dispatch_campaign(
    workspace_id: str,
    campaign_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> DispatchOut:
    workspace = workspace_for_user(workspace_id, user, db)
    campaign = db.get(Campaign, campaign_id)
    if campaign is None or campaign.workspace_id != workspace.id:
        raise HTTPException(status_code=404, detail="Campaign not found")

    sent = suppressed = skipped = 0
    recipients = list(
        db.scalars(select(CampaignRecipient).where(CampaignRecipient.campaign_id == campaign.id))
    )
    for recipient in recipients:
        if recipient.status != "pending":
            skipped += 1
            continue
        lead = lead_for_workspace(recipient.lead_id, workspace, db)
        if lead.suppressed_at:
            recipient.status = "suppressed"
            suppressed += 1
            continue
        body = (
            campaign.body.replace("{{first_name}}", lead.first_name).replace("{{company}}", lead.company)
        )
        subject = campaign.subject.replace("{{company}}", lead.company)
        recipient.provider_message_id = email_provider.send(
            to=lead.email, subject=subject, body=body
        )
        recipient.sent_at = utcnow()
        recipient.status = "sent"
        sent += 1
    campaign.status = "completed"
    db.commit()
    return DispatchOut(sent=sent, suppressed=suppressed, skipped=skipped)


@router.post("/workspaces/{workspace_id}/replies", response_model=ReplyCreateOut)
def create_reply(
    workspace_id: str,
    payload: ReplyCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> ReplyCreateOut:
    workspace = workspace_for_user(workspace_id, user, db)
    lead = lead_for_workspace(payload.lead_id, workspace, db)
    if payload.campaign_id:
        campaign = db.get(Campaign, payload.campaign_id)
        if campaign is None or campaign.workspace_id != workspace.id:
            raise HTTPException(status_code=404, detail="Campaign not found")
    classification, confidence, reason = classify_reply(payload.text)
    reply = Reply(
        workspace_id=workspace_id,
        lead_id=lead.id,
        campaign_id=payload.campaign_id,
        text=payload.text,
        classification=classification,
        confidence=confidence,
        classification_reason=reason,
    )
    db.add(reply)
    db.flush()

    followup: FollowUp | None = None
    if classification == "unsubscribe":
        lead.suppressed_at = utcnow()
        lead.suppression_reason = "Reply classified as unsubscribe"
    elif classification in {"interested", "objection"}:
        followup = FollowUp(
            workspace_id=workspace_id,
            lead_id=lead.id,
            reply_id=reply.id,
            scheduled_for=utcnow() + timedelta(days=2),
            reason=f"Review {classification} reply: {reason}",
        )
        db.add(followup)
    db.commit()
    db.refresh(reply)
    return ReplyCreateOut(
        reply=reply, followup_id=followup.id if followup else None, lead_suppressed=lead.suppressed_at is not None
    )


@router.post(
    "/workspaces/{workspace_id}/followups",
    response_model=FollowUpOut,
    status_code=status.HTTP_201_CREATED,
)
def create_followup(
    workspace_id: str,
    payload: FollowUpCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> FollowUp:
    workspace = workspace_for_user(workspace_id, user, db)
    lead_for_workspace(payload.lead_id, workspace, db)
    followup = FollowUp(
        workspace_id=workspace_id,
        lead_id=payload.lead_id,
        scheduled_for=payload.scheduled_for,
        reason=payload.reason.strip(),
    )
    db.add(followup)
    db.commit()
    db.refresh(followup)
    return followup


@router.get("/workspaces/{workspace_id}/followups", response_model=list[FollowUpOut])
def list_followups(
    workspace_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[FollowUp]:
    workspace_for_user(workspace_id, user, db)
    return list(
        db.scalars(
            select(FollowUp)
            .where(FollowUp.workspace_id == workspace_id)
            .order_by(FollowUp.scheduled_for)
        )
    )
