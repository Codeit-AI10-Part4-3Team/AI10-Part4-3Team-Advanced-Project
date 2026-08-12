# GCP VM 사용 가이드

브라우저의 웹 SSH 밖에서 배포용 GCP VM에 접근하는 방법을 다루는 문서입니다. 내 PC의 터미널,
에디터, 파일 전송 도구로 VM을 쓰려는 사람이 읽습니다.

| 목적 | 문서 |
|---|---|
| **VM에 접근하는 방법** (이 문서) | 여기 |
| VM 스펙, 권한 실측, 프로비저닝 재현 절차 | [infra/README.md](../../infra/README.md) |
| 스펙과 권한을 그대로 받기로 한 결정의 배경 | [ADR-0011](../adr/0011-배포_환경_스펙과_권한_경계.md) |
| 내 PC 개발 환경 맞추기 | [환경_세팅_가이드.md](환경_세팅_가이드.md) |
| 결과물 보존 기간 | [세션_보관_정책.md](../기술문서/세션_보관_정책.md) |

스펙과 권한 실측값은 여기에 복제하지 않습니다. 값이 두 곳에 있으면 한쪽이 반드시 낡습니다.

## 1. 접근 경로가 SSH 하나뿐인 이유

IAP TCP forwarding을 쓰려고 실제로 시도했지만 커스텀 역할에 `iap.tunnelInstances.accessViaIAP`가
없어서(`4033: not authorized`) 터널이 성립하지 않았고, 그 권한은 우리가 부여할 수 없습니다.
그래서 **외부 IP + SSH 22번 직결이 유일한 원격 경로**이며, 22번이 `0.0.0.0/0`으로 열려 있는 것은
되돌린 결과로 남은 **의도된 상태**입니다. 경위는 [infra/README.md](../../infra/README.md)의
"SSH 접근 경로" 절이 정본입니다.

여기서 따라오는 규칙이 두 개 있습니다.

- **22번을 잠그지 마세요.** 잠그면 남는 복구 수단이 직렬 콘솔 하나뿐입니다.
- **새 포트를 열지 마세요.** 외부에 노출하는 포트는 backend `8000` 하나이고, 그 밖에 필요한
  것은 전부 4-e절의 포트 포워딩으로 해결합니다. ai-engine `8100`은 내부 계약 경로에 인증이
  없으므로 어떤 이유로도 열지 않습니다.

열린 22번을 받아들일 수 있는 이유는 GCP 리눅스 이미지가 **비밀번호 인증을 꺼 둔 상태**로
제공되기 때문입니다. 키가 없으면 들어올 수 없으므로 무차별 대입이 성립하지 않습니다.

## 2. 사전 준비

### 2-a. gcloud CLI 설치와 인증

```bash
gcloud auth login
gcloud config set project <프로젝트ID>       # 콘솔에서 확인합니다
gcloud config set compute/zone us-central1-c
gcloud compute instances list                # 인스턴스 이름과 상태 확인
```

마지막 줄이 인스턴스를 보여주면 준비가 끝난 것입니다. 여기서 실패하면 접속 문제가 아니라
계정 권한 문제이므로 8절 대신 팀에 문의하세요.

### 2-b. 저장소에 적지 않는 값

**외부 IP 주소와 프로젝트 ID는 저장소에 적지 않습니다.** 이 저장소는 public입니다. 값이 필요하면
리소스 이름(`ai10-part4-team3-ip`)으로 콘솔이나 `gcloud`에서 조회하세요. 개인 PC의
`~/.ssh/config`에 적어 두는 것은 괜찮습니다. 그 파일은 저장소 밖에 있습니다.

SSH 개인키도 같습니다. 저장소 안으로 복사하지 마세요. gitleaks의 pre-commit 훅과 CI 스캔이
잡지만, 잡히기 전에 이미 로컬에 있는 상태가 됩니다.

## 3. 아래 명령에서 쓰는 변수

이 문서의 예시는 아래 두 변수를 씁니다. 셸에 미리 넣어 두면 그대로 복사해 쓸 수 있습니다.

```bash
VM=<인스턴스명>
ZONE=$(gcloud compute instances list --filter="name=$VM" --format="value(zone)")
```

## 4. 접속 방법

### 4-a. gcloud compute ssh (처음 한 번은 이걸로)

```bash
gcloud compute ssh $VM --zone=$ZONE
```

키가 없으면 `~/.ssh/google_compute_engine`을 만들고 **공개키를 프로젝트 메타데이터에 자동으로
등록**합니다(실측 확인). 팀원이 처음 접속할 때 이 경로를 쓰면 5절의 수동 등록이 필요 없습니다.

