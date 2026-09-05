from app.models import Lead


def score_lead(lead: Lead) -> tuple[int, list[dict]]:
    """Return a deterministic, user-readable score breakdown for a lead."""
    factors: list[dict] = []

    def add(points: int, reason: str) -> None:
        factors.append({"points": points, "reason": reason})

    if lead.email:
        add(25, "A contact email is available.")
    if lead.website:
        add(10, "A company website is available.")
    title = lead.job_title.lower()
    if any(keyword in title for keyword in ("cto", "vp", "director", "head", "chief")):
        add(30, "Title indicates decision-making or leadership responsibility.")
    elif title:
        add(12, "A job title is available.")
    if lead.company:
        add(15, "A company is identified.")
    if lead.enrichment:
        add(20, "Mock enrichment supplied firmographic context.")

    score = min(sum(factor["points"] for factor in factors), 100)
    factors.append({"points": 0, "reason": f"Final score is capped at {score}/100."})
    return score, factors


def classify_reply(text: str) -> tuple[str, int, str]:
    value = text.lower()
    if any(term in value for term in ("unsubscribe", "remove me", "stop emailing", "opt out")):
        return "unsubscribe", 99, "Matched an explicit opt-out request."
    if any(term in value for term in ("not interested", "no thanks", "don't contact")):
        return "objection", 93, "Matched a clear negative-interest phrase."
    if any(term in value for term in ("out of office", "away until", "automatic reply")):
        return "out_of_office", 96, "Matched an automated absence phrase."
    if any(term in value for term in ("interested", "sounds good", "book a call", "let's talk")):
        return "interested", 91, "Matched a positive-interest phrase."
    return "neutral", 55, "No deterministic keyword rule matched; manual review is recommended."
