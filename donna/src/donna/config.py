"""Runtime wiring for the Azure Functions host.

Bootstrap identifiers come from app settings (no secrets among them);
tunables live in the CONFIG table so nothing requires a redeploy;
the two secrets (close-token HMAC key, Teams webhook URL) live in
Key Vault and are read with the managed identity.

App settings:
  DONNA_TENANT_ID        Entra tenant id
  DONNA_CLIENT_ID        app registration client id
  DONNA_MI_CLIENT_ID     user-assigned managed identity client id
  DONNA_KEYVAULT_URI     https://<vault>.vault.azure.net/
  DONNA_DB_HOST / DONNA_DB_NAME / DONNA_DB_USER
  DONNA_DRY_RUN          "1" renders digests to files instead of sending
"""
from __future__ import annotations

import os
from functools import lru_cache

from .store import Store
from .telemetry import get_logger, install

log = get_logger(__name__)

HMAC_SECRET_NAME = "donna-close-hmac-key"
WEBHOOK_SECRET_NAME = "donna-teams-webhook-url"


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"missing app setting {name}")
    return value


@lru_cache(maxsize=1)
def graph_client():
    from .graph import GraphClient, build_credential
    credential = build_credential(
        _required("DONNA_TENANT_ID"), _required("DONNA_CLIENT_ID"),
        os.environ.get("DONNA_MI_CLIENT_ID"))
    return GraphClient(credential)


@lru_cache(maxsize=1)
def _secret_client():
    from azure.identity import ManagedIdentityCredential
    from azure.keyvault.secrets import SecretClient
    return SecretClient(
        vault_url=_required("DONNA_KEYVAULT_URI"),
        credential=ManagedIdentityCredential(
            client_id=os.environ.get("DONNA_MI_CLIENT_ID")))


def close_token_key() -> bytes:
    override = os.environ.get("DONNA_HMAC_KEY_LOCAL")
    if override:  # local dry runs only; never set in Azure
        return override.encode("utf-8")
    return _secret_client().get_secret(HMAC_SECRET_NAME).value.encode("utf-8")


def teams_webhook_url() -> str:
    override = os.environ.get("DONNA_WEBHOOK_URL_LOCAL")
    if override:
        return override
    return _secret_client().get_secret(WEBHOOK_SECRET_NAME).value


@lru_cache(maxsize=1)
def store() -> Store:
    install()  # telemetry boundary before anything logs
    url = os.environ.get("DONNA_DB_URL")
    if not url:
        # Entra (passwordless) auth to Postgres Flexible Server: the MI
        # access token is presented as the password. Zero secrets.
        from azure.identity import ManagedIdentityCredential
        token = ManagedIdentityCredential(
            client_id=os.environ.get("DONNA_MI_CLIENT_ID")).get_token(
            "https://ossrdbms-aad.database.windows.net/.default").token
        url = (f"postgresql+psycopg://{_required('DONNA_DB_USER')}:{token}"
               f"@{_required('DONNA_DB_HOST')}:5432/"
               f"{_required('DONNA_DB_NAME')}?sslmode=require")
    s = Store.from_url(url)
    s.ensure_schema()
    return s


def dry_run_dir(s: Store) -> str | None:
    if os.environ.get("DONNA_DRY_RUN") == "1" \
            or s.config_get("digest_dry_run") == "1":
        return s.config_get("dry_run_output_dir")
    return None
