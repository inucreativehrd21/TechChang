from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('common', '0017_game_controls')]

    operations = [
        migrations.CreateModel(
            name='LogAnalysisReport',
            fields=[
                ('hours', models.PositiveIntegerField(primary_key=True, serialize=False)),
                ('period_end', models.DateTimeField()),
                ('metrics', models.JSONField(default=dict)),
                ('analysis', models.JSONField(default=dict)),
            ],
        ),
    ]
