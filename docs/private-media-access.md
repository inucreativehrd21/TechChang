# 비공개 미디어 접근제어 (2026-11-07)

운영 Nginx 설정 파일 `/etc/nginx/sites-available/techchang`에는 다음 경로를
일반 `/media/` alias보다 앞에 별도 `^~` location으로 둔다.

- `/media/question_files/`
- `/media/questions/`
- `/media/answers/`
- `/media/comments/`
- `/media/portfolio/`

각 location의 `auth_request /_media_auth;`는 Django
`/media/_authorize/`에 원래 URI를 `X-Original-URI` 헤더로 전달한다.
`community/media_auth.py`가 DB 레코드의 공개 상태와 소유자를 확인해 204 또는
403을 반환한다. 허용 응답일 때만 Nginx가 파일을 제공한다. 원본 파일은
`Cache-Control: private, no-store`와 `X-Content-Type-Options: nosniff`로 제공하며
질문 첨부파일에는 `Content-Disposition: attachment`를 추가한다.

각 경로의 location 예시는 다음과 같다. `question_files`에는 attachment 헤더를
추가하고, 다른 네 경로에는 같은 형식을 경로에 맞게 적용한다.

```nginx
location ^~ /media/portfolio/ {
    alias /home/ubuntu/projects/mysite/media/portfolio/;
    auth_request /_media_auth;
    add_header Cache-Control "private, no-store" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Content-Security-Policy "default-src 'none'; sandbox" always;
}
```

내부 location은 다음처럼 외부 접근을 막는다.

```nginx
location = /media/_authorize/ { return 404; }
location = /_media_auth {
    internal;
    proxy_pass http://127.0.0.1:8000/media/_authorize/;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Original-URI $request_uri;
}
```

실제 설정은 `sudo nginx -t`를 통과한 뒤 `sudo systemctl reload nginx`로 적용한다.
새 미디어 업로드 경로를 추가할 때는 공개 여부를 먼저 검토하고, 비공개 가능성이
있으면 이 접근제어에 경로와 DB 조회 규칙을 함께 추가한다.
