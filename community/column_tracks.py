"""칼럼 분야(HRD·데이터·코딩)와 별도로 유지하는 편집 유형."""
RESEARCH = 'research'
PRACTICAL = 'practical'
TRACKS = (RESEARCH, PRACTICAL)
TRACK_CHOICES = [('', '기존 칼럼'), (RESEARCH, '학술·기술 심화'), (PRACTICAL, '일상·실용 팁')]
