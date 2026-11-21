/* 기존 POST 계약을 사용하는 연속 플레이. 판정과 새 seq는 서버 응답만 사용해요. */
(() => {
  'use strict';
  const shell = document.querySelector('.sg-shell');
  if (!shell) return;
  const content = document.createElement('div');
  content.className = 'sg-content';
  content.append(...shell.childNodes);
  shell.append(content);
  const feedback = document.createElement('section');
  feedback.className = 'sg-feedback';
  feedback.hidden = true;
  feedback.setAttribute('aria-label', '행동 결과');
  shell.append(feedback);
  const announcer = document.createElement('div');
  announcer.className = 'visually-hidden';
  announcer.setAttribute('role', 'status');
  announcer.setAttribute('aria-live', 'polite');
  announcer.setAttribute('aria-atomic', 'true');
  shell.append(announcer);
  const busy = document.createElement('div');
  busy.className = 'sg-saving';
  busy.hidden = true;
  busy.setAttribute('role', 'status');
  busy.textContent = '진행 중…';
  shell.append(busy);
  let boardState = {}, pending = false, needsSync = false, disabledButtons = [];
  let currentUrl = location.pathname + location.search, noticeTimer, recoveryLogin = null;
  const screens = new Set(['home', 'tutorial', 'ranking', 'replay', 'manor', 'codex', 'inn', 'pc_only']);
  const gameKey = (root, fallback) => root.querySelector('[data-sg-key]')?.dataset.sgKey || fallback;
  const postButtons = () => [...content.querySelectorAll('form button:not([type]), form button[type=submit], form input[type=submit], [data-sg-autosubmit]')];
  const formKey = form => JSON.stringify([new URL(form.action, location.href).pathname,
    [...form.querySelectorAll('input[type=hidden]')].filter(e => !['seq', 'csrfmiddlewaretoken'].includes(e.name)).map(e => [e.name, e.value]).sort()]);
  const detailKey = (el, i) => el.dataset.sgDetail || el.id || el.className + ':' + i;
  const editable = form => [...form.elements].filter(e => e.name && ['INPUT', 'SELECT', 'TEXTAREA'].includes(e.tagName) && !e.matches('[data-sg-autosubmit]') && !['hidden', 'submit', 'button', 'file'].includes(e.type));

  function notify(items, recovery = false, loginUrl = null) {
    clearTimeout(noticeTimer);
    feedback.replaceChildren();
    feedback.classList.toggle('is-error', recovery || items.some(m => m.level?.includes('error')));
    const list = document.createElement('div');
    list.className = 'sg-feedback-lines';
    items.forEach(item => { const p = document.createElement('p'); p.textContent = item.text; list.append(p); });
    feedback.append(list);
    if (recovery) {
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'sg-button'; button.dataset.sgSync = '';
      button.textContent = '최신 상태 확인'; feedback.append(button);
    }
    if (loginUrl) {
      const link = document.createElement('a');
      link.href = loginUrl; link.textContent = '다시 로그인'; feedback.append(link);
    }
    const close = document.createElement('button');
    close.type = 'button'; close.className = 'sg-feedback-close'; close.dataset.sgDismiss = '';
    close.setAttribute('aria-label', '알림 닫기'); close.textContent = '×'; if (!recovery) feedback.append(close);
    const report = content.querySelector('[data-sg-board] .sg-report');
    const inBoard = report?.getClientRects().length && !recovery && !feedback.classList.contains('is-error');
    feedback.hidden = !items.length || !!inBoard;
    announcer.textContent = items.map(m => m.text).join(' ');
    if (!recovery && !feedback.classList.contains('is-error')) noticeTimer = setTimeout(() => {
      if (!feedback.contains(document.activeElement)) feedback.hidden = true;
    }, 6500);
    feedback.classList.toggle('sg-registration', items.some(m => m.text.includes('도감에 올랐어요')));
  }

  function setBusy(value) {
    pending = value; busy.hidden = !value;
    shell.setAttribute('aria-busy', String(value));
    if (value) {
      disabledButtons = postButtons().filter(b => !b.disabled);
      disabledButtons.forEach(b => b.disabled = true);
    } else if (!needsSync) {
      disabledButtons.forEach(b => { if (b.isConnected) b.disabled = false; });
      disabledButtons = [];
    }
  }

  function renderBoard() {
    const board = content.querySelector('[data-sg-board]');
    if (!board) return;
    const cards = [...board.querySelectorAll('.sg-city')];
    if (!cards.some(c => c.dataset.city === boardState.city)) boardState.city = (cards.find(c => c.classList.contains('is-mine')) || cards[0])?.dataset.city;
    board.classList.add('sg-board-interactive');
    board.dataset.enhanced = 'true';
    board.classList.toggle('sg-map-collapsed', !!boardState.mapCollapsed);
    cards.forEach(c => c.hidden = c.dataset.city !== boardState.city);
    board.querySelectorAll('[data-select-city]').forEach(marker => {
      const active = marker.dataset.selectCity === boardState.city;
      marker.classList.toggle('is-selected', active);
      if (active) marker.setAttribute('aria-current', 'location'); else marker.removeAttribute('aria-current');
    });
    const picker = board.querySelector('[data-sg-city-picker]');
    if (picker) picker.value = boardState.city;
    const tablist = board.querySelector('.sg-tabs');
    tablist?.setAttribute('role', 'tablist');
    const tabs = [...board.querySelectorAll('.sg-tabs [data-sg-tab]')];
    if (!tabs.some(t => t.dataset.sgTab === boardState.tab)) boardState.tab = 'cities';
    tabs.forEach(tab => {
      const active = tab.dataset.sgTab === boardState.tab;
      tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
    });
    board.querySelectorAll('[data-sg-panel]').forEach(panel => {
      panel.hidden = panel.dataset.sgPanel !== boardState.tab;
      panel.setAttribute('role', 'tabpanel');
    });
    const toggle = board.querySelector('.sg-map-toggle');
    toggle?.setAttribute('aria-expanded', String(!boardState.mapCollapsed));
    if (toggle) toggle.textContent = boardState.mapCollapsed ? '지도 펼치기' : '지도 접기';
  }

  function filterCodex() {
    const codex = content.querySelector('.sg-codex');
    if (!codex) return;
    const term = codex.querySelector('[data-codex-search]').value.trim().toLocaleLowerCase();
    const state = codex.dataset.filter || 'all';
    let visible = 0;
    codex.querySelectorAll('.sg-codex-card').forEach(card => {
      card.hidden = !(state === 'all' || card.classList.contains('is-' + state)) || !card.dataset.name.toLocaleLowerCase().includes(term);
      if (!card.hidden) visible++;
    });
    codex.querySelectorAll('.sg-codex-group').forEach(group => {
      group.hidden = !group.querySelector('.sg-codex-card:not([hidden])') && (state !== 'all' || !!term);
    });
    codex.querySelector('[data-codex-empty]').hidden = visible > 0;
    codex.querySelectorAll('[data-codex-filter]').forEach(button => {
      const active = button.dataset.codexFilter === state;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('btn-primary', active); button.classList.toggle('btn-outline-secondary', !active);
    });
  }

  function capture() {
    const forms = new Map();
    content.querySelectorAll('form[method=post]').forEach(form => forms.set(formKey(form), editable(form).map(e => ({
      name: e.name, type: e.type, value: e.value, checked: e.checked,
      selected: e.multiple ? [...e.selectedOptions].map(o => o.value) : null
    }))));
    const active = document.activeElement, focusForm = active?.closest('form');
    return {
      key: gameKey(content, currentUrl), board: {...boardState}, forms,
      details: new Map([...content.querySelectorAll('details')].map((el, i) => [detailKey(el, i), el.open])),
      scroll: new Map([...content.querySelectorAll('[data-sg-scroll]')].map(el => [el.dataset.sgScroll, el.scrollTop])),
      x: scrollX, y: scrollY,
      focus: focusForm && content.contains(focusForm) ? {form: formKey(focusForm), index: [...focusForm.elements].indexOf(active), name: active.name, type: active.type, value: active.value} : null,
      search: content.querySelector('[data-codex-search]')?.value || '',
      filter: content.querySelector('.sg-codex')?.dataset.filter || 'all',
      motionPaused: content.querySelector('.sg-estate')?.classList.contains('sg-motion-paused')
    };
  }

  function setup(snapshot) {
    boardState = snapshot?.board || {city: location.hash.startsWith('#sg-city-') ? location.hash.slice(9) : null, tab: 'cities', mapCollapsed: false};
    if (snapshot) {
      content.querySelectorAll('form[method=post]').forEach(form => {
        const saved = snapshot.forms.get(formKey(form));
        if (!saved) return;
        editable(form).forEach(el => {
          const old = saved.find(s => s.name === el.name && s.type === el.type && (!['checkbox', 'radio'].includes(el.type) || s.value === el.value));
          if (!old) return;
          if (['checkbox', 'radio'].includes(el.type)) el.checked = old.checked;
          else if (el.tagName === 'SELECT') {
            if (el.multiple) [...el.options].forEach(o => o.selected = old.selected.includes(o.value));
            else if ([...el.options].some(o => o.value === old.value)) el.value = old.value;
          } else {
            el.value = old.value;
            if (el.type === 'number' && el.value !== '') {
              let n = Number(el.value);
              if (el.max !== '') n = Math.min(n, Number(el.max));
              if (el.min !== '') n = Math.max(n, Number(el.min));
              el.value = String(n);
            }
          }
        });
      });
      [...content.querySelectorAll('details')].forEach((el, i) => { if (snapshot.details.has(detailKey(el, i))) el.open = snapshot.details.get(detailKey(el, i)); });
      const search = content.querySelector('[data-codex-search]');
      if (search) search.value = snapshot.search;
      const codex = content.querySelector('.sg-codex');
      if (codex) codex.dataset.filter = snapshot.filter;
      const estate = content.querySelector('.sg-estate');
      if (estate && snapshot.motionPaused) estate.classList.add('sg-motion-paused');
    }
    renderBoard(); filterCodex();
    content.querySelectorAll('[data-sg-attack-target]').forEach(select => updateCost(select));
    content.querySelectorAll('.sg-motion-toggle').forEach(button => {
      const paused = button.closest('.sg-estate').classList.contains('sg-motion-paused');
      button.setAttribute('aria-pressed', String(paused)); button.textContent = paused ? '움직임 이어가기' : '움직임 멈추기';
    });
  }

  function updateCost(select) {
    const cost = select.selectedOptions[0]?.dataset.cost;
    const text = select.form.querySelector('[data-sg-attack-cost]');
    if (text && cost) text.textContent = '군령 ' + cost;
  }

  function commit(payload) {
    const url = new URL(payload.url, location.origin);
    if (payload.version !== 1 || !screens.has(payload.screen) || typeof payload.html !== 'string' || url.origin !== location.origin || !url.pathname.startsWith('/samguk/')) throw new Error('invalid-fragment');
    const template = document.createElement('template');
    template.innerHTML = payload.html;
    if (!template.content.firstElementChild || template.content.querySelector('script')) throw new Error('invalid-fragment');
    const snapshot = capture();
    const same = snapshot.key === gameKey(template.content, url.pathname + url.search);
    if (same) {
      const oldPicture = content.querySelector('.sg-map-art > picture'), newPicture = template.content.querySelector('.sg-map-art > picture');
      if (oldPicture && newPicture && oldPicture.querySelector('img').getAttribute('src') === newPicture.querySelector('img').getAttribute('src')) newPicture.replaceWith(oldPicture);
      for (const selector of ['.sg-estate-world', '.sg-estate-wanderer']) {
        const old = content.querySelector(selector), next = template.content.querySelector(selector);
        if (old && next) next.replaceWith(old);
      }
    }
    content.replaceChildren(template.content);
    currentUrl = url.pathname + url.search;
    setup(same ? snapshot : null);
    document.title = payload.title;
    history.replaceState(history.state, '', currentUrl + (same ? location.hash : ''));
    if (same) {
      content.querySelectorAll('[data-sg-scroll]').forEach(el => el.scrollTop = snapshot.scroll.get(el.dataset.sgScroll) || 0);
      if (snapshot.focus) {
        const form = [...content.querySelectorAll('form[method=post]')].find(f => formKey(f) === snapshot.focus.form);
        const element = form?.elements[snapshot.focus.index];
        if (element && element.name === snapshot.focus.name && !element.disabled && !element.closest('[hidden]')) element.focus({preventScroll: true});
      }
      window.scrollTo({left: snapshot.x, top: snapshot.y, behavior: 'instant'});
    }
    needsSync = false;
    recoveryLogin = null;
    shell.removeAttribute('data-sg-uncertain');
    notify(Array.isArray(payload.messages) ? payload.messages : []);
    shell.dispatchEvent(new CustomEvent('samguk:updated', {detail: {screen: payload.screen}}));
  }

  async function request(url, options) {
    if (pending) return;
    setBusy(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(url, {...options, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
        headers: {'X-Samguk-Partial': '1', 'Accept': 'application/json'}});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
        const destination = new URL(response.url || url, location.href);
        const error = new Error('unexpected-response');
        if (destination.origin === location.origin && destination.pathname.includes('login')) {
          destination.searchParams.set('next', currentUrl);
          error.login = destination.href;
        }
        throw error;
      }
      commit(await response.json());
    } catch (error) {
      needsSync = true; shell.dataset.sgUncertain = 'true';
      recoveryLogin = error.login || recoveryLogin;
      notify([{level: 'error', text: recoveryLogin ? '로그인이 만료됐어요. 다시 로그인한 뒤 이어서 진행해 주세요.' : '결과를 확인하지 못했어요. 최신 상태를 확인한 뒤 계속해 주세요. 행동은 다시 보내지 않았어요.'}], true, recoveryLogin);
    } finally {
      clearTimeout(timeout); setBusy(false);
    }
  }

  function submit(form, submitter) {
    if (pending || needsSync || !form.isConnected) {
      if (needsSync) notify([{level: 'error', text: '최신 상태를 먼저 확인해 주세요. 같은 행동은 다시 보내지 않아요.'}], true, recoveryLogin);
      return;
    }
    const body = new FormData(form);
    if (submitter?.name) body.append(submitter.name, submitter.value);
    request(form.action, {method: 'POST', body});
  }

  let confirmTarget = null;
  const dialog = document.createElement('dialog');
  dialog.className = 'sg-confirm';
  dialog.setAttribute('aria-labelledby', 'sg-confirm-title');
  dialog.innerHTML = '<h2 id="sg-confirm-title">오늘 판을 마칠까요?</h2><p>남은 군령은 사용할 수 없어요. 지금까지 얻은 점수와 도감 기록은 유지돼요.</p><div><button type="button" class="sg-button" data-sg-cancel>계속 플레이</button><button type="button" class="sg-button sg-button-primary" data-sg-confirm-end>오늘 판 마치기</button></div>';
  shell.append(dialog);
  dialog.addEventListener('close', () => { confirmTarget = null; });

  shell.addEventListener('submit', event => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== 'post' || !window.fetch) return;
    const url = new URL(form.action, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith('/samguk/')) return;
    event.preventDefault();
    if (pending || needsSync) { submit(form, event.submitter); return; }
    if (form.dataset.sgConfirm === 'end') {
      confirmTarget = {form, button: event.submitter};
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else if (window.confirm('오늘 판을 마칠까요? 남은 군령은 사용할 수 없어요.')) submit(form, event.submitter);
      return;
    }
    submit(form, event.submitter);
  });

  shell.addEventListener('click', event => {
    const marker = event.target.closest('[data-select-city]');
    if (marker) {
      event.preventDefault(); boardState.city = marker.dataset.selectCity; boardState.tab = 'cities'; renderBoard();
      history.replaceState(history.state, '', currentUrl + '#sg-city-' + boardState.city);
      return;
    }
    const tab = event.target.closest('[data-sg-tab]');
    if (tab) { boardState.tab = tab.dataset.sgTab; renderBoard(); return; }
    if (event.target.closest('.sg-map-toggle')) { boardState.mapCollapsed = !boardState.mapCollapsed; renderBoard(); return; }
    if (event.target.closest('[data-sg-dismiss]')) { feedback.hidden = true; return; }
    if (event.target.closest('[data-sg-sync]')) { request(currentUrl, {method: 'GET'}); return; }
    if (event.target.closest('[data-sg-cancel]')) { dialog.close(); return; }
    if (event.target.closest('[data-sg-confirm-end]')) {
      const target = confirmTarget; dialog.close(); if (target) submit(target.form, target.button); return;
    }
    const motion = event.target.closest('.sg-motion-toggle');
    if (motion) {
      const paused = motion.closest('.sg-estate').classList.toggle('sg-motion-paused');
      motion.setAttribute('aria-pressed', String(paused)); motion.textContent = paused ? '움직임 이어가기' : '움직임 멈추기';
    }
    const filter = event.target.closest('[data-codex-filter]');
    if (filter) { filter.closest('.sg-codex').dataset.filter = filter.dataset.codexFilter; filterCodex(); }
  });
  shell.addEventListener('change', event => {
    const el = event.target;
    if (el.matches('[data-sg-city-picker]')) { boardState.city = el.value; boardState.tab = 'cities'; renderBoard(); }
    if (el.matches('[data-sg-attack-target]')) updateCost(el);
    if (el.matches('[data-sg-autosubmit]')) el.form.requestSubmit();
    if (el.matches('input[name=officers]') && el.form.querySelectorAll('input[name=officers]:checked').length > 3) {
      el.checked = false; notify([{level: 'info', text: '출정 장수는 세 명까지 고를 수 있어요.'}]);
    }
  });
  shell.addEventListener('input', event => { if (event.target.matches('[data-codex-search]')) filterCodex(); });
  shell.addEventListener('toggle', event => {
    const detail = event.target;
    if (detail.matches('.sg-operation') && detail.open) detail.closest('.sg-city').querySelectorAll('.sg-operation').forEach(other => { if (other !== detail) other.open = false; });
  }, true);
  shell.addEventListener('keydown', event => {
    const tab = event.target.closest('.sg-tabs [data-sg-tab]');
    if (!tab || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...tab.parentElement.querySelectorAll('[data-sg-tab]')], i = tabs.indexOf(tab);
    const next = tabs[event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (i + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    boardState.tab = next.dataset.sgTab; renderBoard(); next.focus({preventScroll: true});
  });
  window.addEventListener('pageshow', event => { if (event.persisted) request(currentUrl, {method: 'GET'}); });
  document.querySelectorAll('.alert').forEach(message => {
    if (message.textContent.includes('도감에 올랐어요')) message.classList.add('sg-registration');
  });
  setup(null);
})();
