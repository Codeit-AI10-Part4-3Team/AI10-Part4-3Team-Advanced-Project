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

### 환경변수 값에 `$`가 들어갈 때 (2026-08-12 실측, 임동규)

위 2번을 **그대로 따르면 값이 깨집니다.** compose는 `${VAR}` 치환을 한 뒤 그 결과를 다시 읽는
것이 아니라, `.env` 값 안의 `$`를 **변수 참조로 해석**합니다. argon2 · bcrypt 해시가 전부
`$argon2id$v=19$...` 꼴이라 이 항목에 정면으로 걸립니다.

```
.env 입력  : password_hash":"$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaA"
컨테이너   : password_hash":"=19=65536,t=3,p=4"
```

`docker compose config` 로그에 `The "argon2id" variable is not set` 경고가 함께 찍힙니다.
`environment:` 목록형(`- ADGEN_ACCOUNTS`, 값 없이 이름만)도 **같은 방식으로 깨집니다.**

위 값은 `docker compose config` 의 렌더 결과가 아니라 **컨테이너 안에서 `printenv` 로 읽은
것**입니다. `config` 출력은 `$` 를 `$$` 로 다시 이스케이프해 보여주므로 그것만으로는 판정할 수
없습니다. 재현:

```bash
docker compose run --rm -T <서비스> printenv ADGEN_ACCOUNTS
```

네 가지를 컨테이너 안에서 확인한 결과입니다.

| 방법 | 컨테이너가 받는 값 | 채택 |
|---|---|---|
| `environment:` + `${VAR}` (규칙 2번 그대로) | 깨짐 | X |
| `environment:` 목록형 (`- VAR`) | 깨짐 | X |
| `.env`에서 `$` 를 `$$` 로 이스케이프 | **`$` 하나로 온전히 도착** | **O** |
| `env_file:` + `format: raw` | 온전히 도착 | X (아래 이유) |

**`.env`에서 `$$` 로 이스케이프하는 쪽을 씁니다.**

```bash
# .env - $ 를 두 번 씁니다
ADGEN_ACCOUNTS=[{"loginId":"demo1","passwordHash":"$$argon2id$$v=19$$m=65536,t=3,p=4$$..."}]
```

`env_file` 을 쓰지 않는 이유는 **파일 단위로만 지정되기 때문**입니다. backend 에 `.env` 를
통째로 물리면 ai-engine 전용인 `ADGEN_MODEL_API_KEY` 까지 backend 컨테이너에 들어갑니다.
외부에 열리는 것은 8000(backend) 쪽이므로, 유료 키를 그쪽에 함께 두지 않는 현재의 분리를
유지합니다. 시크릿 전용 `.env` 를 하나 더 두는 안은 `cp .env.example .env` 한 줄로 끝나는
세팅 절차가 둘로 갈라져 쓰지 않았습니다.

이스케이프를 빠뜨리면 값이 조용히 뭉개지고 증상은 "로그인만 안 됨"으로 나옵니다. 그래서
**backend 가 기동 시점에 해시 모양을 검사해 거부**합니다 - 사람이 규칙을 기억하는 것에만
기대지 않기 위해서입니다.

## 배포

**대상: GCP VM 1대 (GPU 포함), 모노레포 전체를 이 VM 위 compose 스택으로 운영.**
결정의 배경은 `docs/adr/`에 ADR로 남기고, 이 문서에는 **재현 절차**를 남깁니다.

스펙은 **학원이 배정한 고정값**입니다. 협상 대상이 아니며 우리가 고를 수 있는 것은 OS뿐입니다.
근거와 파생 제약: [ADR-0011](../docs/adr/0011-배포_환경_스펙과_권한_경계.md).

> 이 문서는 **어떻게 만들었는가**(프로비저닝·권한 실측)를 다룹니다.
> **어떻게 접속해서 쓰는가**(SSH·에디터·파일 전송·포트 포워딩·팀원 키 등록)는
> [docs/공통_가이드/GCP_VM_사용_가이드.md](../docs/공통_가이드/GCP_VM_사용_가이드.md) 입니다.

