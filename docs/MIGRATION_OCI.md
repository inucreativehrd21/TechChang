# techchang.com — AWS Lightsail → OCI 이전 런북

대상: 이 레포(`inucreativehrd21/TechChang`)로 운영 중인 techchang.com 을 Lightsail(43.203.93.244) 에서 OCI 인스턴스로 옮기는 절차.
이 문서는 **레포 실제 구조**를 기준으로 작성됐다 (2026-09 기준, `main` 36bbdd6).

관련 파일
| 파일 | 역할 |
|---|---|
| [deploy_oci.sh](../deploy_oci.sh) | OCI 서버 초기 구성 + 재배포 (멱등) |
| [scripts/restore_db.sh](../scripts/restore_db.sh) | `backups/db_*.sql.gz` 복원 (복원 전 자동 백업 → 복원 → migrate → 재시작) |
| [scripts/crontab.oci](../scripts/crontab.oci) | OCI 용 crontab (Lightsail 과 동일 경로) |
| [requirements-prod.txt](../requirements-prod.txt) | `requirements.txt` + `mysqlclient` (운영 전용) |
| [.env.example](../.env.example) | `.env` 키 전체 목록 (DB 키 포함으로 갱신) |

---

## A. 레포 탐색 결과 요약

### settings 구조
- `config/settings/__init__.py` = `from .base import *` → `manage.py` / `wsgi.py` / `asgi.py` 의 기본은 **base.py**.
- 라이브 gunicorn 만 systemd 유닛에서 `DJANGO_SETTINGS_MODULE=config.settings.prod` 를 지정. **cron 은 base.py 로 돈다.**
- `base.py` 가 `python-dotenv` 로 `BASE_DIR/.env` 를 로드하고, `prod.py` 는 `from .base import *` 후 다시 `load_dotenv()`.
- `prod.py`: `DEBUG=False` 고정, `DJANGO_SECRET_KEY` 없으면 raise, `ManifestStaticFilesStorage`, HSTS 1년+preload, `SECURE_SSL_REDIRECT`(이번에 `DJANGO_SECURE_SSL_REDIRECT` 환경변수로 토글 가능하게 변경, 기본 true), Secure 쿠키, django-csp.

### DATABASES 위치 → `config/settings/base.py:126-149`
```python
_DB_ENGINE = os.environ.get('DJANGO_DB_ENGINE', 'sqlite3')
if _DB_ENGINE == 'mysql':
    DATABASES = {'default': {'ENGINE': 'django.db.backends.mysql',
        'NAME': DJANGO_DB_NAME(기본 techchang), 'USER': DJANGO_DB_USER(기본 techchang),
        'PASSWORD': DJANGO_DB_PASSWORD, 'HOST': DJANGO_DB_HOST(127.0.0.1), 'PORT': DJANGO_DB_PORT(3306),
        'OPTIONS': {'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"}}}
else:  # SQLite (db.sqlite3)
```
- **`.env` 에 `DJANGO_DB_ENGINE=mysql` 이 없으면 조용히 SQLite 로 뜬다** (빈 사이트). `deploy_oci.sh` 가 이를 강제 검사한다.
- `mysqlclient` 는 `requirements.txt` 에 **없다**(주석에 "현재 SQLite 사용"). Lightsail venv 에 수동 설치된 상태 → OCI 용으로 `requirements-prod.txt` 추가.
- community 앱 테이블은 `db_table='pybo_*'` 로 유지됨 (`pybo_question` 등). 덤프/복원에 영향 없음.

### requirements.txt (Python 3.12, Django 5.2.6)
Django 5.2.6, gunicorn, channels/channels-redis/daphne(설치만, 운영은 WSGI), django-csp 4.0, django-allauth, anthropic, python-dotenv, Pillow, Markdown, bleach, python-magic(libmagic1 필요, 없으면 폴백), requests, google-api-python-client/google-auth(-oauthlib).
- CI(`.github/workflows/ci.yml`)는 Python 3.12 + SQLite. Ubuntu 24.04 기본 python3 = 3.12 → 동일.
- **aarch64 (OCI A1) 빌드 의존**: `mysqlclient` 소스 빌드용 `default-libmysqlclient-dev pkg-config build-essential python3-dev`, Pillow 대비 `libjpeg-dev zlib1g-dev`. `deploy_oci.sh` 2단계가 설치한다.

