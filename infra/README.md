# infra/

로컬·배포 공용 인프라 정의입니다. 스택 기동, 환경변수 템플릿, 프로비저닝 문서가 여기 모입니다.

```bash
cp infra/.env.example infra/.env        # 값 채우기 — ⚠️ .env는 커밋 금지
docker compose -f infra/docker-compose.yml up --build
```

## 파일

| 파일 | 역할 |
|---|---|
| `docker-compose.yml` | 전체 스택(caddy + frontend + backend + ai-engine). 로컬과 배포가 같은 파일을 씁니다 |
| `Caddyfile` | 앞단 프록시 설정. **HTTPS 종단 지점**입니다 ([ADR-0016](../docs/adr/0016-HTTPS_종단_지점과_인증서_발급_경로.md)) |
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
   — ⚠️ **값에 `$`가 들어가면 이 방식이 값을 조용히 깨뜨립니다.** 비밀번호 해시가 여기
   해당합니다. 아래 "환경변수 값에 `$`가 들어갈 때"를 먼저 읽으세요
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
**backend 가 기동 시점에 해시를 실제로 파싱해 보고, 안 되면 거부**합니다 - 사람이 규칙을
기억하는 것에만 기대지 않기 위해서입니다.

⚠️ **모양(접두어)만 보지 않고 파싱하는 이유가 있습니다** (2026-08-13 실측). `$argon2` 나
`$argon2id$v=19` 처럼 앞부분만 맞고 잘린 값은 접두어 검사를 통과하는데, argon2 는 그것을
`InvalidHashError` 로 거부합니다. 그런데 이 예외는 `Argon2Error` 가 아니라 `ValueError` 를
상속해서 로그인 경로의 예외 처리를 빠져나가고, 사용자에게는 **500** 으로 나갑니다. 깨진 설정
값은 로그인 화면의 원인 불명 오류가 아니라 컨테이너가 안 뜨는 것으로 드러나야 합니다.

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
| 외부 노출 포트 | 프록시의 `80` + `443` 둘뿐. backend `8000`과 ai-engine `8100`은 **루프백 바인딩**이라 밖에서 닿지 않습니다 |

> **2026-08-19: HTTPS 종단이 들어오면서 호스트에 열리는 포트가 프록시의 것 둘만 남았습니다**
> ([ADR-0016](../docs/adr/0016-HTTPS_종단_지점과_인증서_발급_경로.md)). frontend `80`과
> backend `8000`은 **루프백에만** 남습니다 -- 밖에서 오는 브라우저도 `curl`도 프록시를
> 거칩니다. 밖에 열지 않는 이유는 열어 두면 **로그인 비밀번호를 평문으로 받는 문이 하나
> 남기** 때문입니다 (ADR-0008). 한 출처라는 성질은 그대로이고(`/v1`은 여전히 컨테이너
> 안에서 backend 로 넘어갑니다), 그것이 세션 쿠키가 실리는 조건입니다.
>
> 루프백을 남긴 것은 디버깅 경로 때문입니다. 프록시가 넘기는 접두어는 `/v1`과 `/health`
> 뿐이라 `/docs`는 프록시로 오지 않고, "프록시가 문제인가 앱이 문제인가"를 가르려면 앱을
> 직접 두드릴 수 있어야 합니다. VM에서 `ssh -L 8000:localhost:8000`으로 닿습니다.

### 이 VM에서 실제로 도는 것 (2026-08-21)

2026-08-11 회의가 "실제 사용 모델과 하드웨어 최적화 여부를 인프라 문서에 적을 것"을 지정했고,
이 절이 그 답입니다. 위 표가 하드웨어를 상세히 적고 있어 **이 스택이 L4에서 모델을 돌린다고
읽히기 쉽기 때문**에 여기 둡니다.

#### 모델은 전부 외부 API입니다

VM 안에서 도는 모델 가중치가 **하나도 없습니다.** 컨테이너 셋(frontend, backend, ai-engine)과
프록시가 전부이고, ai-engine이 하는 일은 프롬프트를 조립해 벤더에 HTTP로 보내는 것입니다.

| 쓰는 곳 | 모델 | 설정 이름 | 비고 |
|---|---|---|---|
| 이미지 생성 (`image:render`) | `gpt-image-2` | `ADGEN_IMAGE_MODEL` | 검증 1순위가 실제로 통과시킨 값입니다 (2026-08-14) |
| 브리프 채우기 (`brief:fill`) | `gpt-5` | `ADGEN_TEXT_MODEL` | 사진을 함께 읽으므로 이미지 입력을 받는 모델이어야 합니다 |
| 시안 생성과 부분 교체 (`draft:generate` · `draft:patch`) | `gpt-5` | 위와 같은 값 | 키도 `ADGEN_MODEL_API_KEY` 하나를 공유합니다 |