| 항목 | 값 |
|---|---|
| 프로젝트 | 학원 배정 (콘솔에서 확인 — 공개 저장소이므로 ID를 적지 않습니다) |
| 리전 / 영역 | `us-central1` / `us-central1-c` — **L4 재고는 영역마다 다릅니다.** 생성이 실패하면 다른 영역을 시도하세요 |
| 머신 타입 | `g2-standard-4` (vCPU 4, 호스트 RAM 16GB) — **RAM만 늘릴 수 없습니다** |
| GPU | NVIDIA L4 1장. **가용 VRAM 23,034MiB (약 22.5GB)** — 공칭 24GB가 아닙니다 (2026-08-10 실측) |
| 부팅 디스크 | 100GB. **확장에 권한이 필요하므로 상한으로 취급합니다** |
| OS | `common-cu129-ubuntu-2404-nvidia-580-stage` (콘솔 표기 `Deep Learning VM with CUDA M132`) — Ubuntu 24.04, CUDA 12.9, Python 3.12. **PyTorch 미포함 판** |
| 스냅샷 일정 | 정책 `adcraft-daily-snap`. UTC 18:00 (KST 03:00), **보존 7일**, `apply-retention-policy` |
| SSH | **22번을 `0.0.0.0/0`에 열어 둡니다(의도된 상태).** 아래 "SSH 접근 경로" 참고 |
| 외부 노출 포트 | backend `8000`만. **ai-engine `8100`은 절대 열지 마세요** (내부 계약 경로에 인증이 없습니다) |

### 권한 경계 (실측 기록)

IAM 역할은 커스텀 역할 `sprinter_vm_role_v1` **하나뿐**이고, **그 역할의 정의를 읽을 권한조차
없습니다**(`iam.roles.get` 거부). 따라서 범위는 **실측으로만** 알 수 있습니다 — 만들었다가 즉시
지우는 프로브로 확인하세요. 배포 주간에 권한 부족을 발견하면 대응할 시간이 없습니다 (리스크 11).

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
| 2026-08-10 | 쓰기: API 활성화 · 고정 IP 예약 · 방화벽 규칙 생성/수정 · 스냅샷 스케줄 생성 | 전부 **가능** |
| 2026-08-10 | `compute.instances.setMetadata` · `compute.disks.addResourcePolicies` | 있음 |
| 2026-08-10 | **`iap.tunnelInstances.accessViaIAP`** | **없음** (`4033: not authorized`). API를 켜도 동일 |

**결론: 컴퓨트 계열에는 제약이 없습니다. 남은 제약은 SA 키 발급 금지와 IAP 터널 접근 불가
둘이며, 후자 때문에 SSH 22번을 잠글 수 없습니다.**
아래는 권한이 확인되어 실제로 가능한 것들입니다 — 권한이 없을 때를 가정한 우회 구성을 만들지 마세요.

- **고정 외부 IP 예약.** VM 정지/재시작에도 주소가 유지됩니다.
- **방화벽 규칙 생성과 수정.** 다만 **SSH 22번은 잠그지 마세요** — IAP 터널 권한이 없어
  좁혔다가 되돌린 이력이 있습니다. 아래 "SSH 접근 경로" 절이 정본입니다.
- **스냅샷 스케줄 + 보존 기간.** 백업 수단이 SQLite cron 하나만 남는 최악 시나리오는 해소됐습니다.
- **API 활성화.** Cloud Monitoring 등 하위 기능이 막히지 않습니다.
  (IAP는 API를 켤 수는 있지만 터널 권한이 없어 쓰지 못합니다.)

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
| 디스크 | 이미지만 올린 직후 96G 중 17G 사용. **세팅 완료 후 36% 사용, 약 61G 여유** (swap 16G + Ops Agent 0.6G + Docker 이미지 포함). **base 모델 예산은 61G 기준** |
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

