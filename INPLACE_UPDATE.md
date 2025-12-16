# 기존 서버 In-Place 업데이트 가이드

> 새 인스턴스 없이 기존 서버에서 코드만 업데이트하기
> 서버: 43.203.93.244 (techchang.com)

## ⚠️ 중요 사항

### 주의해야 할 문제들
1. **앱 이름 변경 문제** (`pybo` → `community`)
   - DB 테이블 이름: `pybo_question` → `community_question`
   - **해결책**: 테이블 이름을 명시적으로 지정하여 기존 이름 유지

2. **URL 변경** (`/pybo/` → `/`)
   - 기존 링크가 깨질 수 있음
   - **해결책**: URL 리다이렉트 추가

3. **다운타임**
   - 예상 시간: 5-10분
   - **해결책**: 새벽 시간대 작업 권장

---

## 📋 사전 준비 체크리스트

- [ ] 서버 접속 정보 확인 (SSH 키)
- [ ] 현재 서비스 상태 확인
- [ ] 작업 시간대 결정 (새벽 권장)
- [ ] 롤백 계획 수립

---

## 🚀 업데이트 프로세스 (10단계)

### 1단계: 백업 (필수!)

```bash
# 기존 서버 접속
ssh -i your-key.pem ubuntu@43.203.93.244

# 백업 디렉토리 생성
mkdir -p ~/backups/$(date +%Y%m%d_%H%M%S)
cd ~/backups/$(date +%Y%m%d_%H%M%S)

# 전체 프로젝트 백업
sudo cp -r /home/ubuntu/projects/mysite ./mysite_backup

# 데이터베이스만 따로 백업
cp /home/ubuntu/projects/mysite/db.sqlite3 ./db_backup.sqlite3

# 미디어 파일 백업
tar -czf media_backup.tar.gz /home/ubuntu/projects/mysite/media/

# .env 파일 백업
cp /home/ubuntu/projects/mysite/.env ./env_backup

# nginx 설정 백업
sudo cp /etc/nginx/sites-available/mysite ./nginx_backup.conf 2>/dev/null || \
sudo cp /etc/nginx/sites-available/techchang ./nginx_backup.conf 2>/dev/null || true

# gunicorn 서비스 백업
sudo cp /etc/systemd/system/gunicorn.service ./gunicorn_backup.service

echo "백업 완료! 백업 위치: $(pwd)"
ls -lah
```

**중요**: 백업이 완료될 때까지 다음 단계로 진행하지 마세요!

---

### 2단계: 서비스 중지

```bash
# Gunicorn 중지
sudo systemctl stop gunicorn

# 상태 확인
sudo systemctl status gunicorn
```

---

### 3단계: 코드 업데이트 준비

```bash
# 임시 디렉토리 생성
mkdir -p ~/temp_update
cd ~/temp_update
```

**로컬에서**: 새 코드를 서버로 업로드

```bash
# Windows (PowerShell)
scp -r c:\projects\mysite ubuntu@43.203.93.244:~/temp_update/mysite_new

# 또는 Git 사용
# ssh ubuntu@43.203.93.244
# cd ~/temp_update
# git clone your-repo-url mysite_new
```

---

### 4단계: 중요! community 앱의 모델 수정

**문제**: 앱 이름이 `pybo`에서 `community`로 바뀌면 Django가 새 테이블(`community_*`)을 만들려고 시도합니다.

**해결**: 서버에서 모델 파일을 수정하여 기존 테이블 이름(`pybo_*`)을 명시적으로 지정합니다.

```bash
# 서버에서
cd ~/temp_update/mysite_new/community

# models.py 백업
cp models.py models.py.backup
```

**로컬에서 먼저 수정**: `community/models.py` 파일의 모든 모델 클래스에 `db_table` 추가

---

### 5단계: 기존 코드와 교체

```bash
cd /home/ubuntu/projects

# 기존 mysite를 mysite_old로 이름 변경
sudo mv mysite mysite_old

# 새 코드를 mysite로 이동
sudo mv ~/temp_update/mysite_new mysite

# 소유권 설정
sudo chown -R ubuntu:www-data mysite
```

---

### 6단계: 기존 데이터 복원

