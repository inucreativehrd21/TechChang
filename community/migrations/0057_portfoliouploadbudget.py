from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('community', '0056_column_editorial_tracks'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(
        name='PortfolioUploadBudget',
        fields=[
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False, to=settings.AUTH_USER_MODEL)),
            ('window_start', models.DateTimeField()),
            ('requests', models.PositiveSmallIntegerField(default=0)),
        ],
    )]
