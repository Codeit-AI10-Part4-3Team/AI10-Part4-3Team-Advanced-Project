# 템플릿 적용·운용 가이드 (TEMPLATE_GUIDE)

`ai-team-project-template`으로 새 프로젝트를 시작하는 절차, 반드시 알아야 할 주의사항, 운용 방법을
다룹니다. **이 문서는 템플릿 전용**이므로, 초기화가 끝난 프로젝트에서는 지워도 됩니다.

## 1. 대원칙: 템플릿은 "파일"만 복사한다

GitHub 템플릿 리포는 **저장소 파일만 복사**하고 **리포 설정은 전혀 복사하지 않습니다.**
따라서 새 리포마다 아래 두 트랙을 모두 처리해야 합니다.

| 트랙 | 자동으로 따라옴 (파일) | 매번 재적용 필요 (설정) |
|---|---|---|
| 내용 | 워크플로, 이슈/PR/Discussion 템플릿, `labels.yml`, pre-commit, pyproject, 코드 골격, 문서 | 브랜치 보호, 라벨 실체, 머지 전략, Secrets/Variables, Discussions 활성화·카테고리, Code security, 협업자 권한 |
| 처리 | "Use this template" 클릭 | `scripts/setup-github.sh` + 소량의 수동 설정 (§3) |

## 2. 새 프로젝트 시작 절차

```bash
# ① GitHub 웹: 템플릿 리포 → "Use this template" → "Create a new repository"
#    (Include all branches는 체크하지 않음 — main만 복사)

# ② clone 후 초기화 — 이름 치환의 원스톱 처리
git clone https://github.com/<owner>/<repo>.git && cd <repo>
python3 scripts/init_template.py --name my-service --owner <owner> --repo <repo>
#    치환: my-ai-project→배포판 이름, MYAPP_→환경변수 접두어,
#          {{GITHUB_OWNER}}/{{GITHUB_REPO}}→URL
#    교체: README.md ← README.project.md / 삭제: 스크립트 자신

# ③ 개발 환경 구성
bash scripts/setup-dev.sh          # Windows: powershell -File scripts\setup-dev.ps1
python3 -m venv .venv && source .venv/bin/activate
pip install -e "./apps/backend[dev]" -e "./apps/ai-engine[dev]"
pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push

# ④ 관통 확인 후 초기화 결과 커밋·푸시
bash scripts/run-tests.sh
git add -A && git commit -m "chore: init from ai-team-project-template" && git push

# ⑤ 리포 설정 재적용 (admin 권한 + gh 인증 필요)
gh auth login
bash scripts/setup-github.sh <owner>/<repo>          # 팀: PR 승인 1 + required checks
bash scripts/setup-github.sh <owner>/<repo> --solo   # 1인: 승인 요구 제외
```

## 3. 초기화 직후 손봐야 할 파일 (순서대로)

`init_template.py`는 **이름만** 바꿉니다. 내용은 사람이 채워야 합니다.

- [ ] **`CODEOWNERS`** — 예시 계정(`@teammate-*`)을 실제 GitHub ID로. 모든 경로에 오너 **2명 이상**
      (작성자 본인 승인은 카운트되지 않아, 단독 오너 경로는 그 사람의 PR이 영구 블록됩니다).
      채우기 전까지 `setup-github.sh`가 코드오너 요구를 자동으로 꺼 둡니다.
- [ ] **`AGENTS.md`** — `TODO` 절(프로젝트 개요·설계 제약·지표·팀). 여기가 비어 있으면 에이전트는
      프로젝트를 모른 채 코드를 씁니다.
- [ ] **`docs/공통_가이드/개발자_가이드.md`** — 1·3·4·5절
- [ ] **`docs/역할_가이드/`·`docs/역할_일정/`** — 역할 파일을 **번호 1:1로** 생성
- [ ] **`packages/contracts/openapi.yaml`** — 실제 계약으로. 스펙이 먼저, 구현이 다음입니다
- [ ] **`apps/ai-engine/src/ai_engine/fixtures/corpus.jsonl`** — 실제 코퍼스로 교체 전까지는
      품질 숫자를 보고하지 마세요
- [ ] **`.github/ISSUE_TEMPLATE/*.yml`** — 모듈 드롭다운을 프로젝트 구성으로
- [ ] **`.github/dependabot.yml`** — 프론트엔드 스캐폴딩 후 npm 블록 주석 해제
- [ ] **`infra/.env.example`** — 실제 키 이름으로 (값은 절대 넣지 말 것)
- [ ] **`LICENSE`** — 저작권자를 프로젝트 소유자로 (GitHub의 라이선스 자동 인식이 이 줄을 봅니다)
- [ ] **`docs/adr/0001-monorepo.md`** — 날짜·결정자 기입 (구조를 그대로 쓴다면 그대로 Accepted)
- [ ] `docs/TEMPLATE_GUIDE.md`·`docs/DESIGN_DECISIONS.md` 삭제 (템플릿 전용 문서)

## 4. 수동 설정 체크리스트 (스크립트가 못 하는 것)

- [ ] **Settings → General → Features**: Discussions 활성화
- [ ] **Discussions → 카테고리 `CollaborationLog` 생성** — Discussion 카테고리는 API가 없어 수동
      생성만 가능합니다. 없으면 이슈 config의 협업 일지 링크와 `DISCUSSION_TEMPLATE`이 동작하지 않습니다.
