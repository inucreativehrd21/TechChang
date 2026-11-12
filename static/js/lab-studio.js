/* 공개 기록만 읽는 장면 컨트롤러. 모델 실행과 DB 쓰기는 하지 않아요. */
const root = document.getElementById('lab-studio');
const $ = id => document.getElementById(id);
const roster = JSON.parse($('lab-roster')?.textContent || '[]');
const people = new Map(roster.map(a => [a.key, a]));
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
let scene, loading = false, selected = '', live = {}, state = {}, stateFailed = false;
let paused = reduced.matches, visible = true, stateTimer, liveTimer, replayTimer;
let replayIndex = -1, replayAuto = !reduced.matches, priorSelection = '';
let pollingEpoch = 0;
const selectButtons = [...document.querySelectorAll('button[data-agent]')];
const controls = ['lab-reset', 'lab-zoom-in', 'lab-zoom-out', 'lab-motion'];

function ageText(minutes) {
  if (minutes == null) return '';
  if (minutes < 1) return '최근 활동 · 방금 전';
  if (minutes < 60) return `최근 활동 · ${minutes}분 전`;
  if (minutes < 1440) return `최근 활동 · ${Math.floor(minutes / 60)}시간 전`;
  return `최근 활동 · ${Math.floor(minutes / 1440)}일 전`;
}
function renderPerson() {
  const agent = people.get(selected);
  const current = state.agents?.find(a => a.key === selected);
  selectButtons.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.agent === selected)));
  $('lab-show-all').hidden = !agent;
  $('lab-person-name').textContent = agent?.name || '연구원을 만나 보세요';
  $('lab-person-role').textContent = agent?.title || '함께 만드는 연구';
  $('lab-person-duty').textContent = agent?.duty || '자료를 찾는 순간부터 글이 공개될 때까지, 각자 맡은 일이 있어요.';
  const working = agent && live.state === 'running' && live.agent === selected;
  $('lab-activity-title').textContent = working ? '지금 맡은 일' : agent ? '최근 공개 활동' : '이 공간에서는';
  $('lab-person-activity').textContent = working ? live.message : agent ? (current?.status?.text || (stateFailed ? '활동을 불러오지 못했어요. 잠시 후 다시 확인해요.' : '아직 공개된 활동이 없어요.')) : '연구원이나 아래 이름을 선택하면 맡은 역할과 최근 활동을 읽을 수 있어요.';
  $('lab-activity-age').textContent = working ? '실제 제작 상태' : agent ? ageText(current?.status?.age_min) : '';
}
function select(key) {
  if (replayIndex >= 0) stopReplay();
  selected = people.has(key) ? key : '';
  scene?.select(selected);
  renderPerson();
}
selectButtons.forEach(b => b.addEventListener('click', () => {
  select(b.dataset.agent);
  const panel = $('lab-person-detail');
  const rect = panel.getBoundingClientRect();
  if (rect.bottom < 0 || rect.top > innerHeight) panel.scrollIntoView({block:'center',behavior:reduced.matches?'instant':'smooth'});
}));
$('lab-show-all').addEventListener('click', () => select(''));

function renderLive(data) {
  live = data;
  root.dataset.state = data.state || 'idle';
  $('lab-studio-status').textContent = data.message || '지금은 쉬는 중이에요.';
  scene?.setActive(data.state === 'running' ? data.agent : '');
  scene?.setLive?.(data);
  const flow = $('lab-flow');
  const steps = [...flow.querySelectorAll('[data-step]')];
  const idx = steps.findIndex(e => e.dataset.step === data.step);
  steps.forEach((el, i) => {
    el.classList.toggle('is-done', idx >= 0 && (i < idx || (data.state === 'done' && i === idx)));
    el.classList.toggle('is-active', idx === i && data.state !== 'done');
    el.classList.toggle('is-waiting', idx === i && data.state === 'waiting');
    if (i === idx) el.setAttribute('aria-current', 'step'); else el.removeAttribute('aria-current');
  });
  const status = $('lab-flow-status');
  status.dataset.state = data.state || 'idle';
  status.querySelector('.tc-lb-live-text').textContent = (data.message || '') + (data.state === 'idle' && data.next ? ` 다음 일정: ${data.next.label} ${data.next.what}.` : '');
  renderPerson();
}
async function json(url) {
  const response = await fetch(url, {headers: {Accept: 'application/json'}, cache: 'no-store', signal: AbortSignal.timeout(12000)});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}
