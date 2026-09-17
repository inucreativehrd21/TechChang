/* 테크창 연구팀 픽셀 연구실 — canvas 렌더러
 *
 * 해상도: 아트는 480x270 "아트 픽셀"로 그리고, 실제 캔버스는 (CSS 폭 × devicePixelRatio) 를 480 으로 나눈
 * 정수 배율 k 로 확대 렌더링한다 (ctx.scale(k) + imageSmoothing off). 배율이 정수라 어떤 화면에서도
 * 픽셀이 뭉개지지 않는다. 정적 배경은 오프스크린 캔버스에 한 번만 그린다.
 *
 * 데이터: /lab/state.json (에이전트 상태·최근 회의). 외부 이미지 없음 — 모든 스프라이트는 문자열 패턴.
 * 모드: office(자리·배회·소파·상태 말풍선) / meeting(회의 테이블에 모여 회의록 재생)
 */
(function () {
  const canvas = document.getElementById('office-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const AW = 480, AH = 270;
  const stateUrl = canvas.dataset.stateUrl;
  const modeLabel = document.getElementById('office-mode');
  const captionEl = document.getElementById('office-caption');
  const btnMeeting = document.getElementById('btn-replay');
  const btnOffice = document.getElementById('btn-office');
  const FONT = '"Pretendard Variable", Pretendard, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif';

  let k = 2;                       // 정수 배율
  let bg = null;                   // 오프스크린 배경
  function resize() {
    const cssW = canvas.parentElement.clientWidth;
    const dpr = window.devicePixelRatio || 1;
    k = Math.max(1, Math.floor(cssW * dpr / AW));
    canvas.width = AW * k; canvas.height = AH * k;
    const cssTarget = AW * k / dpr;
    canvas.style.width = (cssTarget <= cssW ? cssTarget : cssW) + 'px';
    canvas.style.height = 'auto';
    bg = document.createElement('canvas'); bg.width = AW * k; bg.height = AH * k;
    const b = bg.getContext('2d'); b.imageSmoothingEnabled = false; b.scale(k, k);
    drawRoom(b);
  }

  // ── 팔레트
  const C = {
    wall: '#efe8dc', wallLo: '#e2d9c9', base: '#8c6a48', baseLo: '#6d5236',
    wood: ['#c98a4b', '#c17f42', '#d1944f'], seam: '#a56a35', grain: '#b9793f',
    tile: '#f2f1ec', tileLine: '#dedbd2', rug: '#e6cfa6', rugEdge: '#c9ad7d',
    ink: '#1f2430', metal: '#8a93a6', metalHi: '#c7cdd8', screen: '#1d2a44', screenHi: '#7bd0ff',
    deskTop: '#a9713e', deskEdge: '#7f5330', deskHi: '#c3894e',
    chair: '#2b2f3a', chairHi: '#3e4453', wood2: '#8a5a33',
    sofa: '#7c3f9e', sofaHi: '#9a5cbb', sofaLo: '#5f2d7c',
    plant: '#2f9e4f', plantHi: '#4cc06a', plantLo: '#20733a', pot: '#b9622e', potLo: '#8d4a22',
    book: ['#d9534f', '#3d4fd9', '#2aa876', '#f0a33a', '#8e5cd9', '#3aa7c9', '#e07aa3'],
    glass: '#bfe6f5', glassHi: '#e8f7fd', white: '#ffffff', shadow: 'rgba(0,0,0,.18)',
  };

  // ── 기본 도형
  function R(c, x, y, w, h, col) { c.fillStyle = col; c.fillRect(x, y, w, h); }
  function pattern(c, rows, x, y, map) {
    for (let j = 0; j < rows.length; j++) for (let i = 0; i < rows[j].length; i++) {
      const ch = rows[j][i]; if (ch === '.' || !map[ch]) continue;
      c.fillStyle = map[ch]; c.fillRect(x + i, y + j, 1, 1);
    }
  }

  // ── 가구 스프라이트
  const CHAIR = ['..MMMMMM..', '.MDDDDDDM.', '.MDDDDDDM.', '.MDDDDDDM.', '..DDDDDD..', '.HHHHHHHH.', '.HDDDDDDH.', '..HHHHHH..', '....MM....', '..MMMMMM..', '.M..MM..M.'];
  const CHAIR_MAP = { M: C.metal, D: C.chair, H: C.chairHi };
  const PLANT = ['....GG..GG....', '...GLGGGGLG...', '..GGGHGGHGGG..', '.GLGGGGGGGGLG.', '..GGGHGGGGGG..', '...GGGGGGGG...', '....LGGGGL....', '.....GGGG.....', '.....PPPP.....', '....PPPPPP....', '....PLLLLP....', '....PPPPPP....', '.....PPPP.....'];
  const PLANT_MAP = { G: C.plant, H: C.plantHi, L: C.plantLo, P: C.pot };
  const COOLER = ['..WWWWWW..', '.WGGGGGGW.', '.WGGHGGGW.', '.WGGGGGGW.', '.WGGGGGGW.', '..WWWWWW..', '.MMMMMMMM.', '.MMMBRMMM.', '.MMMMMMMM.', '.MMMMMMMM.', '.MMMMMMMM.', '..MMMMMM..'];
  const COOLER_MAP = { W: C.white, G: C.glass, H: C.glassHi, M: C.metalHi, B: '#3d4fd9', R: '#d9534f' };
  const PRINTER = ['..MMMMMMMMMMMM..', '.MDDDDDDDDDDDDM.', '.MDDDDDDDDDDDDM.', 'MMMMMMMMMMMMMMMM', 'MHHHHHHHHHHHHHHM', 'MHHHHGHHHHHHHHHM', 'MMMMMMMMMMMMMMMM', '.MDDDDDDDDDDDDM.', '.MMMMMMMMMMMMMM.'];
  const PRINTER_MAP = { M: C.metal, D: C.chair, H: C.metalHi, G: '#4cc06a' };
  const RACK = ['..M..', '.MMM.', 'M.M.M', '..M..', '..M..', '..M..', '..M..', '..M..', '..M..', '..M..', '..M..', '.MMM.', 'M...M'];
  const RACK_MAP = { M: C.wood2 };
  const TRASH = ['MMMMMM', 'M....M', '.MDDM.', '.MDDM.', '.MDDM.', '.MDDM.', '..MM..'];
  const TRASH_MAP = { M: C.metal, D: C.chair };

  function desk(c, x, y) {                     // 48x22 책상 + 모니터·키보드·머그
    R(c, x + 2, y + 22, 44, 3, C.shadow);
    R(c, x, y, 48, 22, C.deskEdge); R(c, x + 1, y + 1, 46, 19, C.deskTop); R(c, x + 1, y + 1, 46, 2, C.deskHi);
    R(c, x + 16, y - 6, 18, 13, C.ink); R(c, x + 17, y - 5, 16, 10, C.screen);   // 모니터
    R(c, x + 24, y + 7, 2, 3, C.ink); R(c, x + 21, y + 10, 8, 1, C.ink);
    R(c, x + 12, y + 13, 14, 5, '#dfe3ea'); R(c, x + 13, y + 14, 12, 3, '#b8bfcb'); // 키보드
    R(c, x + 30, y + 13, 4, 4, '#dfe3ea');                                        // 마우스
    R(c, x + 39, y + 11, 5, 5, '#f8f8f8'); R(c, x + 44, y + 12, 1, 3, '#f8f8f8'); R(c, x + 40, y + 12, 3, 1, '#d9534f'); // 머그
    R(c, x + 4, y + 12, 6, 6, '#fff'); R(c, x + 5, y + 13, 4, 1, '#999'); R(c, x + 5, y + 15, 4, 1, '#999'); // 메모지
  }
  function officeChair(c, x, y) { pattern(c, CHAIR, x, y, CHAIR_MAP); }
  function bookshelf(c, x, y) {                 // 56x44
    R(c, x, y, 56, 44, '#5f3d22'); R(c, x + 2, y + 2, 52, 40, '#7d5231');
    for (let s = 0; s < 3; s++) {
      const sy = y + 4 + s * 13; R(c, x + 2, sy + 11, 52, 2, '#5f3d22');
      let bx = x + 4, i = s * 7;
      while (bx < x + 50) { const w = 3 + (i * 7) % 3, h = 8 + (i * 5) % 3; R(c, bx, sy + 11 - h, w, h, C.book[i % C.book.length]); bx += w + 1; i++; }
    }
  }
  function whiteboard(c, x, y) {                // 78x26
    R(c, x, y, 78, 26, '#9aa3b2'); R(c, x + 2, y + 2, 74, 22, '#fbfbfb');
    R(c, x + 6, y + 6, 24, 2, '#3d4fd9'); R(c, x + 6, y + 10, 40, 2, '#3d4fd9'); R(c, x + 6, y + 14, 30, 2, '#d9534f');
    R(c, x + 44, y + 6, 26, 2, '#2aa876'); R(c, x + 52, y + 10, 18, 2, '#2aa876'); R(c, x + 44, y + 14, 12, 2, '#f0a33a');
    R(c, x + 6, y + 19, 60, 1, '#c9ced6'); R(c, x + 10, y + 26, 58, 2, '#7c8595');
  }
  function tv(c, x, y) { R(c, x, y, 46, 26, C.ink); R(c, x + 2, y + 2, 42, 22, '#0d1526'); R(c, x + 5, y + 5, 36, 16, '#132542'); R(c, x + 8, y + 16, 12, 2, '#7bd0ff'); R(c, x + 8, y + 10, 26, 2, '#3aa7c9'); }
  function window_(c, x, y) {                   // 40x30 창 + 도시
    R(c, x, y, 40, 30, '#6f7c90'); R(c, x + 2, y + 2, 36, 26, '#9fd3f5');
    R(c, x + 2, y + 2, 36, 10, '#bfe3ff');
    [[4, 12, 6, 16], [11, 8, 5, 20], [17, 14, 7, 14], [25, 6, 6, 22], [32, 11, 4, 17]].forEach(([bx, by, bw, bh]) => R(c, x + bx, y + by, bw, bh, '#4b5b74'));
    R(c, x + 19, y + 2, 2, 26, '#6f7c90'); R(c, x + 2, y + 14, 36, 2, '#6f7c90');
  }
  function sofaH(c, x, y) { R(c, x + 2, y + 18, 46, 3, C.shadow); R(c, x, y, 50, 8, C.sofaLo); R(c, x + 2, y + 2, 46, 6, C.sofa); R(c, x, y + 8, 50, 10, C.sofa); R(c, x + 6, y + 9, 17, 6, C.sofaHi); R(c, x + 27, y + 9, 17, 6, C.sofaHi); R(c, x, y + 6, 6, 12, C.sofaLo); R(c, x + 44, y + 6, 6, 12, C.sofaLo); }
  function sofaV(c, x, y) { R(c, x + 2, y + 44, 18, 3, C.shadow); R(c, x, y, 8, 46, C.sofaLo); R(c, x + 8, y, 12, 46, C.sofa); R(c, x + 9, y + 6, 10, 15, C.sofaHi); R(c, x + 9, y + 25, 10, 15, C.sofaHi); R(c, x + 6, y, 14, 6, C.sofaLo); R(c, x + 6, y + 40, 14, 6, C.sofaLo); }
  function glassTable(c, x, y) { R(c, x + 3, y + 14, 26, 3, C.shadow); R(c, x + 4, y, 24, 14, C.glass); R(c, x, y + 2, 32, 10, C.glass); R(c, x + 6, y + 2, 20, 4, C.glassHi); R(c, x + 2, y + 11, 28, 2, '#8fc8de'); }
  function meetingTable(c, x, y, w, h) { R(c, x + 3, y + h, w - 4, 4, C.shadow); R(c, x, y, w, h, C.deskEdge); R(c, x + 2, y + 2, w - 4, h - 4, C.deskTop); R(c, x + 2, y + 2, w - 4, 3, C.deskHi); for (let i = 0; i < 3; i++) { R(c, x + 12 + i * 26, y + 8, 10, 8, '#f8f8f8'); R(c, x + 13 + i * 26, y + 10, 8, 1, '#aaa'); R(c, x + 13 + i * 26, y + 12, 8, 1, '#aaa'); } R(c, x + w / 2 - 4, y + h / 2 - 2, 8, 6, C.plantLo); }
  function door(c, x, y) { R(c, x, y, 34, 24, '#3f4b63'); R(c, x + 2, y + 2, 14, 22, '#5ea9c9'); R(c, x + 18, y + 2, 14, 22, '#5ea9c9'); R(c, x + 4, y + 4, 10, 14, '#8fd0e8'); R(c, x + 20, y + 4, 10, 14, '#8fd0e8'); R(c, x + 13, y + 12, 2, 4, '#e6e6e6'); R(c, x + 19, y + 12, 2, 4, '#e6e6e6'); }

  // ── 방 (정적)
  function drawRoom(c) {
    // 벽·바닥
    R(c, 0, 0, AW, 42, C.wall); R(c, 0, 0, AW, 4, C.wallLo); R(c, 0, 38, AW, 3, C.base); R(c, 0, 41, AW, 2, C.baseLo);
    for (let row = 0; row < (AH - 42) / 8 + 1; row++) {
      const y = 42 + row * 8;
      for (let x = -((row * 24) % 48); x < AW; x += 48) {
        R(c, x, y, 48, 8, C.wood[row % 3]); R(c, x, y, 48, 1, C.grain); R(c, x + 47, y, 1, 8, C.seam);
        if (row % 2) R(c, x + 10, y + 4, 18, 1, C.grain); else R(c, x + 24, y + 3, 14, 1, C.grain);
      }
      R(c, 0, y + 7, AW, 1, C.seam);
    }
    // 탕비 타일 (우상단)
    R(c, 340, 42, 140, 66, C.tile); for (let x = 340; x < 480; x += 14) R(c, x, 42, 1, 66, C.tileLine); for (let y = 42; y < 108; y += 14) R(c, 340, y, 140, 1, C.tileLine);
    R(c, 338, 42, 2, 66, C.baseLo); R(c, 340, 107, 140, 2, C.baseLo);
    // 라운지 러그
    R(c, 330, 150, 140, 104, C.rugEdge); R(c, 334, 154, 132, 96, C.rug); for (let i = 0; i < 6; i++) R(c, 342 + i * 20, 158, 10, 88, '#dfc394');
    // 벽 장식
    window_(c, 8, 6); whiteboard(c, 60, 8); tv(c, 200, 8); bookshelf(c, 280, 4);
    // 시계 테두리 (바늘은 동적)
    R(c, 150, 10, 20, 20, C.ink); R(c, 152, 12, 16, 16, '#fbfbfb');
    // 탕비: 정수기·프린터·휴지통
    pattern(c, COOLER, 452, 52, COOLER_MAP); pattern(c, PRINTER, 396, 60, PRINTER_MAP); pattern(c, TRASH, 380, 96, TRASH_MAP);
    // 회의 테이블 + 의자 6
    meetingTable(c, 22, 92, 92, 44);
    SEATS.forEach(s => officeChair(c, s.x - 5, s.y - 12));
    // 책상 6 + 의자
    DESKS.forEach(d => { officeChair(c, d.x + 19, d.y + 20); desk(c, d.x, d.y); });
    // 라운지
    sofaH(c, 348, 158); sofaV(c, 440, 176); glassTable(c, 372, 200); pattern(c, PLANT, 448, 128, PLANT_MAP);
    // 화분·옷걸이·문
    pattern(c, PLANT, 250, 22, PLANT_MAP); pattern(c, PLANT, 8, 160, PLANT_MAP); pattern(c, RACK, 300, 236, RACK_MAP); door(c, 222, 246);
  }

  const DESKS = [{ x: 140, y: 66 }, { x: 226, y: 66 }, { x: 140, y: 120 }, { x: 226, y: 120 }, { x: 140, y: 174 }, { x: 226, y: 174 }];
  const SEATS = [{ x: 40, y: 88 }, { x: 68, y: 88 }, { x: 96, y: 88 }, { x: 40, y: 156 }, { x: 68, y: 156 }, { x: 96, y: 156 }];
  const SPOTS = { coffee: [430, 100], board: [100, 58], plant: [30, 190], sofa: [[364, 172], [386, 172], [408, 172]], tv: [222, 58] };

  // ── 캐릭터 16x24. H 머리 S 피부 E 눈 B 상의 P 바지 D 신발 K 하이라이트
  const HEAD = {
    short: ['....HHHHHHHH....', '...HHHHHHHHHH...', '..HHKHHHHHHHHH..', '..HHSSSSSSSSHH..', '..HSSSSSSSSSSH..', '..HSSESSSSESSH..', '...SSSSSSSSSS...', '...SSSSSSSSSS...', '....SSSSSSSS....', '.....SSSSSS.....'],
    long:  ['....HHHHHHHH....', '...HHHHHHHHHH...', '..HHKHHHHHHHHH..', '..HHSSSSSSSSHH..', '..HSSSSSSSSSSH..', '..HSSESSSSESSH..', '..HSSSSSSSSSSH..', '..HHSSSSSSSSHH..', '..HH.SSSSSS.HH..', '..HH..SSSS..HH..'],
    bob:   ['....HHHHHHHH....', '...HHHHHHHHHH...', '..HHKHHHHHHHHH..', '..HHHSSSSSSHHH..', '..HHSSSSSSSSHH..', '..HHSESSSSESHH..', '..HHSSSSSSSSHH..', '..HHHSSSSSSHHH..', '...HH.SSSS.HH...', '......SSSS......'],
  };
  const BODY = ['....BBBBBBBB....', '...BBBBBBBBBB...', '..BBBBBBBBBBBB..', '..SBBBBBBBBBBS..', '..SBBBBBBBBBBS..', '..S.BBBBBBBB.S..', '....BBBBBBBB....', '....PPPPPPPP....', '....PPPPPPPP....'];
  const LEGS = [['....PPP..PPP....', '....PPP..PPP....', '....PPP..PPP....', '....DDD..DDD....', '...DDDD..DDDD...'],
                ['...PPP....PPP...', '...PPP....PPP...', '..PPP......PPP..', '..DDD......DDD..', '.DDDD......DDDD.']];

  function drawAgent(c, a, x, y, frame, sitting) {
    const map = { H: a.sprite.hair, K: lighten(a.sprite.hair), S: a.sprite.skin, E: a.blink > 0 ? a.sprite.skin : '#1b1b1b', B: a.sprite.shirt, P: '#2d3142', D: '#2b1d14' };
    const head = HEAD[a.sprite.style] || HEAD.short;
    pattern(c, head, x, y, map);
    pattern(c, BODY, x, y + 10, map);
    if (!sitting) pattern(c, LEGS[frame % 2], x, y + 19, map);
  }
  function lighten(hex) { const n = parseInt(hex.slice(1), 16); const r = Math.min(255, (n >> 16) + 40), g = Math.min(255, ((n >> 8) & 255) + 40), b = Math.min(255, (n & 255) + 40); return `rgb(${r},${g},${b})`; }

  function roundRect(c, x, y, w, h, r, fill, stroke) {
    c.beginPath(); c.moveTo(x + r, y); c.lineTo(x + w - r, y); c.quadraticCurveTo(x + w, y, x + w, y + r); c.lineTo(x + w, y + h - r);
    c.quadraticCurveTo(x + w, y + h, x + w - r, y + h); c.lineTo(x + r, y + h); c.quadraticCurveTo(x, y + h, x, y + h - r); c.lineTo(x, y + r); c.quadraticCurveTo(x, y, x + r, y); c.closePath();
    if (fill) { c.fillStyle = fill; c.fill(); } if (stroke) { c.strokeStyle = stroke; c.lineWidth = 1; c.stroke(); }
  }
  function nameTag(c, a, cx, top) {
    c.font = `600 7px ${FONT}`; const w = Math.ceil(c.measureText(a.name).width) + 8;
    roundRect(c, Math.round(cx - w / 2), top - 11, w, 9, 2, 'rgba(20,24,34,.85)');
    c.fillStyle = '#fff'; c.textBaseline = 'alphabetic'; c.fillText(a.name, Math.round(cx - w / 2) + 4, top - 4);
  }
  function bubble(c, text, cx, top, accent) {
    if (!text) return;
    c.font = `8px ${FONT}`;
    const maxW = 150, lines = []; let line = '';
    for (const ch of text) { const t = line + ch; if (c.measureText(t).width > maxW - 12) { lines.push(line); line = ch; } else line = t; if (lines.length >= 4) break; }
    if (line && lines.length < 4) lines.push(line);
    if (lines.length === 4 && text.length > lines.join('').length) lines[3] = lines[3].slice(0, -1) + '…';
    const w = Math.min(maxW, Math.ceil(Math.max(...lines.map(l => c.measureText(l).width))) + 12), h = lines.length * 10 + 8;
    const x = Math.max(2, Math.min(AW - w - 2, Math.round(cx - w / 2))), y = Math.max(2, top - h - 8);
    roundRect(c, x, y, w, h, 3, '#ffffff', '#1f2430');
    R(c, x + 1, y + 1, 3, h - 2, accent || '#4f46e5');
    c.fillStyle = '#1f2430'; lines.forEach((l, i) => c.fillText(l, x + 8, y + 10 + i * 10));
    c.fillStyle = '#ffffff'; c.fillRect(cx - 2, y + h - 1, 4, 4); c.fillStyle = '#1f2430'; c.fillRect(cx - 3, y + h + 3, 6, 1);
  }

  // ── 상태
  let agents = [], meeting = null, mode = 'office', tick = 0;
  let replay = { i: 0, t: 0 };
  const rnd = (a, b) => a + Math.random() * (b - a);
  function deskPos(a) { const d = DESKS[a.sprite.desk % 6]; return { x: d.x + 24, y: d.y + 46 }; }   // 의자에 앉은 위치(발 기준선). 등받이가 머리 위로 보인다
  function seatPos(a) { const s = SEATS[a.sprite.desk % 6]; return { x: s.x, y: s.y + 8 }; }

  function planIdle(a) {
    const r = Math.random();
    if (r < 0.55) { a.task = 'work'; a.wait = rnd(300, 700); const d = deskPos(a); a.tx = d.x; a.ty = d.y; }
    else if (r < 0.7) { a.task = 'coffee'; a.wait = rnd(150, 260); a.tx = SPOTS.coffee[0] + rnd(-6, 6); a.ty = SPOTS.coffee[1] + rnd(0, 6); }
    else if (r < 0.8) { a.task = 'board'; a.wait = rnd(150, 260); a.tx = SPOTS.board[0] + rnd(-24, 24); a.ty = SPOTS.board[1]; }
    else if (r < 0.92) { const s = SPOTS.sofa[Math.floor(Math.random() * 3)]; a.task = 'sofa'; a.wait = rnd(200, 400); a.tx = s[0]; a.ty = s[1]; }
    else { a.task = 'plant'; a.wait = rnd(100, 200); a.tx = SPOTS.plant[0] + rnd(0, 20); a.ty = SPOTS.plant[1] + rnd(-6, 6); }
  }
  function step(a) {
    const dx = a.tx - a.x, dy = a.ty - a.y, dist = Math.hypot(dx, dy);
    if (dist > 0.8) { const v = 0.55; a.x += dx / dist * v; a.y += dy / dist * v; a.moving = true; } else { a.moving = false; a.x = a.tx; a.y = a.ty; }
    if (a.blink > 0) a.blink--; else if (Math.random() < 0.005) a.blink = 6;
    if (mode === 'office') {
      if (!a.moving) { a.wait--; if (a.wait <= 0) planIdle(a); }
      const ph = (tick + a.phase) % 1500; a.showStatus = ph < 220 && a.status && a.status.text;   // 250 간격 위상 → 동시 표시 없음
    } else { const s = seatPos(a); a.tx = s.x; a.ty = s.y; a.showStatus = false; }
  }

  function drawDynamic(c) {
    // 시계 바늘
    const now = new Date(), cx = 160, cy = 20;
    const hA = (now.getHours() % 12 + now.getMinutes() / 60) / 12 * Math.PI * 2, mA = now.getMinutes() / 60 * Math.PI * 2;
    c.strokeStyle = C.ink; c.lineWidth = 1; c.beginPath(); c.moveTo(cx, cy); c.lineTo(cx + Math.sin(hA) * 4, cy - Math.cos(hA) * 4); c.stroke();
    c.beginPath(); c.moveTo(cx, cy); c.lineTo(cx + Math.sin(mA) * 6, cy - Math.cos(mA) * 6); c.stroke(); R(c, cx - 1, cy - 1, 2, 2, '#d9534f');
    // 모니터 화면 (자리에 있을 때 밝게)
    DESKS.forEach((d, i) => {
      const a = agents.find(x => x.sprite.desk % 6 === i);
      const on = a && !a.moving && a.task === 'work' && mode === 'office';
      R(c, d.x + 17, d.y - 5, 16, 10, on ? '#2c4a7c' : C.screen);
      if (on) { R(c, d.x + 19, d.y - 3, 12, 1, C.screenHi); R(c, d.x + 19, d.y - 1, 8 + (Math.floor(tick / 20) % 4), 1, '#9fd3f5'); R(c, d.x + 19, d.y + 1, 10, 1, '#9fd3f5'); }
    });
    // 정수기 기포
    if (tick % 120 < 60) R(c, 456 + (tick % 3), 54 + Math.floor((tick % 60) / 15), 1, 1, C.glassHi);
  }

  function render() {
    tick++;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.imageSmoothingEnabled = false;
    ctx.drawImage(bg, 0, 0);
    ctx.setTransform(k, 0, 0, k, 0, 0);
    for (const a of agents) step(a);
    drawDynamic(ctx);
    const order = agents.slice().sort((p, q) => p.y - q.y);
    for (const a of order) {
      const sitting = !a.moving && (a.task === 'work' || a.task === 'sofa' || mode === 'meeting');
      const frame = a.moving ? Math.floor(tick / 9) % 2 : 0;
      const bob = (!a.moving && a.task === 'work' && mode === 'office' && tick % 40 < 20) ? 1 : 0;
      const top = Math.round(a.y - (sitting ? 20 : 24)) + bob;
      drawAgent(ctx, a, Math.round(a.x - 8), top, frame, sitting);
      nameTag(ctx, a, Math.round(a.x), top);
    }
    for (const a of order) if (mode === 'office' && a.showStatus) bubble(ctx, a.status.text, Math.round(a.x), Math.round(a.y - 36), a.sprite.shirt);
    if (mode === 'meeting') renderMeeting();
    requestAnimationFrame(render);
  }

  function renderMeeting() {
    if (!meeting || !meeting.transcript.length) { captionEl.textContent = '재생할 회의록이 없습니다.'; return; }
    const line = meeting.transcript[replay.i];
    const a = agents.find(x => x.key === line.agent);
    replay.t++;
    const shown = line.text.slice(0, Math.floor(replay.t / 2));
    if (a && !a.moving) bubble(ctx, shown, Math.round(a.x), Math.round(a.y - 32), a.sprite.shirt);
    captionEl.innerHTML = `<b>${line.name}</b> <span class="muted">${line.round}라운드 · ${replay.i + 1}/${meeting.transcript.length}</span><br>${shown}`;
    if (shown.length >= line.text.length && replay.t > line.text.length * 2 + 240) { replay.i = (replay.i + 1) % meeting.transcript.length; replay.t = 0; }
  }

  function setMode(m) {
    mode = m; replay = { i: 0, t: 0 };
    modeLabel.textContent = m === 'meeting' ? '편집회의 재생 중' : '연구실';
    btnMeeting.hidden = m === 'meeting'; btnOffice.hidden = m !== 'meeting';
    if (m === 'office') { captionEl.textContent = ''; agents.forEach(planIdle); }
  }
  btnMeeting.addEventListener('click', () => setMode('meeting'));
  btnOffice.addEventListener('click', () => setMode('office'));
  canvas.addEventListener('click', ev => {
    const r = canvas.getBoundingClientRect();
    const mx = (ev.clientX - r.left) * AW / r.width, my = (ev.clientY - r.top) * AH / r.height;
    const hit = agents.find(a => Math.abs(a.x - mx) < 12 && my > a.y - 30 && my < a.y + 4);
    if (hit) hit.phase = (1500 - tick % 1500) % 1500;
  });
  window.addEventListener('resize', resize);

  async function load() {
    try {
      const res = await fetch(stateUrl, { headers: { Accept: 'application/json' } });
      const data = await res.json();
      meeting = data.meeting;
      if (!agents.length) {
        agents = data.agents.map((a, i) => { const d = deskPos(a); return { ...a, x: d.x, y: d.y, tx: d.x, ty: d.y, task: 'work', wait: rnd(120, 400), blink: 0, phase: i * 250, moving: false }; });
        btnMeeting.disabled = !(meeting && meeting.transcript.length);
      } else data.agents.forEach(s => { const a = agents.find(x => x.key === s.key); if (a) a.status = s.status; });
    } catch (e) { /* 조용히 */ }
  }

  resize();
  load().then(() => { setMode('office'); render(); });
  setInterval(load, 60000);
})();