`--tunnel-through-iap`는 **쓰지 마세요.** 1절의 이유로 항상 실패합니다.

### 4-b. 표준 SSH 클라이언트

한 번 접속에 성공했다면 그 뒤로는 일반 `ssh`로 붙는 편이 빠르고, 에디터와 파일 전송 도구가
전부 이 경로를 씁니다.

```bash
gcloud compute config-ssh        # ~/.ssh/config 에 호스트 항목을 자동 생성합니다
ssh <VM>.<zone>.<프로젝트ID>      # 생성된 별칭
```

별칭이 길어서 불편하면 `~/.ssh/config`에 직접 씁니다.

```
Host adcraft-vm
  HostName <고정 외부 IP>
  User <VM 계정명>
  IdentityFile ~/.ssh/google_compute_engine
  ServerAliveInterval 60
  ServerAliveCountMax 3
```

`ServerAliveInterval`을 넣는 이유는 유휴 연결이 중간 장비에서 끊길 때 클라이언트가 그것을
모르고 멈춰 있는 상황을 막기 위해서입니다.

Windows는 OpenSSH 클라이언트가 기본 포함되어 있으므로 PowerShell에서 같은 명령이 동작합니다.
PuTTY를 쓸 경우 키 형식이 달라 `puttygen`으로 변환해야 합니다.

### 4-c. VS Code Remote-SSH

4-b의 호스트 항목이 있으면 확장에서 그대로 잡힙니다. Remote-SSH로 접속한 뒤 VM 위의 폴더를
열면 편집, 터미널, 디버깅이 전부 VM에서 돌고 화면만 로컬에 옵니다.

- 첫 접속 때 VM에 `~/.vscode-server`가 설치됩니다. **디스크를 수백 MB 쓰므로** 7-b절의
  디스크 여유를 먼저 확인하세요. 디스크가 가득 차면 설치가 조용히 실패하고 연결이 계속
  재시도만 반복합니다.
- 확장은 원격 쪽에 따로 설치됩니다. Python, Jupyter 확장을 원격에서 다시 설치해야 합니다.

### 4-d. 파일 주고받기

```bash
gcloud compute scp <로컬파일> $VM:<원격경로> --zone=$ZONE       # gcloud 경로
scp <로컬파일> adcraft-vm:<원격경로>                             # 4-b 별칭 사용
rsync -avz --progress <로컬디렉토리>/ adcraft-vm:<원격경로>/     # 큰 폴더, 재개 가능
```

큰 데이터는 `rsync`를 쓰세요. `scp`는 중단되면 처음부터 다시 받습니다.

**sshfs로 로컬에 마운트하는 구성은 권하지 않습니다.** 편집은 되지만 학습 데이터 입출력이
네트워크를 타서 크게 느려집니다(높은 신뢰). 편집은 Remote-SSH로 하고, 대용량 입출력은 VM
안에서 끝내는 것이 맞습니다.

### 4-e. 포트 포워딩 (방화벽을 건드리지 않는 방법)

VM에서 도는 웹 UI를 내 브라우저에서 보려면 포트를 여는 것이 아니라 SSH 터널을 씁니다.

```bash
ssh -N -L 8888:127.0.0.1:8888 adcraft-vm     # Jupyter
ssh -N -L 6006:127.0.0.1:6006 adcraft-vm     # TensorBoard
ssh -N -L 8100:127.0.0.1:8100 adcraft-vm     # ai-engine 을 열지 않고 확인할 때
```

서버 쪽은 반드시 루프백에만 바인딩합니다. `jupyter lab --ip=127.0.0.1`이 그 예이고,
`--ip=0.0.0.0`은 방화벽이 막아 주기를 기대하는 구성이라 쓰지 않습니다. 토큰 하나가 새면 그것이
곧 이 VM의 셸이고, 이 VM은 삭제 보호가 걸린 학원 결제 자원입니다.

### 4-f. 장시간 작업은 tmux 안에서

SSH 연결이 끊기면 그 세션에서 돌던 프로세스는 함께 죽습니다. 학습이나 배치 작업은 반드시
분리 가능한 세션 안에서 실행하세요.

```bash
tmux new -s train        # 새 세션
# Ctrl-b 그다음 d 로 분리
tmux attach -t train     # 재접속 후 붙기
```

`nohup`도 가능하지만 진행 화면을 다시 볼 수 없어 학습에는 불편합니다.

## 5. 팀원에게 접근 권한 주기

