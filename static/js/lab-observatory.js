(() => {
  'use strict';
  const app = document.querySelector('.lo');
  if (!app) return;
  const jobs = app.querySelector('[data-jobs]'), tree = app.querySelector('[data-tree]');
  const panel = app.querySelector('[data-detail]'), connection = app.querySelector('[data-connection]');
  const pause = app.querySelector('[data-pause]');
  const motion = app.querySelector('[data-motion]'), flowLayer = app.querySelector('[data-flows]');
  const nodes = [...app.querySelectorAll('[data-agent]')];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const positions = {lead:[400,70],hrd:[160,215],data:[400,215],coding:[640,215],
    checker:[160,385],critic:[400,385],charter:[640,385],editor:[400,530],research:[672,62]};
  const labels = {running:'실행 중',started:'실행 중',done:'완료',completed:'실행 종료',pending:'대기',
    failed:'실패',unknown:'종료 확인 필요',quarantined:'종료 확인 필요',cancelled:'취소',interrupted:'중단',skipped:'건너뜀'};
  let data = {works:[], agents:Object.fromEntries(nodes.map(n => [n.dataset.agent, {
    name:n.querySelector('strong').textContent, title:n.querySelector('.lo-agent-role').textContent,
  }]))}, selectedWork, selectedItem, selectedAgent, paused = false, timer, controller, failures = 0;
  let motionPaused = reduced.matches, connected = false, flowSignature = '';
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
  const resultBadge = result => {
    const n = el('span', result.label, 'lo-result-label'); n.dataset.outcome = result.state; return n;
  };
  function renderReport(target, detail) {
    target.replaceChildren();
    const report = detail.report;
    if (report) {
      const verdict = el('section', null, 'lo-verdict'); verdict.dataset.outcome = report.outcome.state;
      verdict.append(resultBadge(report.outcome), el('p', report.outcome.explanation)); target.append(verdict);
      if (report.metrics.length) {
        const metrics = el('dl', null, 'lo-report-metrics');
        for (const metric of report.metrics) { const row=el('div'); row.append(el('dt',metric.label),el('dd',metric.value));metrics.append(row); }
        target.append(metrics);
      }
      target.append(el('h4','다음 조치'),el('p',report.next_action,'lo-next-action'));
      for (const section of report.sections) {
        const group=el(section.collapsible ? 'details' : 'section',null,'lo-report-section');
        group.append(el(section.collapsible ? 'summary' : 'h4',section.title));
        for (const item of section.items) {
          const row=el('div',null,'lo-report-item');
          if (item.title) row.append(el('strong',item.title));
          if (item.body) row.append(el('p',item.body));
          if (item.fields.length) {
            const fields=el('dl');
            for (const field of item.fields) fields.append(el('dt',field.label),el('dd',field.text));
            row.append(fields);
          }
          group.append(row);
        }
        if (section.omitted) group.append(el('p', `나머지 ${section.omitted}건은 원 데이터에서 확인해요.`, 'lo-meta'));
        target.append(group);
      }
      if (report.limited) target.append(el('p','긴 보고는 일부 항목을 생략했어요. 원 데이터를 함께 확인해 주세요.','lo-meta'));
    } else target.append(el('p','이 기록의 관리자 보고가 없어요. 원 데이터를 확인해 주세요.'));
    const raw=el('details',null,'lo-raw');
    raw.append(el('summary','원 데이터 보기'),el('pre',detail.text || '저장된 원 데이터가 없어요.'));
    target.append(raw);
  }
  async function loadReport(work, item, target, version) {
    const url = new URL(app.dataset.detailUrl, location.origin);
    url.searchParams.set('run',work.id); url.searchParams.set('item',item.id);
    try {
      const res=await fetch(url,{cache:'no-store',headers:{Accept:'application/json'},signal:AbortSignal.timeout(10000)});
      if (!res.ok || res.redirected || !res.headers.get('content-type')?.includes('application/json')) throw Error();
      const detail=await res.json();
      if (version===detailVersion) renderReport(target,detail);
    } catch (_) {
      if (version===detailVersion) {
        target.replaceChildren(el('p','보고 내용을 불러오지 못했어요. 관리자 인증과 연결을 확인해 주세요.'));
        const retry=el('button','다시 불러오기','lo-detail-back');retry.type='button';retry.dataset.retryDetail='';target.append(retry);
        detailKey='';
      }
    }
  }
  const svg = (tag, attributes) => {
    const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attributes)) n.setAttribute(key, String(value));
    return n;
  };
  function syncMotion() {
    const stopped = motionPaused || reduced.matches || document.hidden || paused || !connected;
    app.classList.toggle('is-motion-paused', stopped);
    app.classList.toggle('is-suspended', !connected);
    motion.textContent = motionPaused || reduced.matches ? '모션 켜기' : '모션 멈추기';
    motion.setAttribute('aria-pressed', String(motionPaused || reduced.matches));
    motion.disabled = reduced.matches;
    motion.title = reduced.matches ? '기기의 동작 줄이기 설정을 따르고 있어요.' : '';
    if (stopped) flowLayer.pauseAnimations(); else flowLayer.unpauseAnimations();
  }
  function route(from, to) {
    const [x1,y1] = positions[from], [x2,y2] = positions[to];
    if (y1 === 70 && y2 === 215) return `M${x1} ${y1} V145 H${x2} V${y2}`;
    if (y1 === 215 && y2 === 385) return `M${x1} ${y1} V300 H400 V330 H${x2} V${y2}`;
    if (y1 === 385 && y2 === 530) return `M${x1} ${y1} V470 H${x2} V${y2}`;
    if (y1 === y2) return `M${x1} ${y1} V${y1-55} H${x2} V${y2}`;
    if (y1 > y2) return `M${x1} ${y1} C780 ${y1},780 ${y2},${x2} ${y2}`;
    return `M${x1} ${y1} C${x1} ${(y1+y2)/2},${x2} ${(y1+y2)/2},${x2} ${y2}`;
  }
  function flowsFor(work) {
    if (!work) return [];
    const valid = (a,b) => Object.hasOwn(positions,a) && Object.hasOwn(positions,b) && a !== b;
    const records = work.calls.filter(c => valid(c.sender, c.recipient) && c.state === 'done').slice(-4).map(c => ({
      id:c.id, from:c.sender, to:c.recipient, label:c.label, kind:'record',
      animate:work.state === 'started' && (Date.now()-Date.parse(c.at) < 18000 ||
        work.calls.some(a => a.state === 'running' && a.agent === c.recipient &&
          Date.parse(a.at)-Date.parse(c.at) >= 0 && Date.parse(a.at)-Date.parse(c.at) < 60000)),
    }));
    const observed = work.calls.filter(c => c.id.startsWith('call-'));
    for (const active of observed.filter(c => c.state === 'running' && work.state === 'started')) {
      if (records.some(r => r.to === active.agent && r.animate)) continue;
      const previous = observed.filter(c => c.state === 'done' && c.ended_at &&
        Date.parse(c.ended_at) <= Date.parse(active.at) && valid(c.agent, active.agent))
        .sort((a,b) => Date.parse(b.ended_at)-Date.parse(a.ended_at))[0];
      if (previous) records.push({id:active.id, from:previous.agent, to:active.agent,
        label:active.label, kind:'sequence', animate:true});
    }
    return records.slice(-6);
  }
  function updateFlows(work) {
    const flows = flowsFor(work), key = JSON.stringify(flows);
    if (flowSignature !== key) {
      flowSignature = key;
      flowLayer.replaceChildren();
      for (const flow of flows) {
        const d = route(flow.from, flow.to);
        const group = svg('g', {'data-from':flow.from, 'data-to':flow.to, 'data-kind':flow.kind});
        const title = svg('title', {});
        title.textContent = `${flow.kind === 'record' ? '전달 기록' : '호출 순서'}: ${flow.from} → ${flow.to}`;
        group.append(title, svg('path', {d, class:`lo-flow-track${flow.kind === 'sequence' ? ' is-sequence' : ''}`}));
        if (flow.animate && !reduced.matches) {
          group.append(svg('path', {d, class:'lo-flow-caption-line'}));
          for (const [r,begin] of [[3,'0s'],[1.5,'-1.2s']]) {
            const packet = svg('circle', {r, class:'lo-flow-packet'});
            packet.append(svg('animateMotion', {path:d, dur:'2.8s', begin, repeatCount:'indefinite', calcMode:'paced'}));
            group.append(packet);
          }
        }
        flowLayer.append(group);
      }
    }
    const latest = [...flows].reverse().find(f => f.animate) || flows.at(-1);
    const who = key => data?.agents?.[key]?.name || key;
    app.querySelector('[data-flow-caption]').textContent = latest
      ? `${who(latest.from)} → ${who(latest.to)} · ${latest.label}${latest.kind === 'sequence' ? ' 시작 순서' : ' 전달 기록'}`
      : work?.state === 'started' ? '실행 중인 담당자가 빛나요. 에이전트를 눌러 내용을 확인해요.'
      : '에이전트를 누르면 작업 내용을 볼 수 있어요.';
    syncMotion();
  }
  function showAgent(work) {
    const agent = data.agents[selectedAgent];
    const calls = [...(work?.calls || [])].filter(c => c.agent === selectedAgent).reverse();
    const ordered = [...calls.filter(c => c.state === 'running'), ...calls.filter(c => c.state !== 'running')];
    const latest = ordered[0];
    const key=`agent/${work?.id}/${selectedAgent}/${latest?.id}/${latest?.state}`;
    if (detailKey===key) return;
    detailKey=key;const version=++detailVersion;
    panel.replaceChildren(el('h3', `${agent.name} · ${agent.title}`));
    if (!calls.length) { panel.append(el('p', '이 작업에 참여한 기록이 없어요. 팀 안에서 자리를 유지하며 대기해요.', 'lo-empty')); return; }
    panel.append(el('p',`${latest.label} · ${labels[latest.state] || latest.state} · ${time(latest.at)}`,'lo-meta'));
    const content=el('div','관리자 보고를 정리하고 있어요.','lo-report');panel.append(content);
    loadReport(work,latest,content,version);
    const history=el('details',null,'lo-history');history.append(el('summary',`작업 기록 ${calls.length}건`));
    for (const c of ordered.slice(0,24)) {
      const button = el('button', c.label, 'lo-agent-record');
      button.type = 'button'; button.dataset.item = c.id;
      button.append(el('small', `${c.outcome?.label || labels[c.state] || c.state} · ${time(c.at)}`));
      history.append(button);
    }
    panel.append(history);
    if (calls.length > 24) panel.append(el('p', '최근 기록 24건을 표시해요.', 'lo-meta'));
  }
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
    const back = el('button', '담당 에이전트 기록', 'lo-detail-back'); back.type = 'button'; back.dataset.backAgent = item.agent;
    panel.prepend(back);
    if (item.model) panel.append(el('p', `요청 모델: ${item.model}`, 'lo-meta'));
    if (item.transfer) panel.append(el('p', `전달: ${item.transfer}`, 'lo-meta'));
    const body = el('div', '관리자 보고를 불러와요.', 'lo-report'); panel.append(body);
    loadReport(work,item,body,version);
  }
  function draw() {
    const focus = document.activeElement;
    const focusKey = focus?.dataset.item || focus?.dataset.agent || focus?.dataset.work;
    const focusType = focus?.dataset.item ? 'item' : focus?.dataset.agent ? 'agent' : 'work';
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
    if (!work) {
      jobs.append(el('p', '아직 기록된 작업이 없어요. 연구실 관리에서 작업을 시작해 주세요.', 'lo-empty'));
    }
    app.querySelector('[data-map-caption]').textContent = work?.title || '작업을 기다리고 있어요.';
    for (const node of nodes) {
      const key = node.dataset.agent, agent = data.agents[key];
      const calls = [...(work?.calls || [])].filter(c => c.agent === key).reverse();
      if (key === 'research') node.hidden = !calls.length;
      const active = calls.find(c => c.state === 'running');
      const latest = active || calls[0];
      const state = active ? 'running' : latest?.state || 'idle';
      node.dataset.state = state;
      const decision=active ? {state:'running',label:'진행 중'} : latest?.outcome;
      const resultState=decision?.state || (state==='failed' ? 'blocked' : state==='unknown' ? 'unknown' : 'idle');
      node.dataset.outcome=resultState;
      node.setAttribute('aria-pressed', String(selectedAgent === key));
      const status = active ? `진행 중 · ${active.label}` : decision?.label || (state==='done' ? '응답 완료 · 판정 대기' : labels[state] || '대기');
      node.querySelector('[data-node-status]').textContent = status;
      node.setAttribute('aria-label', `${agent?.name || key} · ${agent?.title || ''} · ${status}`);
      node.title = latest ? `${status} · ${time(latest.at)}` : '이 작업에는 아직 참여 기록이 없어요.';
    }
    updateFlows(work);
    const item = work?.calls.find(c => c.id === selectedItem);
    if (item) showItem(work, item);
    else if (selectedAgent) { selectedItem = null; showAgent(work); }
    else if (work) { selectedItem = null; showSummary(work); }
    else panel.replaceChildren(el('p', '에이전트를 선택해 팀의 역할을 살펴봐요.', 'lo-empty'));
    if (focusKey) app.querySelector(`[data-${focusType}="${CSS.escape(focusKey)}"]`)?.focus({preventScroll:true});
  }
  jobs.addEventListener('click', e => {
    const b = e.target.closest('[data-work]'); if (!b) return;
    selectedWork = b.dataset.work; selectedItem = null; selectedAgent = null; detailKey = ''; draw();
  });
  tree.addEventListener('click', e => {
    const b = e.target.closest('[data-agent]'); if (!b) return;
    selectedAgent = b.dataset.agent; selectedItem = null; detailKey = ''; draw();
  });
  panel.addEventListener('click', e => {
    if (e.target.closest('[data-retry-detail]')) { detailKey='';draw();return; }
    const back = e.target.closest('[data-back-agent]');
    if (back) { selectedAgent = back.dataset.backAgent; selectedItem = null; detailKey = ''; draw(); return; }
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
      data = await res.json(); failures = 0; connected = true;
      if (!data.works.some(w => w.id === selectedWork)) { selectedWork = data.works[0]?.id; selectedItem = null; }
      const next = JSON.stringify(data.works);
      if (signature !== next) { signature = next; draw(); }
      else updateFlows(current());
      connection.textContent = paused ? '자동 갱신을 멈췄어요.' : '실시간 연결 중 · 3초마다 확인해요.';
      app.querySelector('[data-updated]').textContent = `마지막 확인 ${time(data.now)}`;
    } catch (e) {
      connected = false; syncMotion();
      failures = Math.min(failures + 1, 4);
      connection.textContent = e.message?.includes('인증') ? e.message : '연결이 끊겼어요. 마지막 확인 내용을 유지하고 다시 시도해요.';
    } finally { clearTimeout(timeout); controller = null; schedule(); }
  }
  pause.addEventListener('click', () => {
    paused = !paused; pause.textContent = paused ? '자동 갱신 다시 시작' : '자동 갱신 멈추기';
    connection.textContent = paused ? '자동 갱신을 멈췄어요.' : '다시 연결해요.';
    syncMotion();
    if (paused) clearTimeout(timer); else refresh();
  });
  app.querySelector('[data-refresh]').addEventListener('click', refresh);
  motion.addEventListener('click', () => { motionPaused = !motionPaused; syncMotion(); });
  reduced.addEventListener('change', () => { motionPaused = reduced.matches; flowSignature = ''; updateFlows(current()); });
  document.addEventListener('visibilitychange', () => { syncMotion(); if (document.hidden) clearTimeout(timer); else if (!paused) refresh(); });
  window.addEventListener('pagehide', () => { paused = true; clearTimeout(timer); controller?.abort(); syncMotion(); });
  syncMotion();
  refresh();
})();