async function loadState() {
  try {
    state = await json(root.dataset.stateUrl);
    stateFailed = false;
    $('lab-replay').disabled = !(state.meeting?.transcript?.length);
    $('lab-replay').title = $('lab-replay').disabled ? '공개된 회의 요약이 아직 없어요.' : '지난 회의의 공개 요약을 보여줘요.';
    renderPerson();
  } catch {
    stateFailed = true;
    renderPerson();
  }
}
async function loadLive() {
  try { renderLive(await json(root.dataset.liveUrl)); }
  catch {
    renderLive({state:'unknown',message:'현재 상태를 확인하지 못했어요. 잠시 후 다시 확인해요.'});
  }
}
function stopPolling() { pollingEpoch++; clearTimeout(stateTimer); clearTimeout(liveTimer); }
async function pollState(epoch) {
  await loadState();
  if (epoch === pollingEpoch && visible && !document.hidden) stateTimer = setTimeout(() => pollState(epoch), 60000);
}
async function pollLive(epoch) {
  await loadLive();
  if (epoch === pollingEpoch && visible && !document.hidden) liveTimer = setTimeout(() => pollLive(epoch), live.state === 'running' ? 10000 : 60000);
}
function startPolling() { stopPolling(); if (visible && !document.hidden) { pollState(pollingEpoch); pollLive(pollingEpoch); } }

function renderMotion() {
  const button = $('lab-motion');
  button.textContent = paused ? '움직임 재생' : '움직임 정지';
  button.setAttribute('aria-pressed', String(paused));
  scene?.setPaused(paused);
}
async function start3D() {
  if (scene || loading) return;
  loading = true;
  const button = $('lab-start');
  button.disabled = true;
  button.querySelector('b').textContent = '연구실을 여는 중…';
  try {
    const plate = root.dataset.engine === 'plate';
    const sceneURL = new URL(plate ? './lab-plate.js' : './lab-scene.js', import.meta.url);
    sceneURL.search = new URL(import.meta.url).search;
    const {createLabScene} = await import(sceneURL.href);
    scene = await createLabScene({canvas: $('lab-canvas'), labels: $('lab-labels'), roster,
      onSelect: select, reducedMotion: reduced.matches, onFailure: fallback});
    root.dataset.renderer = plate ? 'plate' : 'webgl';
    $('lab-canvas').hidden = plate;
    $('lab-poster').hidden = true;
    button.hidden = true;
    controls.forEach(id => $(id).disabled = false);
    $('lab-scene-note').textContent = '아래 이름으로도 연구원을 선택할 수 있어요.';
    scene.select(selected);
    scene.setActive(live.state === 'running' ? live.agent : '');
    scene.setLive?.(live);
    if (replayIndex >= 0) {
      const turn = transcript()[replayIndex];
      scene.setMeeting(turn?.agent || '');
      scene.setReplay?.(turn ? {name: people.get(turn.agent)?.name || '', text: turn.text} : null);
    }
    scene.setVisible(visible && !document.hidden);
    renderMotion();
  } catch { fallback(); }
  finally { loading = false; }
}
function fallback() {
  scene?.dispose(); scene = null;
  root.dataset.renderer = 'poster';
  $('lab-canvas').hidden = true;
  $('lab-poster').hidden = false;
  $('lab-labels').replaceChildren();
  $('lab-start').hidden = false;
  $('lab-start').disabled = false;
  $('lab-start').querySelector('b').textContent = '연구실 다시 열기';
  $('lab-start').querySelector('small').textContent = '미리보기와 아래 연구원 정보는 계속 볼 수 있어요';
  $('lab-scene-note').textContent = '연구실 이미지를 불러오지 못했어요. 아래 이름으로 연구원 정보를 볼 수 있어요.';
  controls.forEach(id => $(id).disabled = true);
}
$('lab-start').addEventListener('click', start3D);
$('lab-reset').addEventListener('click', () => { select(''); scene?.reset(); });
$('lab-zoom-in').addEventListener('click', () => scene?.zoom(.88));
$('lab-zoom-out').addEventListener('click', () => scene?.zoom(1.14));
$('lab-motion').addEventListener('click', () => { paused = !paused; renderMotion(); });
reduced.addEventListener('change', e => { if (e.matches) { paused = true; renderMotion(); pauseReplay(); } });