### `.env` 키 전체 목록 (코드에서 `os.environ` 으로 읽는 키 — 역추출)
| 구분 | 키 | 비고 |
|---|---|---|
| **필수** | `DJANGO_SECRET_KEY` | prod.py 에서 없으면 raise |
| **필수(운영)** | `DJANGO_DB_ENGINE=mysql`, `DJANGO_DB_NAME`, `DJANGO_DB_USER`, `DJANGO_DB_PASSWORD`, `DJANGO_DB_HOST`, `DJANGO_DB_PORT` | base.py DATABASES |
| 필수(사실상) | `DJANGO_ALLOWED_HOSTS` | 기본값에 Lightsail IP 가 하드코딩 → **OCI IP 로 바꿔서 지정** |
| 선택 | `DJANGO_ADMIN_URL` | 기본 `secret-control-panel/` |
| 선택(신규) | `DJANGO_SECURE_SSL_REDIRECT` | 기본 true. IP 검증 시에만 false |
| 이메일 | `DJANGO_EMAIL_BACKEND`, `DJANGO_EMAIL_HOST`, `DJANGO_EMAIL_PORT`, `DJANGO_EMAIL_HOST_USER`, `DJANGO_EMAIL_HOST_PASSWORD`, `DJANGO_EMAIL_USE_TLS`, `DJANGO_EMAIL_USE_SSL`, `DJANGO_EMAIL_TIMEOUT`, `DJANGO_DEFAULT_FROM_EMAIL`, `DJANGO_SERVER_EMAIL`, `DJANGO_ADMIN_EMAIL` | Gmail 앱 비밀번호. `DJANGO_ADMIN_EMAIL` 은 OTP 수신·리포트 기본 수신자 |
| LLM | `ANTHROPIC_API_KEY` | `auto_write_columns`, `auto_write_series`, AI 답변 (`common/services/claude.py`) |
| 카카오 | `KAKAO_REST_API_KEY`, `KAKAO_CLIENT_SECRET` | 카카오 개발자 콘솔의 Redirect URI 는 도메인 기준이라 IP 변경 무관 |
| GitHub | `GITHUB_DISPATCH_TOKEN`, `GITHUB_REPO` | 자동 수정 PR 트리거 (선택) |
| GSC | `GSC_OAUTH_TOKEN`(token.json **절대경로**), `GSC_CREDENTIALS_JSON`, `GSC_SITE_URL` | 방문자 리포트 검색 지표 (선택). **token.json 파일도 같이 옮겨야 함** |
| 게임 | `WORDCHAIN_TIMEOUT`, `WORDCHAIN_USE_DICTIONARY_API`, `KOREAN_DICT_API_KEY` | |
| 보안 | `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW`, `DDOS_THRESHOLD`, `BLOCK_DURATION`, `SUSPICION_SCORE_THRESHOLD`, `PROTECTED_PATH_ATTEMPTS_LIMIT`, `SUSPICIOUS_USER_AGENT_PATTERNS`, `TRUSTED_USER_AGENT_PATTERNS`, `TRUSTED_HEALTHCHECK_PATHS` | 기본값 있음 |
| 기타 | `DEBUG`(base.py 만, 라이브 무시), `SITE_DOMAIN`(마이그레이션 0012 전용), `GUNICORN_LOG_DIR` | |

### management command (`manage.py <cmd>`)
| 앱 | 커맨드 | 용도 / cron |
|---|---|---|
| common | `backup_db` | mysqldump+gzip → `backups/db_<ts>.sql.gz`, `--keep`, `--dest`, `--email` |
| common | `send_log_report` | journalctl(`-u mysite`) 우선, 폴백 `logs/django.log`; nginx `/var/log/nginx/techchang_access.log` 읽음 |
| common | `send_visitor_report` | DB(`DailyVisitor`) + GSC |
| common | `auto_write_columns`, `auto_write_series` | Anthropic API, 봇 계정 `techchang연구팀` (DB 에 있어야 함 → 덤프 복원으로 따라옴) |
| common | `check_email`, `gsc_authorize`(로컬 전용), `seed_emoticons` | |
| community | `initialize_categories`, `setup_album_category`, `update_categories` | 초기화용, 이전 시엔 불필요 |

### 레포 내 서버 설정 파일
| 파일 | 상태 |
|---|---|
| `gunicorn.conf.py` | 사용 중. `bind 127.0.0.1:8000`, workers=cpu*2+1, 로그 `logs/gunicorn_*.log`, `preload_app` |
| `mysite.service` | **stale**: venv 경로가 `projects/mysite/venv`, `User=www-data`, `postgresql.service` 의존. 실서버 유닛과 다를 가능성 큼 → 0단계에서 `systemctl cat mysite` 로 확인. OCI 는 `deploy_oci.sh` 가 생성하는 유닛이 기준 |
| `nginx.conf` | HTTPS 최종형 (444 default_server, HSTS, /static /media alias, robots/favicon). certbot 경로 `/etc/letsencrypt/live/techchang.com/`. `client_max_body_size 10M` (Django 는 20MB) |
| `.github/workflows/` | ci.yml(check+test), auto-fix.yml — 서버와 무관 |

기타: 라이브는 **WSGI(gunicorn) 만** — daphne/ASGI 서비스 없음 → WebSocket(`/ws/…`) 은 현재도 서빙되지 않음. 이전 시 그대로 유지(별도 과제).

---

## 0. Lightsail 사전 확인 (실행 후 결과를 붙여넣기)