```bash
cd /home/ubuntu/projects/mysite

# 데이터베이스 복원
sudo cp ../mysite_old/db.sqlite3 ./db.sqlite3

# 미디어 파일 복원
sudo cp -r ../mysite_old/media ./

# .env 파일 복원 및 업데이트
sudo cp ../mysite_old/.env ./.env

# 도메인 설정 업데이트
sed -i 's/tc\.o-r\.kr/techchang.com/g' .env
sed -i 's/www\.tc\.o-r\.kr/www.techchang.com/g' .env

# 권한 설정
sudo chown ubuntu:www-data db.sqlite3
sudo chmod 664 db.sqlite3
sudo chown -R ubuntu:www-data media/
sudo chmod -R 755 media/
```

---

### 7단계: 가상환경 및 패키지 업데이트

```bash
cd /home/ubuntu/projects/mysite

# 기존 가상환경 사용 또는 새로 생성
if [ -d "../mysite_old/venv" ]; then
    cp -r ../mysite_old/venv ./
else
    python3 -m venv venv
fi

# 가상환경 활성화
source venv/bin/activate

# 패키지 업데이트
pip install --upgrade pip
pip install -r requirements.txt

# 정적 파일 수집
python manage.py collectstatic --noinput
```

---

### 8단계: 마이그레이션 처리

```bash
# 마이그레이션 상태 확인
python manage.py showmigrations

# ⚠️ 주의: migrate 실행 전 반드시 확인
# - community 앱의 모델에 db_table이 설정되어 있는지
# - 새로운 마이그레이션이 테이블을 재생성하지 않는지

# 마이그레이션 적용 (있다면)
python manage.py migrate

# 데이터 확인
python manage.py shell
```

```python
# Django shell에서
from django.contrib.auth.models import User
from community.models import Question

print(f"사용자 수: {User.objects.count()}")
print(f"게시글 수: {Question.objects.count()}")

# 몇 개 게시글 확인
for q in Question.objects.all()[:3]:
    print(f"- {q.subject}")

exit()
```

---

### 9단계: Nginx 및 Gunicorn 설정 업데이트

```bash
# Nginx 설정 업데이트
sudo cp /home/ubuntu/projects/mysite/nginx.conf /etc/nginx/sites-available/techchang

# 기존 심볼릭 링크 제거
sudo rm -f /etc/nginx/sites-enabled/mysite
sudo rm -f /etc/nginx/sites-enabled/default

# 새 설정 활성화
sudo ln -sf /etc/nginx/sites-available/techchang /etc/nginx/sites-enabled/

# Nginx 설정 테스트
sudo nginx -t

# Gunicorn 서비스 파일 확인
sudo cat /etc/systemd/system/gunicorn.service
# WorkingDirectory가 /home/ubuntu/projects/mysite인지 확인
```

**Gunicorn 서비스가 없거나 잘못되어 있다면:**

```bash
sudo nano /etc/systemd/system/gunicorn.service
```

내용:
```ini
[Unit]
Description=Gunicorn daemon for TechChang Django project
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/home/ubuntu/projects/mysite
Environment="PATH=/home/ubuntu/projects/mysite/venv/bin"
EnvironmentFile=/home/ubuntu/projects/mysite/.env
ExecStart=/home/ubuntu/projects/mysite/venv/bin/gunicorn \
    --workers 3 \
    --bind 127.0.0.1:8000 \
    --timeout 120 \
    --access-logfile /var/log/gunicorn/access.log \
    --error-logfile /var/log/gunicorn/error.log \
    config.wsgi:application

[Install]
WantedBy=multi-user.target
```

```bash
# 로그 디렉토리 생성
sudo mkdir -p /var/log/gunicorn
sudo chown ubuntu:www-data /var/log/gunicorn

# systemd 재로드
sudo systemctl daemon-reload
```

---

### 10단계: 서비스 재시작 및 확인

```bash
# Gunicorn 시작
sudo systemctl start gunicorn
sudo systemctl enable gunicorn

# 상태 확인
sudo systemctl status gunicorn

# Nginx 재시작
sudo systemctl restart nginx

# 로그 확인
sudo tail -f /var/log/gunicorn/error.log
```

**별도 터미널에서 접속 테스트:**
```bash
curl http://43.203.93.244
curl https://techchang.com
```

---

## 🔍 검증 체크리스트

### 서비스 상태
- [ ] Gunicorn 실행 중: `sudo systemctl status gunicorn`
- [ ] Nginx 실행 중: `sudo systemctl status nginx`
- [ ] 포트 8000 사용 중: `sudo netstat -tulpn | grep :8000`