- [ ] **Settings → Code security**: Secret scanning + Push protection 활성화 (public 전용)
- [ ] (팀) Collaborators/Teams 권한 부여 → `CODEOWNERS`의 계정이 write 권한을 갖는지 확인
- [ ] (필요 시) Actions Secrets/Variables 등록

상세와 무료 플랜 제약 매트릭스: [공통_가이드/저장소_운영.md](공통_가이드/저장소_운영.md).

## 5. 주의사항 (함정 모음)

- **required check + `paths:` 필터 조합 금지.** 필터가 걸린 워크플로는 해당 경로 변경이 없는 PR에서
  체크가 **생성되지 않아** 머지가 영원히 `Expected`로 막힙니다. 그래서 `ci.yml`만 필터 없이 돌고,
  나머지 4종은 required가 아닙니다. CI 비용을 줄이려면 `dorny/paths-filter` 같은 **잡 내부** 필터를 쓰세요.
- **required check의 context 이름 = 잡의 `name:`.** 앱을 추가하면 `ci.yml`의 matrix와
  `setup-github.sh`의 `contexts`를 **같은 PR에서** 함께 늘리세요. 매트릭스라 이름이 전개됩니다.
- **앱을 추가할 때 고쳐야 하는 네 곳**: 루트 `pyproject.toml`의 ruff `src`(빠뜨리면 isort가 앱 내부
  import를 서드파티로 보고 CI가 I001로 실패), `ci.yml` matrix, `setup-github.sh` contexts, `CODEOWNERS`.
- **ruff 버전은 세 곳이 한 쌍.** `.pre-commit-config.yaml`의 rev ↔ 두 앱의 dev extra `ruff==`.
  ruff는 0.x라 마이너 업그레이드에서 기본 규칙셋이 넓어지므로, 한쪽만 올리면 같은 코드가 한쪽에서만
  통과합니다. 버전 상향은 "린트 설정 변경"으로 취급해 세 파일을 같은 PR에서 올리세요.
- **gitleaks는 훅 + CI 두 개가 한 쌍.** 훅의 entry가 `--staged` 고정이라 `pre-commit run --all-files`는
  아무것도 검사하지 않습니다. CI의 전체 트리 스캔 스텝을 지우면 훅 미설치자의 키를 막을 수단이 없습니다.
- **mypy·pytest는 앱 디렉토리를 cwd로** 실행해야 설정을 집습니다. 루트에서 `pytest apps/backend`로
  돌리면 testpaths·마커가 적용되지 않습니다.
- **`from src.xxx` import 금지.** src 레이아웃에서 `src.` 접두어는 설치 환경에서 깨지는데 린트가
  못 잡습니다. 리뷰에서 확인하세요.
- **`.gitignore`의 화이트리스트.** git은 무시된 디렉토리 안의 파일을 되살리지 못하므로 커밋 대상
  데이터는 **파일 패턴**으로 예외 처리돼 있습니다. 새 커밋 대상 파일을 도입하면 예외 줄도 추가하세요.
- **노트북 정합성.** 출력이 포함된 채 커밋된 노트북은 nbstripout 필터와 어긋나 영구히 `modified`로
  보입니다. 발견 즉시 stripped 상태로 재커밋하세요.
- **`git pull` autostash 함정.** staged 변경이 있는 채로 pull하면 복원 실패로 작업이 dangling stash로
  빠질 수 있습니다. clean한 트리에서 통합하세요.

## 6. 운용 방법

- **브랜치 전략**: main 직접 push 금지. feature 브랜치 → PR → Squash merge → 브랜치 자동 삭제.
  절차는 [pr-checklist.md](pr-checklist.md).
- **품질 게이트**: CI와 pre-commit이 같은 기준을 봅니다. 로컬 `bash scripts/run-tests.sh`가 통과하면
  CI도 통과하는 구조를 유지하세요 — 둘이 어긋나면 사람들이 훅을 무시하기 시작합니다.
- **라벨**: `.github/labels.yml`이 원천. 바꾸면 `bash scripts/apply-labels.sh <owner>/<repo>`로 동기화
  (PR 템플릿의 '변경 유형'과 짝을 맞출 것).
- **이음매에서 교체**: 스텁을 우회해 옆에 새 경로를 만들지 말고, `Retriever`/`Generator`/`ai_client`
  같은 프로토콜 구현을 갈아끼우세요. 우회하는 순간 스켈레톤이 검증하던 성질이 사라집니다.
- **의존성**: 무거운 라이브러리(LangChain·벡터 DB·torch 계열)는 앱의 optional extra로 분리해
  CI/기본 설치를 가볍게 유지. mypy는 `[[tool.mypy.overrides]]`로 예외 처리.
- **AGENTS.md 갱신**: 아키텍처 규칙·함정·사고 이력이 생길 때마다 기록하세요.
  "왜"가 없는 규칙은 에이전트도 사람도 무시합니다.

## 7. 템플릿 자체의 유지보수

파생 프로젝트에서 발견한 개선점(새 함정, 더 나은 CI 구성, 관례 추가)은 이 템플릿 리포에
역반영하세요. 템플릿은 "가장 최근 프로젝트의 교훈이 축적된 곳"일 때 가치가 있습니다.
단, 이미 생성된 파생 리포에는 자동 전파되지 않으므로 필요 시 수동으로 가져갑니다
(`git remote add template ...` 후 선별 cherry-pick).
