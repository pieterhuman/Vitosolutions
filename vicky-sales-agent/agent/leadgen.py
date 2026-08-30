"""Workflow 1 — lead generation: search Apollo for ICP people, enrich,
dedupe, score, and stage them in the local pipeline."""

from __future__ import annotations

import logging

from . import db, guardrails
from .apollo_client import ApolloClient
from .config import Config
from .scoring import score_lead

log = logging.getLogger("vicky.leadgen")

EMPLOYEE_RANGES = ["51,100", "101,200", "201,500"]


def _person_to_lead(person: dict) -> dict:
    org = person.get("organization") or {}
    return {
        "apollo_person_id": person.get("id"),
        "apollo_contact_id": person.get("contact_id")
        or (person.get("contact") or {}).get("id"),
        "email": person.get("email"),
        "first_name": person.get("first_name"),
        "last_name": person.get("last_name"),
        "title": person.get("title"),
        "linkedin_url": person.get("linkedin_url"),
        "company": org.get("name"),
        "company_domain": org.get("primary_domain"),
        "company_size": org.get("estimated_num_employees"),
        "city": person.get("city"),
        "state": person.get("state"),
        "country": person.get("country"),
    }


def _detect_signals(cfg: Config, apollo: ApolloClient, person: dict) -> dict:
    """Best-effort signal detection; failures never block sourcing."""
    org = person.get("organization") or {}
    signals: dict = {"hiring_signal": False, "funding_signal": False,
                     "tech_signal": False, "labels": []}
    keywords = cfg.s("icp.signal_keywords", [])

    blob = " ".join(str(org.get(k, "")) for k in
                    ("short_description", "seo_description", "keywords")).lower()
    if any(k in blob for k in keywords):
        signals["tech_signal"] = True
        signals["labels"].append("ai/ml/data mentions")

    funding = org.get("latest_funding_round_date") or ""
    if funding:
        signals["funding_signal"] = True
        signals["labels"].append(f"funding {funding[:10]}")

    org_id = org.get("id")
    if org_id:
        try:
            postings = apollo.org_job_postings(org_id).get(
                "organization_job_postings", [])
            titles = " ".join(p.get("title", "") for p in postings).lower()
            if any(k in titles for k in keywords):
                signals["hiring_signal"] = True
                signals["labels"].append(f"{len(postings)} open roles incl. data/AI")
        except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
            log.debug("job postings lookup failed for %s: %s", org_id, exc)
    return signals


def run(cfg: Config, apollo: ApolloClient, max_new: int | None = None) -> dict:
    """One sourcing pass. Returns summary counts."""
    max_new = max_new or cfg.s("volumes.max_new_leads_per_day", 60)
    icp = cfg.s("icp", {})
    added = scored_out = suppressed = 0

    with db.connect() as conn:
        page = int(db.kv_get(conn, "leadgen_page", "1"))
        while added < max_new:
            result = apollo.search_people(
                titles=icp.get("titles", []),
                locations=icp.get("locations", ["United States"]),
                employee_ranges=EMPLOYEE_RANGES,
                page=page,
                per_page=25,
            )
            people = result.get("people", []) + result.get("contacts", [])
            if not people:
                page = 1  # wrap around; dedupe makes re-scans cheap
                db.kv_set(conn, "leadgen_page", "1")
                break

            for person in people:
                if added >= max_new:
                    break
                lead = _person_to_lead(person)
                if not lead["email"]:
                    continue
                if guardrails.is_suppressed(cfg, lead["email"],
                                            lead["company_domain"]):
                    suppressed += 1
                    continue

                signals = _detect_signals(cfg, apollo, person)
                lead.update({k: signals[k] for k in
                             ("hiring_signal", "funding_signal", "tech_signal")})
                lead["signals"] = signals["labels"]
                lead["score"], lead["score_reasons"] = score_lead(cfg, lead)

                lead_id, created = db.upsert_lead(conn, lead)
                if created:
                    added += 1
                    db.log(conn, "lead_scored",
                           f"score={lead['score']} ({lead['score_reasons']})",
                           lead_id)
                    if lead["score"] < cfg.s("scoring.enroll_threshold", 60):
                        scored_out += 1
            page += 1
            db.kv_set(conn, "leadgen_page", str(page))

        db.log(conn, "leadgen_run",
               f"added={added} below_threshold={scored_out} "
               f"suppressed={suppressed}")
    return {"added": added, "below_threshold": scored_out,
            "suppressed": suppressed}
