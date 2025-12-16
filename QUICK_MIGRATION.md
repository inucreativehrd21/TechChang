# 빠른 마이그레이션 가이드 (요약본)

> 상세 가이드는 [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) 참조

## 🚀 3단계로 완료하기

### 1️⃣ 기존 서버에서 백업 (5-10분)

```bash
# 기존 서버 접속
ssh -i your-key.pem ubuntu@기존서버IP

# 백업 스크립트 업로드 및 실행
# (로컬에서 먼저 backup_data.sh를 업로드해야 함)
chmod +x backup_data.sh
./backup_data.sh

# 백업 파일을 로컬로 다운로드 (로컬 터미널에서)
scp -i your-key.pem ubuntu@기존서버IP:~/backups/db_*.sqlite3 ./
scp -i your-key.pem ubuntu@기존서버IP:~/backups/media_*.tar.gz ./
scp -i your-key.pem ubuntu@기존서버IP:~/backups/.env_backup ./
```

### 2️⃣ 새 서버에 배포 (15-20분)

```bash
# 새 EC2 인스턴스 생성 (Ubuntu 22.04, t3.small)

# 프로젝트 업로드 (로컬에서)
cd c:/projects
scp -r mysite ubuntu@새서버IP:/home/ubuntu/projects/

# 새 서버 접속
ssh -i your-key.pem ubuntu@새서버IP

# 배포 실행
cd /home/ubuntu/projects/mysite
./deploy_new_instance.sh
# .env 설정 메시지가 나오면 잠시 대기...
```

### 3️⃣ 데이터 복원 (5-10분)

```bash
# 백업 파일 업로드 (로컬에서, 별도 터미널)
cd ~/techchang_migration
scp -i your-key.pem db_*.sqlite3 ubuntu@새서버IP:/home/ubuntu/projects/mysite/
scp -i your-key.pem media_*.tar.gz ubuntu@새서버IP:/home/ubuntu/projects/mysite/
scp -i your-key.pem .env_backup ubuntu@새서버IP:/home/ubuntu/projects/mysite/.env

# 새 서버에서 복원 스크립트 실행
cd /home/ubuntu/projects/mysite
chmod +x restore_data.sh
./restore_data.sh

# 배포 스크립트가 실행 중이던 터미널로 돌아가서
# Enter 눌러서 계속 진행
```

## ✅ 검증 (5분)

```bash
# 데이터 확인
source venv/bin/activate
python manage.py shell
```

```python
from django.contrib.auth.models import User
from community.models import Question

print(f"사용자 수: {User.objects.count()}")
print(f"게시글 수: {Question.objects.count()}")
exit()
```

```bash
# 웹 접속 테스트
curl http://$(curl -s ifconfig.me)
```

## 🌐 DNS 전환 (5-30분)

1. **SSL 인증서 발급**
   ```bash
   sudo certbot --nginx -d techchang.com -d www.techchang.com
   ```

2. **DNS 레코드 업데이트** (도메인 관리 콘솔)
   ```
   A    @      새서버IP
   A    www    새서버IP
   ```

3. **확인**
   ```bash
   nslookup techchang.com
   # 5-30분 대기 후 접속
   https://techchang.com
   ```

## 📋 체크리스트

- [ ] 기존 서버 데이터 백업 완료
- [ ] 백업 파일 로컬 다운로드 완료
- [ ] 새 서버 생성 및 프로젝트 업로드 완료
- [ ] deploy_new_instance.sh 실행 완료
- [ ] 데이터 복원 완료
- [ ] 웹사이트 IP 접속 테스트 통과
- [ ] SSL 인증서 발급 완료
- [ ] DNS 전환 완료
- [ ] HTTPS 접속 테스트 통과

## 🆘 문제 발생 시

### 데이터베이스 연결 안됨
```bash
sudo systemctl restart gunicorn
sudo tail -f /var/log/gunicorn/error.log
```

### 미디어 파일 안보임
```bash
sudo chown -R ubuntu:www-data media/
sudo chmod -R 755 media/
sudo systemctl restart nginx
```

### 500 에러
```bash
# .env 파일 확인
cat .env
# DJANGO_ALLOWED_HOSTS에 도메인이 있는지 확인
# DEBUG=False 확인
```

## 📞 롤백 방법

DNS를 다시 기존 서버 IP로 변경
```
A    @      기존서버IP
A    www    기존서버IP
```

---

**상세 가이드**: [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md)
**배포 가이드**: [DEPLOYMENT.md](DEPLOYMENT.md)
