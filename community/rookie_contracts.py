"""MLB 계약의 권리와 실제 선수 경로. CBA 전체가 아니라 시즌 단위 게임 규칙이에요.

연봉 보장과 마이너 거부권을 분리한다. 기존 계약에는 새 불이익을 소급하지 않는다.
실제 근거·게임 근사 범위는 rookie_mlb_contracts.md에 기록한다.
"""
from . import rookie_world as W


def terms(deal):
    d = dict(deal)
    if d.get('system') == 'mlb':
        d.setdefault('minor_veto', False)
        d.setdefault('split', False)
        d.setdefault('minor_annual', min(6000, int(d['annual'] * .12)))
        d.setdefault('player_opt_out', False)
        d.setdefault('roster_pressure', .1)
    return d


def signed(deal, season):
    d = terms(deal)
    keys = ('system', 'team', 'years', 'annual', 'role', 'minor_veto', 'split', 'minor_annual',
            'player_opt_out', 'roster_pressure', 'entry_league')
    return dict({k: d[k] for k in keys if k in d}, version=2, signed_season=season, elapsed=0,
                last_season=season)


def active(p):
    from . import rookie_story as S
    d = S.state(p).get('contract') or {}
    return d if (not getattr(p, 'retired_at', None) and d.get('version') == 2 and d.get('system') == 'mlb' and d.get('years', 0) > 0
                 and d.get('team') == p.club and W.system_of(p.league) == 'mlb') else None


def veto(p):
    from . import rookie_story as S
    d = active(p)
    return bool(d and (d.get('minor_veto') or S.state(p).get('mlb_service', 0) >= 5))


def camp_risk(p, deal=None):
    from . import rookie_story as S
    d = deal or active(p) or {}
    return S.clamp(.32 + (W.level('mlb') - p.ovr) * .055 + d.get('roster_pressure', .1)
                   + (50 - S.value(p, 'trust')) * .002, .04, .85)


def assignment_choices(p):
    out = [dict(key='accept', label='트리플A에서 다시 증명할게요', tone='마이너 수용',
                hint='MLB 등록 기간인 서비스타임이 쌓이지 않아요. 스플릿 계약이면 마이너 체류 기간의 연봉도 줄어요')]
    if veto(p):
        out.append(dict(key='refuse', label='마이너 거부권을 행사할게요', tone='권리 행사',
                        hint='마이너행은 막지만 MLB에서 벤치·롱릴리프 역할을 맡아요. 출전과 성장 기회가 줄 수 있어요'))
    else:
        out.append(dict(key='appeal', label='에이전트를 통해 재고를 요청할게요', tone='보장 없는 호소',
                        hint='거부할 권리는 없어요. 실력·감독 신뢰에 따라 번복되기도 하지만 실패하면 트리플A로 가요'))
    return out


def assignment_view(p, event_id='', phase='mid'):
    return dict(id=event_id, kind='assignment', background='manager-office', title='구단이 트리플A행을 통보했어요',
                text=('에이전트가 계약서를 펼쳤어요. 마이너 거부권이 있어 동의 없이 내려보낼 수 없어요. 다만 주전 출전은 보장하지 않아요.'
                      if veto(p) else '계약서에 마이너 거부권이 없어요. 구단은 로스터 경쟁에서 밀린 선수를 내려보낼 수 있어요.'),
                choices=assignment_choices(p), contract_terms=summary(p), phase=phase)


def assignment_reply(p, choice, rng, season):
    from . import rookie_story as S
    if not active(p) or choice not in {c['key'] for c in assignment_choices(p)}:
        raise ValueError('현재 계약에서 가능한 선택지를 골라 주세요.')
    keep = choice == 'refuse'
    if choice == 'appeal':
        keep = rng.random() < S.clamp(.15 + (p.ovr - W.level('mlb')) * .035
                                      + (S.value(p, 'trust') - 50) * .003, .05, .6)
    data = S.state(p)
    if keep:
        data['mlb_bench_season'] = season
        text = 'MLB 로스터에 남았지만 벤치·롱릴리프 역할을 맡아요. 거부권은 출전 시간을 보장하지 않아요.'
    else:
        data.pop('mlb_bench_season', None)
        p.league = 'mlb_aaa'
        text = '트리플A로 내려갔어요. MLB 서비스타임이 멈추고, MLB 무대의 수상·성적 기회도 줄어요.'
        if active(p).get('split'):
            text += ' 스플릿 계약이라 마이너 체류 기간에는 낮은 연봉을 받아요.'
    S.put(p, data)
    return S.change(p, text, confidence=-3 if keep else -8)