```bash
ssh ubuntu@43.203.93.244
cd ~/projects/mysite

# 0-1 코드/파이썬/의존성
git status --short && git log -1 --oneline
python3 --version; ~/venvs/mysite/bin/python3 --version
~/venvs/mysite/bin/pip freeze | grep -iE '^(django|mysqlclient|pymysql|gunicorn|pillow|python-magic)='
cat /etc/os-release | head -2; uname -m; timedatectl | head -3

# 0-2 .env 키 목록(값 가림) + DB 접속 키는 값 그대로(비번 제외)
sed 's/=.*/=***/' .env
grep -E '^DJANGO_DB_(ENGINE|NAME|USER|HOST|PORT)=' .env
grep -E '^(GSC_OAUTH_TOKEN|GSC_CREDENTIALS_JSON)=' .env; ls -la *.json 2>/dev/null   # GSC 토큰 파일 위치

# 0-3 MySQL
mysql --version
sudo mysql -e "SELECT VERSION(); SELECT DEFAULT_CHARACTER_SET_NAME, DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME='techchang';"
sudo mysql -e "SELECT user,host FROM mysql.user WHERE user NOT IN ('mysql.sys','mysql.session','mysql.infoschema','debian-sys-maint');"
sudo mysql -e "SELECT COUNT(*) AS tz_rows FROM mysql.time_zone_name; SHOW VARIABLES LIKE 'skip_name_resolve';"
sudo mysql -e "SELECT table_schema, ROUND(SUM(data_length+index_length)/1024/1024,1) AS mb FROM information_schema.tables WHERE table_schema='techchang';"

# 0-4 서비스/nginx/SSL
systemctl cat mysite
systemctl status mysite --no-pager | head -5
ls -la /etc/nginx/sites-enabled/
sudo cat /etc/nginx/sites-enabled/*
sudo diff /etc/nginx/sites-available/techchang nginx.conf && echo "nginx 설정 = 레포와 동일"
sudo ls /etc/letsencrypt/live/; sudo certbot certificates; systemctl list-timers --no-pager | grep -i certbot

# 0-5 데이터 크기 / 정체 불명 파일
du -sh media backups logs staticfiles
ls -la backups | tail -5
ls -la backup_data.json; head -c 300 backup_data.json; echo; python3 -c "import json;d=json.load(open('backup_data.json'));print(type(d).__name__, len(d), d[0].get('model') if isinstance(d,list) and d else '')"

# 0-6 cron / 방화벽 / 권한
crontab -l
cat /var/log/techchang_report.log | tail -3; ls -la /var/log/techchang_report.log
id ubuntu; ls -ld /home/ubuntu
sudo iptables -L INPUT -n --line-numbers; sudo ufw status

# 0-7 DNS (TTL 확인 — 7단계 전에 낮춰야 함)
dig +noall +answer techchang.com www.techchang.com
```

### 0단계 확인 결과 (2026-09-12 실행)

| 항목 | 확인값 | 이전에 미치는 영향 |
|---|---|---|
| OS / arch / Python | Ubuntu 24.04.3, **x86_64**, Python 3.12.3 (venv 동일) | OCI A1 은 aarch64 → `mysqlclient 2.2.8` 은 소스 빌드 가능성. 스크립트가 빌드 의존성 설치 |
| 의존성 | Django 5.2.6, gunicorn 21.2.0, **mysqlclient 2.2.8**, pillow 10.4.0, python-magic 0.4.27 | `requirements-prod.txt` 로 동일 구성 |
| 타임존 | KST | 스크립트 기본 Asia/Seoul 과 일치 |
| MySQL | 8.0.46, DB `techchang` **utf8mb4_unicode_ci**, 사용자 `techchang@localhost` 만, `skip_name_resolve=OFF`, 데이터 15.3MB | 스크립트 기본 `DB_COLLATION` 과 일치. **tz 테이블 0행** — Lightsail 도 미적재(현재 `__date` 류 조회가 조용히 빈 결과일 수 있음). OCI 에서 적재하는 건 개선이지 회귀 아님 |
| systemd `mysite` | 레포 `mysite.service` 그대로 설치됨: **`User=www-data`** (ExecStart 부분은 출력 잘림 — 아래 추가 확인) | 이전 후 계정 정책 결정 필요 (아래) |
| nginx | `/etc/nginx/sites-available/techchang` = 레포 `nginx.conf` 와 동일 (육안 대조) | 8단계 최종형 = 레포 `nginx.conf` |
| certbot | `techchang.com`(ECDSA, ~2026-11-14) + **`tc.o-r.kr`(만료, 옛 도메인)**, `certbot.timer` 활성 | 이관 시 `tc.o-r.kr` 제거하지 않으면 renew 가 매번 실패 로그 |
| `.env` | DB 키 6개 있음. `GSC_CREDENTIALS_JSON=/home/ubuntu/secrets/gsc_key.json`, `GSC_OAUTH_TOKEN=/home/ubuntu/secrets/token.json` (**프로젝트 밖**). 미사용 잔재 `DATABASE_URL`, `SECRET_KEY` | **`~/secrets/` 디렉터리도 전송** (4단계). 잔재 키는 무해 |
| 데이터 | media 37M, backups 24M, logs 73M, staticfiles 17M | rsync 수 분 |
| `backup_data.json` | 2026-02-28, `dumpdata` JSON 8591 객체(`common.kakaouser`…) — SQLite→MySQL 전환일 산출물 확정 | **`loaddata` 금지**. 로컬 보관 후 서버에서 제외 |
| cron | ubuntu crontab 10줄 = `scripts/crontab.oci` 와 동일(시리즈 게이트 `%V` 홀수 주 포함) | 그대로 이관 가능 |
| **cron 실행 주체 의심** | `backups/db_*.sql.gz` 와 `/var/log/techchang_report.log` 가 **root:root 644** | ubuntu crontab 의 `>> /var/log/techchang_report.log` 는 권한상 실패 → 실제 동작 중인 건 **root crontab 복사본**일 가능성. `sudo crontab -l` 로 확인(아래) |
| 권한 | ubuntu ∈ adm, www-data, sudo (systemd-journal 아님), 홈 755 | OCI 도 동일하게 스크립트가 처리 |
| 방화벽 | iptables INPUT 정책 ACCEPT·규칙 없음, ufw inactive (Lightsail 콘솔 방화벽만) | OCI 는 iptables 규칙 필수 — 스크립트 3단계 |
| DNS | A 43.203.93.244, **TTL 300** | 7단계 전 60 으로 |

