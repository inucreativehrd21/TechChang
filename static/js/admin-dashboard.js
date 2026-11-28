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
    // ── OTP 인증 시간이 끝나면 열어 둔 화면도 재인증으로 보낸다. 서버가 남은 초(data-otp-left)를 준다 —
    //    브라우저 시계와 서버 시계가 달라도 '페이지를 받은 뒤 몇 초'로 계산한다. 작성 중인 글이 있으면
    //    이동하지 않고 안내만 띄운다(새로고침하면 글이 사라진다).
    function typing() {
        return Array.prototype.some.call(document.querySelectorAll('.ad-console textarea, .ad-console input[type=text], .ad-console input:not([type])'),
            function (el) { return el.value.trim() && el.value !== el.defaultValue; });
    }
    var otpBanner = null;
    function reauth() {
        if (!typing()) { location.replace(location.pathname + location.search); return; }
        if (otpBanner) return;
        otpBanner = document.createElement('div');
        otpBanner.className = 'ad-otp-expired'; otpBanner.setAttribute('role', 'alert');
        otpBanner.innerHTML = '<span>관리자 인증 시간이 끝났어요. 작성 중인 내용을 복사해 둔 뒤 다시 인증해 주세요.</span>';
        var again = document.createElement('a');
        again.href = location.pathname + location.search; again.textContent = '다시 인증';
        otpBanner.appendChild(again); document.body.appendChild(otpBanner);
    }
    window.tcAdminReauth = reauth;
    if (root.dataset.otpLeft) {
        var otpDeadline = Date.now() + Number(root.dataset.otpLeft) * 1000;
        var otpCheck = function () { if (Date.now() >= otpDeadline) { clearInterval(otpTimer); reauth(); } };
        var otpTimer = setInterval(otpCheck, 5000);
        document.addEventListener('visibilitychange', function () { if (!document.hidden) otpCheck(); });
        // 마지막 사용 후 30분 — 한 화면에서 입력·클릭·스크롤이 이어지면 몇 분마다 '사용 중' 신호를 보내 서버와
        // 이 화면의 마감을 함께 늦춘다(긴 글 직접 수정 중에 끊기지 않게). 손대지 않으면 신호도 없다.
        var active = false, lastPing = Date.now();
        ['keydown', 'input', 'pointerdown', 'wheel'].forEach(function (type) {
            document.addEventListener(type, function () { active = true; }, {passive: true, capture: true});
        });
        var csrf = token || (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || '';
        setInterval(async function () {
            if (!active || Date.now() - lastPing < 4 * 60 * 1000 || Date.now() >= otpDeadline) return;
            active = false; lastPing = Date.now();
            try {
                var res = await fetch(root.dataset.otpPing, {method: 'POST', credentials: 'same-origin',
                    headers: {'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'}});
                var data = await res.json().catch(function () { return {}; });
                if (res.ok && data.left) otpDeadline = Date.now() + data.left * 1000;
            } catch (e) { /* 연결이 끊기면 다음 사용 때 다시 시도 */ }
        }, 30 * 1000);
    }
    async function post(url, body) {
        var response = await fetch(url, {method: 'POST', headers: {'X-CSRFToken': token, 'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded'}, body: body || ''});
        if (response.status === 403) {
            var denied = await response.json().catch(function () { return {}; });
            if (denied.otp_required) { reauth(); throw new Error(denied.message); }
        }
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
