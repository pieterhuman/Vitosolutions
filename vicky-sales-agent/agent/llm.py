"""Claude API helpers: reply classification, reply drafting, personalization.

Uses the official Anthropic SDK. The persona block is passed as a stable
system prompt so it stays prompt-cache-friendly across calls.
"""

from __future__ import annotations

import json
import logging
import re

import anthropic

from .config import Config

log = logging.getLogger("vicky.llm")


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY / profile
        self.model = cfg.s("llm.model", "claude-opus-5")
        self.persona = cfg.prompts.get("persona", "")

    def _text(self, prompt: str, max_tokens: int) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=[{
                "type": "text",
                "text": self.persona,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in response.content if b.type == "text").strip()

    # ------------------------------------------------------------------------
    def classify_reply(self, lead: dict, reply_body: str, last_email: str = "",
                       step: int = 0) -> dict:
        prompt = self.cfg.prompts["classify_reply"].format(
            objection_keys=", ".join(self.cfg.objections.keys()),
            first_name=lead.get("first_name") or "",
            last_name=lead.get("last_name") or "",
            title=lead.get("title") or "",
            company=lead.get("company") or "",
            step=step,
            last_email=last_email[:1500],
            reply_body=reply_body[:4000],
        )
        raw = self._text(prompt, self.cfg.s("llm.classify_max_tokens", 1000))
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            log.warning("classifier returned no JSON; escalating to human")
            return {"classification": "other", "requires_human": True,
                    "summary": raw[:200], "objection_key": None,
                    "sentiment": "neutral"}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"classification": "other", "requires_human": True,
                    "summary": raw[:200], "objection_key": None,
                    "sentiment": "neutral"}
        parsed.setdefault("requires_human", True)
        parsed.setdefault("objection_key", None)
        return parsed

    def draft_reply(self, lead: dict, reply_body: str, classification: dict,
                    slots: list[str] | None = None) -> str:
        objection_block = ""
        key = classification.get("objection_key")
        if key and key in self.cfg.objections:
            script = self.cfg.objections[key]["response"]
            objection_block = f"- Pre-approved objection script to ground in:\n{script}"
        slots_block = ""
        if slots:
            slots_block = "- Calendar slots to offer (ET): " + "; ".join(slots)
        prompt = self.cfg.prompts["draft_reply"].format(
            first_name=lead.get("first_name") or "",
            last_name=lead.get("last_name") or "",
            title=lead.get("title") or "",
            company=lead.get("company") or "",
            classification=classification.get("classification"),
            summary=classification.get("summary", ""),
            stage=lead.get("stage", ""),
            objection_block=objection_block,
            slots_block=slots_block,
            reply_body=reply_body[:4000],
        )
        return self._text(prompt, self.cfg.s("llm.draft_max_tokens", 2000))

    def personalize_opener(self, lead: dict) -> str:
        prompt = self.cfg.prompts["personalize_opener"].format(
            first_name=lead.get("first_name") or "",
            title=lead.get("title") or "",
            company=lead.get("company") or "",
            employee_count=lead.get("company_size") or "?",
            industry=lead.get("industry") or "unknown",
            signals=lead.get("signals") or "none known",
        )
        return self._text(prompt, 200)

    def referral_ask(self, lead: dict, context: str) -> str:
        prompt = self.cfg.prompts["referral_ask"].format(
            first_name=lead.get("first_name") or "",
            company=lead.get("company") or "",
            context=context,
        )
        return self._text(prompt, 400)