# 4) swappiness - 기본값 60은 RAM에 여유가 있어도 미리 페이지를 밀어내 학습 중 지연을 만듭니다.
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swappiness.conf
sudo sysctl -p /etc/sysctl.d/99-swappiness.conf
```

**swap은 메모리 증설이 아니라 안전망입니다.** 가중치를 CPU에 올렸다 GPU로 옮기는 구간의 뾰족한
피크를 넘기는 용도이고, 상시로 RAM을 초과하면 thrashing으로 학습이 사실상 멈춥니다. 그때는
worker 수를 줄여야 합니다. **VRAM에는 swap이 없으므로 리스크 1번은 이것으로 해결되지 않습니다.**

**검증** (이 두 줄이 통과해야 프로비저닝 완료입니다)

```bash
docker compose version
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi   # L4가 보여야 함
```

호스트의 `nvidia-smi`가 아니라 **컨테이너 안에서 GPU가 보이는지**가 기준입니다. 배포가 compose
스택이기 때문입니다.

**재부팅 1회 실검증** (2026-08-10 통과). 스택이 비어 있을 때 미리 해두면 배포 후에 놀랄 일이 없습니다.

```bash
sudo reboot
# 재접속 후
free -h                                              # Swap 15Gi 유지
systemctl is-enabled docker && systemctl is-active docker   # enabled / active
cat /proc/sys/vm/swappiness                          # 10
```

⚠️ 여기까지는 **docker 데몬 수준**입니다. `restart: unless-stopped`가 붙은 compose 스택이 실제로
살아 돌아오는지는 **배포 후 한 번 더 재부팅**해서 확인해야 리스크 10번이 닫힙니다.

**가용성 정책 확인** (2026-08-10 통과). 콘솔에서 놓치기 쉬운 자리라 값으로 확인합니다.

```bash
VM=<인스턴스명>
ZONE=$(gcloud compute instances list --filter="name=$VM" --format="value(zone)")
gcloud compute instances describe $VM --zone=$ZONE \
  --format="yaml(scheduling, deletionProtection)"
```

| 키 | 기대값 | 왜 |
|---|---|---|
| `deletionProtection` | `true` | [ADR-0010](../docs/adr/0010-상태_저장소와_파일_보관_위치.md)의 "복구 경로 없음" |
| `automaticRestart` | `true` | **false면 GCP 유지보수가 곧 조용한 다운타임입니다** (리스크 10번) |
| `onHostMaintenance` | `TERMINATE` | GPU라서 강제 고정. 바꿀 수 없고 정상입니다 |
| `provisioningModel` | `STANDARD` | Spot이면 예고 없이 회수됩니다 |

**스냅샷 스케줄** (2026-08-10 설정)

```bash
gcloud compute resource-policies create snapshot-schedule adcraft-daily-snap \
  --region=us-central1 --daily-schedule --start-time=18:00 \
  --max-retention-days=7 --on-source-disk-delete=apply-retention-policy \
  --storage-location=us-central1

gcloud compute disks add-resource-policies <디스크명> --zone=us-central1-c \
  --resource-policies=adcraft-daily-snap

# 붙었는지 반드시 확인 - 스케줄만 만들고 안 붙이면 아무 일도 일어나지 않습니다
gcloud compute disks describe <디스크명> --zone=us-central1-c \
  --format="yaml(resourcePolicies)"
```

- `--start-time`은 **UTC**입니다. 18:00 UTC = KST 03:00.
- 보존 7일은 [세션_보관_정책.md](../docs/기술문서/세션_보관_정책.md) 2절과 맞춘 값입니다.
  `keep-auto-snapshots`로 두면 디스크를 지워도 스냅샷이 영구히 남아 **업로드 사진의 보존 기간
  규정과 정면으로 어긋납니다.**
- ⚠️ 콘솔의 데이터 보호 섹션에서 이미 스케줄을 만들었다면 **정책이 두 개 붙습니다.** 스냅샷이
  하루 두 번 생기고 저장 비용도 두 배가 됩니다. `resourcePolicies`에 하나만 남는지 확인하세요.

**Ops Agent** (2026-08-10 설치, `2.70.0`)

```bash
curl -sSO https://dl.google.com/cloudagents/add-google-cloud-ops-agent-repo.sh
sudo bash add-google-cloud-ops-agent-repo.sh --also-install
systemctl is-active google-cloud-ops-agent-fluent-bit \
                   google-cloud-ops-agent-opentelemetry-collector
