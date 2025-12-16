# In-Place 업데이트 빠른 체크리스트

> 기존 서버: 43.203.93.244 (techchang.com)
> 상세 가이드: [INPLACE_UPDATE.md](INPLACE_UPDATE.md)

## ⚠️ 업데이트 전 필수 확인

### 준비된 파일 체크
- [x] `community/models.py` - 모든 모델에 `db_table = 'pybo_*'` 추가됨 ✅
- [x] `config/urls.py` - `/pybo/` → `/` 리다이렉트 추가됨 ✅
- [x] 모든 템플릿 파일 - `pybo:` → `community:` 변경됨 ✅

### 서버 정보
- **IP**: 43.203.93.244
- **도메인**: techchang.com
- **현재 위치**: /home/ubuntu/projects/mysite
- **SSH 접속**: `ssh -i your-key.pem ubuntu@43.203.93.244`

---

## 📋 10분 완료 체크리스트

### [ ] 1. 백업 (3분)
```bash
ssh -i your-key.pem ubuntu@43.203.93.244
mkdir -p ~/backups/$(date +%Y%m%d_%H%M%S)
cd ~/backups/$(date +%Y%m%d_%H%M%S)
sudo cp -r /home/ubuntu/projects/mysite ./mysite_backup
cp /home/ubuntu/projects/mysite/db.sqlite3 ./db_backup.sqlite3
```

### [ ] 2. 서비스 중지 (30초)
```bash
sudo systemctl stop gunicorn
```

### [ ] 3. 코드 업로드 (로컬에서)
```bash
# Windows PowerShell
scp -r c:\projects\mysite ubuntu@43.203.93.244:~/temp_update/mysite_new
```

### [ ] 4. 코드 교체 (1분)
```bash
# 서버에서
cd /home/ubuntu/projects
sudo mv mysite mysite_old
sudo mv ~/temp_update/mysite_new mysite
sudo chown -R ubuntu:www-data mysite
```

### [ ] 5. 데이터 복원 (1분)
```bash
cd /home/ubuntu/projects/mysite
sudo cp ../mysite_old/db.sqlite3 ./db.sqlite3
sudo cp -r ../mysite_old/media ./
sudo cp ../mysite_old/.env ./.env

# 권한 설정
sudo chown ubuntu:www-data db.sqlite3
sudo chmod 664 db.sqlite3
sudo chown -R ubuntu:www-data media/
```

### [ ] 6. 가상환경 (2분)
```bash
cp -r ../mysite_old/venv ./
source venv/bin/activate
pip install -r requirements.txt
python manage.py collectstatic --noinput
```

### [ ] 7. 마이그레이션 확인 (1분)
```bash
python manage.py showmigrations
# ⚠️ 새로운 마이그레이션이 없어야 함!
# 만약 있다면 db_table 설정을 확인하세요

# 데이터 확인
python manage.py shell
```

```python
from community.models import Question
print(f"게시글 수: {Question.objects.count()}")
exit()
```

### [ ] 8. Nginx 설정 (30초)
```bash
sudo cp nginx.conf /etc/nginx/sites-available/techchang
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/techchang /etc/nginx/sites-enabled/
sudo nginx -t
```

### [ ] 9. 서비스 재시작 (30초)
```bash
sudo systemctl start gunicorn
sudo systemctl restart nginx
```

### [ ] 10. 검증 (1분)
```bash
sudo systemctl status gunicorn
curl http://43.203.93.244
curl https://techchang.com
```

---

## 🆘 문제 발생 시 즉시 롤백

```bash
sudo systemctl stop gunicorn
cd /home/ubuntu/projects
sudo rm -rf mysite
sudo mv mysite_old mysite
sudo systemctl start gunicorn
```

---

## ✅ 검증 체크리스트

### 서비스 상태
- [ ] Gunicorn 실행 중
- [ ] Nginx 실행 중
- [ ] 포트 8000 사용 중

### 웹사이트 기능
- [ ] https://techchang.com 접속
- [ ] 로그인/로그아웃
- [ ] 게시글 목록 (기존 데이터 확인)
- [ ] 게시글 작성
- [ ] 프로필 이미지 확인
- [ ] /pybo/ URL 리다이렉트 확인

### 데이터 무결성
```python
# Django shell에서
from django.contrib.auth.models import User
from community.models import Question, Answer, Comment

print(f"사용자: {User.objects.count()}")
print(f"게시글: {Question.objects.count()}")
print(f"답변: {Answer.objects.count()}")
print(f"댓글: {Comment.objects.count()}")
```

---

## 🔍 일반적인 문제

### ❌ 500 Error
```bash
sudo tail -50 /var/log/gunicorn/error.log
cat /home/ubuntu/projects/mysite/.env
# DJANGO_ALLOWED_HOSTS 확인
```

### ❌ 데이터 없음
```bash
python manage.py dbshell
```
```sql
.tables
-- pybo_question 등이 있어야 함
SELECT COUNT(*) FROM pybo_question;
.quit
```

### ❌ 미디어 파일 안보임
```bash
sudo chown -R ubuntu:www-data media/
sudo chmod -R 755 media/
```

---

## 📞 긴급 연락

- **Gunicorn 로그**: `sudo tail -f /var/log/gunicorn/error.log`
- **Nginx 로그**: `sudo tail -f /var/log/nginx/techchang_error.log`
- **Django shell**: `cd mysite && source venv/bin/activate && python manage.py shell`

---

**업데이트 성공! 🎉**