**추가 확인 결과 (2026-09-12)**

| 항목 | 확인값 | 의미 |
|---|---|---|
| root crontab | backup_db ×2, send_log_report ×2 **4줄만** | `/var/log/techchang_report.log` 에 쓰는 줄은 root 에서 실행 중 |
| ubuntu crontab | 10줄 전부 | 1~6번(report.log 리다이렉트)은 권한 오류로 **실행 안 됨** → root 것과 겹치는 4줄은 무해하지만, **`send_visitor_report` 2줄은 어느 쪽에도 실행되지 않고 있었음**(주간/월간 방문자 메일이 안 왔다면 이 때문). auto_write 4줄은 `logs/` 에 쓰므로 ubuntu 에서 정상 |
| mysite.service | `User=www-data`, `ExecStart=~/venvs/mysite/bin/gunicorn`(서버에서 수정됨), `WorkingDirectory` 정상 | 레포 파일과 venv 경로만 다름 |
| 프로젝트 디렉터리 | `drwxrwx--- ubuntu www-data`(770), `logs/` ACL(+), `media/` www-data 소유 setgid | nginx 는 그룹으로 접근. 3주체 혼재의 흔적 |
| `logs/gunicorn_access.log` | **75MB, 회전 없음** | gunicorn 은 자체 회전이 없음 → OCI 는 logrotate 등록(스크립트) |
| `~/secrets/*.json` | root 소유 644 | rsync 로 받으면 ubuntu 소유가 됨. 600 으로 |

**계정 정책 — 결정: `ubuntu` 단일 계정** (스크립트 기본값 그대로)
- gunicorn(`User=ubuntu`)·crontab(ubuntu)·수동 작업이 한 계정 → 소유권/ACL/setgid 불필요, 회전 로그 권한 문제 소멸, 방문자 리포트도 정상 실행.
- 프로젝트 디렉터리는 clone 기본값(755)이라 nginx(www-data)는 other 권한으로 static/media 를 읽는다. 홈만 `o+x`(스크립트).
- 유닛 `NoNewPrivileges=true` 로 gunicorn 프로세스가 sudo 승격 불가. `.env` 는 `chmod 600`.
- root crontab 은 만들지 않는다. `/var/log/techchang_report.log` 는 스크립트가 ubuntu 소유로 생성.
- (`SERVICE_USER=www-data` 옵션은 스크립트에 남아 있지만 이 이전에서는 쓰지 않음)

---

## 1. 코드 준비 (로컬)

1. 이 브랜치의 변경을 `main` 에 머지/푸시: `prod.py`(SSL 토글), `.env.example`, `requirements-prod.txt`, `deploy_oci.sh`, `scripts/`, `docs/`.
2. `py manage.py check` 통과 확인 (CI 도 통과).
3. Lightsail 도 `git pull` 해서 동일 커밋으로 맞춘다 (서버 코드 = origin/main 유지). 코드만 바뀌므로 재시작 불필요(prod.py 는 기본값 그대로 true).

---

## 2. OCI 콘솔

1. 인스턴스: Ubuntu 24.04 (Canonical), VM.Standard.A1.Flex 2 OCPU / 12GB, 부트 볼륨 50GB+, SSH 키 등록.
2. **VCN → 서브넷 → 보안 목록(Security List) → Ingress 규칙 추가**
   - Source `0.0.0.0/0`, Protocol TCP, Dest port `80`
   - Source `0.0.0.0/0`, Protocol TCP, Dest port `443`
   - (22 는 기본 있음. 본인 IP 로 제한 권장)
   - NSG(Network Security Group) 를 쓰는 서브넷이면 NSG 에도 동일 규칙.
3. 공인 IP 메모 → 이하 `<OCI_IP>`. (예약(Reserved) 공인 IP 로 만들어야 재생성 시 안 바뀜.)

---

## 3. OCI 서버 구성

```bash
ssh ubuntu@<OCI_IP>
sudo apt-get update && sudo apt-get install -y git
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/inucreativehrd21/TechChang.git mysite
cd mysite
```

`.env` 는 4단계에서 Lightsail 것을 그대로 가져온 뒤 두 줄만 손본다. 먼저 4단계의 `.env` 전송을 하고 돌아와도 되고, 임시로 만들어도 된다. 스크립트는 `.env` 가 없으면 즉시 중단한다.

