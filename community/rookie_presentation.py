"""선택 내용과 실제 결과를 분리해 보여 주는 표시 전용 변환이에요."""


def receipt(playback):
    data = dict(playback or {})
    text = data.get('text', '')
    # Story.change가 남긴 실제 변화량만 별도 배지로 옮겨요.
    outcome, mark, effects = text.partition(' — ')
    if data.get('selection') and outcome.rstrip('.! ') == data['selection'].rstrip('.! '):
        outcome = '답변을 반영했어요. 아래가 이번 선택으로 달라진 수치예요.'
    data['outcome'] = outcome
    data['effects'] = [x.strip() for x in effects.split(' · ') if x.strip()] if mark else []
    return data
