# TechChang 커뮤니티 사이트 배포 가이드

## 목차
1. [사전 준비사항](#사전-준비사항)
2. [새 EC2 인스턴스 설정](#새-ec2-인스턴스-설정)
3. [도메인 설정](#도메인-설정)
4. [프로젝트 배포](#프로젝트-배포)
5. [트러블슈팅](#트러블슈팅)

---

## 사전 준비사항

### 1. 필요한 정보 준비
- **AWS 계정** 및 EC2 접근 권한
- **도메인**: techchang.com (또는 원하는 도메인)
- **API 키들**:
  - OpenAI API Key
  - Kakao REST API Key & Client Secret
  - Korean Dictionary API Key (선택사항)

### 2. 로컬 환경에서 준비
```bash
# SECRET_KEY 생성
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

생성된 키를 안전하게 보관하세요.

---

## 새 EC2 인스턴스 설정

### 1. EC2 인스턴스 생성
1. AWS Console에서 EC2 > Launch Instance
2. 추천 사양:
   - **AMI**: Ubuntu 22.04 LTS
   - **Instance Type**: t3.small 이상 (t2.micro는 메모리 부족 가능)
   - **Storage**: 20GB 이상
3. Security Group 설정:
   - SSH (22) - 본인 IP만
   - HTTP (80) - 0.0.0.0/0
   - HTTPS (443) - 0.0.0.0/0

### 2. 인스턴스 접속
```bash
ssh -i your-key.pem ubuntu@your-instance-ip
```

### 3. 초기 설정
```bash
# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 타임존 설정
sudo timedatectl set-timezone Asia/Seoul

# 호스트명 설정 (선택사항)
sudo hostnamectl set-hostname techchang
```

---

## 도메인 설정

### 1. DNS 레코드 설정
도메인 제공업체(가비아, Route53 등)에서 다음 레코드 추가:

```
Type    Name    Value
A       @       <EC2 Public IP>
A       www     <EC2 Public IP>
```

### 2. DNS 전파 확인
```bash
# 5-30분 정도 소요
nslookup techchang.com
dig techchang.com
```

---

## 프로젝트 배포

### 방법 1: 자동 배포 스크립트 사용 (추천)

#### 1. 프로젝트 파일 업로드
```bash
# 로컬에서 실행
scp -i your-key.pem -r /path/to/mysite ubuntu@your-instance-ip:/home/ubuntu/projects/
```

#### 2. 스크립트 실행
```bash
# EC2 인스턴스에서 실행
cd /home/ubuntu/projects/mysite
chmod +x deploy_new_instance.sh
./deploy_new_instance.sh
```

#### 3. 환경변수 설정
스크립트가 멈추면 `.env` 파일을 편집:
```bash
nano .env
```

필수 설정 항목:
```env
DJANGO_SECRET_KEY=<앞서 생성한 SECRET_KEY>
DEBUG=False
DJANGO_ALLOWED_HOSTS=techchang.com,www.techchang.com
ANTHROPIC_API_KEY=<your-anthropic-key>
KAKAO_REST_API_KEY=<your-key>
KAKAO_CLIENT_SECRET=<your-secret>
```

저장 후 스크립트 계속 진행.

---

### 방법 2: 수동 배포

#### 1. 프로젝트 디렉토리 생성
```bash
mkdir -p /home/ubuntu/projects/mysite
cd /home/ubuntu/projects/mysite
```

#### 2. 필수 패키지 설치
```bash
sudo apt install -y python3-pip python3-venv python3-dev \
    nginx postgresql postgresql-contrib \
    git curl wget build-essential \
    certbot python3-certbot-nginx
```

#### 3. 가상환경 및 패키지 설치
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### 4. 환경변수 설정
```bash
cp .env.example .env
nano .env
# 필요한 값들 입력
```

#### 5. Django 설정
```bash
# 정적 파일 수집
python manage.py collectstatic --noinput

# 데이터베이스 마이그레이션
python manage.py migrate

# 관리자 계정 생성
python manage.py createsuperuser
```

#### 6. Gunicorn 서비스 설정
```bash
sudo nano /etc/systemd/system/gunicorn.service
```

다음 내용 입력:
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

로그 디렉토리 생성 및 서비스 시작:
```bash
sudo mkdir -p /var/log/gunicorn
sudo chown ubuntu:www-data /var/log/gunicorn

sudo systemctl daemon-reload
sudo systemctl start gunicorn
sudo systemctl enable gunicorn
sudo systemctl status gunicorn
```

#### 7. Nginx 설정
```bash
# 설정 파일 복사
sudo cp nginx.conf /etc/nginx/sites-available/techchang

# 기본 사이트 비활성화
sudo rm -f /etc/nginx/sites-enabled/default

# TechChang 사이트 활성화
sudo ln -s /etc/nginx/sites-available/techchang /etc/nginx/sites-enabled/

# 설정 테스트 및 재시작
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```

#### 8. SSL 인증서 발급
```bash
sudo certbot --nginx -d techchang.com -d www.techchang.com
```

이메일 입력 및 약관 동의 후 진행.

자동 갱신 확인:
```bash
sudo systemctl status certbot.timer
```

---

## 배포 후 확인사항

### 1. 서비스 상태 확인
```bash
# Gunicorn 상태
sudo systemctl status gunicorn

# Nginx 상태
sudo systemctl status nginx

# 포트 사용 확인
sudo netstat -tulpn | grep :8000
sudo netstat -tulpn | grep :80
sudo netstat -tulpn | grep :443
```

### 2. 로그 확인
```bash
# Gunicorn 로그
sudo tail -f /var/log/gunicorn/error.log

# Nginx 로그
sudo tail -f /var/log/nginx/techchang_error.log
sudo tail -f /var/log/nginx/techchang_access.log

# Django 로그
tail -f /home/ubuntu/projects/mysite/logs/django.log
```

### 3. 웹사이트 접속 테스트
- https://techchang.com
- https://techchang.com/admin
- https://techchang.com/games/

---

## 운영 및 유지보수

### 코드 업데이트
```bash
cd /home/ubuntu/projects/mysite
source venv/bin/activate

# Git pull (Git 사용 시)
git pull origin main

# 패키지 업데이트
pip install -r requirements.txt

# 정적 파일 재수집
python manage.py collectstatic --noinput

# 마이그레이션
python manage.py migrate

# Gunicorn 재시작
sudo systemctl restart gunicorn
```

### 데이터베이스 백업
```bash
# 백업 디렉토리 생성
mkdir -p ~/backups

# SQLite 백업 (현재 설정)
cp /home/ubuntu/projects/mysite/db.sqlite3 ~/backups/db_$(date +%Y%m%d_%H%M%S).sqlite3

# 자동 백업 크론잡 설정 (매일 2시)
crontab -e
# 다음 줄 추가:
# 0 2 * * * cp /home/ubuntu/projects/mysite/db.sqlite3 ~/backups/db_$(date +\%Y\%m\%d).sqlite3
```

### SSL 인증서 수동 갱신
```bash
sudo certbot renew
sudo systemctl reload nginx
```

---

## 트러블슈팅

### 1. Gunicorn이 시작되지 않음
```bash
# 로그 확인
sudo journalctl -u gunicorn -n 50

# 환경변수 확인
cat /home/ubuntu/projects/mysite/.env

# 수동 실행 테스트
cd /home/ubuntu/projects/mysite
source venv/bin/activate
gunicorn config.wsgi:application
```

### 2. 502 Bad Gateway 에러
```bash
# Gunicorn 상태 확인
sudo systemctl status gunicorn

# Gunicorn 재시작
sudo systemctl restart gunicorn

# Nginx 에러 로그 확인
sudo tail -f /var/log/nginx/techchang_error.log
```

### 3. 정적 파일이 로드되지 않음
```bash
# 정적 파일 재수집
cd /home/ubuntu/projects/mysite
source venv/bin/activate
python manage.py collectstatic --noinput

# 권한 확인
ls -la staticfiles/
sudo chown -R ubuntu:www-data staticfiles/
sudo chmod -R 755 staticfiles/
```

### 4. CSRF 에러
- `.env` 파일의 `DJANGO_ALLOWED_HOSTS`에 도메인이 포함되어 있는지 확인
- `SECURE_PROXY_SSL_HEADER` 설정 확인 (prod.py)

### 5. 데이터베이스 마이그레이션 에러
```bash
# 마이그레이션 상태 확인
python manage.py showmigrations

# 특정 앱 마이그레이션
python manage.py migrate community

# 마이그레이션 초기화 (주의!)
# python manage.py migrate --fake community zero
# python manage.py migrate community
```

---

## 보안 체크리스트

- [ ] `.env` 파일이 `.gitignore`에 포함되어 있음
- [ ] `DEBUG=False` 설정됨
- [ ] 강력한 `SECRET_KEY` 사용 중
- [ ] `ALLOWED_HOSTS`가 올바르게 설정됨
- [ ] SSL 인증서 적용됨
- [ ] SSH는 키 기반 인증만 허용
- [ ] 불필요한 포트는 Security Group에서 차단
- [ ] Django 관리자 계정 강력한 비밀번호 사용
- [ ] 정기적인 백업 설정됨

---

## 성능 최적화 (선택사항)

### PostgreSQL 사용
현재는 SQLite를 사용하지만, 트래픽이 증가하면 PostgreSQL로 전환 권장:

```bash
# PostgreSQL 설치
sudo apt install postgresql postgresql-contrib

# 데이터베이스 생성
sudo -u postgres psql
CREATE DATABASE techchang;
CREATE USER techchang_user WITH PASSWORD 'strong_password';
GRANT ALL PRIVILEGES ON DATABASE techchang TO techchang_user;
\q

# settings/prod.py 수정
# DATABASES 설정 변경 후 마이그레이션
```

### Redis 캐싱
```bash
sudo apt install redis-server
pip install redis django-redis
```

### CDN 사용
정적 파일을 AWS CloudFront, Cloudflare 등 CDN을 통해 제공.

---

## 문의 및 지원

문제가 발생하면 다음을 확인하세요:
1. 로그 파일 (/var/log/gunicorn/, /var/log/nginx/)
2. 서비스 상태 (systemctl status)
3. 환경변수 설정 (.env)

---

**배포 성공을 기원합니다! 🚀**