- ⚠️ **`ADGEN_TEXT_MODEL`의 기본값은 실측으로 고른 값이 아닙니다.** `ADGEN_IMAGE_MODEL`과 달리
  검증 회차가 없습니다. 실물로 처음 돌리기 전에 그 이름이 벤더에 실재하는지부터 확인하세요.
- 품질 티어는 **요청이 실어 옵니다** (만화형 `medium`, 단일 광고형 `low`). 설정으로 누르는
  통로는 `ADGEN_IMAGE_QUALITY_OVERRIDE` 하나이고 **배포에서는 비워 두는 것이 정상**입니다.
  채우면 요청 값을 덮어쓰고 경고 로그를 남깁니다.
- 기본값은 `ADGEN_GENERATION_MODE=stub`입니다. **실물로 돌리려면 배포에서 `model`로 바꿔야
  하고**, 기동 로그의 WARNING 한 줄이 어느 쪽인지 알려 줍니다.

#### 하드웨어 최적화는 하지 않습니다

**최적화할 대상이 없습니다.** 양자화도, 오프로드도, 배치도 로컬 추론이 있을 때의 이야기입니다.

- 로컬 모델 채택 여부는 2026-08-20에 **미채택**으로 닫혔습니다
  ([회의록](../docs/회의록/2026-08-20_검증4순위_로컬모델_미채택.md), 미결정_대장 A-5).
  파인튜닝도 하지 않습니다 ([ADR-0004](../docs/adr/0004-파인튜닝_보류.md)).
- **compose의 어떤 서비스도 GPU를 예약하지 않습니다.** `deploy.resources`도 `--gpus`도 없어서,
  스택을 띄워도 L4는 유휴 상태로 남습니다.
- 그래도 드라이버와 `nvidia-container-toolkit` 항목을 지우지 않는 이유는 **이미지가 그 상태로
  배정됐기 때문**입니다. 우리가 설치한 것이 아니라 받은 것이고, 되살릴 조건(A-5 확정을 뒤집는
  회의록)이 남아 있습니다. 아래 "프로비저닝 재현 절차"의 GPU 확인 단계도 같은 이유로 남깁니다.
- ⚠️ 위 표의 **"base 모델 예산은 61G 기준"** 은 로컬 모델을 얹을 수 있다는 전제로 쓴 문장입니다.
  지금은 그 예산을 쓰는 것이 없습니다.

#### 그래서 실제 자원 압박은 어디인가

GPU가 아닙니다. 배포에서 조일 곳은 셋입니다.

| 압박 | 값 | 근거 |
|---|---|---|
| 외부 API 지연 | 만화형 한 세트 `medium` 118.0초, `low` 52.8초 (운영 경로 실측) | [API생성_시험_보고서.md](../docs/보고서/API생성_시험_보고서.md) |
| 외부 API 비용 | 만화형 `medium` 세트당 0.4041 USD. 텍스트는 세션당 0.0277 ~ 0.0305 USD, 부분 교체 1회 0.0090 USD | 검증 6순위 |
| 호스트 RAM 16GB와 디스크 100GB | 늘릴 수 없습니다 ([ADR-0011](../docs/adr/0011-배포_환경_스펙과_권한_경계.md)) | 2026-08-10 실측 |

⚠️ **단일 광고형은 텍스트가 이미지보다 4배 비쌉니다** (0.0277 대 0.0069). 예산 상한을 이미지
기준으로만 잡으면 그 유형에서 틀립니다.

지연을 다루는 장치는 **타임아웃 예산**입니다. 엔진이 칸 하나를 기다리는 상한과 렌더 응답 전체의
예산이 따로 있고, 호출자(backend)보다 **안쪽이 먼저 포기하도록** 벌려 둡니다. 그래야 어느 칸에서
막혔는지가 로그에 남습니다. 값과 근거: [세션_보관_정책.md](../docs/기술문서/세션_보관_정책.md) 6.1절.

### HTTPS (2026-08-19, ADR-0016)

앞단의 `caddy` 서비스가 TLS 를 종단하고, 인증서는 Let's Encrypt 에서 자동 발급받습니다.
**켜고 끄는 것은 환경변수 하나입니다.**

| `ADGEN_PUBLIC_HOST` | 결과 |
|---|---|
| 비어 있음 | 프록시가 `:80` 평문으로 뜹니다. 로컬 개발과 CI 가 이 상태입니다 |
| 호스트명 | 그 이름으로 인증서를 자동 발급하고 HTTPS 를 켭니다. `80`은 리다이렉트가 됩니다 |

- ⚠️ **배포에서 이 값을 비워 두지 마세요.** 세션 쿠키가 `Secure` 라 브라우저가 버리고,
  증상은 "로그인은 되는데 새로고침하면 풀림" 입니다 (2026-08-18 실측).
