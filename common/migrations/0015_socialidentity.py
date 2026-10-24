from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def legacy_kakao(apps, schema_editor):
    Identity = apps.get_model('common', 'SocialIdentity')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))
    Kakao = apps.get_model('common', 'KakaoUser')
    alias = schema_editor.connection.alias
    for kakao_id in Kakao.objects.using(alias).values_list('kakao_id', flat=True).iterator():
        user = User.objects.using(alias).filter(username=f'kakao_{kakao_id}', is_active=True).first()
        if user:
            Identity.objects.using(alias).get_or_create(provider='kakao', subject=str(kakao_id),
                                                        defaults={'user_id': user.pk})


class Migration(migrations.Migration):
    dependencies = [('common', '0014_profile_terms_consent'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='SocialIdentity', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('provider', models.CharField(choices=[('kakao', '카카오'), ('google', 'Google')], max_length=16)),
            ('subject', models.CharField(max_length=255)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='social_identities', to=settings.AUTH_USER_MODEL)),
        ], options={'constraints': [
            models.UniqueConstraint(fields=('provider', 'subject'), name='social_provider_subject_unique'),
            models.UniqueConstraint(fields=('user', 'provider'), name='social_user_provider_unique'),
        ]}),
        migrations.RunPython(legacy_kakao, migrations.RunPython.noop),
    ]