```

기본 액세스 범위에 `logging.write`와 `monitoring.write`가 있어 추가 권한 없이 동작합니다.
`nvidia-smi`가 있으면 GPU 메트릭도 수집합니다 -> 리스크 1번의 탐지 신호가 여기서 생깁니다.
디스크 약 560MB를 씁니다. **알림 정책은 별개입니다** — 에이전트는 수집만 하고,
"디스크 85% 초과" 같은 알림은 Cloud Monitoring에서 따로 만들어야 합니다.

`apt-get update`에서 Google 저장소 두 곳에 대한 `Key is stored in legacy trusted.gpg keyring`
경고가 뜨는 것은 이미지가 원래 그렇게 만들어진 것입니다. 정상 동작하며 고치지 마세요.

### SSH 접근 경로 (22번을 잠그지 마세요)

**`default-allow-ssh`의 `sourceRanges`는 `0.0.0.0/0`이고, 이건 의도된 상태입니다.**
좁히는 것이 낫다고 판단해 실제로 시도했다가 되돌린 결과입니다. 근거 없이 다시 잠그면
**접속 수단을 잃습니다.**

경위 (2026-08-10):

1. 22번을 IAP TCP forwarding 대역(`35.235.240.0/20`)으로 제한
2. `gcloud compute ssh --tunnel-through-iap`가 **`4033: not authorized`로 실패**
3. `iap.googleapis.com`을 활성화하고 재시도했으나 **동일하게 실패** ->
   원인은 API가 아니라 **커스텀 역할에 `iap.tunnelInstances.accessViaIAP`가 없는 것**
4. 그 권한은 우리가 부여할 수 없으므로 `0.0.0.0/0`으로 되돌림

**받아들일 만한 이유**

- GCP 리눅스 이미지는 **비밀번호 인증이 꺼져 있습니다.** 키 없이는 들어올 수 없고, 열린 22번에
  오는 무차별 대입은 애초에 성립하지 않습니다. 거의 모든 GCE VM의 기본 상태입니다.
- **접근 경로를 잃는 위험이 노출 위험보다 큽니다.** 22번을 잠그면 남는 복구 수단은 직렬 콘솔
  하나뿐이고, 실작업 22일에서 그 도박은 값을 하지 않습니다.

**잠갔다가 막혔을 때의 복구 경로** (`compute.instances.setMetadata` 권한 확인됨)

```bash
gcloud compute instances add-metadata <VM> --zone=<영역> \
  --metadata=serial-port-enable=TRUE     # 직렬 콘솔로 진입해 방화벽 원복
```

주의: 보안 화면의 **"프로젝트 차원 SSH 키 차단"을 켜지 마세요.** `gcloud compute ssh`는 키를
프로젝트 메타데이터에 등록합니다(실측 확인). 차단하면 그 키가 무시되어 접속이 막힙니다.

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
  산출물을 미리 내려받아 두세요 (리스크 9). 예산 알림은 권한 밖이라 대응책이 아닙니다.
- **배포를 마지막 주로 미루지 마세요.** W2에 빈 스택이라도 한 번 올려 두면 "우리 환경에서만
  안 되는 것"을 미리 발견합니다.

> ⚠️ **스냅샷 보존 기간을 데이터 보존 정책에 맞추세요.**
> [세션_보관_정책.md](../docs/기술문서/세션_보관_정책.md) 2절이 결과 이미지·브리프·시안을
> **7일**만 보존하도록 정하고 정리 배치가 실제로 지웁니다. 스냅샷을 30일 보관하면 지웠어야 할
> 업로드 사진이 스냅샷 안에 남습니다 — 개인정보이거나 저작물일 수 있는 데이터입니다.
> 보존 기간을 설정하지 않으면 스냅샷이 무한 누적됩니다.

남은 착수 항목: [docs/공통_가이드/착수_체크리스트.md](../docs/공통_가이드/착수_체크리스트.md) §5
