"""Job — the render that runs after the draft is locked.

Contract: packages/contracts/openapi.yaml. Edit it first (AGENTS.md 교체 순서).

Rendering takes tens of seconds, so it is never a synchronous HTTP response: finalize
accepts the work and the client polls this (API_계약.md 2.1절).
"""

from datetime import datetime
from typing import Literal

from pydantic import Field

from backend_core.models.common import Base, Error, Omittable

JobStatus = Literal["queued", "running", "done", "failed"]
"""Contract: `components.schemas.JobStatus`.

⚠️ A different layer from `SessionState`. A job exists only after `finalized`, and success
here is `done` — the session's success is `completed` (용어_사전.md 1.4절).
"""


class JobResult(Base):
    """Contract: `components.schemas.JobResult`. Present only once the job is `done`."""

    image_url: str
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    expires_at: datetime = Field(description="결과 이미지 보존 만료. 7일 (세션_보관_정책 2절)")


class Job(Base):
    """Contract: `components.schemas.Job`.

    ⚠️ `queuePosition`, `result` and `error` are present only in their own situation.
    **Test for the key, not for a value** — this contract has no `null`, so "not yet" is a
    missing key.
    """

    job_id: str
    status: JobStatus
    queue_position: Omittable[int] = Field(
        default=None,
        ge=0,
        description="대기 중일 때만. 렌더는 직렬 1건 (GPU 1대), 동시 실행 수는 설정값 기본 1",
    )
    result: Omittable[JobResult] = None
    error: Omittable[Error] = Field(
        default=None,
        description=(
            "실패했을 때만. CONTENT_POLICY_REJECTED 와 GENERATION_TIMEOUT 이 HTTP 상태와 "
            "잡 결과 양쪽에 쓰이는 이유는 화면이 어느 경로로 왔든 같은 분기를 타야 하기 때문입니다"
        ),
    )
