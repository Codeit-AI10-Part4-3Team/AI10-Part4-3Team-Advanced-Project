# infra/

로컬·배포 공용 인프라 정의입니다. 스택 기동, 환경변수 템플릿, 프로비저닝 문서가 여기 모입니다.

```bash
cp infra/.env.example infra/.env        # 값 채우기 — ⚠️ .env는 커밋 금지
docker compose -f infra/docker-compose.yml up --build
```

## 파일

| 파일 | 역할 |
|---|---|
| `docker-compose.yml` | 전체 스택(backend + ai-engine). 로컬과 배포가 같은 파일을 씁니다 |
| `.env.example` | **키 이름만** 담은 템플릿. 값은 절대 넣지 마세요 |
| `.env` | 실제 값 — `.gitignore` 대상. 존재해도 커밋되지 않습니다 |

## 시크릿 취급 (공개 저장소 전제)

커밋된 키는 푸시되는 순간 공개된 것으로 간주하세요. 되돌리는 방법은 revert가 아니라
**폐기 후 재발급**입니다. 방어선은 세 겹이고, 세 겹 다 필요합니다:

1. GitHub Push protection — **제휴 발급사 패턴만** 잡습니다.
2. pre-commit `detect-private-key` — **PEM 개인키만** 잡습니다.
3. **gitleaks** — 위 둘의 사각지대(일반 API 키 문자열)를 덮습니다. pre-commit 훅(staged) +
   CI의 전체 트리 스캔이 **한 쌍**입니다. 훅 entry가 `--staged` 고정이라
   `pre-commit run --all-files`로는 아무것도 검사하지 않으므로, CI 스텝을 지우면 훅을
   설치하지 않은 사람의 키를 아무도 막지 못합니다.
   버전을 올릴 때는 `.pre-commit-config.yaml`의 rev만 고치면 됩니다 - CI가 그 값을 읽어 씁니다.

## 새 환경변수를 추가할 때

1. `.env.example`에 **키 이름과 설명**을 추가 (값은 빈칸)
2. `docker-compose.yml`의 해당 서비스 `environment:`에 전달 (`${VAR:-기본값}`)
3. 앱의 설정 클래스(`backend_core/config.py` 등)에 필드 추가 — 접두어 규약을 지킬 것
4. 필요하면 CI/배포 시크릿에도 등록

빠뜨리기 쉬운 것은 4번입니다. 로컬에서만 되는 변수는 배포에서 조용히 기본값으로 동작합니다.

## 배포

**대상: GCP VM 1대 (GPU 포함), 모노레포 전체를 이 VM 위 compose 스택으로 운영.**
결정의 배경은 `docs/adr/`에 ADR로 남기고, 이 문서에는 **재현 절차**를 남깁니다.

스펙은 **학원이 배정한 고정값**입니다. 협상 대상이 아니며 우리가 고를 수 있는 것은 OS뿐입니다.
근거와 파생 제약: [ADR-0011](../docs/adr/0011-배포_환경_스펙과_권한_경계.md).

| 항목 | 값 |
|---|---|
| 프로젝트 | 학원 배정 (콘솔에서 확인 — 공개 저장소이므로 ID를 적지 않습니다) |
| 리전 | `us-central1` |
| 머신 타입 | `g2-standard-4` (vCPU 4, 호스트 RAM 16GB) — **RAM만 늘릴 수 없습니다** |
| GPU | NVIDIA L4 1장. **가용 VRAM 23,034MiB (약 22.5GB)** — 공칭 24GB가 아닙니다 (2026-08-10 실측) |
| 부팅 디스크 | 100GB. **확장에 권한이 필요하므로 상한으로 취급합니다** |
| OS | `Deep Learning VM with CUDA M132` (Ubuntu 24.04, CUDA 12.9, Python 3.12) — **PyTorch 미포함 판을 고름** |
| 스냅샷 일정 | UTC 18:00 ~ 19:00 (KST 03:00 ~ 04:00). 보존 기간은 아래 주의 참고 |
| 외부 노출 포트 | backend `8000`만. **ai-engine `8100`은 절대 열지 마세요** (내부 계약 경로에 인증이 없습니다) |

### 권한 경계 (실측 기록)

IAM 역할은 커스텀 역할 `sprinter_vm_role_v1` **하나뿐**이고, **그 역할의 정의를 읽을 권한조차
없습니다**(`iam.roles.get` 거부). 따라서 범위는 **실측으로만** 알 수 있습니다 — 만들었다가 즉시
지우는 프로브로 확인하세요. 배포 주간에 권한 부족을 발견하면 대응할 시간이 없습니다 (리스크 ⑮).

