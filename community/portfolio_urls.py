"""공개 주소는 표시 이름을 사용하고 저장된 슬러그는 호환·관리 주소로 유지해요."""
from urllib.parse import unquote, urlsplit

from django.urls import reverse
from django.utils.text import slugify


def portfolio_key(portfolio):
    return ('collection' if portfolio._meta.model_name == 'portfoliocollection' else 'legacy', portfolio.pk)


def public_portfolio_urls():
    from .models import Portfolio, PortfolioCollection

    collections = list(PortfolioCollection.objects.filter(
        is_published=True, approval_status='approved',
    ).select_related('user').only('pk', 'display_name', 'is_main', 'user_id', 'user__username'))
    legacy = list(Portfolio.objects.filter(is_public=True, approval_status='approved').select_related('user')
                  .only('pk', 'display_name', 'user_id', 'user__username'))
    # 비공개 포트폴리오의 기존 주소와도 충돌하지 않게 해요.
    reserved = {slug: ('collection', pk) for pk, slug in PortfolioCollection.objects.values_list('pk', 'slug')}
    entries = sorted(collections + legacy, key=lambda obj: (
        not getattr(obj, 'is_main', False), portfolio_key(obj)[0] != 'collection', obj.pk,
    ))
    used = {'create', 'edit', 'request-publish'}
    result = {}
    for portfolio in entries:
        key = portfolio_key(portfolio)
        base = slugify(portfolio.get_display_name().strip(), allow_unicode=True)[:150] or 'portfolio'
        slug = base
        suffix = 0
        while slug in used or (slug in reserved and reserved[slug] != key):
            suffix += 1
            slug = f'{base}-{portfolio.pk}' + (f'-{suffix}' if suffix > 1 else '')
        used.add(slug)
        result[key] = reverse('community:portfolio_collection_detail', args=[slug])
    return result


def portfolio_url(portfolio, urls=None):
    if hasattr(portfolio, '_public_url'):
        return portfolio._public_url
    if portfolio.is_publicly_visible():
        result = (public_portfolio_urls() if urls is None else urls).get(portfolio_key(portfolio))
        if result:
            return result
    if portfolio_key(portfolio)[0] == 'collection':
        return reverse('community:portfolio_collection_detail', args=[portfolio.slug])
    return reverse('community:portfolio_view', args=[portfolio.user_id])


def named_portfolio(slug):
    from .models import Portfolio, PortfolioCollection

    urls = public_portfolio_urls()
    for (kind, pk), url in urls.items():
        if unquote(urlsplit(url).path).rstrip('/').rsplit('/', 1)[-1] == slug:
            model = PortfolioCollection if kind == 'collection' else Portfolio
            queryset = model.objects.select_related('user')
            if kind == 'collection':
                queryset = queryset.defer('html_content')
            portfolio = queryset.filter(pk=pk).first()
            if portfolio is None:
                return None
            portfolio._public_url = url
            return portfolio
    return None
