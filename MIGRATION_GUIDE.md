# 기존 서버 → 새 인스턴스 데이터 마이그레이션 가이드

> 기존 tc.o-r.kr 서버의 데이터를 보존하면서 새 techchang.com 서버로 이전하기

## 📋 목차
1. [사전 준비](#사전-준비)
2. [기존 서버에서 백업](#기존-서버에서-백업)
3. [새 서버 배포](#새-서버-배포)
4. [데이터 복원](#데이터-복원)
5. [검증 및 테스트](#검증-및-테스트)
6. [DNS 전환](#dns-전환)

---

## 사전 준비

### 필요한 정보
- **기존 서버 IP**: 기존 tc.o-r.kr 서버 IP 주소
- **새 서버 IP**: 새로 생성한 EC2 인스턴스 IP 주소
- **SSH 키**: 두 서버 모두 접속 가능한 SSH 키

### 로컬 환경 준비
```bash
# 작업 디렉토리 생성
mkdir -p ~/techchang_migration
cd ~/techchang_migration
```

---

## 기존 서버에서 백업

### 1단계: 기존 서버 접속
```bash
# 기존 서버 접속
ssh -i your-key.pem ubuntu@기존서버IP
```

### 2단계: 서비스 중지 (선택사항 - 데이터 일관성 보장)
```bash
# Gunicorn 중지 (백업 중 데이터 변경 방지)
sudo systemctl stop gunicorn

# 또는 서비스를 계속 실행하면서 백업도 가능합니다
# (단, 백업 중 변경된 데이터는 포함되지 않음)
```

### 3단계: 데이터베이스 백업
```bash
# 프로젝트 디렉토리로 이동
cd /home/ubuntu/projects/mysite

# 백업 디렉토리 생성
mkdir -p ~/backups

# 데이터베이스 백업 (타임스탬프 포함)
BACKUP_DATE=$(date +%Y%m%d_%H%M%S)
cp db.sqlite3 ~/backups/db_${BACKUP_DATE}.sqlite3

# 백업 확인
ls -lh ~/backups/
```

### 4단계: 미디어 파일 백업
```bash
# 미디어 파일 압축 (사용자 업로드 이미지 등)
cd /home/ubuntu/projects/mysite
tar -czf ~/backups/media_${BACKUP_DATE}.tar.gz media/

# 압축 파일 크기 확인
ls -lh ~/backups/media_${BACKUP_DATE}.tar.gz
```

### 5단계: 정적 파일 백업 (선택사항)
```bash
# 정적 파일 백업 (필요시)
# 대부분 새 서버에서 collectstatic으로 재생성 가능
tar -czf ~/backups/static_${BACKUP_DATE}.tar.gz static/ staticfiles/
```

### 6단계: 환경변수 파일 백업
```bash
# .env 파일 백업 (중요!)
cp .env ~/backups/.env_backup

# .env 내용 확인 (API 키 등)
cat .env
```

### 7단계: 서비스 재시작
```bash
# 서비스 중지했었다면 재시작
sudo systemctl start gunicorn
```

---

## 로컬로 백업 파일 다운로드

### 방법 1: 직접 다운로드 (권장)
```bash
# 로컬 터미널에서 실행
cd ~/techchang_migration

# 데이터베이스 다운로드
scp -i your-key.pem ubuntu@기존서버IP:~/backups/db_*.sqlite3 ./

# 미디어 파일 다운로드
scp -i your-key.pem ubuntu@기존서버IP:~/backups/media_*.tar.gz ./

# .env 파일 다운로드
scp -i your-key.pem ubuntu@기존서버IP:~/backups/.env_backup ./

# 다운로드 확인
ls -lh
```

### 방법 2: S3 사용 (큰 파일용)
```bash
# 기존 서버에서
aws s3 cp ~/backups/db_*.sqlite3 s3://your-bucket/techchang-migration/
aws s3 cp ~/backups/media_*.tar.gz s3://your-bucket/techchang-migration/

# 로컬에서 다운로드
aws s3 cp s3://your-bucket/techchang-migration/ ./ --recursive
```

---

## 새 서버 배포

### 1단계: 새 EC2 인스턴스 생성
- Ubuntu 22.04 LTS
- t3.small 이상 권장
- Security Group: SSH(22), HTTP(80), HTTPS(443) 오픈

### 2단계: 프로젝트 파일 업로드
```bash
# 로컬에서 실행 - 현재 프로젝트 전체 업로드
cd c:/projects
scp -r mysite ubuntu@새서버IP:/home/ubuntu/projects/

# 또는 Git 사용
# 새 서버에서: git clone your-repo-url
```

### 3단계: 자동 배포 스크립트 실행
```bash
# 새 서버 접속
ssh -i your-key.pem ubuntu@새서버IP

# 프로젝트 디렉토리로 이동
cd /home/ubuntu/projects/mysite

# 배포 스크립트 실행
chmod +x deploy_new_instance.sh
./deploy_new_instance.sh
```

**중요**: 스크립트가 .env 설정을 요구하면 **기다리세요!** 다음 단계에서 백업한 .env를 복원합니다.

### 4단계: 스크립트 일시 중지 시 다른 터미널 열기
```bash
# 새 터미널에서 새 서버 접속
ssh -i your-key.pem ubuntu@새서버IP
```

---

## 데이터 복원

### 1단계: 백업 파일 업로드
```bash
# 로컬 터미널에서 실행
cd ~/techchang_migration

# 데이터베이스 업로드
scp -i your-key.pem db_*.sqlite3 ubuntu@새서버IP:/home/ubuntu/projects/mysite/

# 미디어 파일 업로드
scp -i your-key.pem media_*.tar.gz ubuntu@새서버IP:/home/ubuntu/projects/mysite/

# .env 파일 업로드
scp -i your-key.pem .env_backup ubuntu@새서버IP:/home/ubuntu/projects/mysite/.env
```

### 2단계: 새 서버에서 데이터 복원
```bash
# 새 서버에서 실행
cd /home/ubuntu/projects/mysite

# .env 파일 복원 (이미 업로드됨)
# 도메인만 업데이트
sed -i 's/tc.o-r.kr/techchang.com/g' .env
sed -i 's/www.tc.o-r.kr/www.techchang.com/g' .env

# .env 확인 및 필요시 수정
nano .env
# DJANGO_ALLOWED_HOSTS=techchang.com,www.techchang.com 확인
# DEBUG=False 확인 (프로덕션)
```

### 3단계: 데이터베이스 복원
```bash
cd /home/ubuntu/projects/mysite

# 기존 빈 db.sqlite3 삭제 (있다면)
rm -f db.sqlite3

# 백업 데이터베이스를 db.sqlite3로 이름 변경
mv db_*.sqlite3 db.sqlite3

# 권한 설정
chmod 664 db.sqlite3
chown ubuntu:www-data db.sqlite3
```

### 4단계: 미디어 파일 복원
```bash
cd /home/ubuntu/projects/mysite

# 기존 media 디렉토리 백업 (혹시 모르니)
mv media media_empty_backup 2>/dev/null || true

# 미디어 파일 압축 해제
tar -xzf media_*.tar.gz

# 권한 설정
sudo chown -R ubuntu:www-data media/
sudo chmod -R 755 media/
```

### 5단계: 마이그레이션 확인
```bash
# 가상환경 활성화
source venv/bin/activate

# 마이그레이션 상태 확인
python manage.py showmigrations

# 만약 새로운 마이그레이션이 있다면 적용
python manage.py migrate

# 정적 파일 수집
python manage.py collectstatic --noinput
```

### 6단계: 배포 스크립트 계속 진행
```bash
# 첫 번째 터미널로 돌아가서
# .env 설정 완료 메시지에 Enter 입력하여 계속 진행
```

---

## 검증 및 테스트

### 1단계: 서비스 상태 확인
```bash
# Gunicorn 상태
sudo systemctl status gunicorn

# Gunicorn 재시작
sudo systemctl restart gunicorn

# Nginx 상태
sudo systemctl status nginx

# Nginx 재시작
sudo systemctl restart nginx
```

### 2단계: 로그 확인
```bash
# Gunicorn 에러 로그
sudo tail -f /var/log/gunicorn/error.log

# Nginx 에러 로그
sudo tail -f /var/log/nginx/techchang_error.log
```

### 3단계: 데이터베이스 연결 테스트
```bash
cd /home/ubuntu/projects/mysite
source venv/bin/activate

# Django shell로 데이터 확인
python manage.py shell
```

```python
# Django shell 내부에서
from django.contrib.auth.models import User
from community.models import Question, Answer

# 사용자 수 확인
print(f"총 사용자 수: {User.objects.count()}")

# 게시글 수 확인
print(f"총 게시글 수: {Question.objects.count()}")

# 답변 수 확인
print(f"총 답변 수: {Answer.objects.count()}")

# 최근 게시글 확인
for q in Question.objects.order_by('-create_date')[:5]:
    print(f"- {q.subject} ({q.author.username if q.author else 'Anonymous'})")

# 종료
exit()
```

### 4단계: 웹 브라우저 테스트
SSL 인증서가 아직 없으므로 임시로 IP로 접속:

```bash
# 서버 IP 확인
curl ifconfig.me
```

브라우저에서 `http://새서버IP` 접속하여:
- [ ] 홈페이지 로딩 확인
- [ ] 게시글 목록 확인 (기존 데이터 보임)
- [ ] 로그인 테스트
- [ ] 프로필 이미지 확인 (미디어 파일)
- [ ] 게임 기능 테스트

---

## DNS 전환

### 1단계: SSL 인증서 발급
```bash
# 새 서버에서
sudo certbot --nginx -d techchang.com -d www.techchang.com

# 인증서 발급 성공 확인
sudo certbot certificates
```

### 2단계: DNS 레코드 업데이트
도메인 관리 콘솔(가비아, Route53 등)에서:

```
Type    Name    Value           TTL
A       @       <새서버IP>      300 (5분)
A       www     <새서버IP>      300
```

**중요**: TTL을 짧게 설정(300초)하면 빠른 전파 가능

### 3단계: DNS 전파 확인
```bash
# 로컬에서 확인
nslookup techchang.com
dig techchang.com

# 전파될 때까지 5-30분 대기
```

### 4단계: HTTPS 접속 테스트
```
https://techchang.com
https://www.techchang.com
```

모든 기능 재테스트:
- [ ] 로그인/로그아웃
- [ ] 게시글 작성/수정/삭제
- [ ] 댓글 작성
- [ ] 파일 업로드
- [ ] 게임 플레이
- [ ] 관리자 페이지

---

## 마이그레이션 체크리스트

### 백업 단계
- [ ] 기존 서버 db.sqlite3 백업 완료
- [ ] 미디어 파일 백업 완료
- [ ] .env 파일 백업 완료
- [ ] 백업 파일 로컬 다운로드 완료

### 배포 단계
- [ ] 새 EC2 인스턴스 생성 완료
- [ ] 프로젝트 파일 업로드 완료
- [ ] deploy_new_instance.sh 실행 완료
- [ ] .env 파일 복원 및 수정 완료

### 복원 단계
- [ ] 데이터베이스 복원 완료
- [ ] 미디어 파일 복원 완료
- [ ] 마이그레이션 확인 및 적용 완료
- [ ] 서비스 재시작 완료

### 검증 단계
- [ ] Gunicorn/Nginx 정상 작동
- [ ] 데이터베이스 데이터 확인
- [ ] 웹사이트 IP 접속 테스트
- [ ] 모든 기능 테스트 통과

### DNS 전환
- [ ] SSL 인증서 발급 완료
- [ ] DNS A 레코드 업데이트 완료
- [ ] DNS 전파 확인 완료
- [ ] HTTPS 접속 테스트 완료

---

## 롤백 계획

만약 문제가 발생하면:

### 즉시 롤백
```bash
# DNS를 다시 기존 서버로 변경
# 도메인 관리 콘솔에서 A 레코드를 기존 서버 IP로 되돌림
```

### 기존 서버 유지
**중요**: DNS 전환 후 최소 24-48시간은 기존 서버를 유지하세요!
- DNS 캐시 문제로 일부 사용자는 여전히 기존 서버 접속
- 문제 발생 시 빠른 롤백 가능

---

## 마이그레이션 후 작업

### 1. 기존 서버 모니터링
```bash
# 기존 서버 접속 로그 확인 (1-2일간)
sudo tail -f /var/log/nginx/access.log

# 트래픽이 0이 되면 안전하게 종료 가능
```

### 2. 백업 정책 수립
```bash
# 새 서버에서 자동 백업 설정
crontab -e

# 매일 새벽 2시 데이터베이스 백업
0 2 * * * cp /home/ubuntu/projects/mysite/db.sqlite3 /home/ubuntu/backups/db_$(date +\%Y\%m\%d).sqlite3

# 매주 일요일 미디어 파일 백업
0 3 * * 0 tar -czf /home/ubuntu/backups/media_$(date +\%Y\%m\%d).tar.gz /home/ubuntu/projects/mysite/media/
```

### 3. 모니터링 설정
```bash
# 디스크 사용량 확인
df -h

# 메모리 사용량 확인
free -h

# 로그 파일 크기 관리
sudo logrotate -f /etc/logrotate.conf
```

---

## 예상 다운타임

최적화된 경우:
- **데이터 백업**: 5-10분
- **새 서버 배포**: 15-20분
- **데이터 복원**: 5-10분
- **DNS 전파**: 5-30분

**총 예상 시간**: 약 30-70분

다운타임 최소화:
- DNS TTL을 미리 짧게 설정 (24시간 전)
- 새벽 시간대 작업
- 기존 서버는 DNS 전환 후에도 유지

---

## 문제 해결

### 문제 1: 데이터베이스 마이그레이션 충돌
```bash
# 마이그레이션 히스토리 확인
python manage.py showmigrations

# Fake 마이그레이션 (데이터베이스는 그대로, 히스토리만 업데이트)
python manage.py migrate --fake community
```

### 문제 2: 미디어 파일이 보이지 않음
```bash
# 권한 확인
ls -la media/

# 권한 수정
sudo chown -R ubuntu:www-data media/
sudo chmod -R 755 media/

# Nginx 설정 확인
sudo nginx -t
```

### 문제 3: 500 Internal Server Error
```bash
# Gunicorn 로그 확인
sudo tail -f /var/log/gunicorn/error.log

# Django 설정 확인
cd /home/ubuntu/projects/mysite
source venv/bin/activate
python manage.py check --deploy
```

---

## 긴급 연락

문제 발생 시:
1. 기존 서버 로그 확인
2. 새 서버 로그 확인
3. DNS 롤백 고려
4. 백업 파일 재확인

---

**성공적인 마이그레이션을 기원합니다! 🚀**