def bench_role(p):
    return ('bench', 0, 'MLB 벤치 대기') if p.role == 'batter' else ('mop', 0, 'MLB 롱릴리프')


def transfer(p, club):
    from . import rookie_story as S
    d = active(p)
    if d:
        data = S.state(p)
        data['contract'] = dict(d, team=club)
        S.put(p, data)
    p.club = club


def salary(deal, splits=None, league='mlb'):
    """시즌을 나눈 여섯 구간의 등록 비율로 지급. 출전하지 않은 벤치도 MLB 급여예요."""
    if not deal.get('split'):
        return int(deal['annual'])
    rows = splits or [{'league': league, 'from': 0, 'to': 6}]
    share = sum((r['to'] - r['from']) / 6 for r in rows if r['league'] == 'mlb')
    return round(deal['annual'] * share + deal['minor_annual'] * (1 - share))


def finish_lite(p, season, flags):
    d = active(p)
    if not d:
        return
    rows = season.splits or [{'league': season.league, 'from': 0, 'to': 6}]
    service = sum((r['to'] - r['from']) / 6 for r in rows if r['league'] == 'mlb')
    flags['mlb_service'] = round(flags.get('mlb_service', 0) + service, 4)
    if service < 1:
        season.news.append(f'MLB 등록 {round(service * 100)}% — 마이너 체류 기간에는 MLB 서비스타임이 쌓이지 않았어요.')
    if d.get('split'):
        season.news.append('스플릿 계약을 적용해 MLB·마이너 등록 구간별로 연봉을 정산했어요.')
    d['elapsed'] = d.get('elapsed', 0) + 1
    flags['contract'] = d


def can_opt_out(p):
    d = active(p)
    return bool(d and d.get('player_opt_out') and d.get('elapsed', 0) >= 1
                and d.get('optout_seen', -1) != d['elapsed'])


def optout_view(p, event_id=''):
    return dict(kind='contract_optout', id=event_id, background='negotiation-room', title='옵트아웃 권리를 쓸 수 있어요',
                text='계약을 유지하면 남은 연봉을 지켜요. 시장에 나가면 남은 보장액을 포기하고 관심 구단 세 곳 중 한 곳과 새 계약을 시도해요. 결렬되면 KBO에서 다시 시작해야 해요.',
                contract_terms=summary(p), choices=[
                    dict(key='keep', label='현재 계약을 유지할게요', tone='보장액 유지', hint='같은 구단과 남은 계약 기간을 보내요'),
                    dict(key='market', label='옵트아웃하고 새 계약을 찾을게요', tone='FA 시장 도전', hint='남은 보장액을 포기해요. 높은 몸값과 계약 실패 위험을 함께 떠안아요')])


def optout_reply(p, choice):
    from . import rookie_story as S
    if not can_opt_out(p) or choice not in ('keep', 'market'):
        raise ValueError('지금은 옵트아웃을 결정할 수 없어요.')
    data = S.state(p)
    d = dict(data['contract'])
    if choice == 'keep':
        d['optout_seen'] = d['elapsed']
        data['contract'] = d
        S.put(p, data)
        return '현재 계약을 유지해요. 남은 보장 연봉과 소속 구단은 그대로예요.'
    data['last_contract'] = dict(d, ended='optout')
    data.pop('contract', None)
    data.pop('mlb_bench_season', None)
    data.pop('pin', None)
    S.put(p, data)
    return '옵트아웃했어요. 남은 보장 연봉을 포기하고 새 계약을 찾아요.'