OS Login은 **꺼져 있습니다.** 필요한 IAM 역할을 우리가 부여할 수 없어서 켜면 오히려 전원이
SSH에서 잠깁니다(ADR-0011의 프로비저닝 표). 따라서 접근 제어는 인스턴스 메타데이터의
`ssh-keys` 하나로만 합니다.

**권장 경로는 팀원 각자가 `gcloud compute ssh`를 한 번 실행하는 것입니다**(4-a절). 키가 자동
등록되므로 아래 수동 절차가 필요 없습니다. 다만 그 계정에도 `compute.instances.setMetadata`가
있어야 하므로, 한 명으로 먼저 확인하고 결과를 [infra/README.md](../../infra/README.md)의
권한 표에 남기세요.

자동 등록이 안 되는 계정은 수동으로 병합합니다.

```bash
gcloud compute instances describe $VM --zone=$ZONE \
  --format="value(metadata.items.ssh-keys)" > keys.txt
# keys.txt 가 비어 있지 않은지 눈으로 확인한 뒤, 끝에 아래 형식으로 한 줄씩 추가합니다.
#   <VM 계정명>:ssh-ed25519 AAAA... <메모>
gcloud compute instances add-metadata $VM --zone=$ZONE --metadata-from-file ssh-keys=keys.txt
```

**`add-metadata`는 `ssh-keys` 값을 통째로 교체합니다.** 기존 값을 읽지 않고 새 키만 넣으면
본인을 포함한 전원이 잠기고, 남는 복구 수단은 직렬 콘솔뿐입니다. 반드시 읽고 합치세요.

콜론 앞의 계정명이 그대로 로그인 사용자명이 됩니다. 로컬 사용자명과 다르면 `ssh`에 `-l`이나
`User` 항목으로 명시해야 합니다.

주의: 콘솔 보안 화면의 **"프로젝트 차원 SSH 키 차단"을 켜지 마세요.** `gcloud compute ssh`가
등록한 키가 프로젝트 메타데이터에 있으므로, 차단하면 그 키들이 한꺼번에 무시됩니다.

## 6. 공용 작업 폴더

여러 사람이 같은 폴더를 쓸 때는 홈 디렉토리가 아니라 공용 경로를 그룹 소유로 만듭니다.

```bash
sudo groupadd -f adcraft
sudo usermod -aG adcraft <계정명>              # 각자 재로그인해야 반영됩니다
sudo mkdir -p /srv/adcraft/exp
sudo chgrp -R adcraft /srv/adcraft/exp
sudo chmod -R 2770 /srv/adcraft/exp            # setgid: 새 파일이 그룹을 상속합니다
sudo setfacl -R -d -m g::rwx /srv/adcraft/exp  # 기본 ACL: umask 가 그룹 쓰기를 지우는 것을 막습니다
```

setgid와 기본 ACL을 빠뜨리면 각자 만든 파일의 그룹과 퍼미션이 갈려서 **서로의 산출물을 지우지도
덮지도 못하는 상태**가 며칠 안에 생깁니다. 그때 고치려면 이미 쌓인 파일 전부를 다시
`chown` 해야 하므로 처음에 걸어 두는 편이 쌉니다.

## 7. 접속한 다음에 지켜야 할 것

### 7-a. GPU는 한 장입니다

학습(`training/`)과 추론(`ai-engine`)이 동시에 VRAM을 요구하면 둘 다 OOM으로 죽습니다.
가용 VRAM은 22.5GB이고 이 값은 상향할 수 없습니다.

- 무거운 작업을 시작하기 전에 `nvidia-smi`로 누가 쓰고 있는지 확인합니다.
- 장시간 학습은 팀에 먼저 알립니다. 시간 분할 규칙은 팀 합의 사항이며
  [착수_체크리스트.md](착수_체크리스트.md) 5-a절에 남아 있는 항목입니다.
- 프로세스 단위 VRAM 상한은 PyTorch의 `torch.cuda.set_per_process_memory_fraction`으로
  부분적으로만 걸립니다(추정, 할당자 밖에서 잡는 메모리는 포함되지 않습니다).

### 7-b. 디스크 여유가 61GB뿐입니다

부팅 디스크 100GB가 상한이고 확장에도 권한이 필요합니다. base 모델 가중치, Docker 이미지,
학습 체크포인트, 7일치 결과 이미지가 전부 이 안에 들어갑니다.

```bash
df -h /                      # 남은 용량
du -sh /srv/adcraft/exp/*    # 무엇이 먹고 있는지
docker system df             # 이미지와 빌드 캐시
```

