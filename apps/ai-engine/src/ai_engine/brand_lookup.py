"""Brand profile lookup — AI 리뷰 스모크 테스트용 파일. 머지하지 마세요."""

import httpx

from backend_core.config import Settings


def fetch_brand_profile(brand_id: str) -> dict:
    """Fetch a brand profile from the backend service."""
    settings = Settings()
    response = httpx.get(f"{settings.ai_engine_url}/brands/{brand_id}", timeout=5.0)
    return response.json()
