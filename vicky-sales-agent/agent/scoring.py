"""Lead fit scoring (0–100) with human-readable reasons."""

from __future__ import annotations

from .config import Config


def score_lead(cfg: Config, lead: dict) -> tuple[int, str]:
    """Return (score, reasons). `lead` uses db column names plus optional
    signal booleans: hiring_signal, funding_signal, tech_signal."""
    w = cfg.s("scoring.weights", {})
    icp = cfg.s("icp", {})
    score = 0
    reasons: list[str] = []

    title = (lead.get("title") or "").lower()
    exact = {t.lower() for t in icp.get("titles", [])}
    if title in exact:
        score += w.get("title_exact", 30)
        reasons.append("title exact match")
    else:
        seniority = any(k in title for k in
                        ("vp", "cto", "chief", "head", "director", "manager"))
        domain = any(k in title for k in
                     ("data", "ai", "ml", "machine learning", "engineer"))
        if seniority and domain:
            score += w.get("title_partial", 15)
            reasons.append("title partial match")

    size = lead.get("company_size") or 0
    lo, hi = icp.get("employee_range", [50, 500])
    slo, shi = icp.get("employee_sweet_spot", [100, 300])
    if slo <= size <= shi:
        score += w.get("size_sweet_spot", 20)
        reasons.append(f"size {size} in sweet spot")
    elif lo <= size <= hi:
        score += w.get("size_in_range", 10)
        reasons.append(f"size {size} in range")

    state = lead.get("state") or ""
    country = (lead.get("country") or "").lower()
    if state in icp.get("eastern_states", []):
        score += w.get("et_state", 15)
        reasons.append(f"ET state ({state})")
    elif "united states" in country or country == "us":
        score += w.get("us_remote", 8)
        reasons.append("US (remote-possible)")

    for key, label in (("hiring_signal", "hiring data/AI roles"),
                       ("funding_signal", "recent funding"),
                       ("tech_signal", "AI/ML/data mentions")):
        if lead.get(key):
            score += w.get(key, 10)
            reasons.append(label)

    return min(score, 100), "; ".join(reasons) or "no ICP criteria matched"
