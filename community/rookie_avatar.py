"""선수 외형만 저장해요. 경기 능력치·난수·결과에는 관여하지 않아요."""
import hashlib
from pathlib import Path
from django.conf import settings
from django.db import transaction

VERSION = 1
KEY = 'avatar_v1'
OPTIONS = {
    'body': [(f'{n:02}', f'피부 톤 {n}') for n in range(1, 10)],
    'hair': [(n, f'머리 모양 {i}') for i,n in enumerate(('01','03','06','10','14','18'),1)],
    'tone': [('01','머리색 1'),('03','머리색 2'),('05','머리색 3')],
    'kit': [('home','화이트 유니폼'),('away','그레이 유니폼'),('dark','다크 유니폼')],
    'cap': [('none','모자 없이'),('red','레드 캡'),('navy','블루 캡'),('green','그린 캡')],
}
LABELS = dict(body='피부', hair='머리 모양', tone='머리색', kit='유니폼', cap='야구 모자')
DEFAULT = dict(body='03', hair='01', tone='03', kit='home', cap='navy')


def clean(values, prefix='avatar_'):
    result = {'v':VERSION}
    for key, choices in OPTIONS.items():
        value = values.get(prefix+key, DEFAULT[key])
        if key == 'cap' and value == 'black':
            value = 'green'  # 초기 로컬 시제품의 조각 식별자를 보정해요.
        if value not in dict(choices):
            raise ValueError('캐릭터 외형을 다시 골라 주세요.')
        result[key] = value
    return result


def recipe(player=None):
    field = 'flags' if hasattr(player,'flags') else 'career'
    data = (getattr(player,field,None) or {}) if player is not None else {}
    stored = data.get(KEY) if isinstance(data,dict) else None
    if isinstance(stored,dict) and stored.get('v') == VERSION:
        try:
            return clean(stored,prefix='')
        except ValueError:
            pass
    result = dict(DEFAULT,v=VERSION)
    # 이전 선수도 매번 같은 외형. 게임 난수는 소비하지 않아요.
    if player is not None and getattr(player,'pk',None):
        model=getattr(getattr(player,'_meta',None),'label_lower',type(player).__name__)
        h=hashlib.sha256(f'{model}:{player.pk}'.encode()).digest()
        result.update(body=OPTIONS['body'][h[0]%9][0],hair=OPTIONS['hair'][h[1]%6][0])
    return result


def parts(value, formal=False):
    files = [f'body-{value["body"]}.png', 'eyes.png', 'formal.png' if formal else f'kit-{value["kit"]}.png',
             f'hair-{value["hair"]}-{value["tone"]}.png']
    if not formal and value['cap'] != 'none':
        files.append(f'cap-{value["cap"]}.png')
    return files


def presentation(player=None, state='idle', size=4, formal=False, value=None):
    value = value or recipe(player)
    state = state if state in ('idle','walk','award') else 'idle'
    formal = bool(formal or state == 'award')
    files = parts(value,formal)
    base = settings.MEDIA_URL.rstrip('/')+'/rookie-avatar/v1/'
    return dict(recipe=value,state=state,size=size if size in (2,3,4,5,6) else 4,formal=formal,
                layers=[base+name for name in files],
                ready=all((Path(settings.MEDIA_ROOT)/'rookie-avatar/v1'/name).is_file() for name in files))


def save(player, value):
    value=clean(value,prefix='')
    field='flags' if hasattr(player,'flags') else 'career'
    with transaction.atomic():
        locked=type(player).objects.select_for_update().get(pk=player.pk)
        data=dict(getattr(locked,field) or {})
        data[KEY]=value
        setattr(locked,field,data)
        locked.save(update_fields=[field])
    setattr(player,field,data)


def picker():
    base = settings.MEDIA_URL.rstrip('/')+'/rookie-avatar/v1/'
    return dict(avatar=presentation(),groups=[dict(key=k,label=LABELS[k],options=[dict(value=v,label=l,selected=v==DEFAULT[k]) for v,l in choices]) for k,choices in OPTIONS.items()],
                avatar_manifest=dict(base=base,default=DEFAULT,options={k:[v for v,_l in choices] for k,choices in OPTIONS.items()}))