```bash
# .env 준비 후. 기본값(SERVICE_USER=ubuntu, DB_COLLATION=utf8mb4_unicode_ci, TIMEZONE=Asia/Seoul)이
# 0단계 확인 결과와 일치하므로 옵션 없이 실행
bash deploy_oci.sh
```

스크립트가 하는 일: 타임존 Asia/Seoul → apt(빌드 도구·MySQL·nginx·certbot) → 그룹(adm, systemd-journal) → `chmod o+x /home/ubuntu`(24.04 는 홈이 750 이라 nginx 가 static/media 를 못 읽음) → iptables 80/443 + `netfilter-persistent save` → MySQL 타임존 테이블 + `.env` 값으로 DB/사용자 → venv `~/venvs/mysite` + `requirements-prod.txt` → `check`/`migrate`/`collectstatic` → `mysite.service`(EnvironmentFile=.env) → nginx HTTP 설정 → 재시작 + 로컬 헬스체크.

이 시점엔 DB 가 비어 있다(마이그레이션만 적용). 5단계에서 덤프를 얹는다.

재배포(코드만 갱신)는 앞으로 `git pull && bash deploy_oci.sh --skip-system`.

---

## 4. `.env` / media / backups 전송

**방법 A — 서버→서버 직접 (권장, 로컬 경유 없음)**. OCI 에서 Lightsail 로 ssh 가 되어야 한다: 로컬에서 `ssh -A ubuntu@<OCI_IP>` (에이전트 포워딩) 또는 OCI 의 `~/.ssh/id_ed25519.pub` 을 Lightsail `~/.ssh/authorized_keys` 에 추가.

```bash
# OCI 에서
LS=ubuntu@43.203.93.244
cd ~/projects/mysite
rsync -avz $LS:~/projects/mysite/.env ./.env
rsync -avz --progress $LS:~/projects/mysite/media/   ./media/
rsync -avz --progress $LS:~/projects/mysite/backups/ ./backups/
# GSC 자격 파일: .env 가 /home/ubuntu/secrets/{gsc_key.json,token.json} 절대경로를 가리킴 (프로젝트 밖!)
rsync -avz $LS:~/secrets/ ~/secrets/ && chmod 700 ~/secrets && chmod 600 ~/secrets/*
# backups/ 는 Lightsail 에서 root 소유(644)라 읽기는 되지만, 받은 뒤 ubuntu 소유로 정리
chown -R ubuntu:ubuntu backups media 2>/dev/null || sudo chown -R ubuntu:ubuntu backups media
```
`backup_data.json` 은 옮기지 않는다 (로컬 PC 에 한 부 보관: `scp ubuntu@43.203.93.244:~/projects/mysite/backup_data.json .`).

**방법 B — 로컬 PC 경유** (Windows 는 Git Bash/WSL 에서)
```bash
rsync -avz ubuntu@43.203.93.244:~/projects/mysite/media/ ./media_copy/
rsync -avz ./media_copy/ ubuntu@<OCI_IP>:~/projects/mysite/media/
# .env, backups 도 동일. scp 도 가능.
```

`.env` 수정 (OCI 에서 `nano .env`):
```
DJANGO_ALLOWED_HOSTS=techchang.com,www.techchang.com,<OCI_IP>
DJANGO_SECURE_SSL_REDIRECT=false     # ← 6단계 IP 검증용. 8단계 후 삭제!
```
DB 접속 키(`DJANGO_DB_*`)는 Lightsail 값 그대로 두면 `deploy_oci.sh` 가 같은 이름/비번으로 만들어 준다.

media 권한: `find media -type d -exec chmod 755 {} \; ; find media -type f -exec chmod 644 {} \;` (rsync 가 원본 권한을 유지하니 보통 불필요).

> `.env` 를 받은 뒤 3단계 스크립트를 (다시) 실행한다. 이미 실행했다면 `bash deploy_oci.sh` 재실행 — 멱등이라 안전.

---

## 5. 최신 덤프 복원

```bash
# Lightsail 에서 지금 시점 덤프 (cron 03:00 것보다 최신)
ssh ubuntu@43.203.93.244 'cd ~/projects/mysite && ~/venvs/mysite/bin/python3 manage.py backup_db --keep 7 --dest ~/projects/mysite/backups'
# OCI 에서 받아서 복원
rsync -avz $LS:~/projects/mysite/backups/ ./backups/
bash scripts/restore_db.sh            # 최신 backups/db_*.sql.gz 자동 선택, 확인 프롬프트
```

복원 스크립트는 복원 전 `backups/pre_restore_<ts>.sql.gz` 를 만들고, `mysite` 를 잠시 멈춘 뒤 덤프를 흘려 넣고, `migrate`, 재시작, `auth_user`/`pybo_question` 건수를 출력한다.

확인:
```bash
~/venvs/mysite/bin/python3 manage.py showmigrations --settings=config.settings.prod | grep -c '\[X\]'
mysql -u techchang -p techchang -e "SELECT COUNT(*) FROM auth_user; SELECT MAX(create_date) FROM pybo_question;"
```

