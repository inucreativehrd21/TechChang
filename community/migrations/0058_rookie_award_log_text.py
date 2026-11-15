"""시즌 1 시상 기록 문구 정리 — '시즌 1 중학 중학 최우수선수 수상'처럼 리그 이름이 두 번 붙은 수상 기록을 한 번으로.
상 이름(label)이 이미 리그 이름으로 시작하는데 기록을 남길 때 리그 이름을 또 붙였다(rookie_league.award_title 로 수정).
수상 기록(kind='award')만, 같은 리그 이름이 연달아 두 번 나오는 경우만 고친다 — 다시 실행해도 결과가 같다."""
from django.db import migrations


def dedupe(apps, schema_editor):
    from community import rookie_world as W
    RookieLog = apps.get_model('community', 'RookieLog')
    shorts = sorted({v['short'] for v in W.LEAGUES.values()}, key=len, reverse=True)
    for log in RookieLog.objects.filter(kind='award', text__startswith='시즌 '):
        text = log.text
        for lg in shorts:
            twice = f' {lg} {lg} '
            if twice in text:
                text = text.replace(twice, f' {lg} ', 1)
                break
        if text != log.text:
            RookieLog.objects.filter(pk=log.pk).update(text=text)


class Migration(migrations.Migration):
    dependencies = [('community', '0057_portfoliouploadbudget')]
    operations = [migrations.RunPython(dedupe, migrations.RunPython.noop)]