컨테이너 이미지와 빌드 캐시가 조용히 수십 GB를 먹는 것이 가장 흔한 경우입니다.
`docker system prune`으로 정리하되, 지금 쓰는 이미지를 지우지 않도록 출력 먼저 확인하세요.

### 7-c. 데이터 취급

이 VM의 부팅 디스크에는 스냅샷이 걸려 있고 보존 기간은 7일입니다. 지운 파일이 최대 7일 더
스냅샷 안에 남는다는 뜻입니다.

- 권리 범위가 확인되지 않은 브랜드 이미지나 고객 데이터를 개인 작업 폴더에 올리지 마세요.
  학습 데이터의 권리 대장은 `training/data/README.md`입니다.
- 결과 이미지, 브리프, 시안의 보존 기간은
  [세션_보관_정책.md](../기술문서/세션_보관_정책.md) 2절이 정합니다.
- 시연과 발표에 쓸 산출물은 **미리 로컬로 내려받아 두세요.** 크레딧 잔여량이 우리 콘솔에서
  보이지 않아 예고 없이 멈출 수 있습니다.

### 7-d. 서비스 스택을 건드릴 때

배포는 SSH 접속 후 `git pull`과 `docker compose up`의 수동 경로입니다. 서비스 계정 키 발급이
조직 정책으로 금지되어 GitHub Actions 자동 배포가 성립하지 않기 때문입니다(ADR-0011).
compose 파일과 절차는 [infra/README.md](../../infra/README.md)를 따릅니다.

`docker` 명령이 `permission denied`로 거부되면 그룹 반영이 안 된 것입니다.
`sudo usermod -aG docker $USER` 후 **재로그인**해야 적용됩니다.

## 8. 접속이 안 될 때

| 증상 | 원인과 조치 |
|---|---|
| `Permission denied (publickey)` | 키가 메타데이터에 없거나 사용자명이 다릅니다. `ssh -v`로 어떤 키를 보냈는지 확인하고, 5절의 `ssh-keys` 값에서 콜론 앞 계정명과 로그인 사용자명이 같은지 봅니다 |
| `Connection timed out` | 방화벽 규칙이 바뀌었거나 VM이 정지했습니다. `gcloud compute instances list`로 상태를, `gcloud compute firewall-rules list`로 22번 규칙을 확인합니다 |
| `4033: not authorized` | `--tunnel-through-iap`를 쓴 경우입니다. 1절의 이유로 항상 실패하므로 옵션을 빼세요 |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | 같은 IP에 다른 호스트가 붙은 경우입니다. `ssh-keygen -R <IP>` 후 재접속합니다 |
| 접속은 되는데 VS Code가 계속 재연결 | 디스크가 가득 차 `~/.vscode-server` 설치가 실패한 경우가 많습니다. 4-a절 방식으로 붙어 `df -h /`를 확인합니다 |
| 유휴 상태에서 자꾸 끊김 | `~/.ssh/config`에 `ServerAliveInterval 60`을 넣습니다 (4-b절) |
| 전원이 SSH로 못 들어감 | 방화벽이나 메타데이터를 잘못 건드린 경우입니다. 아래 직렬 콘솔로 복구합니다 |

직렬 콘솔은 마지막 복구 수단이고, `compute.instances.setMetadata` 권한이 있어 실제로 쓸 수
있는 것이 확인되어 있습니다.

```bash
gcloud compute instances add-metadata $VM --zone=$ZONE --metadata=serial-port-enable=TRUE
gcloud compute connect-to-serial-port $VM --zone=$ZONE
```

## 9. 하지 말 것

이유 없이 금지된 항목은 하나도 없습니다. 각 항목의 근거는 괄호 안 문서에 있습니다.

- **SSH 22번의 소스 범위를 좁히지 않습니다** (IAP 터널 권한 없음, infra/README.md)
- **OS Login을 켜지 않습니다** (필요한 IAM을 부여할 수 없어 전원이 잠깁니다, ADR-0011)
- **"프로젝트 차원 SSH 키 차단"을 켜지 않습니다** (5절)
- **`ssh-keys` 메타데이터를 읽지 않고 덮어쓰지 않습니다** (5절)
- **backend 8000 외의 포트를 방화벽에 열지 않습니다.** 필요하면 포트 포워딩입니다 (4-e절)
- **서비스 계정 키를 발급해 반출하려 하지 않습니다** (조직 정책으로 금지, ADR-0011)
- **비용을 이유로 VM을 정지하지 않습니다** (절감 대상이 우리 비용이 아닙니다, ADR-0011)
- **외부 IP와 프로젝트 ID를 저장소에 적지 않습니다** (2-b절)
