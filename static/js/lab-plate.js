/* 고정 시점 연구실. 공개 상태만 표시하며 렌더 루프를 만들지 않아요. */
export async function createLabScene({canvas, labels, roster, onSelect, reducedMotion, onFailure}) {
  const root = canvas.closest('[data-engine]');
  const viewport = canvas.parentElement;
  const abort = new AbortController();
  const response = await fetch(root.dataset.layoutUrl, {signal: abort.signal});
  if (!response.ok) throw new Error('연구실 배치를 불러오지 못했어요.');
  const layout = await response.json();
  const assetBase = new URL('.', new URL(root.dataset.layoutUrl, location.href));
  const version = new URL(root.dataset.layoutUrl, location.href).search;
  const frame = document.createElement('div');
  frame.className = 'tc-lp-frame';
  frame.tabIndex = 0;
  frame.setAttribute('role', 'group');
  frame.setAttribute('aria-label', '연구실 확대 화면. 방향키로 이동, 더하기와 빼기로 확대·축소, Escape로 전체 보기');
  frame.setAttribute('aria-describedby', 'lab-scene-help');
  frame.dataset.paused = String(reducedMotion);
  const plane = document.createElement('div');
  plane.className = 'tc-lp-plane';
  const background = document.getElementById('lab-poster').cloneNode();
  background.removeAttribute('id');
  background.removeAttribute('hidden');
  background.className = 'tc-lp-background';
  plane.append(background);
  const ns = 'http://www.w3.org/2000/svg';
  const flow = document.createElementNS(ns, 'svg');
  flow.setAttribute('viewBox', '0 0 1536 1024');
  flow.setAttribute('aria-hidden', 'true');
  flow.classList.add('tc-lp-flow');
  for (const className of ['tc-lp-halo', 'tc-lp-trail', 'tc-lp-stream', 'tc-lp-glint']) {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('d', layout.flow);
    path.setAttribute('class', className);
    flow.append(path);
  }
  const stage = document.createElementNS(ns, 'circle');
  stage.classList.add('tc-lp-stage');
  stage.setAttribute('r', '15');
  stage.setAttribute('hidden', '');
  flow.append(stage);
  const flowPath = flow.querySelector('.tc-lp-trail');
  const stepOrder = ['meeting', 'decision', 'brief', 'draft', 'check', 'critique', 'chart', 'review', 'publish'];
  plane.append(flow);
  for (const item of layout.ambient || []) {
    if (!['screen', 'paper'].includes(item.kind)) continue;
    const light = document.createElement('span');
    light.className = `tc-lp-ambient tc-lp-ambient--${item.kind}`;
    light.setAttribute('aria-hidden', 'true');
    Object.assign(light.style, {
      left: `${item.x / 1536 * 100}%`, top: `${item.y / 1024 * 100}%`,
      width: `${item.width / 1536 * 100}%`, height: `${item.height / 1024 * 100}%`,
      animationDelay: `${item.delay || 0}s`,
    });
    plane.append(light);
  }
  const mask = background.cloneNode();
  mask.alt = '';
  mask.setAttribute('aria-hidden', 'true');
  mask.className = 'tc-lp-occlusion';
  mask.style.clipPath = layout.tableMask;
  plane.append(mask);
  const buttons = new Map();
  const images = [background, mask];
  let disposed = false, scale = 1, x = 0, y = 0, selected = '', meeting = '', active = '';
  let liveData = {}, replayTurn = null, replayCamera = null;
  let paused = reducedMotion, visible = true, updates = 0, drag = null, moved = false;
  const listen = (el, event, fn) => el.addEventListener(event, fn, {signal: abort.signal});
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
  function transform() {
    const limit = 50 * (scale - 1);
    x = clamp(x, -limit, limit); y = clamp(y, -limit, limit);
    plane.style.transform = `translate(${x}%, ${y}%) scale(${scale})`;
    frame.dataset.zoomed = String(scale > 1);
    updates++;
  }
  function center(key) {
    const p = layout.people[key];
    if (!p || scale === 1) return;
    x = (50 - (p.x + p.width / 2) / 1536 * 100) * scale;
    y = (50 - (p.y + p.height / 2) / 1024 * 100) * scale;
    transform();
  }
  function focusReplay() {
    if (!replayTurn || paused || !visible || !layout.people[meeting]) return;
    scale = 1.16;
    center(meeting);
  }
  function mark() {
    for (const [key, b] of buttons) {
      b.setAttribute('aria-pressed', String(key === selected));
      b.classList.toggle('is-selected', key === selected);
      b.classList.toggle('is-speaking', key === meeting);
      b.classList.toggle('is-active', key === active);
    }
    frame.dataset.working = String(Boolean(active));
    updates++;
  }
  function renderCue() {
    const index = stepOrder.indexOf(liveData.step);
    const showStage = index >= 0 && ['running', 'waiting', 'done'].includes(liveData.state);
    stage.toggleAttribute('hidden', !showStage);
    frame.dataset.stageState = showStage ? liveData.state : 'idle';
    if (showStage) {
      const point = flowPath.getPointAtLength(flowPath.getTotalLength() * (index / (stepOrder.length - 1)));
      stage.setAttribute('cx', point.x);
      stage.setAttribute('cy', point.y);
    }
    // 문장은 그림 밖 한 곳에서만 — 지금 하는 일은 위쪽 상태 줄, 지난 회의는 아래 재생 패널(그림 속 설명 상자는 중복이라 없앴다)
  }
  for (const agent of roster) {
    const p = layout.people[agent.key];
    if (!p) continue;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tc-lp-person';
    button.dataset.person = agent.key;
    button.setAttribute('aria-label', `${agent.name} · ${agent.title}`);
    button.setAttribute('aria-pressed', 'false');
    Object.assign(button.style, {left: `${p.x / 1536 * 100}%`, top: `${p.y / 1024 * 100}%`,
      width: `${p.width / 1536 * 100}%`, height: `${p.height / 1024 * 100}%`, zIndex: p.layer || 4});
    // 집필석은 인물과 가구를 함께 렌더해 책상 아래의 가림·접지를 보존해요.
    // 선택 영역과 실제 상태 표시는 다른 연구원과 동일하게 유지해요.
    button.classList.toggle('tc-lp-person--integrated', Boolean(p.integrated));
    if (!p.integrated) {
      const img = document.createElement('img');
      img.src = new URL(`people/${agent.key}.webp${version}`, assetBase).href;
      img.alt = ''; img.setAttribute('aria-hidden', 'true');
      img.width = p.pixelWidth; img.height = p.pixelHeight;
      img.draggable = false;
      button.append(img);
      images.push(img);
    }
    const name = document.createElement('span');
    name.className = 'tc-lp-name'; name.textContent = agent.name;
    name.setAttribute('aria-hidden', 'true');
    button.append(name);
    listen(button, 'click', e => { if (!moved || e.detail === 0) onSelect(agent.key); });
    listen(button, 'focus', () => center(agent.key));
    buttons.set(agent.key, button); plane.append(button);
  }
  frame.append(plane);
  // 로드가 끝나기 전에는 기존 미리보기를 유지해요. 실패하면 반쪽 장면을 노출하지 않아요.
  try { await Promise.all(images.map(img => img.decode())); }
  catch (error) { abort.abort(); throw error; }
  viewport.append(frame);
  canvas.hidden = true; labels.hidden = true;
  listen(frame, 'pointerdown', e => {
    moved = false;
    if (scale <= 1 || e.button !== 0) return;
    drag = {id: e.pointerId, px: e.clientX, py: e.clientY, x, y, width: plane.clientWidth, height: plane.clientHeight};
  });
  listen(frame, 'pointermove', e => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx = e.clientX - drag.px, dy = e.clientY - drag.py;
    if (Math.abs(dx) + Math.abs(dy) < 6 && !moved) return;
    moved = true; frame.dataset.dragging = 'true';
    frame.setPointerCapture(e.pointerId);
    x = drag.x + dx / drag.width * 100; y = drag.y + dy / drag.height * 100;
    transform();
  });
  const endDrag = () => { drag = null; frame.dataset.dragging = 'false'; };
  listen(frame, 'pointerup', endDrag); listen(frame, 'pointercancel', endDrag);
  listen(frame, 'lostpointercapture', endDrag);
  function zoom(factor) { scale = clamp(scale / factor, 1, 2.2); center(meeting || selected); transform(); }
  function reset() { scale = 1; x = 0; y = 0; transform(); }
  listen(frame, 'keydown', e => {
    if (e.key === '+' || e.key === '=') zoom(.88);
    else if (e.key === '-') zoom(1.14);
    else if (e.key === 'Escape') { onSelect(''); reset(); }
    else if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) {
      if (scale === 1) scale = 1.35;
      x += e.key === 'ArrowLeft' ? 6 : e.key === 'ArrowRight' ? -6 : 0;
      y += e.key === 'ArrowUp' ? 6 : e.key === 'ArrowDown' ? -6 : 0;
      transform();
    } else return;
    e.preventDefault();
  });
  function motion() { frame.dataset.paused = String(paused || !visible); }
  return {
    select(key) { selected = buttons.has(key) ? key : ''; mark(); center(selected); },
    setMeeting(key) { meeting = buttons.has(key) ? key : ''; mark(); center(meeting); },
    setActive(key) { active = buttons.has(key) ? key : ''; mark(); },
    setLive(data) { liveData = data || {}; renderCue(); },
    setReplay(turn) {
      if (turn && !replayTurn) replayCamera = {scale, x, y};
      replayTurn = turn;
      frame.dataset.replaying = String(Boolean(turn));
      if (turn) focusReplay();
      else if (replayCamera) {
        ({scale, x, y} = replayCamera);
        replayCamera = null;
        transform();
      }
      renderCue();
    },
    setPaused(value) { paused = value; motion(); if (!paused) focusReplay(); },
    setVisible(value) { visible = value; motion(); if (visible) focusReplay(); },
    zoom, reset,
    dispose() { if (disposed) return; disposed = true; abort.abort(); frame.remove(); labels.hidden = false; },
    stats() { return {engine: 'plate', people: buttons.size, scale, x, y, updates, animationPaused: paused || !visible, renderLoop: false}; },
  };
}