| 확인일 | 항목 | 결과 |
|---|---|---|
| 2026-08-10 | 프로젝트 수준 조직 정책 | 0건 |
| 2026-08-10 | `compute.vmExternalIpAccess` | `ALLOW` — 외부 IP 부여 가능. 브라우저 접속 구성이 성립합니다 |
| 2026-08-10 | `compute.trustedImageProjects` | `ALLOW` — 이미지 프로젝트 제한 없음. **Deep Learning VM 이미지 사용 가능** |
| 2026-08-10 | `compute.requireShieldedVm` | 미적용 — 이미지 선택에 추가 제약 없음 |
| 2026-08-10 | `compute.disableSerialPortAccess` | 미적용 — **부팅 실패 시 시리얼 콘솔로 원인 확인 가능** |
| 2026-08-10 | `iam.disableServiceAccountKeyCreation` | **적용(enforced)** — 아래 "배포 자동화" 참고 |
| 2026-08-10 | `sprinter_vm_role_v1` 포함 권한 | **조회 불가**(`iam.roles.get` 거부). 아래는 실측 프로브 결과 |
| 2026-08-10 | 읽기: API 목록 · 인스턴스 · 방화벽 · 스냅샷 · DLVM 이미지 | 전부 **가능** |
| 2026-08-10 | 쓰기: API 활성화 · 고정 IP 예약 · 방화벽 규칙 생성 · 스냅샷 스케줄 생성 | 전부 **가능** |

**결론: 컴퓨트 계열에는 제약이 없고, 유일한 제약은 SA 키 발급 금지입니다.**
따라서 아래가 전부 가능합니다 — 권한이 없을 때를 가정한 우회 구성을 만들지 마세요.

- **고정 외부 IP 예약.** VM 정지/재시작에도 주소가 유지됩니다.
- **태그 기반 방화벽 규칙.** default VPC의 `default-allow-ssh`(22번이 `0.0.0.0/0`)를 그대로 두지
  말고, VM에 네트워크 태그를 붙여 필요한 포트만 여세요. SSH는 IAP TCP forwarding 대역
  (`35.235.240.0/20`)으로 제한하면 22번을 인터넷에 열지 않아도 됩니다.
- **스냅샷 스케줄 + 보존 기간.** 백업 수단이 SQLite cron 하나만 남는 최악 시나리오는 해소됐습니다.
- **API 활성화.** IAP, Cloud Monitoring 등 하위 기능이 막히지 않습니다.

> 프로브로 만든 리소스(`probe-ip` · `probe-fw` · `probe-snap`)는 **반드시 지웠는지 확인하세요.**
> `probe-fw`는 소스 범위를 지정하지 않아 `0.0.0.0/0`으로 열립니다.

#### 배포 자동화는 서비스 계정 키를 쓸 수 없습니다

`iam.disableServiceAccountKeyCreation`이 조직 수준에서 적용되어 **SA JSON 키를 발급할 수
없습니다.** 따라서:

- GitHub Actions에서 SA 키로 VM에 배포하는 경로는 **성립하지 않습니다.** 계획에 넣지 마세요.
- 배포는 SSH 접속 후 `git pull` + `docker compose up` 수동 경로입니다. 절차를 이 문서에 남기세요.
- **VM에 붙은 서비스 계정으로 VM 안에서 GCP API를 쓰는 것은 영향받지 않습니다.** 메타데이터
  서버가 토큰을 주므로 키가 필요 없습니다. 막힌 것은 키를 **VM 밖으로 꺼내는 일**입니다.

**막힌 권한은 우회하지 말고 여기에 기록한 뒤 학원에 요청하세요.** 우회 구성은 재현 절차를
학원 환경과 갈라놓습니다. 에러 메시지로 원인을 구분할 수 있습니다:

- `PERMISSION_DENIED: Required '...' permission` -> 내 IAM 역할 문제. 역할 추가로 해결됩니다.
- `Constraint constraints/... violated` -> 조직 정책. 역할을 줘도 안 되며 정책 예외 요청이 필요합니다.

### 프로비저닝 재현 절차 (2026-08-10 수행)

**콘솔 생성 시 기본값에서 바꾼 것** — 나머지는 전부 기본값입니다.

| 항목 | 값 | 이유 |
|---|---|---|
| 부팅 디스크 삭제 규칙 | **유지** | VM을 지워도 데이터가 남아야 합니다 ([ADR-0010](../docs/adr/0010-상태_저장소와_파일_보관_위치.md)) |
| 외부 IP | **고정** (`ai10-part4-team3-ip`) | GPU VM은 호스트 유지보수 때 강제 종료 후 재시작되며, 그때 임시 IP가 바뀝니다 |
| 부하 분산기 상태 점검 | **끔** | LB를 쓰지 않습니다. 유령 설정이 인수인계를 어렵게 합니다 |
| 보안 부트 | **끔** | 서명되지 않은 NVIDIA 커널 모듈이 로드되지 않아 GPU가 통째로 죽습니다 |
| OS Login | **끔** | 필요한 IAM 역할을 우리가 부여할 수 없어, 켜면 SSH에서 잠깁니다 |
| 삭제 보호 | **켬** | ADR-0010의 "복구 경로 없음" 제약 |
| 액세스 범위 | 기본 유지 | "전체 액세스"는 금물. 기본 범위에 `logging.write`/`monitoring.write`가 이미 포함됩니다 |

