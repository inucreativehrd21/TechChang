# 정식 판 시간대별 경기(rookie_clock) — 그날 어느 시각 경기까지 치렀는지

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('community', '0054_liteseason_env'),
    ]

    operations = [
        migrations.AddField(
            model_name='rookieseason',
            name='slot_through',
            field=models.DateTimeField(blank=True, null=True, verbose_name='경기 진행 시각'),
        ),
    ]
