/* 개인 읽기 도구: 이 브라우저의 공개 칼럼만 보관하며 서버로 전송하지 않아요. */
(function () {
    'use strict';
    var key = 'techchang-reading-v1';
    var topics = ['HRD', '데이터분석', '프로그래밍'];
    var state = { recent: [], saved: [], interests: [] };
    var available = true;
    function jumpTo(top) {
        var style = document.documentElement.style;
        var before = style.scrollBehavior;
        style.scrollBehavior = 'auto';
        window.scrollTo(0, top);
        style.scrollBehavior = before;
    }
    function status(message) {
        document.querySelectorAll('[data-reading-status]').forEach(function (el) { el.textContent = message; });
    }
    function articleURL(value) { return typeof value === 'string' && /^\/[1-9]\d*\/$/.test(value); }
    function records(value, limit) {
        if (!Array.isArray(value)) return [];
        var seen = new Set();
        return value.filter(function (item) {
            if (!item || !articleURL(item.url) || typeof item.title !== 'string' || seen.has(item.url)) return false;
            seen.add(item.url);
            return true;
        }).slice(0, limit).map(function (item) {
            return { url: item.url, title: item.title.slice(0, 200), category: topics.includes(item.category) ? item.category : '',
                position: Math.max(0, Math.min(1, Number(item.position) || 0)),
                next: articleURL(item.next) ? item.next : '',
                nextTitle: typeof item.nextTitle === 'string' ? item.nextTitle.slice(0, 200) : '' };
        });
    }
    try {
        var raw = JSON.parse(localStorage.getItem(key) || '{}') || {};
        state.recent = records(raw.recent, 24);
        state.saved = records(raw.saved, 100);
        state.interests = Array.isArray(raw.interests) ? topics.filter(function (topic) { return raw.interests.includes(topic); }) : [];
    } catch (error) {
        // 잘못된 데이터는 버리고, 저장소 차단 여부는 실제 저장할 때 다시 확인해요.
        state = { recent: [], saved: [], interests: [] };
    }
    function persist() {
        try { localStorage.setItem(key, JSON.stringify(state)); return true; }
        catch (error) {
            available = false;
            status('브라우저 저장 공간을 사용할 수 없어 변경 사항을 보관하지 못했어요. 브라우저의 저장 설정을 확인해 주세요.');
            return false;
        }
    }
    function makeLink(item, resume) {
        var a = document.createElement('a');
        a.className = 'fl-post';
        a.href = item.url + (resume && item.position > .01 && item.position < .95 ? '#reading-resume' : '');
        var meta = document.createElement('span');
        meta.className = 'fl-meta';
        meta.textContent = item.category + (resume ? ' · ' + Math.round(item.position * 100) + '% 지점' : ' · 저장한 글');
        var heading = document.createElement('h3');
        heading.textContent = item.title;
        a.append(meta, heading);
        return a;
    }
    function renderList(selector, items, resume, emptyText) {
        var root = document.querySelector(selector);
        if (!root) return;
        root.replaceChildren();
        if (!items.length) {
            var empty = document.createElement('p');
            empty.className = 'fl-empty';
            empty.textContent = emptyText;
            root.appendChild(empty);
        } else {
            items.forEach(function (item) { root.appendChild(makeLink(item, resume)); });
        }
    }
    function render() {
        document.querySelectorAll('[data-interest]').forEach(function (button) {
            button.hidden = false;
            var active = state.interests.includes(button.dataset.interest);
            button.setAttribute('aria-pressed', String(active));
            button.textContent = active ? '관심 주제 해제' : '관심 주제로 저장';
            button.setAttribute('aria-label', button.dataset.interest + ' ' + button.textContent);
        });
        document.querySelectorAll('[data-interest-links]').forEach(function (root) {
            root.replaceChildren();
            state.interests.forEach(function (topic) {
                var a = document.createElement('a');
                a.href = '/explore/?category=' + encodeURIComponent(topic);
                a.textContent = '내 관심 주제 · ' + topic;
                root.appendChild(a);
            });
            root.hidden = !state.interests.length;
        });
        renderList('[data-reading-saved]', state.saved, false, '아직 저장한 글이 없어요. 칼럼에서 ‘글 저장’을 눌러 보세요.');
        renderList('[data-reading-recent]', state.recent, true, '칼럼을 읽으면 이곳에서 이어 읽을 수 있어요.');
        document.querySelectorAll('[data-reading-clear]').forEach(function (button) {
            button.disabled = !state[button.dataset.readingClear].length;
        });
        var home = document.querySelector('[data-reading-home]');
        if (home) {
            home.hidden = !state.recent.length;
            if (state.recent.length) {
                var item = state.recent[0];
                var go = home.querySelector('[data-reading-home-link]');
                if (item.position >= .95 && item.next) {
                    home.querySelector('p').textContent = '다음 회차로 이어 읽기';
                    go.href = item.next;
                    go.textContent = item.nextTitle;
                } else {
                    go.href = item.url + (item.position > .01 && item.position < .95 ? '#reading-resume' : '');
                    go.textContent = item.title;
                }
            }
        }
    }
    document.querySelectorAll('[data-interest]').forEach(function (button) {
        button.addEventListener('click', function () {
            var topic = button.dataset.interest;
            if (!topics.includes(topic)) return;
            state.interests = state.interests.includes(topic) ? state.interests.filter(function (x) { return x !== topic; }) : state.interests.concat(topic);
            if (persist()) { render(); status('관심 주제를 이 브라우저에 보관했어요.'); }
        });
    });
    document.querySelectorAll('[data-reading-clear]').forEach(function (button) {
        button.addEventListener('click', function () {
            if (!window.confirm('이 브라우저의 ' + (button.dataset.readingClear === 'saved' ? '저장 목록' : '읽기 목록') + '을 비울까요?')) return;
            state[button.dataset.readingClear] = [];
            if (persist()) { render(); status('목록을 비웠어요.'); }
        });
    });
    var article = document.querySelector('[data-reading-article]');
    var body = document.querySelector('[data-reading-body]');
    if (article && body && articleURL(article.dataset.url)) {
        var previous = state.recent.find(function (item) { return item.url === article.dataset.url; });
        var save = article.querySelector('[data-reading-save]');
        var resume = article.querySelector('[data-reading-resume]');
        var progressTimer;
        function record() {
            var top = body.getBoundingClientRect().top + window.scrollY;
            var travel = Math.max(1, body.offsetHeight - window.innerHeight + 160);
            var last = state.recent.find(function (item) { return item.url === article.dataset.url; });
            // 목록을 누르려고 본문 위로 올라와도 마지막 읽던 위치를 지우지 않아요.
            var position = window.scrollY + 80 < top && last ? last.position :
                Math.max(0, Math.min(1, (window.scrollY - top + 80) / travel));
            return { url: article.dataset.url, title: article.dataset.title.slice(0, 200), category: article.dataset.category,
                position: position,
                next: articleURL(article.dataset.next) ? article.dataset.next : '', nextTitle: article.dataset.nextTitle || '' };
        }
        function remember() {
            if (!available) return;
            var item = record();
            state.recent = [item].concat(state.recent.filter(function (x) { return x.url !== item.url; })).slice(0, 24);
            state.saved = state.saved.map(function (x) { return x.url === item.url ? item : x; });
            persist();
        }
        function renderSave() {
            var saved = state.saved.some(function (item) { return item.url === article.dataset.url; });
            save.hidden = false;
            save.setAttribute('aria-pressed', String(saved));
            save.textContent = saved ? '저장 해제' : '글 저장';
        }
        save.addEventListener('click', function () {
            var item = record();
            if (state.saved.some(function (x) { return x.url === item.url; })) {
                state.saved = state.saved.filter(function (x) { return x.url !== item.url; });
            } else {
                if (state.saved.length >= 100) { status('최대 100편까지 저장할 수 있어요. 내 읽기 목록에서 먼저 정리해 주세요.'); return; }
                state.saved.unshift(item);
            }
            if (persist()) { renderSave(); status('읽기 목록을 이 브라우저에 보관했어요.'); }
        });
        function restoreArticle() {
            if (!previous || previous.position <= .01 || previous.position >= .95) return;
            var ready = document.fonts ? document.fonts.ready : Promise.resolve();
            ready.then(function () {
                requestAnimationFrame(function () {
                    var top = body.getBoundingClientRect().top + window.scrollY;
                    jumpTo(top - 80 + previous.position * Math.max(1, body.offsetHeight - window.innerHeight + 160));
                });
            });
        }
        if (previous && previous.position > .01 && previous.position < .95) {
            resume.hidden = false;
            resume.addEventListener('click', restoreArticle);
            if (location.hash === '#reading-resume') restoreArticle();
        }
        window.addEventListener('scroll', function () { clearTimeout(progressTimer); progressTimer = setTimeout(remember, 400); }, { passive: true });
        window.addEventListener('pagehide', remember);
        document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'hidden') remember(); });
        renderSave();
    }
    render();

    // 목록의 검색 조건·페이지·스크롤을 같은 탭에서 복원해요. 서버에는 별도 기록하지 않아요.
    var listPath = /^\/(?:$|explore\/|map\/|board\/|series\/|my\/)/;
    function internalList(value) {
        if (!value) return null;
        try {
            var url = new URL(value, location.origin);
            return url.origin === location.origin && listPath.test(url.pathname) ? url : null;
        } catch (error) { return null; }
    }
    document.addEventListener('click', function (event) {
        var link = event.target.closest('a');
        if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download')) return;
        var url;
        try { url = new URL(link.href); } catch (error) { return; }
        if (url.origin !== location.origin || !articleURL(url.pathname)) return;
        var source = internalList(location.href) || internalList(new URLSearchParams(location.search).get('from') || '');
        if (!source) return;
        url.searchParams.set('from', source.pathname + source.search + source.hash);
        link.href = url.pathname + url.search + url.hash;
        try { if (listPath.test(location.pathname)) sessionStorage.setItem('tc-list:' + source.pathname + source.search + source.hash, String(window.scrollY)); } catch (error) { /* 링크는 그대로 사용할 수 있어요. */ }
    });
    if (listPath.test(location.pathname)) {
        try {
            var offset = Number(sessionStorage.getItem('tc-list:' + location.pathname + location.search + location.hash));
            var returning = internalList(document.referrer) === null && new URL(document.referrer || location.href).origin === location.origin;
            if (returning && offset > 0) {
                var fontsReady = document.fonts ? document.fonts.ready : Promise.resolve();
                fontsReady.then(function () { requestAnimationFrame(function () { jumpTo(offset); }); });
            }
        } catch (error) { /* 저장소를 사용할 수 없어도 목록은 정상 표시해요. */ }
    }
})();