- ⚠️ **값을 커밋하지 마세요.** `<외부 IP>.sslip.io` 형태라 그 문자열 자체가 외부 IP 입니다
  ([GCP_VM_사용_가이드.md](../docs/공통_가이드/GCP_VM_사용_가이드.md) 2-b절).
  값은 `infra/.env`, 이름만 `.env.example`.
- ⚠️ **`80`을 닫지 마세요.** HTTPS 를 켜면 리다이렉트만 하는 것처럼 보이지만, 주소를 그냥 친
  사람이 닿는 곳이고 **인증서 발급의 HTTP-01 폴백 경로**이기도 합니다. 2026-08-19 첫 발급은
  `tls-alpn-01`(443)로 끝나 80 이 필수 조건은 아니었지만, 그 경로가 막히면 남는 것이
  이쪽뿐입니다.
- 인증서와 ACME 계정 키는 `adgen-caddy-data` 볼륨에 있습니다. `docker compose down -v` 는
  이것도 지우고, 지우면 다음 기동이 재발급을 시도해 발급 한도를 먹습니다.
- 발급이 실패하면 `docker compose logs caddy` 에 즉시 드러납니다. 한도로 막히면 ADR-0016 의
  선택지 B(자체 서명)로 내려가고 그 ADR 을 갱신합니다.

### 배포 체크아웃은 `/srv/adcraft/app`

배포 트리는 **개인 홈이 아니라 `adcraft` 그룹 소유의 공용 경로 하나**입니다.

```
/srv/adcraft/
├── app/     <- 배포 체크아웃. deploy-vm.sh 가 여기서만 돕니다
└── exp/     <- 공용 실험 폴더. 배포와 무관합니다 (GCP_VM_사용_가이드.md 6절)
```

> **2026-08-19 이관 완료 (실측).** `~/adcraft`에서 옮겼고 아래를 확인했습니다.
> `drwxrws---+ spai1032 adcraft` (setgid + ACL 상속됨), `core.sharedRepository=group`,
> `--system safe.directory` 등록됨, `infra/.env`는 `-rw-rw----`, 컨테이너 3종 healthy,
> backend `/health` 200 · frontend `/` 200 · 프록시 `/v1/sessions` 401.
> **볼륨 `adgen_adgen-state`의 `CreatedAt`이 `2026-08-15T02:28:18Z`로 이관 전과 같고**
> 계정 2건이 그대로입니다 -- 경로를 옮겨도 상태가 따라오지 않는다는 것이 실제로 확인됐습니다.
> 옛 체크아웃은 `~/adcraft.retired-20260819`로 무력화했습니다.

`/srv/adcraft`에는 `adcraft` 그룹과 setgid, 기본 ACL이 **이미 걸려 있습니다.** `app`을 그
아래에 두는 이유가 그것입니다 -- 새 경로에 권한을 처음부터 세울 필요 없이 상속받습니다.

홈에 두지 않는 이유는 셋입니다.

- **소유자 한 명에게 묶입니다.** 그 계정이 빠지거나 잠기면 배포 경로가 함께 사라지고, 다른
  사람은 남의 홈을 읽지도 고치지도 못합니다. 배포는 한 사람의 자산이 아닙니다.
- **경로가 사람마다 달라집니다.** `~`는 실행하는 계정에 따라 다른 곳을 가리키므로, 문서에
  `~/adcraft`라고 적으면 그 문서는 쓴 사람에게만 맞습니다.
- **어느 트리가 떠 있는지 알 수 없게 됩니다.** compose 프로젝트 이름이 `adgen`으로 고정이라
  (`docker-compose.yml`의 `name:`) **어느 체크아웃에서 올리든 같은 컨테이너와 같은 볼륨을
  갈아끼웁니다.** 옛 체크아웃에서 실행해도 에러 없이 성공하고, 그때부터 배포된 코드는 아무도
  보고 있지 않은 트리가 됩니다. 실패로 드러나지 않는 것이 이 함정의 전부입니다.

마지막 항목 때문에 `deploy-vm.sh`는 **`/srv/adcraft/app` 밖에서 실행되면 중단합니다.**
개인 체크아웃에서 시험 배포를 돌릴 때만 `--allow-any-root`나 `ADCRAFT_DEPLOY_ROOT`로 끕니다.

#### 최초 1회 준비

`/srv/adcraft`가 이미 `adcraft` 그룹 · setgid · 기본 ACL 상태이므로
([GCP_VM_사용_가이드.md](../docs/공통_가이드/GCP_VM_사용_가이드.md) 6절), 그 아래에 만들면
**그룹과 ACL이 상속됩니다.** 그룹에 속한 계정이면 `sudo` 없이 만들어집니다.

```bash
mkdir -p /srv/adcraft/app
git clone <저장소 URL> /srv/adcraft/app

git -C /srv/adcraft/app config core.sharedRepository group
sudo git config --system --add safe.directory /srv/adcraft/app
```