def summary(p=None, deal=None):
    from . import rookie_story as S
    d = deal or (active(p) if p is not None else None)
    if not d or d.get('system') != 'mlb':
        return None
    return dict(d, veto=bool(d.get('minor_veto') or (p is not None and S.state(p).get('mlb_service', 0) >= 5)),
                service=round(S.state(p).get('mlb_service', 0), 2) if p is not None else 0,
                risk=round(camp_risk(p, d) * 100) if p is not None else 0)


def roll_full(p, season):
    from . import rookie_story as S
    d = active(p)
    if not d or season <= d.get('last_season', season):
        return
    n = season - d['last_season']
    d = dict(d, years=d['years'] - n, elapsed=d.get('elapsed', 0) + n, last_season=season)
    data = S.state(p)
    if d['years'] > 0:
        data['contract'] = d
    else:
        data['last_contract'] = dict(d, ended='expired')
        data.pop('contract', None)
    S.put(p, data)


def expiry_market(p, rng, day=None):
    """계약 만료 뒤 옛 구단에서 무계약으로 계속 뛰지 않는다. 새 제안 중 하나를 고른다."""
    from . import rookie_story as S
    data = S.state(p)
    last = data.get('last_contract') or {}
    marker = f'{last.get("team")}:{last.get("signed_season")}'
    if (last.get('ended') != 'expired' or last.get('system') != 'mlb' or active(p)
            or W.system_of(p.league) != 'mlb' or data.get('contract_market_seen') == marker):
        return None
    data['contract_market_seen'] = marker
    data.pop('move', None)  # 이전 구단의 콜업 예약이 새 국가 계약 뒤 실행되지 않게 한다.
    data.pop('assignment_pending', None)
    data.pop('mlb_bench_season', None)
    data.pop('pin', None)
    p.league, p.club = 'kbo2', p.team
    S.put(p, data)
    if day is not None:
        from . import rookie_career as C
        p.league_since = day
        C._reset_role(p, day)
        C._path(p, p.league, p.club, day)
    return dict(kind='posting', offers=S.posting_offers(p, rng), origin='expiry')


def full_assignment(p, day, rng):
    from . import rookie_league as L
    from . import rookie_career as C
    from . import rookie_story as S
    import secrets
    season = L.season_no(day)
    roll_full(p, season)
    expired = expiry_market(p, rng, day)
    if expired:
        data = S.state(p)
        data['story_pending'] = dict(expired, id=secrets.token_hex(8))
        S.put(p, data)
        p.save(update_fields=['career', 'league', 'club', 'league_since', 'lineup', 'slot', 'role_since'])
        return
    d, data = active(p), S.state(p)
    if not d or p.league != 'mlb' or data.get('mlb_camp_season') == season or data.get('mlb_bench_season') == season:
        return
    data['mlb_camp_season'] = season
    S.put(p, data)
    if rng.random() < camp_risk(p):
        if veto(p):
            data.setdefault('assignment_pending', assignment_view(p, secrets.token_hex(8)))
            S.put(p, data)
        else:
            assignment_reply(p, 'accept', rng, season)
            p.league_since = day
            C._reset_role(p, day)
            C._path(p, p.league, p.club, day)
    p.save(update_fields=['career', 'league', 'league_since', 'lineup', 'slot', 'role_since'])


def full_service(p, day):
    from . import rookie_story as S
    from . import rookie_league as L
    if not active(p):
        return
    data = S.state(p)
    if data.get('mlb_service_day', '') >= day.isoformat():
        return
    data['mlb_service_day'] = day.isoformat()
    if p.league == 'mlb':
        data['mlb_service_days'] = data.get('mlb_service_days', round(data.get('mlb_service', 0) * L.SEASON_DAYS)) + 1
        data['mlb_service'] = data['mlb_service_days'] / L.SEASON_DAYS
    # 정식 판엔 현금 상점이 없으므로 계약 수입은 경력 장부로만 표시한다.
    pay = salary(active(p), league=p.league) / L.SEASON_DAYS
    data['mlb_contract_income'] = round(data.get('mlb_contract_income', 0) + pay, 2)
    S.put(p, data)
