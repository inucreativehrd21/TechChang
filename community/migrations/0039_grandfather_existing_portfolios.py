from django.db import migrations


def approve_existing_public(apps, schema_editor):
    """
    승인제 도입 이전부터 공개되어 있던 포트폴리오는 기존 노출을 유지하기 위해
    '승인됨' 상태로 처리한다. 비공개 상태였던 것은 '작성 중'으로 둔다.
    """
    Portfolio = apps.get_model('community', 'Portfolio')
    PortfolioCollection = apps.get_model('community', 'PortfolioCollection')

    Portfolio.objects.filter(is_public=True).update(approval_status='approved')
    PortfolioCollection.objects.filter(is_published=True).update(approval_status='approved')


def revert(apps, schema_editor):
    Portfolio = apps.get_model('community', 'Portfolio')
    PortfolioCollection = apps.get_model('community', 'PortfolioCollection')
    Portfolio.objects.update(approval_status='draft')
    PortfolioCollection.objects.update(approval_status='draft')


class Migration(migrations.Migration):

    dependencies = [
        ('community', '0038_portfolio_approval_requested_at_and_more'),
    ]

    operations = [
        migrations.RunPython(approve_existing_public, revert),
    ]
