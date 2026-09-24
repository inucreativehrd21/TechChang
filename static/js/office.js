/* 테크창 연구팀 픽셀 연구실 — canvas 렌더러 v2
 *
 * 해상도: 아트는 640x360 "아트 픽셀"로 그리고, 실제 캔버스는 (CSS 폭 × devicePixelRatio) 를 640 으로 나눈
 *   정수 배율 k 로 확대한다 (ctx.scale(k) + imageSmoothing off). 배율이 정수라 어떤 화면에서도 픽셀이 선명하다.
 * 레이어: [정적 배경] → [바닥 그림자·가구] → [인물] → [조명 오버레이(multiply)] → [스크린 글로우(lighter)] → [말풍선]
 *   정적 배경과 조명 맵은 오프스크린에 한 번만 그리고 매 프레임 합성만 한다.
 * 캐릭터: 24x32 절차적 렌더 — 4방향, 걷기 4프레임(팔 스윙), 앉기, 타이핑, 호흡, 눈 깜빡임, 발밑 그림자.
 * 데이터: /lab/state.json (연구원 상태·최근 회의). 외부 이미지 없음.
 */
(function () {
  const canvas = document.getElementById('office-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const ART = { w: 640, h: 360, wall: 74 };          // 매니페스트가 있으면 덮어쓴다
  const SEAT_OFF = { x: 28, y: 58 };                 // 책상 기준 착석 위치
  const stateUrl = canvas.dataset.stateUrl;
  const modeLabel = document.getElementById('office-mode');
  const captionEl = document.getElementById('office-caption');
  const btnMeeting = document.getElementById('btn-replay');
  const btnOffice = document.getElementById('btn-office');
  const FONT = '"Pretendard Variable", Pretendard, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif';
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ── 팔레트 (같은 재질은 4단 램프: 하이라이트 / 기본 / 음영 / 외곽)
  const P = {
    floor: ['#d7a367', '#c9924f', '#b8813f', '#a06c32'],
    floorDark: '#8d5d2a',
    wall: ['#f3ece0', '#e8dfd0', '#d8ccb8', '#b9a98f'],
    wainscot: ['#9c7b56', '#886a49', '#6f563a'],
    desk: ['#c98f58', '#b07a45', '#8d5f33', '#6d4826'],
    metal: ['#d4d9e2', '#aab3c0', '#7e8797', '#5a6270'],
    dark: ['#39404e', '#2b303b', '#1e222b', '#141820'],
    screen: ['#8fd8ff', '#4a9fd8', '#1f4f7a', '#12314d'],
    sofa: ['#a06ec4', '#8451a8', '#673f85', '#4d2d64'],
    plant: ['#5bc272', '#3da256', '#2b7d40', '#1d5c2e'],
    pot: ['#d07a44', '#b05f33', '#8a4826'],
    rug: ['#e9d7b4', '#dcc59a', '#c9ad7d'],
    tile: ['#f4f3ef', '#e6e4dc', '#d2cfc4'],
    paper: '#fbfaf6',
    glass: ['#d5f0fb', '#a9dcef', '#7bc0d8'],
    book: ['#d9534f', '#3d4fd9', '#2aa876', '#f0a33a', '#8e5cd9', '#3aa7c9', '#e07aa3', '#c94f7c'],
    sky: ['#cfe9ff', '#a9d4f5', '#7fb6e0'],
    city: ['#6b7d96', '#57687e', '#455468'],
  };

  // ── 기본 유틸 (모든 좌표는 정수로 스냅)
  let g = null;                                    // 현재 그리기 컨텍스트
  const R = (x, y, w, h, c) => { g.fillStyle = c; g.fillRect(x | 0, y | 0, w | 0, h | 0); };
  const dither = (x, y, w, h, c1, c2) => {         // 2색 체커 디더 — 부드러운 그라데이션 대용
    for (let j = 0; j < h; j++) for (let i = 0; i < w; i++) R(x + i, y + j, 1, 1, (i + j) % 2 ? c2 : c1);
  };
  function shadowEllipse(cx, cy, rx, ry, alpha) {
    g.fillStyle = `rgba(20,16,10,${alpha})`;
    g.beginPath(); g.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); g.fill();
  }

  // ── 레이아웃 (아트 좌표)
  const WALL_H = ART.wall;                         // (폴백 렌더러용)
  const DESKS = [                                  // 6개 책상 (매니페스트로 대체 가능)
    { x: 176, y: 108 }, { x: 292, y: 108 },
    { x: 176, y: 186 }, { x: 292, y: 186 },
    { x: 176, y: 264 }, { x: 292, y: 264 },
  ];
  const TABLE = { x: 28, y: 120, w: 110, h: 72 };   // 회의 테이블
  const SEATS = [                                   // 회의 좌석 (테이블 위/아래)
    { x: 52, y: 116, dir: 'down' }, { x: 83, y: 116, dir: 'down' }, { x: 114, y: 116, dir: 'down' },
    { x: 52, y: 212, dir: 'up' }, { x: 83, y: 212, dir: 'up' }, { x: 114, y: 212, dir: 'up' },
  ];
  const LAMPS = [[120, 96], [300, 96], [480, 96], [120, 250], [300, 250], [500, 250]];
  const WINDOWS = [[40, 18], [120, 18], [430, 18], [510, 18]];
  const SPOTS = {
    coffee: [566, 150], cooler: [600, 196], board: [236, 96], plant: [154, 322],
    sofa: [[452, 268, 'up'], [486, 268, 'up'], [520, 268, 'up']],
  };

  // ── 가구
  function drawDesk(x, y) {                        // 56x30 상판 + 측면(입체) + 소품
    shadowEllipse(x + 28, y + 31, 30, 6, 0.16);
    R(x, y + 22, 56, 8, P.desk[3]);                // 측면(두께)
    R(x, y, 56, 23, P.desk[1]);                    // 상판
    R(x, y, 56, 2, P.desk[0]);                     // 상판 하이라이트
    R(x, y + 21, 56, 2, P.desk[2]);
    R(x + 2, y + 28, 4, 8, P.desk[3]); R(x + 50, y + 28, 4, 8, P.desk[3]);   // 다리
    // 모니터 (받침 + 베젤 + 화면)
    R(x + 20, y + 16, 16, 3, P.dark[1]); R(x + 26, y + 10, 4, 6, P.dark[0]);
    R(x + 15, y - 14, 26, 18, P.dark[2]); R(x + 16, y - 13, 24, 16, P.dark[1]);
    R(x + 17, y - 12, 22, 14, P.screen[2]);
    // 키보드 · 마우스 · 머그 · 메모지
    R(x + 14, y + 8, 18, 6, P.metal[0]); R(x + 15, y + 9, 16, 4, P.metal[1]);
    for (let i = 0; i < 4; i++) R(x + 16 + i * 4, y + 10, 3, 2, P.metal[2]);
    R(x + 35, y + 9, 5, 5, P.metal[0]); R(x + 36, y + 10, 3, 2, P.metal[2]);
    R(x + 45, y + 5, 6, 7, P.paper); R(x + 51, y + 7, 2, 3, P.paper); R(x + 46, y + 6, 4, 2, '#d9534f');
    R(x + 4, y + 6, 8, 8, P.paper); R(x + 5, y + 8, 6, 1, '#b9b3a6'); R(x + 5, y + 10, 5, 1, '#b9b3a6');
  }

  function drawChair(x, y, dir) {                  // 16x18 스위블 의자
    shadowEllipse(x + 8, y + 17, 8, 3, 0.14);
    R(x + 6, y + 12, 4, 4, P.metal[2]);            // 기둥
    R(x + 2, y + 15, 12, 3, P.metal[1]); R(x + 1, y + 16, 14, 2, P.metal[2]);  // 발
    if (dir === 'up') { R(x + 1, y, 14, 4, P.dark[0]); R(x + 2, y + 1, 12, 2, P.dark[1]); }
    R(x + 1, y + 4, 14, 9, P.dark[1]); R(x + 2, y + 5, 12, 6, P.dark[0]);      // 좌판
    if (dir !== 'up') { R(x + 1, y + 11, 14, 4, P.dark[2]); }
  }

  function drawBookshelf(x, y) {                   // 64x52
    R(x, y, 64, 52, P.desk[3]); R(x + 2, y + 2, 60, 48, P.desk[2]);
    for (let s = 0; s < 3; s++) {
      const sy = y + 4 + s * 16;
      let bx = x + 5, i = s * 5;
      while (bx < x + 58) {
        const w = 3 + (i * 7) % 3, h = 9 + (i * 5) % 4;
        R(bx, sy + 13 - h, w, h, P.book[i % P.book.length]);
        R(bx, sy + 13 - h, w, 1, 'rgba(255,255,255,.25)');
        bx += w + 1; i++;
      }
      R(x + 2, sy + 13, 60, 3, P.desk[3]);
    }
  }

  function drawWhiteboard(x, y) {                  // 96x36
    R(x - 1, y - 1, 98, 38, P.metal[3]); R(x, y, 96, 36, P.paper);
    R(x + 6, y + 6, 30, 2, '#3d4fd9'); R(x + 6, y + 11, 48, 2, '#3d4fd9'); R(x + 6, y + 16, 36, 2, '#d9534f');
    R(x + 58, y + 6, 30, 2, '#2aa876'); R(x + 64, y + 11, 24, 2, '#2aa876'); R(x + 58, y + 16, 18, 2, '#f0a33a');
    R(x + 6, y + 23, 74, 1, '#d6d2c8'); R(x + 6, y + 27, 52, 1, '#d6d2c8');
    R(x + 8, y + 36, 80, 3, P.metal[2]); R(x + 20, y + 37, 8, 2, '#d9534f');   // 마커 트레이
  }

  function drawWindow(x, y) {                      // 60x44 — 하늘 그라데이션 + 도시 실루엣
    R(x - 2, y - 2, 64, 48, P.wainscot[2]); R(x, y, 60, 44, P.sky[2]);
    dither(x, y, 60, 16, P.sky[0], P.sky[1]); R(x, y + 16, 60, 12, P.sky[1]);
    [[4, 20, 8, 24], [14, 14, 7, 30], [23, 24, 9, 20], [34, 10, 8, 34], [44, 18, 6, 26], [52, 26, 6, 18]]
      .forEach(([bx, by, bw, bh], i) => {
        R(x + bx, y + by, bw, bh, P.city[i % 3]);
        for (let wy = by + 3; wy < by + bh - 2; wy += 5)
          for (let wx = bx + 1; wx < bx + bw - 1; wx += 3)
            if ((wx + wy) % 7 < 3) R(x + wx, y + wy, 1, 2, '#ffe9a8');
      });
    R(x + 29, y, 3, 44, P.wainscot[1]); R(x, y + 21, 60, 3, P.wainscot[1]);     // 창틀
    R(x, y, 60, 2, P.wainscot[2]); R(x, y + 42, 60, 2, P.wainscot[2]);
  }

  function drawPlant(x, y, big) {                  // 화분 (big: 대형)
    const s = big ? 1.4 : 1;
    shadowEllipse(x + 10 * s, y + 30 * s, 11 * s, 4, 0.16);
    R(x + 4 * s, y + 22 * s, 13 * s, 9 * s, P.pot[1]); R(x + 4 * s, y + 22 * s, 13 * s, 2, P.pot[0]);
    R(x + 3 * s, y + 20 * s, 15 * s, 3, P.pot[2]);
    const sway = reduceMotion ? 0 : Math.round(Math.sin(tick / 60 + x) * 1);
    [[0, 0, 6], [6, -4, 7], [12, 0, 6], [3, -8, 5], [9, -9, 6]].forEach(([dx, dy, h], i) => {
      const px = x + (4 + dx) * s + (i % 2 ? sway : -sway), py = y + (18 + dy) * s;
      R(px, py - h * s, 3 * s, h * s, i % 2 ? P.plant[1] : P.plant[2]);
      R(px, py - h * s, 1, h * s, P.plant[0]);
      R(px - 2, py - h * s - 3, 7 * s, 4, i % 2 ? P.plant[0] : P.plant[1]);
    });
  }

  function drawSofa(x, y, w) {                     // 가로 소파
    shadowEllipse(x + w / 2, y + 26, w / 2, 5, 0.16);
    R(x, y, w, 12, P.sofa[2]); R(x + 2, y + 2, w - 4, 9, P.sofa[1]); R(x + 2, y + 2, w - 4, 2, P.sofa[0]);
    R(x, y + 12, w, 13, P.sofa[1]);
    for (let i = 0; i < Math.floor(w / 26); i++) { R(x + 5 + i * 26, y + 14, 22, 9, P.sofa[0]); R(x + 5 + i * 26, y + 14, 22, 1, '#b98ad6'); }
    R(x - 3, y + 8, 7, 18, P.sofa[2]); R(x + w - 4, y + 8, 7, 18, P.sofa[2]);
  }

  function drawCoffeeBar(x, y) {                   // 커피머신 + 상판
    R(x - 4, y + 20, 56, 12, P.metal[3]); R(x - 4, y + 18, 56, 4, P.metal[0]);
    R(x, y - 16, 22, 36, P.dark[1]); R(x + 1, y - 15, 20, 12, P.metal[1]);
    R(x + 3, y - 13, 16, 8, P.dark[2]); R(x + 4, y - 12, 6, 2, '#4cc06a');
    R(x + 6, y - 2, 10, 8, P.dark[2]); R(x + 8, y + 4, 6, 4, P.paper);
    R(x + 30, y + 10, 8, 9, P.paper); R(x + 38, y + 12, 2, 4, P.paper);        // 머그
  }

  function drawCooler(x, y) {
    R(x, y - 22, 18, 22, P.glass[1]); dither(x + 2, y - 20, 14, 14, P.glass[0], P.glass[2]);
    R(x, y, 18, 26, P.metal[0]); R(x + 1, y + 1, 16, 24, P.metal[1]);
    R(x + 5, y + 8, 8, 6, P.dark[2]); R(x + 6, y + 6, 2, 3, '#3d4fd9'); R(x + 10, y + 6, 2, 3, '#d9534f');
  }

  function drawRug(x, y, w, h) {
    R(x, y, w, h, P.rug[2]); R(x + 3, y + 3, w - 6, h - 6, P.rug[1]);
    R(x + 7, y + 7, w - 14, h - 14, P.rug[0]);
    for (let i = 0; i < w - 14; i += 10) R(x + 7 + i, y + 7, 5, h - 14, P.rug[1]);
    R(x + 12, y + 12, w - 24, h - 24, P.rug[0]);
  }

  function drawMeetingTable() {
    const t = TABLE;
    shadowEllipse(t.x + t.w / 2, t.y + t.h + 2, t.w / 2, 7, 0.16);
    R(t.x, t.y + t.h - 8, t.w, 10, P.desk[3]);
    R(t.x, t.y, t.w, t.h - 6, P.desk[1]); R(t.x, t.y, t.w, 3, P.desk[0]);
    R(t.x + 4, t.y + 4, t.w - 8, t.h - 14, P.desk[2]);
    R(t.x + 6, t.y + 6, t.w - 12, t.h - 18, P.desk[1]);
    for (let i = 0; i < 3; i++) {                  // 서류 · 노트북
      R(t.x + 14 + i * 32, t.y + 16, 12, 9, P.paper);
      R(t.x + 15 + i * 32, t.y + 18, 10, 1, '#c3bdb0'); R(t.x + 15 + i * 32, t.y + 21, 8, 1, '#c3bdb0');
    }
    R(t.x + t.w / 2 - 8, t.y + 32, 16, 10, P.dark[1]); R(t.x + t.w / 2 - 7, t.y + 33, 14, 8, P.screen[2]);
    R(t.x + t.w / 2 - 4, t.y + 44, 8, 6, P.plant[2]); R(t.x + t.w / 2 - 6, t.y + 42, 12, 3, P.plant[1]);
  }

  function drawPrinter(x, y) {
    shadowEllipse(x + 14, y + 20, 15, 4, 0.14);
    R(x, y, 28, 18, P.metal[2]); R(x + 1, y + 1, 26, 8, P.metal[0]); R(x + 2, y + 10, 24, 7, P.metal[1]);
    R(x + 4, y + 3, 18, 4, P.paper); R(x + 22, y + 3, 3, 2, '#4cc06a');
  }

  function drawServerRack(x, y) {
    R(x, y, 22, 46, P.dark[2]); R(x + 2, y + 2, 18, 42, P.dark[1]);
    for (let i = 0; i < 6; i++) { R(x + 4, y + 5 + i * 7, 14, 4, P.dark[0]); R(x + 5, y + 6 + i * 7, 2, 2, '#4cc06a'); }
  }

  function drawClock(x, y) { R(x - 1, y - 1, 22, 22, P.dark[2]); R(x, y, 20, 20, P.paper); R(x + 9, y + 9, 2, 2, P.dark[1]); }

  function drawPoster(x, y, hue) {
    R(x, y, 26, 34, P.metal[3]); R(x + 1, y + 1, 24, 32, P.paper);
    R(x + 3, y + 3, 20, 14, hue); R(x + 3, y + 20, 20, 2, '#b9b3a6'); R(x + 3, y + 24, 14, 2, '#b9b3a6');
  }

  // ── 정적 배경
  function drawRoom() {
    // 벽
    R(0, 0, ART.w, WALL_H, P.wall[1]);
    dither(0, 0, ART.w, 10, P.wall[0], P.wall[1]);
    R(0, WALL_H - 16, ART.w, 12, P.wainscot[0]); R(0, WALL_H - 16, ART.w, 2, '#b08f68');
    R(0, WALL_H - 4, ART.w, 4, P.wainscot[2]);
    // 바닥 (널마루 + 나뭇결 + 벽 아래 AO)
    for (let row = 0; row * 12 + WALL_H < ART.h; row++) {
      const y = WALL_H + row * 12;
      for (let x = -((row * 30) % 90); x < ART.w; x += 90) {
        const shade = P.floor[(row + (x / 90 | 0)) % 2 ? 1 : 2];
        R(x, y, 90, 12, shade);
        R(x, y, 90, 1, P.floor[0]);
        R(x + 89, y, 1, 12, P.floorDark);
        R(x + 14, y + 5, 30, 1, P.floor[3]); R(x + 52, y + 8, 20, 1, P.floor[3]);
      }
      R(0, y + 11, ART.w, 1, P.floorDark);
    }
    for (let i = 0; i < 10; i++) R(0, WALL_H + i, ART.w, 1, `rgba(60,36,12,${0.16 - i * 0.016})`);
    // 탕비 구역 타일
    R(540, WALL_H, 100, 96, P.tile[1]);
    for (let x = 540; x < 640; x += 16) R(x, WALL_H, 1, 96, P.tile[2]);
    for (let y = WALL_H; y < WALL_H + 96; y += 16) R(540, y, 100, 1, P.tile[2]);
    R(538, WALL_H, 2, 96, 'rgba(60,36,12,.18)'); R(540, WALL_H + 95, 100, 2, 'rgba(60,36,12,.18)');
    // 라운지 러그
    drawRug(424, 232, 190, 116);
    // 벽 요소
    WINDOWS.forEach(([x, y]) => drawWindow(x, y));
    drawWhiteboard(188, 14); drawClock(300, 22); drawPoster(330, 16, '#4f46e5'); drawPoster(362, 16, '#2aa876');
    drawBookshelf(560, 8);
    // 가구
    drawMeetingTable();
    SEATS.forEach(s => drawChair(s.x - 8, s.y - (s.dir === 'up' ? 22 : -4), s.dir === 'up' ? 'up' : 'down'));
    DESKS.forEach(d => { drawChair(d.x + 20, d.y + 30, 'up'); drawDesk(d.x, d.y); });
    drawCoffeeBar(SPOTS.coffee[0], SPOTS.coffee[1]); drawCooler(SPOTS.cooler[0], SPOTS.cooler[1]);
    drawPrinter(556, 214); drawServerRack(608, 250);
    drawSofa(436, 236, 96); drawSofa(436, 318, 96);
    R(508, 276, 44, 26, P.glass[1]); R(510, 278, 40, 22, P.glass[0]);          // 유리 테이블
    R(506, 300, 48, 4, P.glass[2]);
    drawPlant(96, 292, true); drawPlant(596, 300, false); drawPlant(404, 92, false);
  }

  // ── 조명 맵 (배경 위에 multiply 로 합성)
  function buildLight(lc) {
    lc.fillStyle = 'rgba(26,28,48,0.30)'; lc.fillRect(0, 0, ART.w, ART.h);
    lc.globalCompositeOperation = 'destination-out';
    const pool = (x, y, r, a) => {
      const gr = lc.createRadialGradient(x, y, 0, x, y, r);
      gr.addColorStop(0, `rgba(0,0,0,${a})`); gr.addColorStop(1, 'rgba(0,0,0,0)');
      lc.fillStyle = gr; lc.beginPath(); lc.arc(x, y, r, 0, Math.PI * 2); lc.fill();
    };
    LAMPS.forEach(([x, y]) => pool(x, y, 96, 0.95));
    WINDOWS.forEach(([x, y]) => pool(x + 30, y + 70, 80, 0.8));
    pool(566, 160, 70, 0.8); pool(480, 290, 90, 0.7);
    lc.globalCompositeOperation = 'source-over';
  }

  // ── 절차적 캐릭터 (24x32, 원점 = 발 중앙)
  const HAIR = {
    short: { top: 4, side: 2, back: 0, fringe: 3 },
    long: { top: 4, side: 3, back: 9, fringe: 2 },
    bob: { top: 5, side: 4, back: 4, fringe: 4 },
    tied: { top: 4, side: 2, back: 6, fringe: 3 },
    curly: { top: 6, side: 3, back: 2, fringe: 5 },
  };
  function shade(hex, f) {                          // 간단 명도 조절
    const n = parseInt(hex.slice(1), 16);
    const r = Math.max(0, Math.min(255, Math.round((n >> 16) * f)));
    const gg = Math.max(0, Math.min(255, Math.round(((n >> 8) & 255) * f)));
    const b = Math.max(0, Math.min(255, Math.round((n & 255) * f)));
    return `rgb(${r},${gg},${b})`;
  }

  function drawPerson(a, x, y, pose, dir, frame, bob) {
    const sk = a.sprite.skin, skS = shade(sk, 0.86);
    const sh = a.sprite.shirt, shH = shade(sh, 1.18), shS = shade(sh, 0.78);
    const hr = a.sprite.hair, hrH = shade(hr, 1.3);
    const pants = '#3a4050', pantsS = shade(pants, 0.8), shoe = '#2a2018';
    const H = HAIR[a.sprite.style] || HAIR.short;
    x = Math.round(x - 12); y = Math.round(y) + bob;   // 좌상단 기준

    shadowEllipse(x + 12, y - 1, 9, 3.2, 0.2);
    const sit = pose === 'sit' || pose === 'type';
    const top = sit ? y - 28 : y - 32;

    // 다리 / 앉은 자세
    if (sit) {
      R(x + 6, top + 20, 5, 8, pants); R(x + 13, top + 20, 5, 8, pants);
      R(x + 6, top + 26, 12, 2, pantsS);
      R(x + 5, top + 27, 6, 3, shoe); R(x + 13, top + 27, 6, 3, shoe);
    } else {
      const sw = pose === 'walk' ? [0, 1, 0, -1][frame] : 0;
      R(x + 7, top + 22, 4, 8 + sw, pants); R(x + 13, top + 22, 4, 8 - sw, pants);
      R(x + 7, top + 22, 1, 8, shade(pants, 1.2));
      R(x + 6, top + 29 + sw, 6, 3, shoe); R(x + 12, top + 29 - sw, 6, 3, shoe);
    }

    // 몸통
    R(x + 5, top + 12, 14, 11, sh);
    R(x + 5, top + 12, 14, 2, shH);                    // 어깨 하이라이트
    R(x + 17, top + 12, 2, 11, shS);                   // 오른쪽 음영
    if (dir === 'down') { R(x + 11, top + 13, 2, 9, shS); }   // 옷 주름
    // 팔
    const arm = pose === 'walk' ? [0, -1, 0, 1][frame] : 0;
    const typing = pose === 'type' ? (Math.floor(tick / 6) % 2 ? 1 : 0) : 0;
    if (sit) {
      R(x + 2, top + 13, 3, 7, sh); R(x + 19, top + 13, 3, 7, sh);
      R(x + 2, top + 19 + typing, 3, 3, sk); R(x + 19, top + 19 + (1 - typing), 3, 3, sk);
    } else {
      R(x + 2, top + 13 + arm, 3, 8, sh); R(x + 19, top + 13 - arm, 3, 8, sh);
      R(x + 2, top + 20 + arm, 3, 3, sk); R(x + 19, top + 20 - arm, 3, 3, sk);
    }

    // 머리
    R(x + 6, top, 12, 12, sk);
    R(x + 6, top, 12, 1, shade(sk, 1.1)); R(x + 16, top + 1, 2, 11, skS);
    // 머리카락
    R(x + 5, top - 1, 14, H.top, hr); R(x + 5, top - 1, 14, 1, hrH);
    R(x + 5, top, H.side, 10, hr); R(x + 19 - H.side, top, H.side, 10, hr);
    if (H.back && dir !== 'up') { R(x + 4, top + 2, 2, H.back, hr); R(x + 18, top + 2, 2, H.back, hr); }
    if (dir === 'up') { R(x + 5, top, 14, 12, hr); R(x + 5, top, 14, 2, hrH); }
    else if (H.fringe) { R(x + 6, top + H.top - 1, H.fringe + 2, 2, hr); }
    // 눈 · 입
    if (dir !== 'up') {
      const blink = a.blink > 0;
      const ey = top + 6;
      if (dir === 'down') {
        R(x + 9, ey, 2, blink ? 1 : 2, blink ? skS : '#23201c');
        R(x + 14, ey, 2, blink ? 1 : 2, blink ? skS : '#23201c');
        R(x + 11, top + 9, 3, 1, skS);
      } else {
        const ex = dir === 'left' ? x + 8 : x + 14;
        R(ex, ey, 2, blink ? 1 : 2, blink ? skS : '#23201c');
        R(dir === 'left' ? x + 6 : x + 16, top + 9, 2, 1, skS);
      }
    }
    // 소품: 커피잔
    if (a.task === 'coffee' && !sit) { R(x + (dir === 'left' ? 0 : 21), top + 19, 4, 4, P.paper); R(x + (dir === 'left' ? 0 : 21), top + 19, 4, 1, '#d9534f'); }
  }

  // ── 입자 (먼지 · 김)
  const motes = [];
  for (let i = 0; i < 26; i++) motes.push({ x: Math.random() * ART.w, y: WALL_H + Math.random() * (ART.h - WALL_H), s: 0.15 + Math.random() * 0.25, p: Math.random() * 6.28 });
  const steam = [];

  function drawParticles() {
    if (reduceMotion) return;
    motes.forEach(m => {
      m.y -= m.s; m.x += Math.sin((tick + m.p * 30) / 70) * 0.18;
      if (m.y < WALL_H) { m.y = ART.h - 4; m.x = Math.random() * ART.w; }
      const nearLight = WINDOWS.some(([wx]) => Math.abs(m.x - (wx + 30)) < 60) || LAMPS.some(([lx, ly]) => Math.abs(m.x - lx) < 50 && Math.abs(m.y - ly) < 70);
      if (nearLight) R(m.x, m.y, 1, 1, 'rgba(255,246,214,.5)');
    });
    if (tick % 14 === 0) steam.push({ x: SPOTS.coffee[0] + 8, y: SPOTS.coffee[1] - 18, life: 40 });
    for (let i = steam.length - 1; i >= 0; i--) {
      const s = steam[i]; s.life--; s.y -= 0.35; s.x += Math.sin(s.life / 6) * 0.3;
      if (s.life <= 0) { steam.splice(i, 1); continue; }
      R(s.x, s.y, 2, 2, `rgba(255,255,255,${(s.life / 40) * 0.45})`);
    }
  }

  // ── 동적 소품 (시계 바늘 · 모니터 화면 · 서버 LED)
  function drawDynamicProps() {
    const now = new Date(), cx = 310, cy = 32;
    const hA = ((now.getHours() % 12) + now.getMinutes() / 60) / 12 * Math.PI * 2, mA = now.getMinutes() / 60 * Math.PI * 2;
    g.strokeStyle = P.dark[1]; g.lineWidth = 1;
    g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.sin(hA) * 5, cy - Math.cos(hA) * 5); g.stroke();
    g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.sin(mA) * 7, cy - Math.cos(mA) * 7); g.stroke();
    R(cx - 1, cy - 1, 2, 2, '#d9534f');

    DESKS.forEach((d, i) => {
      const a = agents.find(x => x.sprite.desk % 6 === i);
      const on = a && !a.moving && (a.task === 'work') && mode === 'office';
      R(d.x + 17, d.y - 12, 22, 14, on ? P.screen[2] : '#16283c');
      if (on) {
        R(d.x + 19, d.y - 10, 18, 1, P.screen[1]);
        R(d.x + 19, d.y - 7, 8 + (Math.floor(tick / 18) % 8), 1, P.screen[0]);
        R(d.x + 19, d.y - 4, 14, 1, P.screen[1]);
        if (Math.floor(tick / 25) % 2) R(d.x + 19 + 15, d.y - 4, 2, 1, P.screen[0]);
      }
    });
    if (Math.floor(tick / 30) % 2) R(613, 255, 2, 2, '#ffd166');
  }

  // 모니터 · 창문 글로우 (additive)
  function drawGlow() {
    g.globalCompositeOperation = 'lighter';
    DESKS.forEach((d, i) => {
      const a = agents.find(x => x.sprite.desk % 6 === i);
      if (!(a && !a.moving && a.task === 'work' && mode === 'office')) return;
      const gr = g.createRadialGradient(d.x + 28, d.y - 4, 0, d.x + 28, d.y - 4, 34);
      gr.addColorStop(0, 'rgba(90,170,230,.22)'); gr.addColorStop(1, 'rgba(90,170,230,0)');
      g.fillStyle = gr; g.fillRect(d.x - 8, d.y - 40, 72, 72);
    });
    WINDOWS.forEach(([x, y]) => {                    // 창 빛 기둥
      const gr = g.createLinearGradient(x + 30, y + 40, x + 30, y + 130);
      gr.addColorStop(0, 'rgba(255,240,200,.16)'); gr.addColorStop(1, 'rgba(255,240,200,0)');
      g.fillStyle = gr; g.beginPath();
      g.moveTo(x + 4, y + 44); g.lineTo(x + 56, y + 44); g.lineTo(x + 74, y + 132); g.lineTo(x - 14, y + 132);
      g.closePath(); g.fill();
    });
    g.globalCompositeOperation = 'source-over';
  }

  // ── 말풍선
  function roundRect(c, x, y, w, h, r, fill, stroke) {
    c.beginPath(); c.moveTo(x + r, y); c.lineTo(x + w - r, y); c.quadraticCurveTo(x + w, y, x + w, y + r);
    c.lineTo(x + w, y + h - r); c.quadraticCurveTo(x + w, y + h, x + w - r, y + h); c.lineTo(x + r, y + h);
    c.quadraticCurveTo(x, y + h, x, y + h - r); c.lineTo(x, y + r); c.quadraticCurveTo(x, y, x + r, y); c.closePath();
    if (fill) { c.fillStyle = fill; c.fill(); } if (stroke) { c.strokeStyle = stroke; c.lineWidth = 1; c.stroke(); }
  }
  function nameTag(a, cx, top) {
    g.font = `600 8px ${FONT}`;
    const w = Math.ceil(g.measureText(a.name).width) + 10;
    roundRect(g, Math.round(cx - w / 2), top - 13, w, 11, 3, 'rgba(22,26,36,.86)');
    g.fillStyle = '#fff'; g.textBaseline = 'alphabetic';
    g.fillText(a.name, Math.round(cx - w / 2) + 5, top - 4.5);
  }
  function bubble(text, cx, top, accent) {
    if (!text) return;
    g.font = `9px ${FONT}`;
    const maxW = 186, lines = []; let line = '';
    for (const ch of text) {
      const t = line + ch;
      if (g.measureText(t).width > maxW - 14) { lines.push(line); line = ch; } else line = t;
      if (lines.length >= 5) break;
    }
    if (line && lines.length < 5) lines.push(line);
    if (lines.length === 5 && text.length > lines.join('').length) lines[4] = lines[4].slice(0, -1) + '…';
    const w = Math.min(maxW, Math.ceil(Math.max(...lines.map(l => g.measureText(l).width))) + 14), h = lines.length * 11 + 10;
    const x = Math.max(3, Math.min(ART.w - w - 3, Math.round(cx - w / 2))), y = Math.max(3, top - h - 9);
    g.fillStyle = 'rgba(20,16,10,.16)'; roundRect(g, x + 1, y + 2, w, h, 4, 'rgba(20,16,10,.16)');
    roundRect(g, x, y, w, h, 4, '#ffffff', 'rgba(31,36,48,.9)');
    R(x + 1, y + 1, 3, h - 2, accent || '#4f46e5');
    g.fillStyle = '#1f2430';
    lines.forEach((l, i) => g.fillText(l, x + 10, y + 12 + i * 11));
    g.fillStyle = '#ffffff'; g.fillRect(cx - 3, y + h - 1, 6, 4);
    g.fillStyle = 'rgba(31,36,48,.9)'; g.fillRect(cx - 4, y + h + 3, 8, 1);
  }

  // ── 쉬는 멘트
  const REST = {
    work: ['자리에서 자료 읽으며 다음 작업을 기다리는 중이에요.', '메모 정리하면서 다음 일정을 확인하고 있어요.', '지난 칼럼 조회수를 다시 들여다보는 중.', '받은 편지함 정리하며 숨 고르는 중이에요.', '키보드 앞에 앉아 있지만 지금은 대기 중이에요.', '모니터 밝기만 만지작거리는 중… 곧 일 시작할게요.'],
    coffee: ['지금은 커피 한 잔 하며 쉬는 중이에요 ☕', '정수기 앞에서 잠깐 숨 고르는 중.', '따뜻한 물 한 잔 마시며 머리 비우는 중.', '커피 내리는 김에 프린터도 한번 봐두는 중.', '탕비실에서 동료 오길 기다리며 수다 준비 중 ☕'],
    sofa: ['소파에서 잠깐 쉬는 중이에요.', '라운지에서 다리 뻗고 쉬고 있어요.', '소파에 기대서 오늘 할 일을 머릿속으로 정리하는 중.', '잠깐 눈 붙이는 중… 5분만요.', '유리 테이블에 발 올리고 쉬는 중 (팀장님 안 보이죠?)'],
    board: ['화이트보드 앞에서 다음 주제를 궁리하는 중.', '보드에 적힌 안건을 다시 훑어보고 있어요.', '마커 들고 아이디어를 낙서하는 중.', '화이트보드 지우다가 좋은 문장 발견해서 다시 적는 중.', '다음 회의 때 꺼낼 이야기를 정리하고 있어요.'],
    plant: ['화분에 물 주며 머리 식히는 중 🌿', '창가에서 잠깐 바람 쐬는 중.', '화분 잎을 닦으며 딴생각 중이에요.', '창밖 도시 보면서 잠깐 멍 때리는 중.', '화분이 잘 크는지 확인하는 중 — 칼럼보다 잘 자라네요.'],
  };
  const ROLE = {
    lead: ['지표 대시보드 새로고침만 세 번째… 방문자 늘었나 보는 중.', '다음 회의 안건 초안을 머릿속으로 짜는 중이에요.', '팀원들 진행 상황을 슬쩍 체크하는 중.', '이번 주 심사 기준을 어떻게 잡을지 고민 중.'],
    hrd: ['요즘 HR 커뮤니티에서 도는 이야기를 훑어보는 중.', '다음 칼럼에 넣을 현장 사례를 찾고 있어요.', '리더십 책 한 페이지 읽다 멈춘 상태예요.', '1on1 잘하는 팀장들 특징을 메모하는 중.'],
    data: ['새로 나온 HR Analytics 사례를 스크랩하는 중.', '그래프 하나로 설명할 수 있는 주제를 찾고 있어요.', '비전공자 눈높이 표현을 고민하는 중.', 'AI 도구 벤치마크 결과를 읽어보는 중.'],
    coding: ['새 프레임워크 릴리스 노트를 훑어보는 중.', '입문자가 헷갈릴 만한 개념을 리스트업하는 중.', 'AI 코딩 도구를 직접 써보며 메모하는 중.', 'Git 로그 보면서 글감을 찾고 있어요.'],
    checker: ['지난 칼럼의 출처 링크가 살아 있는지 점검하는 중.', '통계 원문을 찾아 읽는 중 — 인용이 맞는지 확인!', '기존 칼럼 제목 목록을 다시 훑어보는 중 (중복 방지).', '검증 체크리스트를 다듬고 있어요.'],
    charter: ['차트 색 팔레트를 만지작거리는 중.', '표로 만들 만한 수치가 있는 자료를 찾는 중.', '막대냐 꺾은선이냐… 고민하는 중.', '지난 차트의 축 라벨을 다시 보는 중.'],
  };
  const pick = arr => arr[Math.floor(Math.random() * arr.length)];
  function newRestLine(a) {
    const pool = [...(REST[a.task] || REST.work), ...(ROLE[a.key] || [])];
    let line = pick(pool); if (line === a.restLine && pool.length > 1) line = pick(pool);
    a.restLine = line;
  }
  function statusText(a) {
    const st = a.status || {};
    if (!a.restLine) newRestLine(a);
    if (!st.text) return `아직 기록된 작업이 없어요. ${a.restLine}`;
    const m = st.age_min == null ? null : st.age_min;
    if (m != null && m < 10) return `지금 하는 일: ${st.text}`;
    const ago = m == null ? '' : m < 60 ? `${m}분 전` : m < 1440 ? `${Math.floor(m / 60)}시간 전` : `${Math.floor(m / 1440)}일 전`;
    return `${ago ? `${ago} ` : ''}마지막 작업: ${st.text} — ${a.restLine}`;
  }

  // ── 에셋 모드 — media/lab/manifest.json 이 있으면 구매 에셋(LimeZu)으로 그린다.
  //    방은 미리 조립한 6프레임 PNG, 인물은 레거시 캐릭터 시트(16x32, 4방향 x 6프레임).
  //    매니페스트가 없거나 로드 실패하면 아래 코드 렌더러로 자동 폴백한다.
  const ASSETS = { on: false, base: canvas.dataset.assetsBase || '', img: {}, man: null, rooms: [], chairs: null };

  const loadImage = src => new Promise(res => {
    const im = new Image();
    im.onload = () => res(im); im.onerror = () => res(null);
    im.src = src;
  });

  async function loadAssets() {
    const url = canvas.dataset.assetsUrl;
    if (!url) return false;
    try {
      const man = await (await fetch(url, { headers: { Accept: 'application/json' } })).json();
      const rooms = await Promise.all((man.room?.frames || []).map(f => loadImage(ASSETS.base + f)));
      if (!rooms.length || !rooms[0]) return false;
      // 의자 전경 레이어 — 인물보다 나중에 그려 등받이가 하반신을 가린다
      ASSETS.chairs = man.chairs ? { meta: man.chairs, img: await loadImage(ASSETS.base + man.chairs.file) } : null;
      const chars = {};
      await Promise.all(Object.entries(man.characters || {}).map(async ([k, c]) => {
        const [idle, run, sit] = await Promise.all(
          ['idle', 'run', 'sit'].map(a => (c[a] ? loadImage(ASSETS.base + c[a]) : null)));
        if (idle || run) chars[k] = { spec: c, idle, run, sit };
      }));
      ASSETS.man = man; ASSETS.rooms = rooms.filter(Boolean); ASSETS.img = chars; ASSETS.on = true;
      // 방 크기·좌표를 매니페스트에 맞춘다
      if (man.art) { ART.w = man.art.w; ART.h = man.art.h; }
      if (man.wall_h) ART.wall = man.wall_h;
      // 좌석: 책상 자리는 그대로 좌표로 (에셋 모드에선 DESKS 대신 seats_desk 를 쓴다)
      if (man.seats_desk) {
        DESKS.length = 0; SEAT_OFF.x = 0; SEAT_OFF.y = 0;
        man.seats_desk.forEach(([x, y]) => DESKS.push({ x, y }));
      }
      if (man.seats_meet) {
        SEATS.length = 0;
        man.seats_meet.forEach(([x, y]) => SEATS.push({ x, y, dir: 'up' }));
      }
      if (man.nav) { NAV.cell = man.nav.cell; NAV.w = man.nav.w; NAV.h = man.nav.h; NAV.grid = man.nav.grid; }
      if (man.approaches) APPROACH = man.approaches.map(([x, y]) => ({ x, y }));
      if (man.activities) ACTS = man.activities;
      if (man.spots) Object.assign(SPOTS, {
        coffee: man.spots.coffee || SPOTS.coffee, cooler: man.spots.cooler || SPOTS.cooler,
        board: man.spots.board || SPOTS.board, plant: man.spots.plant || SPOTS.plant,
        sofa: (man.spots.lounge || []).map(([x, y]) => [x, y, 'up']).concat(SPOTS.sofa).slice(0, 3),
      });
      return true;
    } catch (e) { return false; }
  }

  function drawRoomAssets() {                       // 방 배경 (프레임 0 — 나머지는 매 프레임 합성)
    g.drawImage(ASSETS.rooms[0], 0, 0);
  }

  function drawPersonAsset(a, x, y, pose, dir, frame, bob) {
    const c = ASSETS.img[a.key];
    if (!c) return false;
    const sp = c.spec, fw = sp.fw || 16, fh = sp.fh || 32, per = sp.frames || 6;
    const dirs = sp.dirs || ['right', 'up', 'left', 'down'];
    const sheet = pose === 'walk' ? (c.run || c.idle) : c.idle;
    if (!sheet) return false;
    const di = Math.max(0, dirs.indexOf(dir));
    // 서 있을 때·앉아 있을 때 모두 idle 을 천천히 돌려 숨쉬는 느낌을 준다
    const f = pose === 'walk' ? (frame % per) : Math.floor(tick / (pose === 'type' ? 22 : 12)) % per;
    // 앉아 작업하는 모습은 idle 의 뒷모습(dir=up)을 쓴다 — sit 시트는 소파용 옆모습이라 책상에선 어색하다
    const anim = pose === 'walk' ? 'run' : 'idle';
    const ox = (sp.ox && sp.ox[anim]) || 0;      // 앉기 시트는 프레임이 6~7px 밀려 있다
    const sx = (di * per + f) * fw + ox;
    shadowEllipse(x, y - 1, 6, 2.4, 0.22);
    g.drawImage(sheet, sx, 0, fw, fh, Math.round(x - fw / 2), Math.round(y - fh) + bob, fw, fh);
    return true;
  }

  // ── DOM 오버레이 (이름표·말풍선) — 캔버스 확대 배율과 무관하게 글자가 선명하다
  const overlay = document.getElementById('office-overlay');
  const tagEls = new Map();
  let sayEl = null;

  function syncOverlay(order) {
    if (!overlay) return;
    const scale = canvas.clientWidth / ART.w;
    for (const a of order) {
      let el = tagEls.get(a.key);
      if (!el) {
        el = document.createElement('div'); el.className = 'tag'; el.textContent = a.name;
        overlay.appendChild(el); tagEls.set(a.key, el);
      }
      const head = a.y - (poseOf(a) === 'sit' || poseOf(a) === 'type' ? 26 : 32);
      el.style.left = (a.x * scale) + 'px';
      el.style.top = (head * scale) + 'px';
      el.style.display = mode === 'meeting' ? 'none' : '';
    }
    // 말풍선: 한 번에 하나만
    const talker = mode === 'office' ? order.find(a => a.showStatus) : null;
    if (!talker) { if (sayEl) { sayEl.remove(); sayEl = null; } return; }
    if (!sayEl) { sayEl = document.createElement('div'); sayEl.className = 'say'; overlay.appendChild(sayEl); }
    const txt = statusText(talker);
    if (sayEl.dataset.txt !== txt) { sayEl.dataset.txt = txt; sayEl.innerHTML = '<b>' + talker.name + '</b> ' + escapeHtml(txt); }
    sayEl.style.setProperty('--accent', talker.sprite.shirt);
    const w = sayEl.offsetWidth, half = w / 2;
    const px = Math.min(Math.max(talker.x * scale, half + 6), canvas.clientWidth - half - 6);
    sayEl.style.left = px + 'px';
    sayEl.style.top = ((talker.y - 38) * scale) + 'px';
  }
  const escapeHtml = t => t.replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));

  // ── 상태 · 이동 · 행동
  //  NAV: 방 이미지에서 뽑은 '걸을 수 있는 칸' 격자. 이게 있으면 A* 로 통로를 따라 걷고,
  //  없으면(폴백 렌더러) 예전처럼 직선으로 움직인다.
  let agents = [], meeting = null, mode = 'office', tick = 0, k = 2, bg = null, light = null;
  let replay = { i: 0, t: 0 };
  const NAV = { cell: 0, w: 0, h: 0, grid: null };
  let APPROACH = [], ACTS = [];
  const busy = new Map();                       // 행동 지점 점유 (key → agent.key)
  const rnd = (a, b) => a + Math.random() * (b - a);
  const deskPos = a => { const d = DESKS[a.sprite.desk % 6]; return { x: d.x + SEAT_OFF.x, y: d.y + SEAT_OFF.y }; };
  const seatOf = a => SEATS[a.sprite.desk % 6];
  const approachOf = a => APPROACH[a.sprite.desk % APPROACH.length] || deskPos(a);

  // ── 길찾기
  const cellOf = (x, y) => ({ cx: Math.floor(x / NAV.cell), cy: Math.floor(y / NAV.cell) });
  const posOf = (cx, cy) => ({ x: cx * NAV.cell + NAV.cell / 2, y: cy * NAV.cell + NAV.cell / 2 });
  const canWalk = (cx, cy) => cx >= 0 && cy >= 0 && cx < NAV.w && cy < NAV.h && NAV.grid[cy][cx] === '.';

  function nearestWalk(x, y) {                  // 막힌 칸이면 가장 가까운 통로 칸으로
    const c = cellOf(x, y);
    if (canWalk(c.cx, c.cy)) return c;
    for (let r = 1; r < 12; r++)
      for (let dy = -r; dy <= r; dy++)
        for (let dx = -r; dx <= r; dx++)
          if (Math.abs(dx) === r || Math.abs(dy) === r)
            if (canWalk(c.cx + dx, c.cy + dy)) return { cx: c.cx + dx, cy: c.cy + dy };
    return c;
  }

  function findPath(from, to) {                 // A* (4방향 + 대각선은 양옆이 뚫렸을 때만)
    if (!NAV.grid) return null;
    const a = nearestWalk(from.x, from.y), b = nearestWalk(to.x, to.y);
    if (a.cx === b.cx && a.cy === b.cy) return [];
    const key = (cx, cy) => cy * NAV.w + cx;
    const open = [{ ...a, g: 0, f: 0, p: null }];
    const seen = new Map([[key(a.cx, a.cy), open[0]]]);
    const H = (cx, cy) => Math.abs(cx - b.cx) + Math.abs(cy - b.cy);
    const DIRS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
    let guard = 6000;
    while (open.length && guard--) {
      open.sort((m, n) => m.f - n.f);
      const cur = open.shift();
      if (cur.cx === b.cx && cur.cy === b.cy) {
        const path = [];
        for (let n = cur; n; n = n.p) path.unshift(posOf(n.cx, n.cy));
        path.shift();
        return path;
      }
      for (const [dx, dy] of DIRS) {
        const nx = cur.cx + dx, ny = cur.cy + dy;
        if (!canWalk(nx, ny)) continue;
        if (dx && dy && !(canWalk(cur.cx + dx, cur.cy) && canWalk(cur.cx, cur.cy + dy))) continue;
        const g = cur.g + (dx && dy ? 1.41 : 1);
        const kk = key(nx, ny), prev = seen.get(kk);
        if (prev && prev.g <= g) continue;
        const node = { cx: nx, cy: ny, g, f: g + H(nx, ny), p: cur };
        seen.set(kk, node); open.push(node);
      }
    }
    return null;
  }

  function goTo(a, x, y, onArrive) {
    a.path = findPath({ x: a.x, y: a.y }, { x, y }) || [];
    a.finalTarget = { x, y };
    a.onArrive = onArrive || null;
    a.state = 'goto';
  }

  // ── 행동 선택
  function startWork(a) {                       // 자리에 앉아 작업
    a.state = 'work'; a.task = 'work'; a.pose = 'type'; a.face = 'up';
    a.wait = rnd(600, 1600);
  }

  function goSit(a) {                           // 통로 → 의자 (충돌 무시하고 살짝 들어간다)
    const d = deskPos(a);
    a.state = 'sitting'; a.task = 'work'; a.sitTarget = d; a.face = 'up';
  }

  function pickActivity(a) {
    const free = ACTS.filter(t => !busy.has(t.key) || busy.get(t.key) === a.key);
    if (!free.length) { startWork(a); return; }
    const t = free[Math.floor(Math.random() * free.length)];
    busy.set(t.key, a.key);
    a.act = t;
    a.state = 'goto'; a.task = t.key;
    goTo(a, t.at[0], t.at[1], () => {
      a.state = 'doing'; a.face = t.face || 'down'; a.pose = t.pose || 'stand';
      a.wait = rnd(t.dur ? t.dur[0] : 200, t.dur ? t.dur[1] : 400);
    });
  }

  function releaseAct(a) {
    if (a.act) { if (busy.get(a.act.key) === a.key) busy.delete(a.act.key); a.act = null; }
  }

  function nextPlan(a) {                        // 작업이 끝나면: 자리 → 용무 → 자리
    if (a.state === 'work') {
      if (Math.random() < 0.75) { releaseAct(a); pickActivity(a); }
      else a.wait = rnd(400, 900);
      return;
    }
    releaseAct(a);
    const ap = approachOf(a);
    a.task = 'return';
    goTo(a, ap.x, ap.y, () => goSit(a));
  }

  // 폴백(에셋 없음) 전용: 예전 방식의 단순 배회
  function planIdleSimple(a) {
    const r = Math.random();
    if (r < 0.5) { const d = deskPos(a); a.task = 'work'; a.wait = rnd(360, 900); a.tx = d.x; a.ty = d.y; a.face = 'up'; }
    else if (r < 0.7) { a.task = 'coffee'; a.wait = rnd(200, 360); a.tx = SPOTS.coffee[0]; a.ty = SPOTS.coffee[1]; a.face = 'up'; }
    else if (r < 0.85) { a.task = 'board'; a.wait = rnd(200, 340); a.tx = SPOTS.board[0] + rnd(-30, 30); a.ty = SPOTS.board[1]; a.face = 'up'; }
    else { a.task = 'plant'; a.wait = rnd(150, 260); a.tx = SPOTS.plant[0]; a.ty = SPOTS.plant[1]; a.face = 'left'; }
  }

  function planIdle(a) {                        // 외부(모드 전환)에서 호출
    if (NAV.grid) { releaseAct(a); a.path = null; goSit(a); }
    else planIdleSimple(a);
  }

  // ── 매 프레임 이동
  const SPEED = 0.42;

  function moveToward(a, x, y, speed) {
    const dx = x - a.x, dy = y - a.y, d = Math.hypot(dx, dy);
    if (d < 0.6) { a.x = x; a.y = y; return true; }
    a.x += dx / d * speed; a.y += dy / d * speed;
    a.dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? 'right' : 'left') : (dy > 0 ? 'down' : 'up');
    a.walkT = (a.walkT + 0.17) % 4;
    return false;
  }

  function step(a) {
    if (a.blink > 0) a.blink--; else if (Math.random() < 0.004) a.blink = 7;

    if (mode === 'meeting') {                   // 회의: 자리로 모인다
      const s = seatOf(a);
      a.moving = !moveToward(a, s.x, s.y, SPEED * 1.3);
      if (!a.moving) { a.dir = s.dir || 'up'; a.pose = 'sit'; }
      a.showStatus = false;
      return;
    }

    if (!NAV.grid) {                            // 폴백: 직선 이동
      a.moving = !moveToward(a, a.tx, a.ty, 0.55);
      if (!a.moving) { a.dir = a.face || 'down'; a.wait--; if (a.wait <= 0) planIdleSimple(a); }
    } else {
      switch (a.state) {
        case 'goto': {
          a.moving = true;
          if (!a.path || !a.path.length) {       // 길이 없으면 목표로 직접
            if (moveToward(a, a.finalTarget.x, a.finalTarget.y, SPEED)) {
              a.moving = false; const cb = a.onArrive; a.onArrive = null; if (cb) cb();
            }
            break;
          }
          const wp = a.path[0];
          if (moveToward(a, wp.x, wp.y, SPEED)) a.path.shift();
          if (!a.path.length) {
            if (moveToward(a, a.finalTarget.x, a.finalTarget.y, SPEED)) {
              a.moving = false; const cb = a.onArrive; a.onArrive = null; if (cb) cb();
            }
          }
          break;
        }
        case 'sitting': {                        // 통로에서 의자로 들어가는 짧은 이동
          a.moving = !moveToward(a, a.sitTarget.x, a.sitTarget.y, SPEED * 0.8);
          if (!a.moving) startWork(a);
          break;
        }
        case 'doing':
        case 'work':
        default: {
          a.moving = false;
          a.dir = a.face || 'down';
          a.wait--;
          if (a.wait <= 0) nextPlan(a);
          break;
        }
      }
    }

    const ph = (tick + a.phase) % 1600, show = ph < 240;
    if (show && !a.showStatus) newRestLine(a);
    a.showStatus = show;
  }

  function poseOf(a) {
    if (mode === 'meeting') return a.moving ? 'walk' : 'stand';
    if (a.moving) return 'walk';
    if (a.state === 'work' || a.task === 'work') return 'type';
    return a.pose || 'stand';
  }

  // ── 렌더
  function resize() {
    const cssW = canvas.parentElement.clientWidth;
    const dpr = window.devicePixelRatio || 1;
    // 백킹 스토어는 정수 배율(픽셀 선명), 표시 폭은 컨테이너를 채운다 (image-rendering: pixelated)
    k = Math.max(1, Math.round(cssW * dpr / ART.w));
    canvas.width = ART.w * k; canvas.height = ART.h * k;
    canvas.style.width = '100%'; canvas.style.maxWidth = (ART.w * 3) + 'px';
    canvas.style.height = 'auto';
    ctx.imageSmoothingEnabled = false;

    bg = document.createElement('canvas'); bg.width = ART.w * k; bg.height = ART.h * k;
    const bc = bg.getContext('2d'); bc.imageSmoothingEnabled = false; bc.scale(k, k);
    g = bc; (ASSETS.on ? drawRoomAssets : drawRoom)(); g = ctx;

    light = document.createElement('canvas'); light.width = ART.w * k; light.height = ART.h * k;
    const lc = light.getContext('2d'); lc.imageSmoothingEnabled = false; lc.scale(k, k);
    buildLight(lc);
  }

  function render() {
    tick++;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.imageSmoothingEnabled = false;
    ctx.drawImage(bg, 0, 0);
    ctx.setTransform(k, 0, 0, k, 0, 0);
    g = ctx;
    if (ASSETS.on && ASSETS.rooms.length > 1 && !reduceMotion) {      // 화면 깜빡임 등 방 애니메이션
      const ms = (ASSETS.man.room && ASSETS.man.room.ms) || 420;
      const idx = Math.floor(Date.now() / ms) % ASSETS.rooms.length;
      if (idx) g.drawImage(ASSETS.rooms[idx], 0, 0);
    }

    for (const a of agents) step(a);
    if (!ASSETS.on) drawDynamicProps();

    const order = agents.slice().sort((p, q) => p.y - q.y);
    for (const a of order) {
      const pose = poseOf(a);
      const breathe = (!a.moving && !reduceMotion && Math.floor(tick / 45) % 2) ? 1 : 0;
      if (!(ASSETS.on && drawPersonAsset(a, a.x, a.y, pose, a.dir || 'down', Math.floor(a.walkT), breathe)))
        drawPerson(a, a.x, a.y, pose, a.dir || 'down', Math.floor(a.walkT), breathe);
      // 이름표는 DOM 오버레이가 그린다
    }
    // 의자 전경: 앉은 사람의 하반신을 등받이가 가리도록 인물 위에 덧그린다
    if (ASSETS.on && ASSETS.chairs && ASSETS.chairs.img) {
      const { img, meta } = ASSETS.chairs;
      meta.at.forEach(([cx, cy], i) => g.drawImage(img, i * meta.w, 0, meta.w, meta.h, cx, cy, meta.w, meta.h));
    }
    if (!ASSETS.on) drawParticles();

    // 조명 합성
    if (!ASSETS.on) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalCompositeOperation = 'multiply'; ctx.drawImage(light, 0, 0);
      ctx.globalCompositeOperation = 'source-over';
      ctx.setTransform(k, 0, 0, k, 0, 0);
      drawGlow();
    }

    syncOverlay(order);
    if (mode === 'meeting') renderMeeting();
    requestAnimationFrame(render);
  }

  function renderMeeting() {
    if (!meeting || !meeting.transcript.length) { captionEl.textContent = '재생할 회의록이 없습니다.'; return; }
    const line = meeting.transcript[replay.i];
    const a = agents.find(x => x.key === line.agent);
    replay.t++;
    const shown = line.text.slice(0, Math.floor(replay.t / 2));
    if (a && !a.moving && overlay) {
      if (!sayEl) { sayEl = document.createElement('div'); sayEl.className = 'say'; overlay.appendChild(sayEl); }
      const scale = canvas.clientWidth / ART.w;
      sayEl.dataset.txt = shown;
      sayEl.innerHTML = '<b>' + line.name + '</b> ' + escapeHtml(shown);
      sayEl.style.setProperty('--accent', a.sprite.shirt);
      const half = sayEl.offsetWidth / 2;
      sayEl.style.left = Math.min(Math.max(a.x * scale, half + 6), canvas.clientWidth - half - 6) + 'px';
      sayEl.style.top = ((a.y - 38) * scale) + 'px';
    }
    captionEl.innerHTML = `<b>${line.name}</b> <span class="muted">${line.round}라운드 · ${replay.i + 1}/${meeting.transcript.length}</span><br>${shown}`;
    if (shown.length >= line.text.length && replay.t > line.text.length * 2 + 240) { replay.i = (replay.i + 1) % meeting.transcript.length; replay.t = 0; }
  }

  function setMode(m) {
    mode = m; replay = { i: 0, t: 0 };
    modeLabel.textContent = m === 'meeting' ? '편집회의 재생 중' : '연구실';
    btnMeeting.hidden = m === 'meeting'; btnOffice.hidden = m !== 'meeting';
    if (sayEl) { sayEl.remove(); sayEl = null; }
    if (m === 'office') { captionEl.textContent = ''; busy.clear(); agents.forEach(planIdle); }
    if (m === 'meeting') agents.forEach(a => { releaseAct(a); a.path = null; });
  }
  btnMeeting.addEventListener('click', () => setMode('meeting'));
  btnOffice.addEventListener('click', () => setMode('office'));
  canvas.addEventListener('click', ev => {
    const r = canvas.getBoundingClientRect();
    const mx = (ev.clientX - r.left) * ART.w / r.width, my = (ev.clientY - r.top) * ART.h / r.height;
    const hit = agents.find(a => Math.abs(a.x - mx) < 14 && my > a.y - 34 && my < a.y + 4);
    if (hit) { newRestLine(hit); hit.phase = (1600 - tick % 1600) % 1600; }
  });
  window.addEventListener('resize', () => { clearTimeout(window.__labRz); window.__labRz = setTimeout(resize, 120); });

  async function load() {
    try {
      const res = await fetch(stateUrl, { headers: { Accept: 'application/json' } });
      const data = await res.json();
      meeting = data.meeting;
      if (!agents.length) {
        const styles = ['long', 'short', 'bob', 'curly', 'tied', 'short'];
        agents = data.agents.map((a, i) => {
          const sprite = { ...a.sprite, style: a.sprite.style || styles[i % styles.length] };
          const d = DESKS[sprite.desk % 6];
          return { ...a, sprite, x: d.x + SEAT_OFF.x, y: d.y + SEAT_OFF.y, tx: d.x + SEAT_OFF.x, ty: d.y + SEAT_OFF.y,
                   task: 'work', state: 'work', pose: 'type', face: 'up', dir: 'up',
                   wait: rnd(240, 1400), blink: 0, walkT: 0, path: null, act: null,
                   phase: i * 266, moving: false };
        });
        btnMeeting.disabled = !(meeting && meeting.transcript.length);
      } else data.agents.forEach(s => { const a = agents.find(x => x.key === s.key); if (a) a.status = s.status; });
    } catch (e) { /* 조용히 */ }
  }

  // 디버그 훅 — 콘솔에서 __lab.agents() 로 연구원 상태 확인 (문제 진단용)
  window.__lab = {
    nav: () => ({ on: ASSETS.on, grid: !!NAV.grid, cells: NAV.grid ? NAV.grid.join('').split('.').length - 1 : 0,
                  acts: ACTS.length, desks: DESKS.length, art: { ...ART } }),
    agents: () => agents.map(a => ({
      key: a.key, name: a.name, state: a.state, task: a.task, pose: poseOf(a),
      x: Math.round(a.x), y: Math.round(a.y), dir: a.dir, moving: a.moving,
      path: (a.path || []).length, wait: Math.round(a.wait || 0),
    })),
    walkable: (x, y) => canWalk(Math.floor(x / NAV.cell), Math.floor(y / NAV.cell)),
  };

  loadAssets().then(() => { resize(); return load(); }).then(() => { setMode('office'); render(); });
  setInterval(load, 60000);
})();