function transcript() { return (state.meeting?.transcript || []).filter(t => people.has(t.agent) && t.text); }
function scheduleReplay() {
  clearTimeout(replayTimer);
  if (replayAuto && replayIndex >= 0 && visible && !document.hidden) replayTimer = setTimeout(() => {
    if (replayIndex + 1 < transcript().length) showTurn(replayIndex + 1); else pauseReplay();
  }, 12000);
}
function pauseReplay() { replayAuto = false; scheduleReplay(); $('lab-replay-pause').textContent = '자동 넘김 재생'; $('lab-replay-pause').setAttribute('aria-pressed', 'true'); }
function showTurn(index) {
  const turns = transcript();
  if (!turns.length) return;
  replayIndex = Math.max(0, Math.min(index, turns.length - 1));
  const t = turns[replayIndex];
  const a = people.get(t.agent);
  const date = new Date(state.meeting.held_at).toLocaleDateString('ko-KR');
  $('lab-replay-heading').textContent = `${date} 공개 회의 요약 · ${a.name}`;
  $('lab-replay-progress').textContent = `${replayIndex + 1} / ${turns.length}`;
  $('lab-replay-text').textContent = t.text;
  $('lab-replay-panel').hidden = false;
  $('lab-replay-stop').hidden = false;
  $('lab-replay').hidden = true;
  $('lab-replay-prev').disabled = replayIndex === 0;
  $('lab-replay-next').disabled = replayIndex === turns.length - 1;
  scene?.setMeeting(t.agent);
  scene?.setReplay?.({name: a.name, text: t.text});
  scheduleReplay();
}
function stopReplay() {
  clearTimeout(replayTimer); replayIndex = -1;
  $('lab-replay-panel').hidden = true;
  $('lab-replay-stop').hidden = true;
  $('lab-replay').hidden = false;
  scene?.setMeeting('');
  scene?.setReplay?.(null);
  scene?.select(priorSelection);
}
$('lab-replay').addEventListener('click', () => { priorSelection = selected; replayAuto = !reduced.matches; $('lab-replay-pause').textContent = replayAuto ? '자동 넘김 정지' : '자동 넘김 재생'; $('lab-replay-pause').setAttribute('aria-pressed', String(!replayAuto)); showTurn(0); });
$('lab-replay-stop').addEventListener('click', stopReplay);
$('lab-replay-prev').addEventListener('click', () => showTurn(replayIndex - 1));
$('lab-replay-next').addEventListener('click', () => showTurn(replayIndex + 1));
$('lab-replay-pause').addEventListener('click', () => { replayAuto = !replayAuto; $('lab-replay-pause').textContent = replayAuto ? '자동 넘김 정지' : '자동 넘김 재생'; $('lab-replay-pause').setAttribute('aria-pressed', String(!replayAuto)); scheduleReplay(); });

// 화면 밖에서는 GPU·상태 조회·회의 재생 타이머를 멈춰요.
const observer = new IntersectionObserver(entries => {
  visible = entries[0].isIntersecting;
  scene?.setVisible(visible && !document.hidden);
  if (visible) { startPolling(); scheduleReplay(); } else { stopPolling(); clearTimeout(replayTimer); }
}, {rootMargin: '100px'});
observer.observe(root);
document.addEventListener('visibilitychange', () => {
  scene?.setVisible(visible && !document.hidden);
  if (document.hidden) { stopPolling(); clearTimeout(replayTimer); } else { startPolling(); scheduleReplay(); }
});
window.addEventListener('pagehide', e => { stopPolling(); clearTimeout(replayTimer); scene?.setVisible(false); if (!e.persisted) { scene?.dispose(); observer.disconnect(); } });
window.addEventListener('pageshow', e => { if (e.persisted) { scene?.setVisible(visible); startPolling(); scheduleReplay(); } });
// 모바일·동작 줄이기·데이터 절약은 사용자가 선택했을 때만 GPU 모듈을 내려받아요.
if (root.dataset.engine === 'plate') {
  start3D();
} else {
  $('lab-start').hidden = false;
  if (matchMedia('(min-width: 960px)').matches && !reduced.matches && !navigator.connection?.saveData) {
    const idle = window.requestIdleCallback || (fn => setTimeout(fn, 100));
    idle(() => start3D(), {timeout: 2000});
  }
}
renderMotion();