---

## 6. IP 로 검증 (DNS 전환 전)

`.env` 에 `DJANGO_SECURE_SSL_REDIRECT=false` 가 있고 `DJANGO_ALLOWED_HOSTS` 에 `<OCI_IP>` 가 있는 상태 (`sudo systemctl restart mysite` 로 반영).

```bash
# 로컬 PC 에서
curl -sI http://<OCI_IP>/ | head -1                        # HTTP/1.1 200
curl -s http://<OCI_IP>/ | grep -o '<title>[^<]*'          # 페이지 렌더
curl -sI http://<OCI_IP>/static/style.css | head -1        # 200 (nginx alias + collectstatic)
curl -sI http://<OCI_IP>/media/profile_images/<아무 파일> | head -1   # 200 (media rsync)
curl -s http://<OCI_IP>/ | grep -c 'class="tc-card"'       # 메인 목록의 게시글 카드 수 (0 이면 DB 비었거나 SQLite)
```

브라우저로 `http://<OCI_IP>/` 열어 게시글·이미지 확인. **로그인은 HTTP 로는 안 된다**(세션/CSRF 쿠키 Secure 고정) — 정상.

로그인까지 전환 전에 검증하려면 **인증서를 먼저 옮기는** 방법(8단계 방법 A)을 쓴 뒤 로컬 `hosts` 파일에 `<OCI_IP> techchang.com` 을 넣고 `https://techchang.com` 으로 접속하면 된다(끝나면 hosts 원복).

서버 쪽 확인:
```bash
sudo journalctl -u mysite -n 30 --no-pager
tail -n 20 logs/django.log logs/gunicorn_error.log
sudo tail -n 5 /var/log/nginx/techchang_error.log
DJANGO_SETTINGS_MODULE=config.settings.prod ~/venvs/mysite/bin/python3 manage.py check --deploy   # 경고 검토
DJANGO_SETTINGS_MODULE=config.settings.prod ~/venvs/mysite/bin/python3 manage.py check_email       # SMTP
```

---

## 7. DNS 전환

1. **미리(최소 하루 전)**: Route 53 에서 `techchang.com` / `www` A 레코드 TTL 을 300→**60** 으로 낮춘다.
2. 전환 직전에 Lightsail 에서 **글쓰기가 멈추도록** 서비스를 유지보수 상태로 두거나(간단히 `sudo systemctl stop mysite` → nginx 502) 그냥 짧게 감수하고, **재덤프 → OCI 복원**:
   ```bash
   ssh ubuntu@43.203.93.244 'cd ~/projects/mysite && sudo systemctl stop mysite && ~/venvs/mysite/bin/python3 manage.py backup_db --keep 7 --dest ~/projects/mysite/backups'
   # OCI
   rsync -avz $LS:~/projects/mysite/backups/ ./backups/ && rsync -avz $LS:~/projects/mysite/media/ ./media/
   bash scripts/restore_db.sh --yes
   ```
3. Route 53 A 레코드(`@`, `www`) 를 `<OCI_IP>` 로 변경.
4. `dig +short techchang.com` 이 새 IP 를 돌려주면 8단계로. (Lightsail 은 아직 끄지 않는다 — 문제 시 A 레코드만 되돌리면 롤백.)

---

## 8. certbot (HTTPS)

**방법 A — Lightsail 의 인증서를 그대로 이관** (DNS 전환 전에도 HTTPS 검증 가능, 발급 한도 소모 없음)
```bash
# OCI 에서 (certbot 은 deploy_oci.sh 가 설치함)
sudo rsync -avz --rsync-path='sudo rsync' $LS:/etc/letsencrypt/ /etc/letsencrypt/
sudo ls -la /etc/letsencrypt/live/techchang.com/
# 만료된 옛 도메인 인증서 제거 (남기면 renew 가 매번 실패 로그를 남김)
sudo certbot delete --cert-name tc.o-r.kr -n
# HTTPS nginx 설정: 실 설정 = 레포 nginx.conf (0단계에서 확인) → 그대로 사용
sudo cp nginx.conf /etc/nginx/sites-available/techchang && sudo nginx -t && sudo systemctl reload nginx
sudo certbot renew --dry-run          # 갱신 경로 확인 (DNS 전환 후에만 성공)
```
인증서는 ECDSA, 만료 2026-11-14 — 전환 후 첫 자동 갱신(10월 중순)이 OCI 에서 성공하는지 10단계에서 확인한다.
`rsync-path='sudo rsync'` 는 Lightsail 의 ubuntu 가 NOPASSWD sudo 여야 한다(Lightsail 기본). 안 되면 Lightsail 에서 `sudo tar czf /tmp/le.tgz /etc/letsencrypt && sudo chown ubuntu /tmp/le.tgz` 후 받아서 푼다.