만든 뒤 상속이 실제로 됐는지 한 번 봅니다. `drwxrws---` 와 그룹 `adcraft` 가 나와야 합니다.

```bash
ls -ld /srv/adcraft/app
```

`s`(setgid)가 없거나 그룹이 다르면 상위 경로 설정이 빠진 것입니다. 그때만 직접 겁니다:

```bash
sudo chgrp -R adcraft /srv/adcraft/app
sudo chmod -R 2770 /srv/adcraft/app
sudo setfacl -R -d -m g::rwx /srv/adcraft/app
```

git 설정 두 줄이 **여러 사람이 같은 체크아웃을 만지기 때문에** 필요한 부분입니다.

- `core.sharedRepository=group` 없이 두면 A가 `fetch`로 만든 객체 파일에 그룹 쓰기가 빠져
  B의 다음 `fetch`가 권한 오류로 죽습니다.
- `safe.directory` 없이 두면 git 2.35.2+가 **소유자가 다른 저장소를 통째로 거부합니다**
  (`dubious ownership`). A가 클론하고 B가 배포하는 순간 첫 git 명령에서 터지는데, 메시지가
  배포와 무관해 보여 원인을 찾는 데 시간이 갑니다. `--global`이 아니라 `--system`인 이유는
  **배포를 누가 돌릴지 정해져 있지 않기 때문**입니다. `--global`은 실행한 사람에게만 걸립니다.

`deploy-vm.sh`의 사전 점검이 이 둘을 각각 진단해 주지만, 진단은 위 명령을 안내할 뿐입니다.

#### 홈 디렉토리에 있던 체크아웃 이관

기존 배포는 개인 홈(`~/adcraft`)에 있었습니다. 옮길 때 확인할 것은 하나뿐입니다 --
**상태 볼륨은 따라 움직이지 않습니다.** `adgen-state`는 호스트 경로가 아니라 이름 있는
볼륨이고 compose 프로젝트 이름도 `adgen`으로 고정이므로, 새 경로에서 스택을 올려도 **계정과
세션은 그대로 살아 있습니다**(ADR-0014). 볼륨을 백업하거나 옮기는 절차는 필요 없습니다.

```bash
# 1. 위 "최초 1회 준비"를 먼저 끝냅니다.

# 2. .env 는 ignore 파일이라 clone 에 따라오지 않습니다. 손으로 옮기는 유일한 파일입니다.
cp ~/adcraft/infra/.env /srv/adcraft/app/infra/.env
chmod 660 /srv/adcraft/app/infra/.env          # 그룹은 읽고, 그 밖은 못 읽게

# 3. 새 경로에서 배포합니다. 여기서 계정 건수가 이관 전과 같아야 합니다.
cd /srv/adcraft/app && bash scripts/deploy-vm.sh

# 4. 옛 체크아웃을 실행할 수 없게 만듭니다. 남겨 두면 언젠가 거기서 배포합니다.
#    (스크립트의 경로 검사가 막지만, 막힌 뒤에야 알게 되는 것보다 낫습니다.)
mv ~/adcraft ~/adcraft.retired-YYYYMMDD
```

4번을 `rm -rf`가 아니라 `mv`로 두는 것은 **옛 트리에만 있는 손댄 파일이 없는지 확인할 시간을
남기기 위해서**입니다. 새 경로에서 배포가 한 번 성공하고 며칠 지난 뒤 지우세요.

> ⚠️ **`docker compose down -v`로 정리하지 마세요.** 옛 경로를 치우는 작업과 볼륨을 비우는
> 작업은 전혀 다른 일이고, `-v`는 계정과 세션을 지웁니다. 컨테이너는 새 경로의 `up`이 알아서
> 갈아끼웁니다 -- 옛 경로에서 내릴 필요가 없습니다.

### 배포 실행 절차 (`scripts/deploy-vm.sh`)

SA 키를 발급할 수 없어 배포는 **SSH 수동 경로**입니다(아래 "배포 자동화" 참고). 그 절차를
사람의 기억이 아니라 스크립트에 고정했습니다 — 손으로 치면 빠뜨리는 것이 매번 다릅니다.

**VM 안에서** 실행합니다. 원격에서는 SSH로 감쌉니다:

```bash
ssh "$ADCRAFT_VM" 'cd /srv/adcraft/app && bash scripts/deploy-vm.sh'
```

