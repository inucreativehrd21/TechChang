from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('community', '0051_lite_splits_press')]
    operations = [migrations.AddField(
        model_name='litecareer', name='mode',
        field=models.CharField(choices=[('lite', '라이트 모드'), ('extreme', '익스트림 모드')],
                               db_index=True, default='lite', db_default='lite', max_length=12),
    )]
