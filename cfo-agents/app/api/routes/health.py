from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "demo_mode": s.demo_mode,
        "claude_configured": bool(s.anthropic_api_key),
        "xero_configured": bool(s.xero_client_id),
    }