| 명령 | 하는 일 |
|---|---|
| `bash scripts/deploy-vm.sh` | `origin/main`으로 fast-forward -> 이미지 재빌드 -> 스택 교체 -> 관통 확인 |
| `bash scripts/deploy-vm.sh --ref <ref>` | 다른 브랜치·태그·커밋으로. **롤백도 이 경로입니다** |
| `bash scripts/deploy-vm.sh --check` | 점검만. 아무것도 바꾸지 않습니다 |
| `bash scripts/deploy-vm.sh --no-build` | **체크아웃과 이미지를 그대로 두고** 재기동. `.env`만 고쳤을 때 (예: `ADGEN_PUBLIC_HOST`) |
| `bash scripts/deploy-vm.sh --allow-any-root` | 배포 경로 검사를 끕니다. 개인 체크아웃에서 시험할 때만 |

> ⚠️ **`--no-build`는 체크아웃을 갱신하지 않습니다**(`--ref`와 함께 쓸 수 없습니다). 코드를
> 새 커밋으로 옮기면서 이미지를 옛것으로 두면, 실제로 도는 코드와 `git rev-parse HEAD`가
> 어긋나 "VM에 뭐가 떠 있나"의 답이 조용히 거짓이 됩니다. 코드를 옮기는 경로는 재빌드하는
> 쪽 하나뿐입니다 — 소스가 그대로면 레이어 캐시가 걸려 재빌드도 몇 초로 끝납니다.

접속 정보(외부 IP · 프로젝트 ID · 인스턴스명)는 **스크립트에도 이 문서에도 적지 않습니다.**
저장소가 public이기 때문이며, 접속 경로는
[GCP_VM_사용_가이드.md](../docs/공통_가이드/GCP_VM_사용_가이드.md)에 있습니다.

스크립트가 사람 대신 지키는 것은 다섯입니다. 손으로 배포할 때도 같은 순서를 지키세요:

- **`/srv/adcraft/app` 밖에서는 실행되지 않습니다.** 옛 체크아웃에서 돌린 배포는 에러 없이
  성공해서, 실패가 아니라 "아무도 안 보는 트리가 떠 있는 상태"로 나타납니다 (위 절).
- **`infra/.env` 없이 기동하지 않습니다.** 없으면 `ADGEN_ACCOUNTS`가 빈 문자열로 넘어가고,
  `seed([])`는 아무것도 지우지 않으므로 **기동은 성공한 채 로그인만 어긋납니다.** 배포 실패로
  보이지 않는 것이 이 함정의 전부입니다 (`apps/backend/tests/api/test_startup.py`).
- **볼륨을 건드리는 플래그를 쓰지 않습니다.** `-v`는 스크립트 어디에도 없습니다 (아래 절).
- **`git merge --ff-only`만 씁니다.** 배포 체크아웃에 머지 커밋이 생기면 "VM에 뭐가 떠 있나"를
  커밋 SHA로 답할 수 없게 됩니다.
- **`--wait`로 healthy를 확인하고, 실패하면 로그와 롤백 명령을 출력합니다.** 안 뜬 스택을
  성공으로 보고하지 않기 위해서입니다.

배포 후 확인 항목도 스크립트가 함께 찍습니다: 컨테이너 상태, `/data/adgen.sqlite` 보존,
시드된 계정 건수(0건이면 로그인이 무조건 401), 생성 모드(`stub` / `model`), 그리고 **프록시를
거친** `/health` · `/` · `/v1/sessions`(미인증 401). 마지막 항목 하나가 라우팅 · 인증 · 에러
계약 셋을 한 번에 봅니다.

> **2026-08-19: 확인 경로가 프록시 하나로 모였습니다** (ADR-0016). backend `8000`이 루프백에만
> 있어 밖에서는 두드릴 수 없고, 무엇보다 프록시를 거치는 편이 실제 사용자 경로와 같습니다.
> `ADGEN_PUBLIC_HOST`가 채워져 있으면 스크립트는 **HTTPS로** 확인하고 `80`이 308 리다이렉트로
> 살아 있는지도 함께 봅니다. 비어 있으면 평문으로 확인하면서 **"브라우저 로그인은 성립하지
> 않는다"고 경고합니다** — 세션 쿠키가 `Secure` 고정이라 평문 응답의 쿠키를 브라우저가
> 저장하지 않기 때문입니다 ([API_계약.md](../docs/기술문서/API_계약.md) 8.3절).

> ⚠️ HTTPS 확인은 `curl --resolve`로 **loopback에 붙여서** 합니다. GCP VM은 자기 외부 IP로
> 되돌아오지 못해, 이름을 그대로 쓰면 배포는 멀쩡한데 확인만 실패합니다. SNI와 Host에는 진짜
> 이름이 실리므로 인증서 검증을 건너뛰는 것이 아닙니다 — 발급이 실패했으면 여기서 걸립니다.

### 상태는 `adgen-state` 볼륨 안에 있습니다

계정·세션이 든 SQLite 파일은 컨테이너의 `/data`에 있고, 그 경로에는 이름 있는 볼륨
`adgen-state`가 붙습니다. 호스트 디렉토리가 아닙니다. 왜 바인드 마운트가 아닌지:
[ADR-0014](../docs/adr/0014-상태_파일은_이름_있는_볼륨에_둔다.md).

