"""
django.contrib.sites 의 Site(id=1) 도메인을 techchang.com 으로 설정.
sitemap.xml / 절대 URL 생성이 example.com 으로 나오지 않도록 보정.
환경변수 SITE_DOMAIN 으로 재정의 가능.
"""
import os

from django.db import migrations


def set_site_domain(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    domain = os.environ.get('SITE_DOMAIN', 'techchang.com')
    Site.objects.update_or_create(
        id=1,
        defaults={'domain': domain, 'name': 'TechChang'},
    )


def revert_site_domain(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')
    Site.objects.filter(id=1).update(domain='example.com', name='example.com')


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0011_alter_emailverification_code_and_more'),
        ('sites', '0002_alter_domain_unique'),
    ]

    operations = [
        migrations.RunPython(set_site_domain, revert_site_domain),
    ]
