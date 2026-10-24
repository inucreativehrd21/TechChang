(function () {
    'use strict';
    var root = document.querySelector('.ad-console');
    if (!root) return;
    var token = (root.querySelector('[name=csrfmiddlewaretoken]') || {}).value;
    var feedback = root.querySelector('[data-ad-feedback]');
    function tell(message, bad) {
        if (!feedback) return;
        feedback.hidden = false; feedback.textContent = message;
        feedback.classList.toggle('ad-danger', !!bad);
    }
    root.querySelectorAll('[data-confirm]').forEach(function (el) {
        if (el.closest('.oa')) return;
        el.addEventListener(el.tagName === 'FORM' ? 'submit' : 'click', function (e) {
            if (!window.confirm(el.dataset.confirm)) e.preventDefault();
        });
    });
    async function post(url, body) {
        var response = await fetch(url, {method: 'POST', headers: {'X-CSRFToken': token, 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded'}, body: body || ''});
        if (!response.ok || response.redirected) throw new Error('로그인과 인증 상태를 확인하고 다시 시도해 주세요.');
        var data = await response.json();
        if (!data.success) throw new Error(data.message || '처리하지 못했어요. 다시 시도해 주세요.');
        return data;
    }
    root.querySelectorAll('.rank-selector').forEach(function (select) {
        var saved = select.value;
        select.addEventListener('change', async function () {
            if (!window.confirm('회원 등급을 변경할까요?')) { select.value = saved; return; }
            select.disabled = true;
            try { var data = await post(select.dataset.url, new URLSearchParams({rank: select.value}).toString()); saved = select.value; tell(data.message); }
            catch (e) { select.value = saved; tell(e.message, true); }
            finally { select.disabled = false; }
        });
    });
    root.querySelectorAll('[data-ad-toggle-user]').forEach(function (button) {
        button.addEventListener('click', async function (e) {
            if (e.defaultPrevented) return;
            button.disabled = true;
            try { await post(button.dataset.url); location.reload(); }
            catch (error) { tell(error.message, true); button.disabled = false; }
        });
    });
    var featureForm = root.querySelector('[data-ad-feature-form]');
    if (featureForm) {
        var initial = new URLSearchParams(new FormData(featureForm)).toString();
        featureForm.addEventListener('change', function () {
            var changed = new URLSearchParams(new FormData(featureForm)).toString() !== initial;
            root.querySelector('[data-ad-dirty]').textContent = changed ? '아직 저장하지 않은 변경 사항이 있어요.' : '현재 설정을 확인하고 저장해 주세요.';
        });
        featureForm.addEventListener('submit', function () {
            var button = featureForm.querySelector('button[type=submit]');
            button.disabled = true; button.textContent = '저장 중…';
        });
    }
    var current = root.querySelector('.ad-nav a[aria-current]');
    if (current && current.parentElement.scrollWidth > current.parentElement.clientWidth) {
        current.parentElement.scrollLeft = Math.max(0, current.offsetLeft - 30);
    }
})();
