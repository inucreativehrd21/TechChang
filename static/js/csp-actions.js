/* 인라인 이벤트 속성(onclick= 등) 대신 쓰는 공용 동작 — CSP 차단 모드(script-src nonce, 'unsafe-inline' 없음)에서
 * onclick·onsubmit·onchange 속성과 javascript: 주소는 실행되지 않아요(2026-11-24 CSP enforce 전환).
 *
 *   data-confirm="문구"                 폼은 제출 전, 링크·버튼은 누를 때 확인 창. 취소하면 동작을 멈춰요.
 *   data-action="함수이름"               전역 함수를 불러요. data-args='["verify"]' (JSON 배열·값, "$event"·"$this" 치환)
 *   data-on="click|submit|change"        data-action 을 부를 이벤트(기본 click)
 *   data-remove="parent" | "<선택자>"      자기 부모 / 가장 가까운 조상을 지워요
 *   data-click="<선택자>"                 다른 요소를 대신 눌러요
 *   data-class-add / data-class-remove="<선택자> 클래스"
 *   data-back                            이전 화면이 있으면 뒤로, 없으면 링크 주소로 가요
 */
(function () {
  'use strict';

  function args(el, ev) {
    var raw = el.getAttribute('data-args');
    if (raw === null || raw === '') return [];
    var list;
    try { list = JSON.parse(raw); } catch (e) { list = raw; }
    if (!Array.isArray(list)) list = [list];
    return list.map(function (a) { return a === '$event' ? ev : (a === '$this' ? el : a); });
  }

  function toggleClass(spec, add) {
    if (!spec) return;
    var at = spec.lastIndexOf(' ');
    var target = document.querySelector(spec.slice(0, at));
    if (target) target.classList[add ? 'add' : 'remove'](spec.slice(at + 1));
  }

  function run(el, ev) {
    var remove = el.getAttribute('data-remove');
    if (remove) {
      var gone = remove === 'parent' ? el.parentElement : el.closest(remove);
      if (gone) gone.remove();
    }
    var click = el.getAttribute('data-click');
    if (click) {
      var other = document.querySelector(click);
      if (other) other.click();
    }
    toggleClass(el.getAttribute('data-class-add'), true);
    toggleClass(el.getAttribute('data-class-remove'), false);
    if (el.hasAttribute('data-back')) {
      var ref = document.referrer;
      if (el.getAttribute('data-back') === 'referrer') {
        // 이 사이트의 다른 화면에서 들어왔으면 그 화면으로(같은 글 안의 #장 기록은 건너뛰어요)
        if (ref && ref.indexOf(location.origin) === 0 && ref.indexOf(location.pathname) < 0) {
          ev.preventDefault();
          location.href = ref;
        }
      } else if (window.history.length > 1) {
        ev.preventDefault();
        window.history.back();
      }
    }
    var name = el.getAttribute('data-action');
    if (name) {
      var fn = window[name];
      if (typeof fn === 'function') return fn.apply(el, args(el, ev));
      if (window.console) console.warn('data-action 함수를 찾지 못했어요:', name);
    }
  }

  // 확인 창은 다른 처리보다 먼저(캡처 단계)
  document.addEventListener('click', function (ev) {
    var el = ev.target.closest && ev.target.closest('[data-confirm]');
    if (el && el.tagName !== 'FORM' && !window.confirm(el.getAttribute('data-confirm'))) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener('click', function (ev) {
    var el = ev.target.closest && ev.target.closest(
      '[data-action],[data-remove],[data-click],[data-class-add],[data-class-remove],[data-back]');
    if (!el || (el.getAttribute('data-on') || 'click') !== 'click') return;
    run(el, ev);
  });

  document.addEventListener('submit', function (ev) {
    var form = ev.target;
    if (form.hasAttribute('data-confirm') && !window.confirm(form.getAttribute('data-confirm'))) {
      ev.preventDefault();
      return;
    }
    if (form.getAttribute('data-on') === 'submit') run(form, ev);
  });

  document.addEventListener('change', function (ev) {
    var el = ev.target;
    if (el.getAttribute && el.getAttribute('data-on') === 'change') run(el, ev);
  });
})();
