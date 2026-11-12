"""두 편집 유형의 기획·집필·독립 심사 계약. 새 모델 호출은 추가하지 않는다."""
from contextlib import contextmanager
from contextvars import ContextVar
from community.column_tracks import RESEARCH, PRACTICAL, TRACKS, TRACK_CHOICES

_track = ContextVar('column_track', default='')
LABELS = dict(TRACK_CHOICES)
CRITERIA = {
    RESEARCH: {
        'question': '학술·기술적 탐구 질문과 기존 설명에서 남은 쟁점',
        'sources': '논문·공식 기술 문서·원자료를 직접 대조한 근거와 방법',
        'mechanism': '결과를 만드는 동작 원리·인과 경로 또는 방법론',
        'limits': '대안과의 비교·반례·연구 또는 기술의 한계와 성립 조건',
    },
    PRACTICAL: {
        'problem': '독자가 해결할 구체적인 생활·업무 문제',
        'steps': '독자가 실행할 수 있는 절차·계산 또는 선택 기준',
        'conditions': '적용 대상·예외·주의할 조건',
    },
}


def current_track():
    return _track.get()


@contextmanager
def use_track(track):
    if track not in ('', *TRACKS):
        raise ValueError('올바른 칼럼 유형을 지정해 주세요.')
    token = _track.set(track)
    try:
        yield
    finally:
        _track.reset(token)


def guidance():
    track = current_track()
    if not track:
        return ''
    base = '\n\n[편집 유형: '+LABELS[track]+']\n'
    if track == RESEARCH:
        return base + (
            '검색량·트래픽과 독립적으로 학문적·기술적 중요성으로 주제를 고르세요. 학술 연구, 실제 기술 변화, '
            '기초 원리의 심화 탐구 중 하나를 다루되 생활 요령·지원금·절약 팁으로 바꾸지 마세요. '
            '연구 질문→1차 자료의 방법·조건→원리→대안 비교와 한계→의미를 연결하세요. '
            '논문·공식 기술 문서·표준·공개 원자료 등 실제로 열어 본 1차 자료 2개 이상을 대조하세요. '
            '트렌드 글은 실제 발표일·버전·기존 대비 변화와 과장된 해석을 구분하고, 기초 심화 글에 최신성을 꾸미지 마세요. '
            '연구의 상관관계와 인과, 저자 주장과 필자 해석, 실측과 가정을 구분하세요. 재현하지 않은 실험·벤치마크는 '
            '실행했다고 쓰지 마세요. 통계가 없으면 근거 있는 방법·스펙 비교표를 쓰고 수치를 만들지 마세요. '
            '제목에 검색어를 기계적으로 앞세우는 요구보다 탐구 질문의 정확성을 우선하세요. '
            '관리자 부분 수정에서는 유형을 이유로 요청 밖 내용을 다시 쓰지 마세요.\n')
    return base + (
        '생활·업무에서 당장 해결할 문제 하나와 실행 가능한 절차·계산·선택 기준에 집중하세요. '
        '검색 수요는 소재 선정의 참고로 쓰되 실제 효용과 검증된 근거가 먼저예요. 적용 대상·예외·기준일을 '
        '밝히고, 가정 예시와 실제 제도·측정값을 구분하세요. 같은 발행일의 심화 글을 단순 요약한 글로 채우지 마세요. '
        '관리자 부분 수정에서는 요청 밖 내용을 다시 쓰지 마세요.\n')


def review_rule():
    track = current_track()
    if not track:
        return ''
    criteria = '\n'.join(f'- {key}: {label}' for key, label in CRITERIA[track].items())
    return ('\n[유형별 독립 심사 — 최종 본문 근거로 판정]\n'+criteria+
            '\n기존 심사 JSON에 track_review를 추가하세요: '
            '{"track": "'+track+'", "items": [{"id": "위 항목 키", "met": true, '
            '"quote": "판정을 뒷받침하는 최종 본문의 정확한 인용 10자 이상", "reason": "구체적 이유"}]}.'
            '\n모든 항목을 한 번씩 판정하고 충족하지 못하면 met:false로 남기세요. '
            '헤더만 있는 것을 충족으로 인정하지 말고 실제 설명을 인용하세요. 검색량·예상 조회수는 심화 심사의 가점이 아니에요.\n')


def review_failures(qa, content, track=None):
    track = current_track() if track is None else track
    if not track:
        return []
    report = qa.get('track_review')
    if not isinstance(report, dict) or report.get('track') != track:
        return ['최종 원고의 '+LABELS[track]+' 유형 심사 기록이 없어요.']
    rows = report.get('items')
    if not isinstance(rows, list):
        return ['유형 심사의 항목별 근거가 없어요.']
    failures = []
    for key, label in CRITERIA[track].items():
        matching = [r for r in rows if isinstance(r, dict) and r.get('id') == key]
        row = matching[0] if len(matching) == 1 else {}
        quote = row.get('quote')
        if (row.get('met') is not True or not isinstance(quote, str) or len(quote.strip()) < 10
                or quote.strip().startswith('#') or quote not in content):
            failures.append(label+' — 최종 본문에서 충족 근거를 확인하지 못했어요.')
    return failures
