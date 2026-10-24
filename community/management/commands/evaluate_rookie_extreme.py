"""격리된 임시 SQLite DB에서 모드별 동일 시드 커리어를 끝까지 비교해요."""
from collections import Counter, defaultdict
import json
from pathlib import Path
import random
import re
import statistics
import time

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.test.utils import override_settings, setup_databases, teardown_databases

from community import rookie_extreme as E
from community import rookie_extreme_preview as P
from community import rookie_lite as X
from community import rookie_modes as Modes
from community import rookie_league as L
from community import rookie_world as W
from community.models import LiteCareer


def evaluate_pair(index, seed):
    records = []
    temporary_users = []
    role = 'pitcher' if index % 2 else 'batter'
    for mode in (Modes.LITE, Modes.EXTREME):
        with transaction.atomic():
            user = User.objects.create_user(f'extreme-eval-{index}-{mode}', password=None, is_staff=True)
            temporary_users.append(user.pk)
            c = X.create(user, mode=mode, name='검증선수', role=role, position='SP' if role == 'pitcher' else 'SS',
                         style=next(iter(X.STYLES[role])), region='서울', team='lg', rng=random.Random(seed))
            initial = dict(ovr=c.ovr, potential=c.potential)
            c.flags['evaluation_seed'] = seed
            if Modes.is_extreme(c):
                c.flags['extreme']['seed'] = seed
            c.save()
            for _ in range(80):
                if c.retired_at:
                    break
                event = E.event_view(c)
                if event:
                    choices = event['choices']
                    picked = next((x for x in choices if x['contest']), choices[index % len(choices)])
                    E.resolve(c.pk, user, event['id'], picked['key'], P.random_for(c, 'event'))
                    c.refresh_from_db()
                P.advance(c, P.token(c), allow_lite=True)
            if not c.retired_at:
                raise E.ExtremeError(f'{mode}/{role}/{seed}: 커리어가 종료되지 않았어요.')
            if c.mode != mode or any(not 25 <= float(v) <= 99 for v in c.stats.values()):
                raise E.ExtremeError('모드 또는 능력치 범위가 달라졌어요.')
            seasons = list(c.seasons.all())
            history = ((c.flags or {}).get('extreme') or {}).get('history', [])
            for season in seasons:
                t = season.totals or {}
                if role == 'batter' and not 0 <= t.get('hr', 0) <= t.get('h', 0) <= t.get('ab', 0) <= t.get('pa', 0):
                    raise E.ExtremeError('타격 기록의 범위가 깨졌어요.')
                if role == 'pitcher' and (t.get('w', 0) + t.get('l', 0) > t.get('g', 0) or t.get('outs', 0) > t.get('g', 0) * 27):
                    raise E.ExtremeError('투구 기록의 범위가 깨졌어요.')
            pro = [s for s in seasons if W.is_pro(s.league)]
            qualified = [s for s in pro if (s.totals or {}).get('ab' if role == 'batter' else 'outs', 0) >= (100 if role == 'batter' else 90)]
            rates = [L.batting(s.totals)['avg'] if role == 'batter' else L.pitching(s.totals)['era'] for s in qualified]
            injuries = [int(n) for s in seasons for text in s.news for n in re.findall(r'(\d+)경기를 쉬었어요', text)]
            records.append(dict(mode=mode, role=role, seed=seed, initial=initial, seasons=len(seasons),
                                retired_age=c.age, best_ovr=c.best_ovr, war=c.war, earnings=c.earnings,
                                peak=c.peak, max_season_war=max((s.war for s in seasons), default=0),
                                event_count=len(history), event_keys=sorted({h['key'] for h in history}),
                                leagues=dict(Counter(s.league for s in seasons)),
                                injury_episodes=len(injuries), injury_missed_games=sum(injuries),
                                qualified_pro_seasons=len(qualified), rate_mean=statistics.mean(rates) if rates else None,
                                rate_min=min(rates) if rates else None, rate_max=max(rates) if rates else None,
                                contests=dict(Counter('win' if h['success'] else 'loss' for h in history if h['success'] is not None))))
    # 각 시드는 독립된 실험이에요. 앞선 가상 실험이 뒤 실험의 회원 경쟁자로 들어가지 않게 해요.
    User.objects.filter(pk__in=temporary_users).delete()
    return records


class Command(BaseCommand):
    help = '비공개 익스트림 시제품을 임시 SQLite DB에서 비교해요. 운영 DB에서는 실행하지 않아요.'

    def add_arguments(self, parser):
        parser.add_argument('--pairs', type=int, default=4)
        parser.add_argument('--seed', type=int, default=20261024)
        parser.add_argument('--output', default='community/reports/rookie-extreme-preview.json')
        parser.add_argument('--allow-preview', action='store_true')

    def handle(self, *args, **opts):
        if not opts['allow_preview']:
            raise CommandError('로컬 시제품 실행에는 --allow-preview를 명시해 주세요.')
        if connection.vendor != 'sqlite' or str(settings.SETTINGS_MODULE).endswith('.prod'):
            raise CommandError('임시 SQLite 검사만 허용해요. 운영 DB에서는 실행하지 않아요.')
        if not 1 <= opts['pairs'] <= 2000 or not 0 <= opts['seed'] <= 2**32 - 1:
            raise CommandError('pairs는 1~2000, seed는 0~4294967295 범위로 지정해 주세요.')
        config = setup_databases(verbosity=0, interactive=False)
        started = time.monotonic()
        records = []
        try:
            with override_settings(ROOKIE_EXTREME_PREVIEW=True):
                for i in range(opts['pairs']):
                    records.extend(evaluate_pair(i, opts['seed'] + i))
                    self.stdout.write(f'{i + 1}/{opts["pairs"]} 쌍 완료')
            groups = defaultdict(list)
            for row in records:
                groups[row['mode'] + ':' + row['role']].append(row)
            summary = {key: dict(count=len(rows), mean_start_ovr=round(statistics.mean(r['initial']['ovr'] for r in rows), 2),
                                 mean_best_ovr=round(statistics.mean(r['best_ovr'] for r in rows), 2),
                                 mean_seasons=round(statistics.mean(r['seasons'] for r in rows), 2),
                                 mean_war=round(statistics.mean(r['war'] for r in rows), 2),
                                 max_season_war=max(r['max_season_war'] for r in rows)) for key, rows in groups.items()}
            report = dict(kind='private-prototype-full-career-smoke', release_approved=False,
                          pairs=opts['pairs'], seed=opts['seed'], seconds=round(time.monotonic() - started, 2),
                          summary=summary, records=records,
                          observed_events=sorted({key for row in records for key in row['event_keys']}))
            target = Path(opts['output'])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            self.stdout.write(json.dumps(summary, ensure_ascii=False))
        finally:
            teardown_databases(config, verbosity=0)