- ⚠️ **`docker compose down -v`는 계정과 세션을 전부 지웁니다.** `-v` 한 글자 차이입니다.
  스택을 내릴 때는 `-v` 없이 내리세요. 볼륨을 비우는 것은 "다시 시드하겠다"는 결정이며,
  되돌릴 방법은 백업뿐입니다.
- 파일을 눈으로 확인할 때: `docker compose -f infra/docker-compose.yml exec backend ls -l /data`
- 백업은 호스트의 파일 복사가 아니라 컨테이너를 한 번 거칩니다. `VACUUM INTO`로 사본을
  만든 뒤 `docker compose cp`로 꺼내는 형태이며, **`scripts/backup-db.sh`가 그것입니다**
  (2026-08-19, [ADR-0010](../docs/adr/0010-상태_저장소와_파일_보관_위치.md)). 아래 절 참고.
- 업로드 사진·결과 이미지가 들어올 때도 **볼륨을 새로 만들지 말고 이 볼륨을 씁니다.**
  보존 기간 정리 배치가 한 곳만 보게 하기 위해서입니다
  ([세션_보관_정책.md](../docs/기술문서/세션_보관_정책.md) 2절).

### 상태 파일 백업 (`scripts/backup-db.sh`)

```bash
bash scripts/backup-db.sh                    # 백업 + 오래된 것 정리
bash scripts/backup-db.sh --list             # 가진 백업 목록
bash scripts/backup-db.sh --restore <파일>    # 되돌리기 (스택을 잠깐 내립니다)
```

백업은 `/srv/adcraft/backups`에 쌓이고 14개를 남깁니다(`ADCRAFT_BACKUP_DIR`,
`ADCRAFT_BACKUP_KEEP`). 배포 체크아웃 **밖**인 이유는 안에 두면 `deploy-vm.sh`의 "추적 파일에
커밋되지 않은 변경" 검사에 걸리고, 더 나쁘게는 실수로 커밋되기 때문입니다.

**cron 에 거는 법.** VM 에서 `crontab -e` 후 한 줄입니다.

```cron
17 3 * * * mkdir -p /srv/adcraft/backups && cd /srv/adcraft/app && bash scripts/backup-db.sh >> /srv/adcraft/backups/cron.log 2>&1
```

