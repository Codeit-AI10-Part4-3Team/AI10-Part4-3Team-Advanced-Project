# 백엔드 단독 이미지.
# 빌드 컨텍스트는 이 디렉토리(apps/backend)입니다. ai-engine 소스를 참조하지 마세요 —
# 두 앱의 결합은 HTTP 계약뿐이고(AGENTS.md), 이미지에 상대 앱을 넣는 순간 그 성질이 깨집니다.
#   docker build -t adgen-backend:dev apps/backend
#   docker run --rm -p 8000:8000 --env-file infra/.env adgen-backend:dev
FROM python:3.12-slim

# 파이썬 런타임 위생: .pyc 미생성, 로그 버퍼링 해제(컨테이너 로그 지연 방지)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 레이어를 소스와 분리해 캐시 적중률을 높인다.
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .

# 비루트 실행 — 한 호스트에 여러 서비스가 뜨므로 권한 격리를 유지한다.
RUN useradd --create-home --uid 10001 appuser

# 상태 디렉토리. **이미지 안에서 미리 만들고 소유권을 넘기는 것이 요점**입니다 —
# 도커는 이름 있는 볼륨을 처음 붙일 때 이미지의 해당 경로 소유권을 물려받습니다.
# 여기서 안 만들면 볼륨이 root 소유로 생기고, 비루트로 도는 앱이 기동하자마자
# PermissionError 로 죽습니다 (2026-08-12 실측). 근거: ADR-0014.
RUN mkdir -p /data && chown appuser:appuser /data
VOLUME ["/data"]

# ⚠️ 이 줄이 없으면 **아무 환경변수 없이 띄운 이미지가 기동하자마자 죽습니다.**
#    코드 기본값은 `./data/adgen.sqlite` 이고 그것은 WORKDIR(`/app`) 기준 상대 경로인데,
#    `/app` 은 root 소유라 비루트 appuser 가 `data/` 를 만들 수 없습니다
#    (`PermissionError: [Errno 13] 'data'`, 2026-08-14 실측 — CI 의 backend 스모크가
#    바로 여기서 떨어졌습니다). 코드 기본값은 `uvicorn` 을 apps/backend 에서 맨몸으로
#    돌리는 경우를 위한 것이고, 컨테이너의 기본값은 위에서 소유권까지 넘겨 준 이 경로여야
#    합니다. compose 도 같은 값을 주지만(infra/docker-compose.yml) 그것은 덧방이고,
#    `docker run` 한 줄로 뜨는 것은 이 줄의 몫입니다. 근거: ADR-0014.
#
# ⚠️ **두 줄입니다.** DB 만 옮기고 이미지를 두고 가면 증상이 기동이 아니라 **첫 업로드**에서
#    납니다 - `/health` 는 계속 초록이고 CI 스모크도 통과하는데, 사람이 사진을 올리는
#    순간 같은 PermissionError 가 납니다. 새 상태 경로를 만들 때마다 이 줄을 함께 보세요.
ENV ADGEN_DB_PATH=/data/adgen.sqlite \
    ADGEN_IMAGE_DIR=/data/images

USER appuser

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
