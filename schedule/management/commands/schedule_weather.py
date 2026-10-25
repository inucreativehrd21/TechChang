"""기상청 단기예보를 받아 날씨 스냅샷을 저장한다.

cron 예시(서버 시간대 Asia/Seoul — 06·18시 발표 직후):
    10 6,18 * * *  cd ~/projects/mysite && ~/venvs/mysite/bin/python manage.py schedule_weather
SCHEDULE['KMA_SERVICE_KEY'] 가 비어 있으면 아무것도 하지 않고 끝난다.
"""
from urllib.error import URLError

from django.core.management.base import BaseCommand, CommandError

from schedule import conf, weather
from schedule.models import WeatherSnapshot

KEEP = 10


class Command(BaseCommand):
    help = '기상청 단기예보를 받아 며칠(일정) 날씨 스냅샷을 저장한다'

    def handle(self, *args, **options):
        if not conf.get('KMA_SERVICE_KEY'):
            self.stdout.write('KMA_SERVICE_KEY 미설정 — 건너뜀')
            return
        try:
            announced, days = weather.fetch()
        except (URLError, TimeoutError, OSError) as exc:
            raise CommandError(f'기상청 응답을 받지 못했습니다: {exc}') from exc
        if not days:
            raise CommandError('기상청 응답에 예보가 없어 저장하지 않았습니다.')
        WeatherSnapshot.objects.create(region=conf.get('WEATHER_REGION'), announced_at=announced, days=days)
        keep = list(WeatherSnapshot.objects.order_by('-fetched_at').values_list('pk', flat=True)[:KEEP])
        WeatherSnapshot.objects.exclude(pk__in=keep).delete()
        self.stdout.write(self.style.SUCCESS(f'저장했습니다: 발표 {announced}, {len(days)}일치'))
