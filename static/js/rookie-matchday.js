/* 경기 계산 없이 표시·기록 재생·시각 경계만 관리해요. 훈련 후 교체된 칸도 초기화해요. */
(function () {
    'use strict';
    var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    var clockFormatter = new Intl.DateTimeFormat('ko-KR', {timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'});
    function parts(board) { return Array.from(board.querySelectorAll('.rl-month,.rl-final,[data-rk-inn]')); }
    function finish(board) { clearInterval(board._rkTimer); parts(board).forEach(function (el) { el.classList.remove('rl-wait'); }); board.classList.remove('is-playing'); var skip=board.querySelector('[data-rk-replay-skip]'); if(skip)skip.hidden=true; }
    function play(board) {
        finish(board);
        if (motion.matches) return;
        var skip=board.querySelector('[data-rk-replay-skip]'); if(skip)skip.hidden=false;
        var rows = Array.from(board.querySelectorAll('.rl-month')), i = 0;
        parts(board).forEach(function (el) { el.classList.add('rl-wait'); });
        board.classList.add('is-playing');
        board._rkTimer = setInterval(function () {
            if (!board.isConnected) { finish(board); return; }
            if (i < rows.length) { rows[i].classList.remove('rl-wait'); board.querySelectorAll('[data-rk-inn="'+i+'"]').forEach(function (el) { el.classList.remove('rl-wait'); }); i++; }
            else finish(board);
        }, 650);
    }
    function show(root, id, replay) {
        root.dataset.rkSelected = id;
        root.querySelectorAll('[data-rk-replay]').forEach(function (board) {
            var active = board.dataset.rkReplay === String(id);
            if (!active) finish(board);
            board.hidden = !motion.matches && !active;
            if (active && replay) play(board);
        });
        root.querySelectorAll('[data-rk-pick]').forEach(function (chip) { chip.setAttribute('aria-pressed', String(chip.dataset.rkPick === String(id))); });
    }
    function race(root, key) {
        var panels = Array.from(root.querySelectorAll('[data-rk-race-view]'));
        if (!panels.some(function (panel) { return panel.dataset.rkRaceView === key; })) key = panels.length ? panels[0].dataset.rkRaceView : '';
        panels.forEach(function (panel) { panel.hidden = panel.dataset.rkRaceView !== key; });
        root.querySelectorAll('[data-rk-race-pick]').forEach(function (button) { button.setAttribute('aria-pressed', String(button.dataset.rkRacePick === key)); });
        var nav = root.querySelector('[data-rk-race-tabs]');
        if (nav) nav.hidden = false;
    }
    function init(scope) {
        scope.querySelectorAll('[data-rk-md]').forEach(function (root) {
            if (root.dataset.rkReady) return;
            root.dataset.rkReady = '1';
            var shown = root.dataset.rkShown;
            if (shown) show(root, shown, !!root.dataset.rkAuto);
            root.querySelectorAll('[data-rk-race]').forEach(function (el) { race(el, el.dataset.rkRaceDefault); });
            var calendar = root.querySelector('.rk-calendar-scroll'), current = calendar && calendar.querySelector('[aria-current]');
            if (current && calendar.scrollWidth > calendar.clientWidth) {
                var left = current.getBoundingClientRect().left-calendar.getBoundingClientRect().left+calendar.scrollLeft;
                calendar.scrollLeft = Math.max(0, left-(calendar.clientWidth-current.clientWidth)/2);
            }
            var post = root.querySelector('[data-rk-post]');
            if (post) {
                var key = 'rk-post-last:'+post.dataset.rkPost, n = Number(post.dataset.rkPostShown);
                try { var last = sessionStorage.getItem(key); if (last !== null && n > Number(last) && !motion.matches) post.classList.add('is-new-result'); sessionStorage.setItem(key, String(n)); } catch (_) {}
            }
            var born = Date.now(), server = Number(root.dataset.rkNow) || born;
            var image = root.querySelector('[data-rk-sky]'), hero = root.querySelector('[data-rk-home]');
            var skyData = root.querySelector('#rk-sky-timeline');
            var timeline = skyData ? JSON.parse(skyData.textContent) : [];
            var due = Number(root.dataset.rkRefresh), reloading = false;
            function update() {
                if (!root.isConnected) { clearInterval(root._rkClock); return; }
                var now = server + Date.now() - born;
                if (image && timeline.length && timeline[0].at <= now) {
                    var next;
                    while (timeline.length && timeline[0].at <= now) next = timeline.shift();
                    var img = new Image();
                    img.onload = function () {
                        if (!image.isConnected) return;
                        image.src = img.src;
                        hero.dataset.rkSkyKey = next.key;
                        hero.classList.toggle('is-lit', next.lit);
                        if (next.lit && !motion.matches) { hero.classList.remove('is-lighting'); requestAnimationFrame(function () { hero.classList.add('is-lighting'); }); }
                        root.querySelector('[data-rk-sky-label]').textContent = next.label;
                    };
                    img.src = image.dataset.rkSkyBase+next.key+'.webp?v='+image.dataset.rkVersion;
                }
                var time = root.querySelector('[data-rk-local-time]');
                if (time) time.textContent = clockFormatter.format(new Date(now));
                if (due && now >= due && !document.hidden && !reloading) {
                    var box = root.querySelector('[data-rk-new]');
                    if (box) box.hidden = false;
                    var editing = document.activeElement && document.activeElement.matches('input,textarea,select');
                    var playArea = document.getElementById('rk-play');
                    var busy = playArea && playArea.dataset.rkBusy === '1';
                    if (!editing && !busy) { reloading = true; window.location.reload(); }
                }
            }
            root._rkClock = setInterval(update, 1000);
            update();
        });
    }
    document.addEventListener('click', function (event) {
        var chip = event.target.closest('[data-rk-pick]');
        if (chip) { show(chip.closest('[data-rk-md]'), chip.dataset.rkPick, true); return; }
        var skip = event.target.closest('[data-rk-replay-skip]');
        if (skip) { finish(skip.closest('[data-rk-replay]')); return; }
        var tab = event.target.closest('[data-rk-race-pick]');
        if (tab) { race(tab.closest('[data-rk-race]'), tab.dataset.rkRacePick); return; }
        if (event.target.closest('[data-rk-reload]')) window.location.reload();
    });
    motion.addEventListener('change', function () { document.querySelectorAll('[data-rk-replay]').forEach(finish); document.querySelectorAll('[data-rk-md]').forEach(function(root){show(root,root.dataset.rkSelected||root.dataset.rkShown,false);}); });
    window.addEventListener('pagehide', function () { document.querySelectorAll('[data-rk-md]').forEach(function (r) { clearInterval(r._rkClock); }); document.querySelectorAll('[data-rk-replay]').forEach(finish); });
    init(document);
    if ('MutationObserver' in window) new MutationObserver(function (changes) {
        if (changes.some(function (change) { return Array.from(change.addedNodes).some(function (n) { return n.nodeType === 1 && (n.matches('[data-rk-md]') || n.querySelector('[data-rk-md]')); }); })) init(document);
    }).observe(document.body, {childList: true, subtree: true});
})();