**방법 B — 새로 발급** (DNS 가 OCI 를 가리킨 뒤)
```bash
sudo certbot --nginx -d techchang.com -d www.techchang.com --redirect -m seunghyunmoon55@gmail.com --agree-tos -n
sudo nginx -t && sudo systemctl reload nginx
systemctl list-timers --no-pager | grep certbot     # 자동 갱신 타이머
```
certbot 이 `/etc/nginx/sites-available/techchang` 에 443 블록을 추가하므로 이후 `deploy_oci.sh` 는 이 파일을 덮어쓰지 않는다. 최종적으로 레포 `nginx.conf` 로 교체하려면 방법 A 의 `cp` 를 쓰면 된다(444 default_server 로 IP 직접 접근 차단, HSTS 헤더 포함).

**어느 방법이든 마지막에:**
```bash
sed -i '/^DJANGO_SECURE_SSL_REDIRECT=/d' .env       # 토글 제거 → 기본 true
sudo systemctl restart mysite
curl -sI http://techchang.com/ | head -1            # 301 → https
curl -sI https://techchang.com/ | grep -iE 'HTTP/|strict-transport'
```
브라우저에서 로그인·글쓰기·이미지 업로드·카카오 로그인·관리자(`/secret-control-panel/` 또는 `DJANGO_ADMIN_URL`) 까지 확인.

---

## 9. crontab 이관

```bash
# OCI
crontab -l 2>/dev/null                   # 비어 있어야 정상
diff <(ssh $LS crontab -l) scripts/crontab.oci   # Lightsail 실제 줄과 대조 (시리즈 격주 게이트 등)
crontab scripts/crontab.oci && crontab -l
# 즉시 동작 확인 (메일 수신)
cd ~/projects/mysite && ~/venvs/mysite/bin/python3 manage.py backup_db --keep 7 --dest ~/projects/mysite/backups
~/venvs/mysite/bin/python3 manage.py send_log_report --hours 1 --to seunghyunmoon55@gmail.com
```
- 경로가 Lightsail 과 동일(`~/projects/mysite`, `~/venvs/mysite`)하므로 줄을 그대로 옮겨도 된다(0단계에서 `crontab.oci` 와 일치 확인). 
- `/var/log/techchang_report.log` 는 `deploy_oci.sh` 가 ubuntu 소유로 만들어 둔다 → 10줄 전부 **ubuntu crontab 한 곳**에 등록. root crontab(`sudo crontab -l`)은 비어 있어야 한다 (Lightsail 의 root 4줄은 권한 우회용 흔적이었음).
- 등록 직후 방문자 리포트가 실제로 도는지 한 번 수동 실행해 확인 (Lightsail 에서는 실행되지 않고 있었음):
  `~/venvs/mysite/bin/python3 manage.py send_visitor_report --period weekly --to seunghyunmoon55@gmail.com`
- **Lightsail 의 crontab 은 이 시점에 비운다** (`crontab -r` **와** `sudo crontab -r`) — 안 그러면 두 서버가 각각 칼럼을 쓰고 메일을 두 번 보낸다. auto_write 는 Lightsail 의 DB(이제 죽은 데이터)에 쓰이므로 사이트에 영향은 없지만 API 비용이 든다.

---

## 10. 1주 관찰 후 Lightsail 정리

관찰 항목 (OCI)
- 매일 08:00 로그 리포트 메일 도착, 03:00 백업 파일 생성 (`ls -la backups`)
- `sudo journalctl -u mysite --since '1 day ago' | grep -iE 'error|traceback' | head`
- `df -h`, `free -h` (12GB 라 여유), `/common/admin/monitor/` 대시보드
- `sudo certbot renew --dry-run` 성공
- 카카오 로그인·이메일 인증코드 발송 실제 사용자 케이스

정리
1. Lightsail: `crontab -r`, `sudo crontab -r`, `sudo systemctl disable --now mysite certbot.timer` (아직 인스턴스는 유지).
2. 최종 `backup_db` 한 번 더 받아 로컬에 보관 + media 전체 로컬 복사본.
3. Route 53 TTL 을 300 으로 되돌린다.
4. 1주 더 문제 없으면 Lightsail 인스턴스 스냅샷 → 삭제. `config/settings/prod.py` 의 `ALLOWED_HOSTS` 기본값과 `claude.md`·`README.md` 의 `43.203.93.244` 를 새 IP 로 갱신하는 커밋.

---

## 함정 정리

