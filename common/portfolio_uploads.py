"""CSRF 폼 파싱 전에 대용량 포트폴리오 요청을 제한해요."""
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler, StopUpload, TemporaryFileUploadHandler
from django.http import HttpResponse
from django.urls import reverse
from django.utils.deprecation import MiddlewareMixin

from community.portfolio_security import MAX_HTML_BYTES, MAX_REQUEST_BYTES, consume_upload_budget


class PortfolioUploadHandler(FileUploadHandler):
    def __init__(self, request):
        super().__init__(request)
        self.total = self.files = 0

    def reject(self):
        self.request.portfolio_upload_too_large = True
        raise StopUpload(connection_reset=True)

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.files += 1
        self.received = 0
        self.limit = MAX_HTML_BYTES if self.field_name == 'html_file' else 5 * 1024 * 1024
        if self.files > 33 or self.field_name not in {'html_file', 'asset_files', 'hero_background_image', 'profile_image'}:
            self.reject()

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        self.total += len(raw_data)
        if self.received > self.limit or self.total > MAX_REQUEST_BYTES:
            self.reject()
        return raw_data

    def file_complete(self, file_size):
        return None


class PortfolioUploadMiddleware(MiddlewareMixin):
    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != 'POST' or request.resolver_match.view_name != 'community:portfolio_collection_edit':
            return None
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse('common:login'))
        from community.models import PortfolioCollection
        if not PortfolioCollection.objects.filter(user=request.user, slug=view_kwargs['slug']).exists():
            return HttpResponse('포트폴리오를 찾을 수 없어요.', status=404)
        try:
            length = int(request.META.get('CONTENT_LENGTH') or 0)
        except (ValueError, TypeError):
            return HttpResponse('올바르지 않은 요청 크기예요.', status=400)
        if length <= 0:
            return HttpResponse('요청 크기가 필요해요.', status=411)
        if length > MAX_REQUEST_BYTES:
            return HttpResponse('한 번에 최대 26MiB까지 전송할 수 있어요.', status=413)
        if not consume_upload_budget(request.user.pk):
            response = HttpResponse('저장 요청이 많아요. 10분 후 다시 시도해 주세요.', status=429)
            response['Retry-After'] = '600'
            return response
        # HTML을 파이썬 메모리에 전부 받은 뒤 검사하지 않고, 수신 중 검사하며 임시 파일에 써요.
        request.upload_handlers = [PortfolioUploadHandler(request), TemporaryFileUploadHandler(request)]
        try:
            request.POST
        except RequestDataTooBig:
            return HttpResponse('요청 내용이 너무 커요.', status=413)
        if getattr(request, 'portfolio_upload_too_large', False):
            for files in request.FILES.lists():
                for upload in files[1]:
                    upload.close()
            return HttpResponse('HTML은 20MiB, 사진은 각각 5MiB까지 올릴 수 있어요.', status=413)
        return None
