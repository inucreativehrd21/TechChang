"""구매한 ZIP에서 게임에 쓰는 조각만 원형 그대로 설치해요. Git/media 분리."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from community import rookie_avatar as A

class Command(BaseCommand):
    help='구매 Character Generator 2.0 Linux ZIP에서 아바타 레이어를 로컬 MEDIA_ROOT에 설치해요.'

    def add_arguments(self,parser):
        parser.add_argument('--source',required=True,type=Path)

    def handle(self,*args,**options):
        source=options['source']
        if not source.is_file():raise CommandError('구매 ZIP 경로를 확인해 주세요.')
        wanted={'eyes.png':('Eyes','Eyes_01.png'),'formal.png':('Outfits','Outfit_06_01.png')}
        wanted.update({f'body-{v}.png':('Bodies',f'Body_{v}.png') for v,_ in A.OPTIONS['body']})
        wanted.update({f'hair-{h}-{t}.png':('Hairstyles',f'Hairstyle_{h}_{t}.png') for h,_ in A.OPTIONS['hair'] for t,_ in A.OPTIONS['tone']})
        wanted.update({f'kit-{key}.png':('Outfits',f'Outfit_08_{n:02}.png') for n,(key,_l) in enumerate(A.OPTIONS['kit'],1)})
        wanted.update({f'cap-{key}.png':('Accessories',f'Accessory_04_Snapback_{n:02}.png') for n,key in enumerate(('red','navy','green'),1)})
        dest=Path(settings.MEDIA_ROOT)/'rookie-avatar/v1'
        with ZipFile(source) as archive:
            names=archive.namelist()
            payload={}
            for target,(group,name) in wanted.items():
                matches=[p for p in names if p.endswith('/Character Pieces/'+group+'/16x16/'+name)]
                if len(matches)!=1:raise CommandError(f'필요한 원본이 없어요: {group}/{name}')
                payload[target]=(matches[0],archive.read(matches[0]))
            dest.mkdir(parents=True,exist_ok=True)
            manifest=[]
            for target,(origin,data) in payload.items():
                path=dest/target
                if path.exists() and path.read_bytes()!=data:raise CommandError(f'다른 파일을 덮어쓰지 않아요: {path}')
                path.write_bytes(data)
                manifest.append(dict(file=target,origin=origin,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data)))
            (dest/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
            (dest/'CREDITS.txt').write_text('Character art: LimeZu — https://limezu.itch.io/moderninteriors\nPurchased Modern Interiors / Character Generator 2.0 pieces. Embedded game use only; do not redistribute as an asset pack.\n',encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(f'{len(payload)}개 레이어를 설치했어요: {dest}'))