| # | 함정 | 대응 |
|---|---|---|
| 1 | **`SECURE_SSL_REDIRECT=True`**: certbot 전엔 IP HTTP 요청이 `https://<IP>` 로 301 → 검증 불가. nginx 가 `X-Forwarded-Proto: http` 를 주므로 무한 리다이렉트는 아니지만 응답을 못 본다 | `.env` `DJANGO_SECURE_SSL_REDIRECT=false`(이번 prod.py 변경) → 검증 → **반드시 제거**. `deploy_oci.sh` 가 false 상태면 경고. 대안: 인증서 먼저 이관(8-A) + hosts 파일 |
| 2 | Secure 쿠키(`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`) 는 토글 대상이 아님 → HTTP 로 로그인 불가 | 로그인 검증은 HTTPS(8-A + hosts) 로 |
| 3 | **HSTS preload(1년, includeSubDomains)**: 브라우저가 `techchang.com` 을 HTTPS 로만 연다. 되돌릴 수 없으므로 전환 후 HTTPS 가 잠시라도 깨지면 사용자는 접속 불가(경고 우회도 불가) | DNS 전환 **전에** 인증서(8-A)를 옮겨 두면 전환 즉시 HTTPS 가 살아 있음. IP 검증은 hostname 이 아니라 IP 라 HSTS 영향 없음 |
| 4 | **ManifestStaticFilesStorage 는 사실 비활성** — `prod.py` 의 `STATICFILES_STORAGE` 는 Django 5.1 에서 제거된 설정이라 무시됨(OCI 첫 배포에서 확인). 라이브도 일반 `StaticFilesStorage`(해시 없음)로 동작 중 | 이전에서는 현행 유지. 스크립트는 실제 활성 백엔드가 Manifest 일 때만 `staticfiles.json` 을 요구. Manifest 전환은 `STORAGES['staticfiles']` 로 별도 작업 |
| 5 | Ubuntu 24.04 홈 디렉터리 750 → nginx(www-data) 가 `/home/ubuntu/projects/mysite/staticfiles` 못 읽어 **403** | `deploy_oci.sh` 가 `chmod o+x /home/ubuntu` |
| 6 | `.env` 에 `DJANGO_DB_ENGINE=mysql` 누락 → SQLite 로 조용히 기동, 빈 사이트 | 스크립트가 강제 검사 |
| 7 | `mysqlclient` 가 requirements.txt 에 없음 → `pip install -r requirements.txt` 만 하면 `ImproperlyConfigured: Error loading MySQLdb` | `requirements-prod.txt` 사용. aarch64 는 소스 빌드 → apt 빌드 의존성 선설치 |
| 8 | MySQL 타임존 테이블 비어 있음 → `USE_TZ=True` 에서 `__date`/`TruncDate` 조회가 빈 결과(방문자 리포트·통계 오류) | 스크립트가 `mysql_tzinfo_to_sql` 적재. Lightsail 0-3 에서 tz_rows 확인 |
| 9 | `DJANGO_ALLOWED_HOSTS` 기본값(prod.py)에 옛 IP 하드코딩 → `.env` 로 새 IP 지정 안 하면 IP 접속 400 | `.env` 에 명시. 나중에 prod.py 기본값도 갱신 |
| 10 | 이메일(Gmail 앱 비밀번호)·`ANTHROPIC_API_KEY`·카카오 키는 `.env` 복사로 그대로 이관. **GSC 는 `.env` 의 절대경로가 가리키는 `token.json` 파일까지** 옮겨야 함 | 4단계 rsync. `manage.py check_email` 로 SMTP 확인. Gmail 이 새 IP 발신을 "새 위치 로그인"으로 막으면 앱 비밀번호 재발급 |
| 11 | crontab 이중 실행(양쪽 서버) → 칼럼 2회 작성·메일 2통·API 비용 | 9단계에서 Lightsail `crontab -r` |
| 12 | 서버 타임존 UTC 면 cron 이 9시간 어긋남 | 스크립트가 Asia/Seoul. Lightsail `timedatectl` 결과와 대조 |
| 13 | `backup_data.json`(untracked): `dumpdata` JSON 으로 추정 — SQLite 시절 산출물. MySQL 덤프와 무관 | 0-5 로 정체 확인 후 로컬 보관만. `loaddata` 하지 말 것(중복 PK 충돌) |
| 14 | `send_log_report` 는 `journalctl -u mysite` 와 `/var/log/nginx/*.log` 를 읽음 → 그룹 권한 필요 | 스크립트가 ubuntu 를 `systemd-journal`, `adm` 에 추가(재로그인 후 적용; cron 은 새 세션이라 바로 적용) |
| 15 | 레포 `mysite.service` 는 stale(venv 경로·www-data) — 그대로 설치하면 기동 실패 | OCI 는 스크립트 생성 유닛 사용. `SERVICE_USER` 를 cron 과 같은 `ubuntu` 로 두어 `logs/django.log` 를 두 주체가 안전하게 공유 |
| 16 | 카카오 로그인 Redirect URI, GSC 속성, Gmail 은 모두 도메인 기준 → IP 변경 무관. 단 **Route 53 이 아닌 곳에 IP 를 박아둔 것**(예: 외부 모니터링, 학교 방화벽 허용목록) 은 별도 갱신 | 목록 점검 |
| 17 | OCI 방화벽 2겹: VCN 보안목록만 열고 iptables 를 안 열면 외부에서 timeout | 스크립트 3단계 + `sudo iptables -L INPUT -n --line-numbers` 로 80/443 ACCEPT 가 REJECT 보다 위에 있는지 확인 |
| 18 | 전환 순간 사이의 신규 글/가입은 Lightsail DB 에만 남음 | 7-2 처럼 Lightsail `mysite` 를 멈춘 뒤 재덤프 → 복원 → DNS 변경 순서를 지키면 유실 0 |

## 롤백

DNS 전환 후 24시간 내 문제 → Route 53 A 레코드를 43.203.93.244 로 되돌리고 Lightsail `sudo systemctl start mysite`. 그 사이 OCI 에 쌓인 데이터는 `backup_db` 로 받아 두었다가 필요 시 수동 병합.
