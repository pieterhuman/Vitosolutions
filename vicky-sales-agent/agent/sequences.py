"""Workflow 2 — Apollo sequence management.

config/templates/sequences.yaml is the source of truth. `sync` creates any
missing sequence in Apollo and verifies existing ones; live IDs are stored
in config/apollo.yaml. Sequences are always created INACTIVE — activation
is a deliberate human step in the Apollo UI (or `vicky activate <key>`).
"""

from __future__ import annotations

import logging

from .apollo_client import ApolloClient
from .config import Config

log = logging.getLogger("vicky.sequences")

EMAIL_TYPES = {"auto_email", "manual_email"}
MESSAGE_TYPES = EMAIL_TYPES | {"linkedin_step_connect", "linkedin_step_message"}


def _body_to_html(body: str) -> str:
    paragraphs = [p.strip().replace("\n", " ")
                  for p in body.strip().split("\n\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs)


def template_to_payload(cfg: Config, key: str) -> dict:
    tpl = cfg.sequences[key]
    steps = []
    for step in tpl["steps"]:
        entry: dict = {
            "type": step["type"],
            "wait_time": step["wait_time"],
            "wait_mode": "day",
        }
        if step.get("note"):
            entry["note"] = step["note"]
        if step["type"] in MESSAGE_TYPES:
            touch: dict = {
                "type": "reply_to_thread" if step.get("thread") == "reply"
                else "new_thread",
                "status": "to_be_reviewed" if step.get("review") else "approved",
                "include_signature": step["type"] in EMAIL_TYPES,
                "emailer_template": {
                    "subject": step.get("subject", ""),
                    "body_html": _body_to_html(step["body"]),
                    "creation_type": "manual",
                },
            }
            entry["emailer_touches"] = [touch]
        steps.append(entry)
    payload = {
        "name": tpl["name"],
        "emailer_steps": steps,
        "active": False,
        "permissions": "team_can_use",
        "label_names": ["vicky-agent"],
    }
    if cfg.apollo.get("emailer_schedule_id"):
        payload["emailer_schedule_id"] = cfg.apollo["emailer_schedule_id"]
    return payload


def sync(cfg: Config, apollo: ApolloClient) -> dict:
    """Ensure every templated sequence exists in Apollo; store IDs."""
    results = {}
    cfg.apollo.setdefault("sequences", {})
    for key in cfg.sequences:
        name = cfg.sequences[key]["name"]
        stored = cfg.apollo["sequences"].get(key) or {}

        found = None
        for seq in apollo.search_sequences(q_name=name).get(
                "emailer_campaigns", []):
            if seq.get("name") == name:
                found = seq
                break

        if found:
            cfg.apollo["sequences"][key] = {
                "id": found["id"], "name": name,
                "active": found.get("active", False),
            }
            results[key] = f"exists ({found['id']})"
        elif stored.get("id"):
            results[key] = f"stored id {stored['id']} not found by name — " \
                           "check Apollo (renamed or deleted?)"
        else:
            created = apollo.create_sequence(template_to_payload(cfg, key))
            seq = created.get("emailer_campaign", created)
            cfg.apollo["sequences"][key] = {
                "id": seq["id"], "name": name, "active": False,
            }
            results[key] = f"created inactive ({seq['id']})"
            log.info("created sequence %s -> %s", name, seq["id"])
    cfg.save_apollo()
    return results


def set_active(cfg: Config, apollo: ApolloClient, key: str,
               active: bool) -> None:
    """Activate/pause via a minimal declarative update: fetch current steps
    and echo them back with only `active` changed."""
    seq_id = cfg.sequence_id(key)
    if not seq_id:
        raise ValueError(f"no stored id for sequence '{key}' — run sync first")
    current = None
    for seq in apollo.search_sequences(
            q_name=cfg.sequences[key]["name"]).get("emailer_campaigns", []):
        if seq["id"] == seq_id:
            current = seq
            break
    if not current:
        raise ValueError(f"sequence {seq_id} not found in Apollo")
    steps = [
        {"id": s["id"], "type": s["type"], "position": s["position"],
         "wait_time": s["wait_time"], "wait_mode": s["wait_mode"]}
        for s in current["emailer_steps"]
    ]
    apollo.update_sequence(seq_id, {"active": active, "emailer_steps": steps})
    cfg.apollo["sequences"][key]["active"] = active
    cfg.save_apollo()
