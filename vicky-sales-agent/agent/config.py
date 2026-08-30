"""Configuration loading: settings.yaml, apollo.yaml, templates, and .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
TEMPLATE_DIR = CONFIG_DIR / "templates"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
DB_PATH = DATA_DIR / "vicky.db"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader; real env vars take precedence."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


@dataclass
class Config:
    settings: dict[str, Any] = field(default_factory=dict)
    apollo: dict[str, Any] = field(default_factory=dict)
    sequences: dict[str, Any] = field(default_factory=dict)
    objections: dict[str, Any] = field(default_factory=dict)
    prompts: dict[str, Any] = field(default_factory=dict)

    # --- env-backed secrets -------------------------------------------------
    @property
    def apollo_api_key(self) -> str | None:
        return os.environ.get("APOLLO_API_KEY")

    @property
    def anthropic_api_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY")

    @property
    def gmail_app_password(self) -> str | None:
        return os.environ.get("GMAIL_APP_PASSWORD")

    # --- convenience accessors ---------------------------------------------
    def s(self, dotted: str, default: Any = None) -> Any:
        """settings lookup: cfg.s('volumes.max_emails_per_day')."""
        node: Any = self.settings
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def sender_email(self) -> str:
        return self.s("identity.email", "vicky@getunicornclub.com")

    def sequence_id(self, key: str) -> str | None:
        return ((self.apollo.get("sequences") or {}).get(key) or {}).get("id")

    def save_apollo(self) -> None:
        (CONFIG_DIR / "apollo.yaml").write_text(
            yaml.safe_dump(self.apollo, allow_unicode=True, sort_keys=False)
        )


def load() -> Config:
    _load_dotenv(ROOT / ".env")
    DATA_DIR.mkdir(exist_ok=True)
    REPORTS_DIR.mkdir(exist_ok=True)

    def read_yaml(path: Path) -> dict:
        return yaml.safe_load(path.read_text()) if path.exists() else {}

    return Config(
        settings=read_yaml(CONFIG_DIR / "settings.yaml"),
        apollo=read_yaml(CONFIG_DIR / "apollo.yaml"),
        sequences=read_yaml(TEMPLATE_DIR / "sequences.yaml"),
        objections=read_yaml(TEMPLATE_DIR / "objections.yaml"),
        prompts=read_yaml(TEMPLATE_DIR / "prompts.yaml"),
    )
