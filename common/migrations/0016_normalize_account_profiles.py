"""회원 번호·비밀번호·기록은 유지하고 예전 카카오 프로필의 빈 값만 보완해요."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import migrations


def normalize_profiles(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    Profile = apps.get_model('common', 'Profile')
    Identity = apps.get_model('common', 'SocialIdentity')
    Kakao = apps.get_model('common', 'KakaoUser')
    alias = schema_editor.connection.alias
    for user in User.objects.using(alias).all().iterator():
        profile, _ = Profile.objects.using(alias).get_or_create(user_id=user.pk)
        # 이름만 같은 일반 계정을 카카오 회원으로 취급하거나 연결을 만들어내지 않아요.
        identity = Identity.objects.using(alias).filter(user_id=user.pk, provider='kakao').first()
        if not identity or not identity.subject.isdigit() or user.username != f'kakao_{identity.subject}':
            continue
        legacy = Kakao.objects.using(alias).filter(kakao_id=int(identity.subject)).first()
        if not legacy:
            continue
        if not profile.nickname and legacy.nickname:
            profile.nickname = legacy.nickname.strip()[:30] or None
            profile.save(using=alias, update_fields=['nickname'])
        if not user.email or user.email.lower().endswith('@kakao.user'):
            email = (legacy.email or '').strip()
            try:
                validate_email(email)
                if len(email) > 254 or email.lower().endswith('@kakao.user'):
                    email = ''
            except ValidationError:
                email = ''
            if email:
                local, domain = email.rsplit('@', 1)
                email = local + '@' + domain.lower()
            user.email = email
            user.save(using=alias, update_fields=['email'])
        # 기존 토큰은 새 로그인에서 쓰지 않아요. 비밀값을 중복 보관하지 않아요.
        Kakao.objects.using(alias).filter(pk=legacy.pk).update(
            access_token='', refresh_token=None, token_expires_at=None)


class Migration(migrations.Migration):
    dependencies = [('common', '0015_socialidentity')]
    operations = [migrations.RunPython(normalize_profiles, migrations.RunPython.noop)]
