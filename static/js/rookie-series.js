/* 저장된 시리즈 기록의 재생만 맡아요. 경기 결과나 커리어 난수를 바꾸지 않아요. */
(function () {
    'use strict';
    var motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    var players = [];
    document.querySelectorAll('[data-sb]').forEach(function (board) {
        var rounds = Array.from(board.querySelectorAll('[data-sb-round]'));
        var entries = [], tabs = [], current = 0, timer = null, observed = false;
        var controls = board.querySelector('[data-sb-controls]');
        var nav = board.querySelector('[data-sb-round-nav]');
        var play = board.querySelector('[data-sb-play]');
        var next = board.querySelector('[data-sb-next]');
        var end = board.querySelector('[data-sb-end]');
        var complete = board.querySelector('[data-sb-complete]');
        var live = board.querySelector('[data-sb-live]');
        var celebration = board.querySelector('.sb-celebration');
        // 커리어·연도·대회와 기록 지문으로 이미 본 결산을 구분해요.
        var signature = board.querySelector('.sb-rounds').textContent;
        var hash = 0;
        for (var h = 0; h < signature.length; h++) hash = (hash * 31 + signature.charCodeAt(h)) | 0;
        var key = 'rl-series-v1:' + board.dataset.sbKey + ':' + hash;
        var seen = board.hasAttribute('data-sb-seen');
        try { seen = seen || sessionStorage.getItem(key) === 'seen'; } catch (_) {}
        function pause() {
            clearTimeout(timer); timer = null;
            play.textContent = '자동 재생'; play.setAttribute('aria-pressed', 'false');
        }
        players.push(pause);
        rounds.forEach(function (round) {
            var cards = Array.from(round.querySelectorAll('[data-sb-game-card]'));
            var chips = Array.from(round.querySelectorAll('[data-sb-rail] > li'));
            var start = entries.length;
            cards.forEach(function (card, i) {
                var chip = chips[i];
                if (!chip) return;
                var button = chip.querySelector('[data-sb-select]');
                var index = entries.length;
                entries.push({round: round, card: card, chip: chip, button: button,
                    label: card.getAttribute('aria-label'), state: chip.querySelector('.sb-chip-state').textContent});
                button.addEventListener('click', function () { pause(); show(index, true); });
            });
            var tab = document.createElement('button');
            tab.type = 'button'; tab.textContent = round.querySelector('.sb-round-name').textContent;
            tab.disabled = entries.length === start;
            tab.addEventListener('click', function () { pause(); show(start, true); });
            nav.appendChild(tab); tabs.push(tab);
        });
        if (!entries.length) return;
        function dots(host, wins, need) {
            host.replaceChildren();
            // 조별 경기의 need=0에는 선승 표시를 붙이지 않아요.
            for (var n = 0; n < need; n++) {
                var dot = document.createElement('i');
                dot.className = 'sb-dot' + (n < wins ? ' is-filled' : '');
                host.appendChild(dot);
            }
        }
        function show(index, announce) {
            current = Math.max(0, Math.min(entries.length - 1, index));
            var active = entries[current], last = current === entries.length - 1;
            var opponent = active.card.querySelector('tr.is-them th');
            if (opponent) {
                active.round.querySelector('.sb-side.is-them .sb-team').textContent = opponent.firstChild.textContent.trim();
                active.round.querySelector('.sb-side.is-them .sb-side-label').textContent = '상대 팀';
            }
            rounds.forEach(function (round, ri) {
                round.hidden = round !== active.round;
                if (round === active.round) tabs[ri].setAttribute('aria-current', 'step');
                else tabs[ri].removeAttribute('aria-current');
                var wins = [Number(round.dataset.sbHeadUs) || 0, Number(round.dataset.sbHeadThem) || 0];
                entries.forEach(function (entry, ei) {
                    if (entry.round === round && ei <= current) wins[entry.chip.dataset.sbWon === '1' ? 0 : 1]++;
                });
                round.querySelector('[data-sb-wins]').textContent = wins[0] + ' : ' + wins[1];
                var need = Number(round.dataset.sbNeed) || 0;
                dots(round.querySelector('[data-sb-dots-us]'), wins[0], need);
                dots(round.querySelector('[data-sb-dots-them]'), wins[1], need);
                round.querySelector('[data-sb-progress]').textContent = need > 1 && Math.max.apply(null, wins) < need ? '라운드 승리까지 ' + (need - wins[0]) + '승' : '';
                var done = entries.every(function (e, ei) { return e.round !== round || ei <= current; });
                round.querySelector('.sb-round-result').textContent = done ? ({won: '승리', lost: '패배', pending: '기록 대기'}[round.dataset.sbState] || '') : '기록 재생 중';
            });
            entries.forEach(function (entry, ei) {
                entry.card.hidden = ei !== current;
                entry.chip.classList.toggle('is-current', ei === current);
                entry.chip.classList.toggle('is-upcoming', ei > current);
                entry.button.disabled = false;
                if (ei === current) entry.button.setAttribute('aria-current', 'step');
                else entry.button.removeAttribute('aria-current');
                entry.chip.querySelector('.sb-chip-state').textContent = ei > current ? '아직 안 봄' : entry.state;
            });
            board.querySelector('[data-sb-position]').textContent = (current + 1) + ' / ' + entries.length + ' 경기 · ' + active.label;
            var rail = active.chip.parentElement;
            if (rail.scrollWidth > rail.clientWidth) rail.scrollLeft = active.chip.offsetLeft - (rail.clientWidth - active.chip.clientWidth) / 2;
            complete.hidden = !last;
            next.disabled = end.disabled = last;
            play.textContent = timer ? '일시정지' : last ? '처음부터 재생' : '자동 재생';
            if (announce) live.textContent = active.label + ', ' + active.state + ', ' + active.card.querySelector('.sb-me').textContent;
            if (last) {
                pause(); play.textContent = '처음부터 재생';
                if (!seen && !motion.matches && board.hasAttribute('data-sb-champion')) celebration.hidden = false;
                seen = true;
                try { sessionStorage.setItem(key, 'seen'); } catch (_) {}
            }
        }
        function tick() {
            timer = setTimeout(function () {
                show(current + 1, true);
                if (current < entries.length - 1) tick();
            }, 2200);
            play.textContent = '일시정지'; play.setAttribute('aria-pressed', 'true');
        }
        function start() {
            if (motion.matches) return;
            players.forEach(function (stop) { stop(); });
            if (current === entries.length - 1) { celebration.hidden = true; show(0, true); }
            tick();
        }
        play.addEventListener('click', function () { if (timer) pause(); else start(); });
        next.addEventListener('click', function () { pause(); show(current + 1, true); });
        end.addEventListener('click', function () { pause(); show(entries.length - 1, true); });
        board.querySelectorAll('[data-rl-skip]').forEach(function (skip) {
            skip.addEventListener('click', function () { pause(); show(entries.length - 1, true); });
        });
        function setup() {
            pause(); celebration.hidden = true;
            board.classList.toggle('is-enhanced', !motion.matches);
            controls.hidden = nav.hidden = motion.matches;
            if (motion.matches) {
                rounds.forEach(function (round) { round.hidden = false; });
                // 정적 모드에서도 최종 전적과 모든 경기 점수를 복원해요.
                show(entries.length - 1, false);
                rounds.forEach(function (round) { round.hidden = false; });
                entries.forEach(function (entry) { entry.card.hidden = false; entry.button.disabled = true; });
            } else show(seen ? entries.length - 1 : current, false);
        }
        setup();
        motion.addEventListener('change', setup);
        document.addEventListener('visibilitychange', function () { if (document.hidden) pause(); });
        window.addEventListener('pagehide', pause);
        if ('IntersectionObserver' in window) {
            var observer = new IntersectionObserver(function (items) {
                items.forEach(function (item) {
                    if (!item.isIntersecting || item.intersectionRatio < .1) { pause(); return; }
                    if (observed) return;
                    observed = true;
                    if (!seen && !motion.matches && !document.hidden && !document.querySelector('[data-rl-mfx]:not([hidden])')) start();
                });
            }, {threshold: [0, .1]});
            observer.observe(board);
        }
    });
})();