주의: **IP 주소 값은 저장소에 적지 않습니다.** 리소스 이름으로 콘솔에서 조회하세요.

**첫 부팅 실측값**

| 항목 | 값 |
|---|---|
| 디스크 | 96G 중 17G 사용, **80G 여유** (이미지가 가볍습니다) |
| 호스트 RAM | 15Gi. **swap 0** -> 16G 생성함 |
| 드라이버 | 580.173.02 (CUDA 13.0 지원). 컨테이너의 CUDA 12.x는 하위 호환으로 동작 |
| `nvidia-container-toolkit` | **1.17.8 사전 설치, `hold` 상태.** 드라이버와 버전이 어긋나지 않도록 고정된 것이니 풀지 마세요 |

**이미지에 Docker가 없습니다.** PyTorch 포함 판에는 있지만 CUDA 전용 판에는 없습니다. 수동 설치하며,
`apt install docker.io`는 **쓰지 마세요** — compose v2 플러그인이 딸려오지 않습니다.

```bash
# 1) Docker CE (공식 저장소)
sudo apt-get update && sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin

# 2) GPU 런타임 연결 - 툴킷은 이미 있으므로 저장소 등록·설치는 건너뜁니다.
#    키 파일이 이미 있다는 프롬프트가 뜨면 덮어쓰지 마세요(N).
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
sudo systemctl enable docker          # 재부팅 시 스택 복구의 전제 조건
sudo usermod -aG docker $USER         # 적용하려면 재로그인

# 3) swap - 호스트 RAM 16GB 고정이라 필수. fstab 줄을 빠뜨리면 재부팅 후 사라집니다.
sudo fallocate -l 16G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

**검증** (이 두 줄이 통과해야 프로비저닝 완료입니다)

```bash
docker compose version
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi   # L4가 보여야 함
```

호스트의 `nvidia-smi`가 아니라 **컨테이너 안에서 GPU가 보이는지**가 기준입니다. 배포가 compose
스택이기 때문입니다.

`apt-get update`에서 Google 저장소 두 곳에 대한 `Key is stored in legacy trusted.gpg keyring`
경고가 뜨는 것은 이미지가 원래 그렇게 만들어진 것입니다. 정상 동작하며 고치지 마세요.

### 이 환경에서 특히 주의할 것

- **GPU는 하나입니다.** 학습(`training/`)과 추론(`ai-engine`)이 동시에 VRAM을 요구하면 둘 다
  OOM으로 죽습니다. 시간 분할 규칙을 팀이 합의하고 여기에 적으세요.
- **호스트 RAM 16GB가 VRAM보다 먼저 터질 수 있습니다.** 머신 타입 고정이라 상향이 불가능하므로
  **swap을 반드시 잡으세요.** 없으면 OOM killer가 컨테이너를 조용히 죽입니다.
- **ai-engine은 방화벽에만 의존하지 말고 compose에서도 막습니다.** `ports:`를 `"127.0.0.1:8100:8100"`으로
  쓰면 커널이 루프백에만 바인딩하므로 방화벽 권한이 없어도 외부 노출이 원천 차단됩니다.
  `"8100:8100"`은 `0.0.0.0`에 붙습니다.
- **디스크 100GB가 상한입니다.** 모델 가중치 + Docker 이미지 + 학습 체크포인트 + 7일치 결과
  이미지가 전부 여기 들어갑니다. 사용률 감시는 선택 사항이 아닙니다.
- **재부팅 후 자동 복구를 실제로 재부팅해서 확인하세요.** `restart: unless-stopped`만으로는
  compose 스택이 부팅 시 기동한다는 보장이 없습니다. `systemctl enable docker`가 함께 필요합니다.
- **크레딧 잔여량은 우리 콘솔에서 보이지 않습니다.** 예고 없이 멈출 수 있으므로 시연·발표
  산출물을 미리 내려받아 두세요 (리스크 ⑨). 예산 알림은 권한 밖이라 대응책이 아닙니다.
- **배포를 마지막 주로 미루지 마세요.** W2에 빈 스택이라도 한 번 올려 두면 "우리 환경에서만
  안 되는 것"을 미리 발견합니다.

> ⚠️ **스냅샷 보존 기간을 데이터 보존 정책에 맞추세요.**
> [세션_보관_정책.md](../docs/기술문서/세션_보관_정책.md) 2절이 결과 이미지·브리프·시안을
> **7일**만 보존하도록 정하고 정리 배치가 실제로 지웁니다. 스냅샷을 30일 보관하면 지웠어야 할
> 업로드 사진이 스냅샷 안에 남습니다 — 개인정보이거나 저작물일 수 있는 데이터입니다.
> 보존 기간을 설정하지 않으면 스냅샷이 무한 누적됩니다.

남은 착수 항목: [docs/공통_가이드/착수_체크리스트.md](../docs/공통_가이드/착수_체크리스트.md) §5
