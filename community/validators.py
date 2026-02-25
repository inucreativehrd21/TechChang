"""
파일 업로드 보안 검증
MIME 타입을 실제 파일 내용 기반으로 검증하여 악성 파일 업로드 방지
"""

from django.core.exceptions import ValidationError
from PIL import Image
import io


def validate_image_file(file):
    """
    이미지 파일 검증 (MIME 타입 + 확장자 + PIL 검증)

    보안 취약점:
    - 확장자만 검증하면 악성 파일을 .jpg로 위장 가능
    - MIME 타입 검증으로 실제 파일 내용 확인
    """
    # 허용 MIME 타입
    allowed_mime_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']

    # 파일 크기 제한 (5MB)
    max_size = 5 * 1024 * 1024
    if file.size > max_size:
        raise ValidationError(
            f'이미지 크기는 5MB를 초과할 수 없습니다. (현재: {file.size / 1024 / 1024:.1f}MB)'
        )

    # MIME 타입 검증 (실제 파일 내용 확인)
    try:
        # python-magic을 사용할 수 있다면 사용 (더 정확함)
        try:
            import magic
            mime = magic.from_buffer(file.read(2048), mime=True)
            file.seek(0)  # 파일 포인터 리셋

            if mime not in allowed_mime_types:
                raise ValidationError(
                    f'허용되지 않는 이미지 형식입니다. (업로드: {mime})\n'
                    f'허용 형식: JPEG, PNG, GIF, WebP'
                )
        except ImportError:
            # python-magic이 없으면 PIL로 검증
            pass
    except Exception as e:
        raise ValidationError('파일 형식을 확인할 수 없습니다.')

    # 확장자 검증
    allowed_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
    ext = file.name.lower().split('.')[-1] if '.' in file.name else ''
    if f'.{ext}' not in allowed_extensions:
        raise ValidationError(
            f'허용되지 않는 파일 확장자입니다: .{ext}\n'
            f'허용 확장자: {", ".join(allowed_extensions)}'
        )

    # PIL로 이미지 유효성 검증
    try:
        img = Image.open(file)
        img.verify()  # 이미지 파일 손상 여부 확인
        file.seek(0)  # verify() 후 파일 포인터 리셋

        # 이미지 해상도 제한 (메모리 폭탄 방지)
        max_dimension = 10000
        if img.width > max_dimension or img.height > max_dimension:
            raise ValidationError(
                f'이미지 해상도가 너무 큽니다. (최대: {max_dimension}x{max_dimension}px)\n'
                f'현재: {img.width}x{img.height}px'
            )

        # 메모리 폭탄 방지 (총 픽셀 수 제한)
        max_pixels = 100_000_000  # 1억 픽셀
        if img.width * img.height > max_pixels:
            raise ValidationError(
                f'이미지가 너무 큽니다. (픽셀 수: {img.width * img.height:,})'
            )

    except ValidationError:
        raise
    except Exception:
        raise ValidationError('유효하지 않은 이미지 파일입니다.')


def validate_question_file(file):
    """
    질문 첨부파일 검증 (안전한 형식만 허용)

    허용 형식:
    - 문서: PDF, Word, Excel, PowerPoint, 텍스트
    - 압축: ZIP
    """
    # 허용 MIME 타입
    allowed_mime_types = [
        'application/pdf',
        'application/msword',  # .doc
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
        'application/vnd.ms-excel',  # .xls
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
        'application/vnd.ms-powerpoint',  # .ppt
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',  # .pptx
        'text/plain',
        'application/zip',
        'application/x-zip-compressed',
        'application/x-hwp',  # .hwp (한글)
    ]

    # 파일 크기 제한 (20MB)
    max_size = 20 * 1024 * 1024
    if file.size > max_size:
        raise ValidationError(
            f'파일 크기는 20MB를 초과할 수 없습니다. (현재: {file.size / 1024 / 1024:.1f}MB)'
        )

    # MIME 타입 검증
    try:
        import magic
        mime = magic.from_buffer(file.read(2048), mime=True)
        file.seek(0)

        if mime not in allowed_mime_types:
            raise ValidationError(
                f'허용되지 않는 파일 형식입니다. (업로드: {mime})\n'
                f'허용 형식: PDF, Word, Excel, PowerPoint, 텍스트, ZIP, HWP만 가능합니다.'
            )
    except ImportError:
        # python-magic이 없으면 확장자만 검증
        allowed_extensions = [
            '.pdf', '.doc', '.docx', '.xls', '.xlsx',
            '.ppt', '.pptx', '.txt', '.zip', '.hwp'
        ]
        ext = file.name.lower().split('.')[-1] if '.' in file.name else ''
        if f'.{ext}' not in allowed_extensions:
            raise ValidationError(
                f'허용되지 않는 파일 확장자입니다: .{ext}\n'
                f'허용 확장자: {", ".join(allowed_extensions)}'
            )
    except ValidationError:
        raise
    except Exception:
        raise ValidationError('파일 형식을 확인할 수 없습니다.')
