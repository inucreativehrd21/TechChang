# Nginx + Certbot HTTP 챌린지 체크리스트

## 1. 현재 상태 점검
- [ ] `nslookup tc.o-r.kr`로 도메인이 서버 공인 IP(예: `43.203.93.244`)와 일치하는지 확인
- [ ] 보안 그룹/방화벽에서 80, 443 포트 인바운드 허용
- [ ] `sudo systemctl status nginx`로 nginx가 실행 중인지 확인

## 2. HTTP(포트 80) 서버 블록 임시 구성
`/etc/nginx/sites-available/mysite` 파일에 최소한 다음 구성이 필요합니다.

```nginx
server {
    listen 80;
    server_name tc.o-r.kr 43.203.93.244;

    # 1) 인증용 임시 응답
    location / {
        return 200 'TechWindow HTTP alive';
        add_header Content-Type text/plain;
    }

    # 2) Certbot 챌린지 경로 허용
    location /.well-known/acme-challenge/ {
        root /var/www/html;  # 또는 Certbot이 사용할 디렉터리
        # include /etc/nginx/letsencrypt-acme-challenge.conf;  # 필요 시
    }
}
```

> ⚠️ 인증서 발급 전에 `return 301 https://...` 리다이렉트는 주석 처리해 두세요.

## 3. nginx 재적용
```bash
sudo nginx -t
sudo systemctl reload nginx
```
- `curl -I http://localhost/` → `200 OK` 또는 `TechWindow HTTP alive` 같은 응답이 나오는지 확인.

## 4. Certbot 실행
```bash
sudo certbot --nginx -d tc.o-r.kr
```
- 인증이 성공하면 `/etc/letsencrypt/live/tc.o-r.kr/`에 인증서가 생성됩니다.
- Certbot이 자동으로 HTTPS 리다이렉트 및 `ssl_certificate` 지시어를 수정했는지 확인합니다.

## 5. HTTPS 블록 복구 및 검증
발급이 끝나면 HTTP → HTTPS 리다이렉트를 다시 활성화합니다.

```nginx
server {
    listen 80;
    server_name tc.o-r.kr 43.203.93.244;
    return 301 https://$host$request_uri;
}
```

HTTPS 서버 블록(443)에 인증서 정보가 들어 있는지 확인하세요.

```nginx
server {
    listen 443 ssl http2;
    server_name tc.o-r.kr 43.203.93.244;

    ssl_certificate     /etc/letsencrypt/live/tc.o-r.kr/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tc.o-r.kr/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Gunicorn 프록시 등 기존 설정 추가
}
```

다시 `sudo nginx -t` → `sudo systemctl reload nginx`로 적용한 뒤, 아래를 검사합니다.
- `curl -I http://tc.o-r.kr` → 301 리다이렉트
- `curl -I https://tc.o-r.kr` → 200 OK

## 6. 인증 자동 갱신 확인
Certbot은 systemd timer(`certbot.timer`)를 통해 자동 갱신을 수행합니다. 필요 시 수동 갱신 테스트:

```bash
sudo certbot renew --dry-run
```

## 7. 문제 발생 시 체크
- `tail -f /var/log/letsencrypt/letsencrypt.log`
- `tail -f /var/log/nginx/error.log`
- 방화벽/보안 그룹 규칙 재확인
- DNS 전파 상태 확인 (TTL 고려)

---
이 문서를 따라가면 인증서 발급 과정을 재현하거나 상태를 점검하는 데 도움이 됩니다.