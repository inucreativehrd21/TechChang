"""
연구실 픽셀 에셋(LimeZu Modern Office 등) 점검·매니페스트 생성.

에셋은 **저장소에 커밋하지 않는다** (재배포 금지 라이선스). 서버의 `media/lab/` 에 직접 올리고,
이 명령으로 목록을 확인한 뒤 `media/lab/manifest.json` 을 만든다. 매니페스트가 있으면 /lab/ 은
타일 기반으로 그리고, 없으면 코드로 그리는 기본 렌더러로 자동 폴백한다.

사용법:
  python manage.py lab_assets --scan            # media/lab/ 파일 목록 출력 (구조 파악용)
  python manage.py lab_assets --init            # 비어 있는 매니페스트 뼈대 생성
  python manage.py lab_assets --check           # 매니페스트가 가리키는 파일이 실제로 있는지 검사

업로드 예:
  scp -r "Modern_Office/16x16/." ubuntu@<서버>:~/projects/mysite/media/lab/office/
  scp -r "Modern_Interiors/4_Characters/." ubuntu@<서버>:~/projects/mysite/media/lab/chars/
"""
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand

SKELETON = {
    "_note": "LimeZu 에셋은 재배포 금지 — 이 파일과 이미지들은 git 에 올리지 않습니다 (media/ 는 추적 제외).",
    "credit": "Modern Office / Modern Interiors by LimeZu (https://limezu.itch.io/)",
    "tile": 16,
    "floor": "",
    "wall": "",
    "wainscot": "",
    "objects": {
        "desk": "", "chair_up": "", "chair_down": "", "monitor": "", "bookshelf": "",
        "whiteboard": "", "window": "", "plant_big": "", "plant_small": "", "sofa": "",
        "coffee": "", "cooler": "", "printer": "", "table": "", "rug": "", "clock": "",
    },
    "characters": {
        # key: 에이전트 키(lead/hrd/data/coding/checker/charter)
        # sheet: media/lab/ 기준 상대경로, fw·fh: 프레임 크기,
        # rows: 애니메이션별 {row: 시트 행 번호, frames: 프레임 수}
        # dirs: 방향 순서 (시트 행 배치에 맞춰 조정)
        "_template": {
            "sheet": "chars/<파일>.png", "fw": 16, "fh": 32,
            "dirs": ["down", "up", "left", "right"],
            "rows": {"idle": {"row": 0, "frames": 1}, "walk": {"row": 1, "frames": 4},
                     "sit": {"row": 2, "frames": 1}},
        },
    },
}


class Command(BaseCommand):
    help = '연구실 픽셀 에셋 점검 및 manifest.json 생성 (media/lab/)'

    def add_arguments(self, parser):
        parser.add_argument('--scan', action='store_true', help='media/lab/ 파일 목록 출력')
        parser.add_argument('--init', action='store_true', help='매니페스트 뼈대 생성')
        parser.add_argument('--check', action='store_true', help='매니페스트가 가리키는 파일 존재 확인')
        parser.add_argument('--limit', type=int, default=200, help='--scan 출력 개수 제한')

    def handle(self, *args, **opts):
        root = os.path.join(settings.MEDIA_ROOT, 'lab')
        mpath = os.path.join(root, 'manifest.json')
        out = self.stdout.write

        if not (opts['scan'] or opts['init'] or opts['check']):
            opts['scan'] = True

        if not os.path.isdir(root):
            out(self.style.WARNING(f'{root} 가 없습니다. 먼저 만드세요: mkdir -p {root}'))
            if not opts['init']:
                return

        if opts['scan']:
            files, total = [], 0
            for dirpath, _dirs, names in os.walk(root):
                for n in sorted(names):
                    if not n.lower().endswith(('.png', '.gif', '.webp')):
                        continue
                    total += 1
                    if len(files) < opts['limit']:
                        rel = os.path.relpath(os.path.join(dirpath, n), root).replace('\\', '/')
                        size = os.path.getsize(os.path.join(dirpath, n)) // 1024
                        files.append(f'  {rel}  ({size} KB)')
            out(f'media/lab/ 이미지 {total}개' + (f' (앞 {len(files)}개만 표시)' if total > len(files) else ''))
            for f in files:
                out(f)
            if not total:
                out(self.style.WARNING('  (비어 있음) 구매한 에셋을 media/lab/ 아래로 올린 뒤 다시 실행하세요.'))

        if opts['init']:
            os.makedirs(root, exist_ok=True)
            if os.path.exists(mpath):
                out(self.style.WARNING(f'이미 있습니다: {mpath} (덮어쓰지 않음)'))
            else:
                with open(mpath, 'w', encoding='utf-8') as f:
                    json.dump(SKELETON, f, ensure_ascii=False, indent=2)
                out(self.style.SUCCESS(f'생성: {mpath} — 파일 경로를 채우면 /lab/ 이 타일 모드로 전환됩니다.'))

        if opts['check']:
            if not os.path.exists(mpath):
                out(self.style.ERROR('manifest.json 이 없습니다 — media/lab/ 에 에셋을 올리세요.'))
                return
            man = json.load(open(mpath, encoding='utf-8'))
            problems = []

            def probe(rel, label):
                if rel and os.path.exists(os.path.join(root, rel)):
                    return True
                problems.append(f'{label}: {rel or "(경로 없음)"}')
                return False

            frames = (man.get('room') or {}).get('frames') or []
            okf = sum(1 for f in frames if probe(f, '방 프레임'))
            out(f'방 이미지 {okf}/{len(frames)} · 크기 {man.get("art", {}).get("w")}x{man.get("art", {}).get("h")}')

            chars = man.get('characters') or {}
            okc = 0
            for key, c in chars.items():
                if key.startswith('_'):
                    continue
                have = [a for a in ('idle', 'run', 'sit') if probe((c or {}).get(a, ''), f'{key} {a}')]
                if len(have) == 3:
                    okc += 1
            out(f'연구원 스프라이트 {okc}/{len([k for k in chars if not k.startswith("_")])}명 (idle·run·sit)')

            nav = man.get('nav') or {}
            cells = sum(row.count('.') for row in (nav.get('grid') or []))
            if cells:
                out(f'길찾기 맵 {nav.get("w")}x{nav.get("h")} 격자 · 통로 {cells}칸 ({nav.get("cell")}px)')
            else:
                problems.append('길찾기 맵(nav) 없음 — 연구원이 통로를 따라 걷지 않고 직선 이동합니다')

            seats = len(man.get('seats_desk') or [])
            acts = len(man.get('activities') or [])
            out(f'좌석 {seats}자리 · 접근점 {len(man.get("approaches") or [])} · 행동 지점 {acts}곳')
            if seats < 6:
                problems.append('좌석(seats_desk)이 6자리가 아님')
            if not acts:
                problems.append('행동 지점(activities) 없음 — 자리에만 앉아 있게 됩니다')

            if problems:
                out(self.style.ERROR(f'문제 {len(problems)}건:'))
                for p_ in problems:
                    out(self.style.ERROR(f'  - {p_}'))
                out(self.style.WARNING('  → 최신 lab_assets.tar.gz 를 media/ 에 다시 풀어 주세요.'))
            else:
                out(self.style.SUCCESS('모두 정상 — /lab/ 이 구매 에셋 + 길찾기로 렌더링됩니다.'))
