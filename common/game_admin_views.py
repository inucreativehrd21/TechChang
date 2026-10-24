"""OTP로 보호하는 게임 운영 화면. 기능 설정·이력·읽기 전용 미리보기만 제공해요."""
from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.migrations.recorder import MigrationRecorder
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .game_controls import FEATURES, STORAGE_MIGRATION, environment_value, read_state
from .models import GameControlState, GameControlChange
from .views import admin_otp_required


class GameControlsForm(forms.Form):
    revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for spec in FEATURES:
            self.fields[spec['key']] = forms.ChoiceField(label=spec['label'], choices=[
                ('inherit', '환경 설정 사용'), ('on', '켜기'), ('off', '끄기')], widget=forms.RadioSelect)


def applied_migrations():
    return set(MigrationRecorder.Migration.objects.values_list('app', 'name'))


def _context(form=None):
    applied = applied_migrations()
    storage_ready = STORAGE_MIGRATION in applied
    state = read_state() if storage_ready else None
    overrides = state.overrides if state else {}
    initial = {'revision': state.revision if state else 0}
    for spec in FEATURES:
        value = overrides.get(spec['key'])
        initial[spec['key']] = 'on' if value is True else 'off' if value is False else 'inherit'
    form = form or GameControlsForm(initial=initial)
    features = []
    for spec in FEATURES:
        key = spec['key']
        value = overrides.get(key)
        base = environment_value(key)
        features.append(dict(spec, field=form[key], effective=value if type(value) is bool else base,
                             inherited=type(value) is not bool, environment=base, ready=spec['schema'] in applied))
    history = []
    if storage_ready:
        labels = {f['key']: f['label'] for f in FEATURES}
        words = {None: '환경 설정 사용', True: '켜기', False: '끄기'}
        for change in GameControlChange.objects.select_related('actor')[:20]:
            history.append({'at': change.created_at, 'actor': change.actor, 'revision': change.revision,
                            'items': [{'label': labels.get(k, k), 'before': words[v['before']], 'after': words[v['after']]}
                                      for k, v in change.changes.items()]})
    from community.models import LiteCareer, RookiePlayer
    stats = []
    if ('community', '0052_litecareer_mode') in applied:
        for mode, label in [('lite', '라이트'), ('extreme', '익스트림')]:
            careers = LiteCareer.objects.filter(mode=mode)
            stats.append({'label': label, 'active': careers.filter(retired_at__isnull=True).count(),
                          'finished': careers.filter(retired_at__isnull=False).count(),
                          'today': careers.filter(created_at__date=timezone.localdate()).count()})
    regular = RookiePlayer.objects.count() if ('community', '0044_rookie') in applied else None
    return {'form': form, 'features': features, 'storage_ready': storage_ready, 'state': state,
            'history': history, 'career_stats': stats, 'regular_count': regular}


@never_cache
@admin_otp_required
@require_http_methods(['GET', 'POST'])
def game_admin(request):
    if request.method == 'GET':
        return render(request, 'common/admin_games.html', _context())
    form = GameControlsForm(request.POST)
    if form.is_valid():
        applied = applied_migrations()
        if STORAGE_MIGRATION not in applied:
            form.add_error(None, '설정 저장소가 아직 준비되지 않았어요. 배포 준비를 먼저 완료해 주세요.')
        overrides = {}
        for spec in FEATURES:
            selected = form.cleaned_data[spec['key']]
            value = {'on': True, 'off': False, 'inherit': None}[selected]
            if value is not None:
                overrides[spec['key']] = value
            effective = environment_value(spec['key']) if value is None else value
            if effective and spec['schema'] not in applied:
                form.add_error(spec['key'], '이 기능의 DB 준비가 아직 끝나지 않았어요. 준비를 완료한 뒤 켜 주세요.')
        if not form.errors:
            with transaction.atomic():
                state, _created = GameControlState.objects.select_for_update().get_or_create(pk=1)
                if state.revision != form.cleaned_data['revision']:
                    form.add_error(None, '다른 관리자가 설정을 변경했어요. 새로고침해서 최신 설정을 확인해 주세요.')
                else:
                    changes = {f['key']: {'before': state.overrides.get(f['key']), 'after': overrides.get(f['key'])}
                               for f in FEATURES if state.overrides.get(f['key']) != overrides.get(f['key'])}
                    if changes:
                        state.overrides = overrides
                        state.revision += 1
                        state.updated_by = request.user
                        state.save()
                        GameControlChange.objects.create(changes=changes, revision=state.revision, actor=request.user)
            if not form.errors:
                messages.success(request, '게임 기능 설정을 저장했어요. 다음 요청부터 적용돼요.')
                return redirect('common:admin_games')
    response = render(request, 'common/admin_games.html', _context(form), status=409 if form.non_field_errors() else 400)
    return response


@never_cache
@admin_otp_required
def game_preview(request):
    from community.views.rookie_preview_views import rookie_preview
    request.rookie_admin_preview = True
    return rookie_preview(request)
