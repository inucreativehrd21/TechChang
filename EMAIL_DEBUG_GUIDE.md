# 서버 이메일 전송 문제 디버깅 가이드

## 🔍 현재 상황
서버에서 SMTP 이메일 전송이 실패하고 있습니다.

## ✅ 확인할 사항

### 1. 서버 환경 변수 확인
서버의 `.env` 파일이 올바르게 설정되어 있는지 확인:

```bash
# 서버에서 실행
cd /home/ubuntu/mysite  # 또는 프로젝트 경로
cat .env | grep EMAIL
```

**올바른 설정:**
```env
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.gmail.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_USE_TLS=true
DJANGO_EMAIL_USE_SSL=false
DJANGO_EMAIL_HOST_USER=seunghyunmoon55@gmail.com
DJANGO_EMAIL_HOST_PASSWORD=ogmmpefsrvbyjkjs
DJANGO_DEFAULT_FROM_EMAIL=테크창 <seunghyunmoon55@gmail.com>
DJANGO_EMAIL_TIMEOUT=30
```

### 2. 서버에서 Gmail SMTP 접근 테스트

```bash
# 서버에서 텔넷으로 SMTP 포트 접근 확인
telnet smtp.gmail.com 587

# 또는 nc(netcat) 사용
nc -vz smtp.gmail.com 587

# 또는 Python으로 직접 테스트
python3 << 'EOF'
import smtplib
import socket

print(f"서버 IP: {socket.gethostbyname(socket.gethostname())}")

try:
    server = smtplib.SMTP('smtp.gmail.com', 587, timeout=10)
    server.set_debuglevel(1)
    server.starttls()
    server.login('seunghyunmoon55@gmail.com', 'ogmmpefsrvbyjkjs')
    print("✅ SMTP 연결 성공!")
    server.quit()
except Exception as e:
    print(f"❌ SMTP 연결 실패: {type(e).__name__}: {e}")
EOF
```

### 3. AWS EC2 보안 그룹 확인

**아웃바운드 규칙 확인:**
- 포트 587 (SMTP TLS)가 허용되어 있는지 확인
- AWS Console → EC2 → Security Groups → 아웃바운드 규칙

기본적으로 모든 아웃바운드 트래픽이 허용되어야 합니다:
```
유형: 모든 트래픽
프로토콜: 모두
포트 범위: 모두
대상: 0.0.0.0/0
```

### 4. Gmail 앱 비밀번호 재생성

현재 사용 중인 앱 비밀번호가 만료되었거나 차단되었을 수 있습니다:

1. Google 계정 → 보안
2. 2단계 인증 활성화
3. 앱 비밀번호 → 새 앱 비밀번호 생성
4. 생성된 16자리 비밀번호를 `.env`에 적용

### 5. 서버 로그 확인

```bash
# Django 로그 확인
sudo journalctl -u mysite.service -n 100 -f

# 또는 로그 파일 확인
tail -f /home/ubuntu/mysite/logs/django.log
```

### 6. Django Shell에서 직접 테스트

```bash
cd /home/ubuntu/mysite
source venv/bin/activate
python manage.py shell

# Shell에서 실행
from django.core.mail import send_mail
from django.conf import settings

print(f"EMAIL_HOST: {settings.EMAIL_HOST}")
print(f"EMAIL_PORT: {settings.EMAIL_PORT}")
print(f"EMAIL_USE_TLS: {settings.EMAIL_USE_TLS}")
print(f"EMAIL_USE_SSL: {settings.EMAIL_USE_SSL}")
print(f"EMAIL_HOST_USER: {settings.EMAIL_HOST_USER}")
print(f"EMAIL_BACKEND: {settings.EMAIL_BACKEND}")

# 테스트 메일 전송
try:
    send_mail(
        '테스트',
        '테스트 메일입니다.',
        settings.DEFAULT_FROM_EMAIL,
        ['seunghyunmoon55@gmail.com'],
        fail_silently=False,
    )
    print("✅ 메일 전송 성공!")
except Exception as e:
    print(f"❌ 메일 전송 실패: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
```

### 7. 일반적인 오류 원인

#### SMTPAuthenticationError (535)
- 앱 비밀번호가 잘못되었거나 만료됨
- 해결: 새 앱 비밀번호 생성

#### SMTPServerDisconnected
- 네트워크 연결 문제
- 타임아웃 설정 증가: `DJANGO_EMAIL_TIMEOUT=60`

#### TimeoutError / socket.timeout
- 방화벽이 587 포트를 차단
- 해결: 보안 그룹 아웃바운드 규칙 확인

#### SMTPConnectError
- SMTP 서버에 연결할 수 없음
- 서버의 DNS 설정 확인

#### ssl.SSLError
- TLS/SSL 설정 문제
- 환경 변수가 문자열 "true"/"false"로 되어 있는지 확인

## 🔧 수정 완료 사항

1. **에러 로깅 개선**: 이제 프로덕션에서도 에러 타입이 표시됩니다.
2. **디버그 정보**: 에러 발생 시 에러 타입이 사용자에게 표시됩니다.

## 📝 다음 단계

1. 위의 테스트를 서버에서 실행
2. 에러 타입 확인
3. 해당 에러에 맞는 해결책 적용

## 💡 권장 조치

### 즉시 시도할 것:
```bash
# 서버에서 실행
cd /home/ubuntu/mysite
source venv/bin/activate

# Python으로 SMTP 연결 테스트 (위의 코드 실행)
# 결과를 확인하여 정확한 에러 원인 파악
```

### 만약 계속 실패한다면:

**대안 1: SendGrid 사용**
```env
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.sendgrid.net
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_USE_TLS=true
DJANGO_EMAIL_HOST_USER=apikey
DJANGO_EMAIL_HOST_PASSWORD=<SendGrid_API_Key>
```

**대안 2: AWS SES 사용**
```bash
pip install django-ses
```

```env
DJANGO_EMAIL_BACKEND=django_ses.SESBackend
AWS_ACCESS_KEY_ID=<your_key>
AWS_SECRET_ACCESS_KEY=<your_secret>
AWS_SES_REGION_NAME=ap-northeast-2
```
