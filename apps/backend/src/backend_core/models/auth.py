"""Auth — login and the identity the client gets back.

Contract: packages/contracts/openapi.yaml. Edit it first (AGENTS.md 교체 순서).

Signup, withdrawal and password change are contract-only in the first cut and answer 501
(ADR-0008): the skeleton's question is "does authentication actually sit on the flow", and
creating accounts does not answer it.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Field

from backend_core.models.common import Base


class LoginRequest(Base):
    """Contract: `components.schemas.LoginRequest`.

    A wrong id and a wrong password are the same answer (`INVALID_CREDENTIALS`); telling
    them apart leaks whether an account exists.
    """

    login_id: str = Field(min_length=1, max_length=64)
    password: str = Field(
        min_length=1,
        description=(
            "요청 본문에만 존재합니다. 저장되는 것은 passwordHash 뿐이고 응답에 실리지 않습니다. "
            "요청 본문 전체를 찍는 디버그 로그가 가장 흔한 사고입니다"
        ),
    )


class Me(Base):
    """Contract: `components.schemas.Me`.

    No profile, display name or email. An email is one more piece of personal data to hold
    and delete, bought for nothing the first cut needs.
    """

    user_id: UUID = Field(description="다른 데이터가 참조하는 것은 이쪽입니다")
    login_id: str = Field(description="사용자가 입력하는 아이디. 바뀔 수 있습니다")
    created_at: datetime
