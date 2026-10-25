"""기상청 단기예보(apihub 육상예보 fct_afs_dl) → 날짜별 요약.

화면은 이 모듈을 직접 부르지 않는다. `manage.py schedule_weather`(cron)가 받아 WeatherSnapshot 에 저장하고
화면은 저장된 것만 읽는다 — 요청마다 기상청을 부르면 응답 지연·타임아웃이 그대로 화면에 번진다.
출처 표시(이용허락 조건): 날씨를 보여 주는 곳에 '기상청 단기예보'를 함께 적는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen

from django.utils import timezone

from . import conf

KMA_FCST_URL = 'https://apihub.kma.go.kr/api/typ01/url/fct_afs_dl.php'

SKY_LABELS = {'DB01': '맑음', 'DB02': '구름조금', 'DB03': '구름많음', 'DB04': '흐림'}
PREP_LABELS = {'0': '', '1': '비', '2': '비/눈', '3': '눈', '4': '소나기'}
ICONS = {
    'sunny': 'schedule/weather/01_sunny.svg',
    'partly_cloudy': 'schedule/weather/02_partly_cloudy.svg',
    'overcast': 'schedule/weather/03_overcast.svg',
    'rain': 'schedule/weather/04_rain.svg',
    'rain_snow': 'schedule/weather/05_rain_snow.svg',
    'snow': 'schedule/weather/06_snow.svg',
    'shower': 'schedule/weather/07_shower.svg',
}


def _icon(sky: str, prep: str) -> str:
    by_prep = {'1': 'rain', '2': 'rain_snow', '3': 'snow', '4': 'shower'}
    if prep in by_prep:
        return ICONS[by_prep[prep]]
    if sky in ('DB03', 'DB04'):
        return ICONS['overcast']
    if sky == 'DB02':
        return ICONS['partly_cloudy']
    return ICONS['sunny']


def _condition(sky: str, prep: str) -> str:
    return PREP_LABELS.get(prep, '') or SKY_LABELS.get(sky, '날씨 정보')


def _to_int(value: str) -> int | None:
    if value in ('-99', ''):
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def announce_window(now: datetime) -> tuple[str, str]:
    """직전 발표시각(tmfc1)~다음 발표시각(tmfc2). 단기 육상예보는 06시·18시 발표, 발표 직후 지연에 대비해 한 회 앞까지 넓힌다."""
    ref = now - timedelta(minutes=30)
    if ref.hour >= 18:
        ann = ref.replace(hour=18, minute=0, second=0, microsecond=0)
        prev = ann.replace(hour=6)
    elif ref.hour >= 6:
        ann = ref.replace(hour=6, minute=0, second=0, microsecond=0)
        prev = (ann - timedelta(days=1)).replace(hour=18)
    else:
        ann = (ref - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        prev = ann.replace(hour=6)
    return prev.strftime('%Y%m%d%H%M'), (ann + timedelta(hours=12)).strftime('%Y%m%d%H%M')


def parse_rows(text: str, reg_id: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split()
        # 컬럼: REG_ID TM_FC TM_EF MOD NE STN C MAN_ID MAN_FC W1 T W2 TA ST SKY PREP WF...
        if len(parts) < 16 or parts[0] != reg_id:
            continue
        rows.append({'tm_fc': parts[1], 'tm_ef': parts[2], 'ta': parts[12], 'st': parts[13],
                     'sky': parts[14], 'prep': parts[15]})
    return rows


def summarize(rows: list[dict]) -> tuple[str, dict]:
    """(최신 발표시각, {'YYYY-MM-DD': {...}}). 하늘·강수확률은 최신 발표 기준, 기온은 발효시각별 최신 유효값으로
    채운다 — 이미 시작된 12시간 구간의 기온은 최신 발표가 -99(결측)로 내므로 직전 발표 값으로 복구한다."""
    if not rows:
        return '', {}
    latest_fc = max(r['tm_fc'] for r in rows)
    latest = [r for r in rows if r['tm_fc'] == latest_fc]
    ta_by_ef: dict[str, int] = {}
    for r in sorted(rows, key=lambda r: r['tm_fc']):
        t = _to_int(r['ta'])
        if t is not None:
            ta_by_ef[r['tm_ef']] = t

    by_date: dict[str, list[dict]] = {}
    for r in latest:
        by_date.setdefault(f"{r['tm_ef'][:4]}-{r['tm_ef'][4:6]}-{r['tm_ef'][6:8]}", []).append(r)

    days = {}
    for iso, day_rows in sorted(by_date.items()):
        temps = [ta_by_ef[r['tm_ef']] for r in day_rows if r['tm_ef'] in ta_by_ef]
        probs = [p for r in day_rows if (p := _to_int(r['st'])) is not None]
        rep = next((r for r in day_rows if r['tm_ef'][8:12] == '1200'),
                   next((r for r in day_rows if r['tm_ef'][8:12] == '0000'), day_rows[0]))
        low, high = (min(temps), max(temps)) if temps else (None, None)
        days[iso] = {
            'condition': _condition(rep['sky'], rep['prep']),
            'icon': _icon(rep['sky'], rep['prep']),
            'temp_low': low if low != high else None,     # 한 구간만 남은 날은 최저를 비운다
            'temp_high': high,
            'rain_prob': max(probs) if probs else None,
        }
    return latest_fc, days


def fetch(now: datetime | None = None, *, timeout: int = 10) -> tuple[str, dict]:
    key = conf.get('KMA_SERVICE_KEY')
    if not key:
        raise RuntimeError('KMA_SERVICE_KEY 가 설정되지 않았습니다.')
    reg_id = conf.get('KMA_REG_ID')
    now = timezone.localtime(now) if now else timezone.localtime()
    tmfc1, tmfc2 = announce_window(now)
    url = f"{KMA_FCST_URL}?{urlencode({'reg': reg_id, 'tmfc1': tmfc1, 'tmfc2': tmfc2, 'disp': '0', 'help': '0', 'authKey': key})}"
    with urlopen(url, timeout=timeout) as resp:  # noqa: S310 — 고정 https 주소
        text = resp.read().decode('euc-kr', errors='replace')
    return summarize(parse_rows(text, reg_id))