> ⚠️ 앞의 `mkdir -p`가 군더더기로 보이지만 아닙니다. **리다이렉트는 스크립트가 시작되기 전에
> 열립니다.** 디렉토리를 만드는 것은 스크립트 안이므로, 수동 실행을 한 번도 하지 않고 cron부터
> 걸면 첫 실행이 통째로 실패하고 **그 실패는 로그에도 남지 않습니다**
> (PR #133 리뷰, 신호정).

> 03:17 인 것은 정각을 피하려는 것뿐입니다. UTC 18:00(KST 03:00)에 도는 디스크 스냅샷
> 정책(`adcraft-daily-snap`)과 겹치지 않게 두었습니다.

#### 왜 이렇게 뜨는가

- **`cp` 로 뜨지 않습니다.** 살아 있는 SQLite 파일을 그대로 복사하면 쓰기가 걸린 순간의 찢어진
  사본이 나올 수 있습니다. `VACUUM INTO`는 SQLite 가 스스로 일관된 시점의 사본을 쓰는 명령이라
  스택을 내리지 않고도 복원 가능한 파일이 나옵니다.
- **사본은 볼륨 밖으로 곧장 씁니다.** 백업 디렉토리를 컨테이너에 `/backup`으로 붙이고
  `VACUUM INTO`가 거기에 씁니다. `/data`에 만들면 그것이 곧 `adgen-state` 볼륨, 즉 백업
  대상이라 다음 백업이 지난 백업을 품고 그다음은 그것을 품습니다.
- **뜬 직후 `chmod 640`으로 좁힙니다.** 파일 안에 `users.password_hash`와 세션이 통째로
  들어 있기 때문입니다. 스크립트 앞의 `umask 077`로는 안 되는 이유는, 파일을 만드는 것이
  호스트 셸이 아니라 컨테이너 프로세스여서 umask 를 물려받지 않기 때문입니다(0644 로
  떨어집니다). 기본 ACL 이 걸린 디렉토리에서는 umask 가 무시되므로 디렉토리에도 효력이
  없습니다 (PR #133 리뷰에서 신호정 실측).
- **0600이 아니라 0640인 것은 의도입니다.** cron 은 한 사람의 crontab 에 걸리므로 0600 이면
  **그 사람만 복원할 수 있습니다.** 장애가 났을 때 VM 에 붙은 사람이 그 사람이라는 보장이
  없고, `/srv/adcraft`를 공용 경로로 세운 이유가 바로 "배포는 한 사람의 자산이 아니다"
  입니다(위 "배포 체크아웃은 `/srv/adcraft/app`" 절). setgid 덕에 파일 그룹이 `adcraft`로
  붙으므로 그룹 읽기 하나면 팀원이 복원할 수 있고, 그 밖의 사용자는 여전히 못 읽습니다
  (PR #133 리뷰, 신호정).
- **뜬 직후 열어 봅니다.** `integrity_check`와 계정 건수를 확인합니다 -- 뜨는 것과 복원 가능한
  것은 다른 주장이고, 확인하지 않은 백업은 없는 백업과 값이 같습니다.
- **이미지 파일은 들어 있지 않습니다.** 상태 파일만입니다. 사진은 24시간, 결과는 7일이면
  어차피 사라지므로(세션_보관_정책 2절) 백업이 그 기간을 우회하게 됩니다. 근거와 잃는 것:
  [ADR-0018](../docs/adr/0018-백업_대상은_상태_파일뿐입니다.md). 시연에 쓸 산출물은 보존
  기간과 무관하게 따로 내려받으세요 - 만료 후 복구 경로는 없습니다.

#### 복원할 때

- ⚠️ **복원은 스택을 잠깐 내립니다.** 살아 있는 프로세스가 열어 둔 파일을 갈아치우면 그 프로세스는
  옛 파일을 계속 들고 있습니다. 볼륨은 건드리지 않으므로 이미지는 그대로입니다.
- ⚠️ **되돌리기 전에 지금 상태를 먼저 뜹니다.** 복원이 틀린 선택이었을 때 돌아올 자리가 필요합니다.
- ⚠️ **복원 중에는 오래된 백업을 정리하지 않습니다.** 사전 백업이 하나 늘어난 상태에서 세면
  가장 오래된 하나가 사라지는데, 그것이 방금 지정한 복원 원본일 수 있습니다. 삭제는 스택을
  내리기 전에 일어나므로 **원본이 사라진 채 서비스가 내려갑니다** (PR #133 리뷰, 재현됨).
- ⚠️ **볼륨에 파일을 넣을 때 `cp` 도 bind mount 도 쓰지 않습니다.** 파일을 stdin 으로
  흘려보냅니다 - 호스트가 읽고 컨테이너가 쓰므로 양쪽 다 자기 것만 만지고 소유권이 그대로
  유지됩니다. `cp` 는 대상을 지우고 새로 만들어 root 소유로 남기고(다음 기동이
  `attempt to write a readonly database` 로 죽습니다), bind mount 는 좁혀 둔 백업(0640)을
  컨테이너가 읽지 못합니다 - 컨테이너 사용자는 그 파일의 소유자도 그룹 구성원도 아닙니다.
  둘 다 **복원은 성공한 것처럼 보이고 스택만 안 뜹니다** (2026-08-19 실측).
- **스택이 죽어 있어도 백업과 복원이 됩니다.** 일회용 컨테이너(`compose run`)로 돌기 때문이며,
  목록을 보고 싶은 때와 복원하고 싶은 때가 대개 그런 때입니다.
- ⚠️ **백업을 못 읽으면 그 사실을 그대로 말합니다.** `sqlite3`는 권한 문제에도
  `unable to open database file`을 내서 **깨진 백업과 구별되지 않습니다.** 장애 중에 그
  메시지를 보면 그다음으로 오래된 백업을 시도하게 되고 전부 같은 이유로 실패하므로, 백업
  전체가 깨진 것으로 오진하게 됩니다. 그래서 `verify`가 열기 전에 읽기 권한을 먼저 보고
  `ls -l` 결과를 함께 찍습니다 (PR #133 리뷰, 신호정).

2026-08-19 에 로컬 스택으로 백업과 복원을 모두 확인했습니다: 백업 시점 이후에 만든 세션이
복원 뒤에 사라지고, 스택이 healthy 로 돌아오며 로그인이 됩니다.

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
| 2026-08-12 | **8100 을 여는 방화벽 규칙** (확인자: 임동규) | **0건.** `--filter="allowed[].ports~8100"` 조회 결과 없음. ingress 는 default-deny 이므로 규칙이 없으면 닫힌 상태입니다 |
| 2026-08-19 | **443 이 밖에서 닿는지** (확인자: 임동규) | **닿습니다.** 연결 거부(refused)이지 타임아웃이 아니므로 방화벽은 통과하고 듣는 쪽만 없는 상태입니다. HTTPS 용 규칙을 새로 만들 필요가 없습니다 |
| 2026-08-12 | 방화벽 규칙의 적용 범위 (확인자: 임동규) | **우리만의 네트워크가 아닙니다.** 아래 "방화벽은 우리 통제 밖입니다" 참고 |

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

#### 방화벽은 우리 통제 밖입니다 (2026-08-12 확인, 임동규)

VPC 는 **학원이 여러 팀에 함께 배정한 `default` 네트워크**입니다. 방화벽 규칙 목록에 우리가
만들지 않은 규칙이 30건 넘게 있고, 태그가 `admaster-frontend` · `jupyterhub` ·
`torchserve-server` 처럼 다른 팀 것입니다.

문제는 **타깃 태그가 없는 규칙**입니다. GCP 에서 태그가 없는 규칙은 그 네트워크의 **모든
인스턴스**에 적용되므로 우리 VM 에도 걸립니다. 22번이 밖에서 열려 있는 것이 그 증거입니다
(`default-allow-ssh`, 태그 없음, `0.0.0.0/0`).

여기서 나오는 결론이 둘입니다.

- **80 과 443 모두 방화벽 규칙을 새로 만들 필요가 없습니다.** 태그 없는 규칙이 이미 열어
  두고 있습니다. 443 은 2026-08-19 에 밖에서 확인했습니다 -- **연결이 거부(refused)되었지
  타임아웃이 아닙니다.** 이 구분이 판정의 근거입니다: 차단된 포트는 패킷을 조용히 버려
  타임아웃이 나고, 거부는 패킷이 VM 까지 닿아 듣는 프로세스가 없다는 뜻입니다.
  즉 규칙은 이미 있고 프록시만 올리면 됩니다.

- **8000 이 열려 있다는 사실 자체는 그대로입니다.** `allow-backend`(tcp:8000) 와
  `allow-ai-services`(tcp:3000,5432,8000,8890,8891,8892) 가 태그 없이 열려 있고 우리는 그
  규칙을 지울 수 없습니다. **그래서 compose 의 `127.0.0.1:8000:8000` 바인딩이 방어선입니다**
  (ADR-0016) -- `127.0.0.1:` 접두어를 지우면 그 순간 평문 로그인 창구가 인터넷에 공개됩니다.
  ai-engine 의 8100 과 **같은 종류의 한 줄**이며, 둘 다 diff 에서 눈에 잘 띄지 않습니다.
- **⚠️ 태그 없이 열려 있는 포트에 `0.0.0.0` 으로 바인딩하지 마세요.** 2026-08-12 기준
  `3000 · 5432 · 8000 · 8003 · 8501 · 8888 · 8890~8893 · 3389` 입니다. 여기에 붙이는 순간
  인터넷에 공개됩니다. Jupyter 를 `--ip=0.0.0.0` 으로 띄우지 말라는 규칙(사용 가이드 4-e절)이
  같은 이유입니다.

**그래서 ai-engine 의 `127.0.0.1:8100` 바인딩이 우리 손에 있는 유일한 방어선입니다.** 지금은
8100 을 여는 규칙이 없지만, 우리가 만들지 않은 규칙이 언제든 늘어날 수 있고 우리는 그것을 막을
수단이 없습니다. compose 의 `ports:` 한 줄을 `"8100:8100"` 으로 바꾸는 변경은 이 방어선을
없애는 것입니다.

그 한 줄은 diff 에서 눈에 잘 띄지 않으므로 검사를 붙였습니다 —
`.github/workflows/docker-build.yml` 의 **"ai-engine이 루프백에만 묶여 있는지 확인"** 스텝이
`docker compose config` 결과를 읽어 루프백 밖 바인딩이면 실패합니다. 원본 YAML 이 아니라 `config`
출력을 보는 이유는 `${BIND:-0.0.0.0}:8100:8100` 같은 치환 우회를 잡기 위해서입니다.

⚠️ **이 검사는 머지를 막지 못합니다.** `docker-build.yml` 은 `paths:` 필터가 걸려 있어 required
status check 로 지정할 수 없습니다(그 조합은 해당 경로 변경이 없는 PR 을 영구히 "Expected" 로
막습니다 — 이 문서 위쪽과 `ci.yml` 머리말의 같은 함정). 즉 빨간 X 를 남길 뿐이며, **리뷰를
대체하지 않습니다.**

이 절의 요약과 거기서 나오는 제약은
[ADR-0011](../docs/adr/0011-배포_환경_스펙과_권한_경계.md)의 "생기는 제약" 9번에 있습니다.

#### 배포 자동화는 서비스 계정 키를 쓸 수 없습니다

`iam.disableServiceAccountKeyCreation`이 조직 수준에서 적용되어 **SA JSON 키를 발급할 수
없습니다.** 따라서:

- GitHub Actions에서 SA 키로 VM에 배포하는 경로는 **성립하지 않습니다.** 계획에 넣지 마세요.
- 배포는 SSH 접속 후 `git pull` + `docker compose up` 수동 경로입니다. 그 절차는
  `scripts/deploy-vm.sh`에 고정했습니다 — 위 "배포 실행 절차" 참고.
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
