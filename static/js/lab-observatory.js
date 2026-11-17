(() => {
  'use strict';
  const app = document.querySelector('.lo');
  if (!app) return;
  const jobs = app.querySelector('[data-jobs]'), tree = app.querySelector('[data-tree]');
  const panel = app.querySelector('[data-detail]'), connection = app.querySelector('[data-connection]');
  const pause = app.querySelector('[data-pause]');
  const labels = {running:'실행 중',started:'실행 중',done:'완료',completed:'실행 종료',pending:'대기',
    failed:'실패',unknown:'종료 확인 필요',quarantined:'종료 확인 필요',cancelled:'취소',interrupted:'중단',skipped:'건너뜀'};
  let data, selectedWork, selectedItem, paused = false, timer, controller, failures = 0;
  let signature = '', detailKey = '', detailVersion = 0;
  const el = (tag, text, cls) => {
    const n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  };
  const badge = (state) => { const n = el('span', labels[state] || state, 'lo-state'); n.dataset.state = state; return n; };
  const time = value => value ? new Date(value).toLocaleTimeString('ko-KR', {hour:'2-digit',minute:'2-digit',second:'2-digit'}) : '';
  const current = () => data?.works.find(w => w.id === selectedWork);
  const showSummary = work => {
    ++detailVersion; detailKey = '';
    panel.replaceChildren(el('h3', work.title), badge(work.state));
    if (work.draft_status) panel.append(el('p', `원고: ${work.draft_status}${work.score != null ? ` / ${work.score}점` : ''}`));
    if (work.run_after && work.state === 'pending') panel.append(el('p', `실행 예정 ${new Date(work.run_after).toLocaleString('ko-KR')}`));
    if (work.note) panel.append(el('h3', '요청 내용'), el('p', work.note));
    const budget = work.budget;
    if (budget) panel.append(el('p', `호출 ${budget.calls}/${budget.max_calls}회 · 남은 시간 ${Math.ceil(budget.remaining_seconds / 60)}분`, 'lo-meta'));
    const r = work.revision;
    if (r) {
      panel.append(el('h3', r.status === 'adopted' ? '수정본 반영 확인' : '기존 원고 유지'));
      if (r.previous_score != null) panel.append(el('p', `기존 ${r.previous_score}점 / 후보 ${r.candidate_score ?? '심사 전'}${r.candidate_score != null ? '점' : ''}`));
      for (const reason of r.reasons || []) panel.append(el('p', reason));
      for (const item of r.items || []) {
        const row = el('div', null, 'lo-requirement');
        row.append(el('p', `${item.id} · ${item.request}`), el('p', item.status_label || (item.met ? '반영 확인' : '확인 필요'), 'lo-meta'));
        if (item.evidence) row.append(el('p', item.evidence));
        panel.append(row);
      }
    }
    if (work.audit_url) { const a = el('a', '원고 감사 기록 보기'); a.href = work.audit_url; panel.append(a); }
  };
  async function showItem(work, item) {
    const key = `${work.id}/${item.id}/${item.state}`;
    if (key === detailKey) return;
    detailKey = key;
    const version = ++detailVersion;
    const agent = data.agents[item.agent];
    panel.replaceChildren(el('h3', item.label), badge(item.state),
      el('p', `${agent ? `${agent.name} · ${agent.title}` : item.agent} / ${time(item.at)}`, 'lo-meta'));
    if (item.model) panel.append(el('p', `요청 모델: ${item.model}`, 'lo-meta'));
    if (item.transfer) panel.append(el('p', `전달: ${item.transfer}`, 'lo-meta'));
    const body = el('pre', item.detail || '내용을 불러와요.'); panel.append(body);
    const url = new URL(app.dataset.detailUrl, location.origin);
    url.searchParams.set('run', work.id); url.searchParams.set('item', item.id);
    try {
      const res = await fetch(url, {cache:'no-store', headers:{Accept:'application/json'}, signal:AbortSignal.timeout(10000)});
      if (!res.ok || res.redirected || !res.headers.get('content-type')?.includes('application/json')) throw Error();
      const detail = await res.json();
      if (version === detailVersion) body.textContent = detail.text;
    } catch (_) {
      if (version === detailVersion) { body.textContent = '내용을 불러오지 못했어요. 다시 선택하거나 관리자 로그인을 확인해 주세요.'; detailKey = ''; }
    }
  }
  function draw() {
    const focus = document.activeElement;
    const focusKey = focus?.dataset.item || focus?.dataset.work;
    const focusType = focus?.dataset.item ? 'item' : 'work';
    jobs.replaceChildren();
    app.querySelector('[data-count]').textContent = data.works.length;
    for (const work of data.works) {
      const b = el('button', null, 'lo-job'); b.type = 'button'; b.dataset.work = work.id;
      b.setAttribute('aria-current', String(work.id === selectedWork));
      const n = work.calls.filter(c => c.state === 'running').length;
      b.append(badge(work.state), el('strong', work.title), el('small', n ? `${n}개 호출 실행 중` : work.draft_status || '작업 상세 보기'));
      jobs.append(b);
    }
    const work = current();
    tree.replaceChildren();
    if (!work) {
      jobs.append(el('p', '아직 기록된 작업이 없어요. 연구실 관리에서 작업을 시작해 주세요.', 'lo-empty'));
      tree.append(el('p', '작업이 시작되면 담당 에이전트와 진행 내용을 표시해요.', 'lo-empty'));
      panel.replaceChildren(el('p', '선택한 작업이 없어요.', 'lo-empty')); return;
    }
    const root = el('div', null, 'lo-root');
    root.append(el('strong', work.title), el('p', `${work.state_label || labels[work.state]}${work.draft_status ? ` / 원고 ${work.draft_status}` : ''}`));
    tree.append(root);
    const branches = el('div', null, 'lo-branches');
    const assigned = new Set(work.calls.map(c => c.agent));
    for (const group of data.groups) {
      const section = el('section', null, 'lo-group'); section.append(el('h3', group.label));
      const agents = el('div', null, 'lo-agents');
      for (const key of group.agents.filter(k => assigned.has(k))) {
        const agent = data.agents[key]; if (!agent) continue;
        const calls = work.calls.filter(c => c.agent === key).reverse();
        const running = calls.some(c => c.state === 'running');
        const state = running ? 'running' : calls.some(c => c.state === 'unknown') ? 'unknown' : calls.length ? 'done' : 'pending';
        const node = el('article', null, `lo-agent${running ? ' is-running' : ''}`);
        const head = el('div', null, 'lo-agent-head'), who = el('div');
        who.append(el('h4', agent.name), el('small', agent.title)); head.append(who, badge(state)); node.append(head);
        const list = el('div', null, 'lo-task-list');
        const ordered = [...calls.filter(c => c.state === 'running'), ...calls.filter(c => c.state !== 'running')];
        const history = el('details', null, 'lo-history');
        if (ordered.length > 1) history.append(el('summary', `이전 기록 ${ordered.length - 1}건`));
        for (const [index, c] of ordered.entries()) {
          const b = el('button', c.label, 'lo-task'); b.type = 'button'; b.dataset.item = c.id;
          b.setAttribute('aria-pressed', String(c.id === selectedItem));
          b.append(el('small', `${labels[c.state] || c.state} · ${time(c.at)}`));
          if (index === 0) list.append(b); else history.append(b);
        }
        if (ordered.length > 1) list.append(history);
        node.append(list);
        if (!calls.length) node.append(el('p', '기록된 호출이 없어요.', 'lo-agent-empty'));
        agents.append(node);
      }
      if (agents.childElementCount) { section.append(agents); branches.append(section); }
    }
    tree.append(branches);
    if (!work.calls.length) tree.append(el('p', work.state === 'pending' ? '실행을 기다려요. 시작되면 실제 호출이 여기에 표시돼요.' : '호출 관측 기록이 없어요. 기존 작업은 저장된 산출물만 표시할 수 있어요.', 'lo-empty'));
    const item = work.calls.find(c => c.id === selectedItem);
    if (item) showItem(work, item); else { selectedItem = null; showSummary(work); }
    if (focusKey) app.querySelector(`[data-${focusType}="${CSS.escape(focusKey)}"]`)?.focus({preventScroll:true});
  }
  jobs.addEventListener('click', e => {
    const b = e.target.closest('[data-work]'); if (!b) return;
    selectedWork = b.dataset.work; selectedItem = null; detailKey = ''; draw();
  });
  tree.addEventListener('click', e => {
    const b = e.target.closest('[data-item]'); if (!b) return;
    selectedItem = b.dataset.item; detailKey = ''; draw();
  });
  function schedule() {
    clearTimeout(timer);
    if (!paused && !document.hidden) timer = setTimeout(refresh, Math.min(30000, 3000 * 2 ** failures));
  }
  async function refresh() {
    clearTimeout(timer);
    if (controller) return;
    controller = new AbortController();
    const timeout = setTimeout(() => controller?.abort(), 10000);
    try {
      const res = await fetch(app.dataset.stateUrl, {cache:'no-store', headers:{Accept:'application/json'}, signal:controller.signal});
      if (res.redirected || res.status === 401 || res.status === 403 || !res.headers.get('content-type')?.includes('application/json')) {
        paused = true; pause.textContent = '자동 갱신 다시 시작';
        throw Error('관리자 인증이 필요해요. 연구실 관리에서 다시 인증해 주세요.');
      }
      if (!res.ok) throw Error('현황을 가져오지 못했어요. 잠시 후 다시 확인해요.');
      data = await res.json(); failures = 0;
      if (!data.works.some(w => w.id === selectedWork)) { selectedWork = data.works[0]?.id; selectedItem = null; }
      const next = JSON.stringify(data.works);
      if (signature !== next) { signature = next; draw(); }
      connection.textContent = paused ? '자동 갱신을 멈췄어요.' : '실시간 연결 중 · 3초마다 확인해요.';
      app.querySelector('[data-updated]').textContent = `마지막 확인 ${time(data.now)}`;
    } catch (e) {
      failures = Math.min(failures + 1, 4);
      connection.textContent = e.message?.includes('인증') ? e.message : '연결이 끊겼어요. 마지막 확인 내용을 유지하고 다시 시도해요.';
    } finally { clearTimeout(timeout); controller = null; schedule(); }
  }
  pause.addEventListener('click', () => {
    paused = !paused; pause.textContent = paused ? '자동 갱신 다시 시작' : '자동 갱신 멈추기';
    connection.textContent = paused ? '자동 갱신을 멈췄어요.' : '다시 연결해요.';
    if (paused) clearTimeout(timer); else refresh();
  });
  app.querySelector('[data-refresh]').addEventListener('click', refresh);
  document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(timer); else if (!paused) refresh(); });
  window.addEventListener('pagehide', () => { paused = true; clearTimeout(timer); controller?.abort(); });
  refresh();
})();