### 웹사이트 기능
- [ ] 홈페이지 로딩: https://techchang.com
- [ ] 로그인/로그아웃
- [ ] 게시글 목록 (기존 데이터 확인)
- [ ] 게시글 작성/수정/삭제
- [ ] 프로필 이미지 (미디어 파일 확인)
- [ ] 게임 기능
- [ ] 관리자 페이지: https://techchang.com/admin

### 데이터 무결성
- [ ] 사용자 수 일치
- [ ] 게시글 수 일치
- [ ] 댓글 수 일치
- [ ] 첨부 파일 접근 가능

---

## 🆘 문제 해결

### 문제 1: 500 Internal Server Error

```bash
# 로그 확인
sudo tail -50 /var/log/gunicorn/error.log
sudo tail -50 /var/log/nginx/techchang_error.log

# 일반적인 원인:
# 1. 환경변수 문제
cat /home/ubuntu/projects/mysite/.env
# DJANGO_ALLOWED_HOSTS에 techchang.com이 있는지 확인

# 2. 권한 문제
ls -la /home/ubuntu/projects/mysite/db.sqlite3
sudo chown ubuntu:www-data db.sqlite3

# 3. 가상환경 경로 문제
which python
# /home/ubuntu/projects/mysite/venv/bin/python 이어야 함
```

### 문제 2: 데이터가 보이지 않음

```bash
# 데이터베이스 연결 확인
cd /home/ubuntu/projects/mysite
source venv/bin/activate
python manage.py dbshell
```

```sql
-- SQLite에서
.tables
-- pybo_question, pybo_answer 등이 있어야 함

SELECT COUNT(*) FROM pybo_question;
-- 기존 게시글 수가 나와야 함

.quit
```

**만약 community_question 테이블이 생성되었다면:**
- 모델에 `db_table` 메타 옵션이 제대로 설정되지 않은 것
- 4단계로 돌아가서 모델 수정 필요

### 문제 3: URL 404 에러

기존 `/pybo/` URL로 접근하는 링크들을 위한 리다이렉트 추가:

```bash
nano /home/ubuntu/projects/mysite/config/urls.py
```

추가:
```python
from django.views.generic import RedirectView

urlpatterns = [
    # 기존 pybo URL 리다이렉트
    path('pybo/', RedirectView.as_view(url='/', permanent=True)),
    path('pybo/<path:path>/', RedirectView.as_view(url='/%(path)s/', permanent=True)),

    # ... 나머지 URL 패턴
]
```

---

## 🔄 롤백 절차

문제가 발생하면 즉시 롤백:

```bash
# 서비스 중지
sudo systemctl stop gunicorn

# 기존 코드로 복원
cd /home/ubuntu/projects
sudo rm -rf mysite
sudo mv mysite_old mysite

# 서비스 재시작
sudo systemctl start gunicorn
sudo systemctl restart nginx

# 상태 확인
sudo systemctl status gunicorn
curl https://techchang.com
```

---

## 📝 업데이트 후 정리

업데이트가 성공적으로 완료되고 24-48시간 동안 문제가 없다면:

```bash
# 백업 확인
ls -la ~/backups/

# 오래된 코드 삭제 (신중하게!)
# sudo rm -rf /home/ubuntu/projects/mysite_old

# 임시 파일 삭제
rm -rf ~/temp_update
```

---

## 🎯 전체 작업 시간표

| 단계 | 예상 시간 | 다운타임 |
|------|-----------|----------|
| 1. 백업 | 5분 | ❌ |
| 2. 서비스 중지 | 1분 | ✅ |
| 3-6. 코드 교체 | 5분 | ✅ |
| 7-8. 환경 설정 | 5분 | ✅ |
| 9-10. 재시작 | 2분 | ✅ |
| **총계** | **18분** | **13분** |

---

## ⚡ 빠른 참조 명령어

```bash
# 로그 실시간 모니터링
sudo tail -f /var/log/gunicorn/error.log

# 서비스 재시작
sudo systemctl restart gunicorn
sudo systemctl restart nginx

# 데이터 확인
cd /home/ubuntu/projects/mysite
source venv/bin/activate
python manage.py shell

# 권한 수정
sudo chown -R ubuntu:www-data /home/ubuntu/projects/mysite
sudo chmod 664 db.sqlite3
sudo chmod -R 755 media/
```

---

**안전하고 성공적인 업데이트를 기원합니다! 🚀**
