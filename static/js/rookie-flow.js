/* 한 화면에 한 장면. 서버 폼·CSRF·검증을 그대로 사용한다. */
(function () {
    'use strict';
    var root = document.querySelector('[data-rl-flow]');
    if (!root) return;
    var stage = root.querySelector('.rl-stage');
    if (!stage) return;
    // 결과 알림이 게임 위에 큰 빈 영역을 만들지 않게 별도 알림 칸으로 옮겨요.
    var alerts = Array.from(document.querySelectorAll('body > div > .container-premium > .alert, body > .m-messages > .alert'));
    if (alerts.length) {
        var notices = document.createElement('aside'); notices.className = 'rl-flow-notices';
        notices.setAttribute('aria-label', '게임 알림');
        alerts.forEach(function (alert) {
            var oldParent = alert.parentElement;
            var close = alert.querySelector('.btn-close');
            if (close) close.setAttribute('aria-label', '알림 닫기');
            notices.appendChild(alert);
            if (!oldParent.childElementCount) oldParent.remove();
        });
        root.appendChild(notices);
    }
    var plan = stage.querySelector('form.rl-plan[data-rl-plan]');
    var key = plan ? 'rl-plan-v1:' + plan.dataset.planKey : '';
    var read = function () { try { return JSON.parse(sessionStorage.getItem(key)) || {}; } catch (_) { return {}; } };
    var write = function (data) { try { sessionStorage.setItem(key, JSON.stringify(data)); } catch (_) {} };
    var values = function () {
        var data = {};
        plan.querySelectorAll('input[name]').forEach(function (input) {
            if (input.name === 'program' || input.name === 'event_choice' || input.name === 'intensity' || input.name.indexOf('intl_') === 0) {
                if (!data[input.name]) data[input.name] = [];
                if (input.checked) data[input.name].push(input.value);
            }
        });
        return data;
    };
    if (plan) {
        var saved = read();
        // sessionStorage를 사용할 수 없어도 성공한 구매의 draft는 서버 렌더링으로 복원된다.
        if (saved.values) plan.querySelectorAll('input[name]').forEach(function (input) {
            if (Object.prototype.hasOwnProperty.call(saved.values, input.name) && !input.hasAttribute('data-rl-locked')) {
                input.checked = saved.values[input.name].indexOf(input.value) !== -1;
                input.disabled = false;
            }
        });
        plan.dispatchEvent(new Event('change', {bubbles: true}));
        var remember = function () { var s = read(); s.values = values(); write(s); };
        plan.addEventListener('change', remember);
        root.querySelectorAll('form').forEach(function (form) {
            form.addEventListener('submit', function () {
                remember();
                if (form === plan) return;
                form.querySelectorAll('[data-rl-draft]').forEach(function (input) { input.remove(); });
                var add = function (name, value) {
                    var i = document.createElement('input');
                    i.type = 'hidden'; i.name = name; i.value = value; i.dataset.rlDraft = '';
                    form.appendChild(i);
                };
                add('_draft_key', plan.dataset.planKey);
                var v = values();
                Object.keys(v).forEach(function (name) { v[name].forEach(function (value) { add('_draft_' + name, value); }); });
            });
        });
        plan.addEventListener('submit', function () {
            // 실패·통신 끊김이면 같은 시즌의 선택을 보존하고, 다음 시즌에는 다른 키를 써요.
            remember();
        });
    }

    var titleOf = function (screen) {
        var h = screen.querySelector('legend, h2, h3, summary, .rl-shop-name b');
        var text = screen.dataset.rlTitle || screen.getAttribute('aria-label') || (h && h.textContent.trim());
        if (!text && screen.matches('form')) text = (screen.querySelector('button') || {}).textContent;
        return (text || '다음 장면').replace(/\s+/g, ' ').replace(/^\d+\s*/, '').slice(0, 34);
    };
    function deck(host, screens, storageKey, validate) {
        if (screens.length < 2) return null;
        host.classList.add('rl-deck');
        var viewport = document.createElement('div');
        viewport.className = 'rl-deck-viewport';
        // 폼을 쪼개지 않고 함께 옮겨 CSRF와 제출 대상·선택 상태를 유지해요.
        Array.from(host.childNodes).forEach(function (node) {
            if (node.nodeType === 1 && node.matches('h2')) return;
            viewport.appendChild(node);
        });
        host.appendChild(viewport);
        if (host === stage) {
            host.classList.add('rl-deck-main');
            screens.forEach(function (screen) { screen.classList.add('rl-main-screen'); });
        }
        var nav = document.createElement('nav');
        nav.className = 'rl-deck-nav'; nav.setAttribute('aria-label', '장면 이동');
        var prev = document.createElement('button'), next = document.createElement('button');
        prev.type = next.type = 'button'; prev.textContent = '이전'; next.textContent = '다음';
        prev.className = next.className = 'gm-btn';
        var select = document.createElement('select');
        select.setAttribute('aria-label', '현재 장면 선택');
        screens.forEach(function (screen, i) {
            screen.classList.add('rl-deck-screen');
            var option = document.createElement('option');
            option.value = i; option.textContent = (i + 1) + ' / ' + screens.length + ' · ' + titleOf(screen);
            select.appendChild(option);
        });
        var status = document.createElement('p'); status.className = 'rl-deck-status'; status.setAttribute('aria-live', 'polite');
        var announcement = document.createElement('p');
        announcement.className = 'visually-hidden'; announcement.setAttribute('aria-live', 'polite');
        announcement.setAttribute('aria-atomic', 'true');
        nav.append(prev, select, next);
        host.insertBefore(status, viewport); host.insertBefore(nav, status); host.insertBefore(announcement, viewport);
        var current = 0, desired = 0, revision = 0, animation = null;
        var getStored = function () { try { return JSON.parse(sessionStorage.getItem(storageKey)) || {}; } catch (_) { return {}; } };
        var apply = function (index, focus) {
            current = desired = index;
            screens.forEach(function (screen, i) { screen.hidden = i !== index; });
            if (host === stage && plan) plan.hidden = !plan.contains(screens[index]);
            viewport.scrollTop = 0;
            select.value = String(index); prev.disabled = index === 0; next.disabled = index === screens.length - 1;
            announcement.textContent = (index + 1) + ' / ' + screens.length + ' · ' + titleOf(screens[index]);
            if (storageKey) {
                var data = getStored(); data.scene = titleOf(screens[index]);
                try { sessionStorage.setItem(storageKey, JSON.stringify(data)); } catch (_) {}
            }
            if (focus) {
                var target = screens[index].querySelector('h2, h3, legend, summary') || screens[index];
                target.tabIndex = -1; target.focus({preventScroll: true});
            }
        };
        var show = async function (index, focus, animate) {
            index = Math.max(0, Math.min(screens.length - 1, Number(index) || 0));
            if (validate && index > current) {
                for (var i = current; i < index; i++) {
                    var issue = validate(screens[i]);
                    if (issue) { index = i; status.textContent = issue; break; }
                }
            }
            desired = index;
            var token = ++revision;
            if (animation) animation.cancel();
            var reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            if (!animate || reduced || !viewport.animate || index === current) {
                viewport.classList.remove('is-transitioning'); viewport.removeAttribute('aria-busy');
                apply(index, focus); return;
            }
            viewport.classList.add('is-transitioning'); viewport.setAttribute('aria-busy', 'true');
            animation = viewport.animate([{opacity: 1}, {opacity: 0}], {duration: 110, easing: 'ease-in', fill: 'forwards'});
            await animation.finished.catch(function () {});
            if (token !== revision) return;
            apply(index, focus);
            animation.cancel();
            animation = viewport.animate([{opacity: 0}, {opacity: 1}], {duration: 170, easing: 'ease-out'});
            await animation.finished.catch(function () {});
            if (token !== revision) return;
            animation = null;
            viewport.classList.remove('is-transitioning'); viewport.removeAttribute('aria-busy');
        };
        prev.addEventListener('click', function (event) { status.textContent = ''; show(desired - 1, event.detail === 0, true); });
        next.addEventListener('click', function (event) { status.textContent = ''; show(desired + 1, event.detail === 0, true); });
        select.addEventListener('change', function () { status.textContent = ''; show(select.value, keyboardInput, true); });
        var stored = storageKey ? getStored().scene : '';
        var initial = screens.findIndex(function (s) { return titleOf(s) === stored; });
        // 복원할 때도 미응답 장면을 건너뛰지 않아요.
        show(initial < 0 ? 0 : initial, false);
        return {show: show, advance: function () { show(desired + 1, keyboardInput, true); }, screens: screens};
    }

    var keyboardInput = false;
    root.addEventListener('keydown', function () { keyboardInput = true; });
    root.addEventListener('pointerdown', function () { keyboardInput = false; });

    // 긴 메뉴는 접어서 열 수 있게 해요.
    var menu = root.querySelector('.rk-nav');
    if (menu) {
        var details = document.createElement('details'); details.className = 'rl-flow-menu';
        var summary = document.createElement('summary'); summary.textContent = '게임 메뉴';
        menu.before(details); details.append(summary, menu);
    }
    var screens = [];
    if (plan) {
        var shopScreen = stage.querySelector('.rl-shop');
        if (shopScreen) shopScreen.dataset.rlTitle = '장비·생활';
        var train = plan.querySelector('.rl-train');
        if (train) {
            train.dataset.rlTitle = '훈련 두 개 고르기';
            var intensity = document.createElement('section');
            intensity.className = 'rk-panel';
            intensity.dataset.rlTitle = plan.querySelector('input[name="routine"]') ? '훈련 강도 · 경기 전 루틴' : '훈련 강도';
            var heading = train.querySelector('h3');
            if (heading) { while (heading) { var sibling = heading.nextSibling; intensity.appendChild(heading); heading = sibling; } }
            train.after(intensity);
        }
        var confirm = plan.querySelector('.rl-cta');
        confirm.classList.add('rk-panel'); confirm.dataset.rlTitle = '선택 확인 · 시즌 시작';
        var h = document.createElement('h2'); h.textContent = '이번 시즌, 이렇게 준비해요';
        confirm.classList.add('rl-prep-board');
        var summaryText = document.createElement('div'); summaryText.className = 'rl-plan-summary';
        summaryText.setAttribute('aria-live', 'polite');
        confirm.prepend(h, summaryText);
        var updateSummary = function () {
            summaryText.replaceChildren();
            var sections = [
                ['이벤트 선택', 'input[name="event_choice"]:checked', 'event'],
                ['훈련 프로그램', 'input[name="program"]:checked', 'training'],
                ['훈련 강도', 'input[name="intensity"]:checked', 'intensity'],
                ['경기 전 루틴', 'input[name="routine"]:checked', 'routine'],
                ['국가대표 일정', 'input[name^="intl_"]:checked', 'intl']
            ];
            sections.forEach(function (group) {
                var inputs = Array.from(plan.querySelectorAll(group[1]));
                if (!inputs.length) return;
                var section = document.createElement('section'), title = document.createElement('h3');
                section.className = 'rl-prep-group'; section.dataset.prepType = group[2]; title.textContent = group[0]; section.append(title);
                inputs.forEach(function (input) {
                    var label = input.closest('label');
                    var strong = label.querySelector('b') || label.querySelector('span');
                    var hint = label.querySelector('small');
                    var row = document.createElement('div'), name = document.createElement('b');
                    row.className = 'rl-prep-item'; name.textContent = (strong || label).textContent.trim();
                    if (group[2] === 'intl') {
                        var tournament = input.closest('.rl-tourney').querySelector('.rl-tourney-main b');
                        if (tournament) name.textContent = tournament.textContent + ' · ' + name.textContent;
                    }
                    row.append(name);
                    if (hint) {
                        var detail = document.createElement('p'); detail.textContent = hint.textContent.trim(); row.append(detail);
                    }
                    section.append(row);
                });
                summaryText.append(section);
            });
            if (!summaryText.childElementCount) summaryText.textContent = '앞 장면에서 선택을 마쳐 주세요.';
        };
        plan.addEventListener('change', updateSummary); updateSummary();
        Array.from(stage.children).forEach(function (node) {
            if (node.matches('script, .rl-scene, .rk-retire, .rl-yearsbox')) return;
            if (node === plan) screens.push.apply(screens, Array.from(plan.children).filter(function (n) { return n.matches('section, .rl-cta'); }));
            else if (node.matches('section, details')) screens.push(node);
        });
    } else {
        var result = stage.querySelector('.rl-result');
        if (result) {
            result.dataset.rlTitle = '시즌 성적';
            var growth = document.createElement('section');
            growth.className = 'rk-panel'; growth.dataset.rlTitle = '성장 · 수입';
            var growthHeading = result.querySelector('h3');
            if (growthHeading) {
                while (growthHeading) { var following = growthHeading.nextSibling; growth.appendChild(growthHeading); growthHeading = following; }
                result.after(growth);
            }
        }
        screens = Array.from(stage.children).filter(function (n) { return n.matches('section, form, [data-rl-scene]'); });
    }
    // 선수 정보·연표도 같은 장면 메뉴에서 열어요.
    var info = document.createElement('section'); info.className = 'rk-panel'; info.dataset.rlTitle = '선수 · 리그 · 기록';
    var infoHeading = document.createElement('h2'); infoHeading.textContent = '내 선수와 커리어'; info.appendChild(infoHeading);
    var main = root.querySelector('.rl-main');
    var side = main && main.querySelector('.rl-side');
    if (side) { info.appendChild(side); main.classList.add('rl-flow-main'); }
    // 마음·리그 표·계약은 HUD와 본문 사이에 있는 요소예요.
    var hud = root.querySelector('.rl-hud');
    if (hud) {
        var item = hud.nextElementSibling;
        while (item && item !== main) {
            var after = item.nextElementSibling;
            info.appendChild(item);
            item = after;
        }
    }
    var coachAdvice = plan && plan.querySelector('.rl-say.is-small');
    if (coachAdvice) {
        var advice = document.createElement('details'), adviceTitle = document.createElement('summary');
        advice.className = 'rl-coach-advice'; adviceTitle.textContent = '코치 조언 보기';
        coachAdvice.before(advice); advice.append(adviceTitle, coachAdvice);
    }
    Array.from(stage.children).filter(function (n) { return n.matches('.rl-yearsbox, .rk-table-wrap, .rk-h2, .rk-retire'); }).forEach(function (n) { info.appendChild(n); });
    var infoScreens = Array.from(info.children).filter(function (n) { return n !== infoHeading && !n.matches('h2, script'); });
    infoScreens.forEach(function (n) {
        if (n.matches('.rl-side, .rl-mcard')) n.dataset.rlTitle = '선수 카드';
        if (n.matches('.rk-table-wrap, .rl-yearsbox')) n.dataset.rlTitle = '커리어 연표';
    });
    info.querySelectorAll(':scope > .rk-h2').forEach(function (n) { n.remove(); });
    deck(info, infoScreens, key ? key + ':info' : '', null);
    stage.appendChild(info); screens.push(info);
    var validation = function (screen) {
        if (screen.hasAttribute('data-extreme-pending')) return '익스트림 전용 이벤트에서 어떻게 할지 먼저 골라 주세요.';
        if (screen.querySelector('[data-rl-ticker].is-playing') || screen.matches('[data-rl-ticker].is-playing')) return '중계를 보거나 바로 결과 보기를 눌러 주세요.';
        var unanswered = Array.from(screen.querySelectorAll('input[required]')).some(function (i) { return !plan || !plan.querySelector('input[name="' + i.name + '"]:checked'); });
        if (unanswered) return '이 장면에서 어떻게 할지 골라 주세요.';
        if (screen.matches('.rl-train')) {
            if (plan.querySelectorAll('input[name=program]:checked').length !== 2) return '훈련을 두 개 골라 주세요.';
            if (!plan.querySelector('[data-rl-banned]').hidden) return '지난 비시즌과 다른 조합으로 골라 주세요.';
        }
        return '';
    };
    var mainDeck = deck(stage, screens, key ? key + ':scene' : '', validation);
    if (plan && mainDeck) plan.addEventListener('change', function (event) {
        if (event.target.name === 'event_choice' || event.target.name.indexOf('intl_') === 0 || event.target.name === 'program') {
            var screen = event.target.closest('section');
            if (screen && !validation(screen)) mainDeck.advance();
        }
    });
    var shop = stage.querySelector('.rl-shop');
    if (shop) {
        shop.open = true;
        var body = shop.querySelector('.rl-shop-body');
        var help = body.querySelector(':scope > .rk-hint');
        if (help) {
            var guide = document.createElement('details'), guideTitle = document.createElement('summary');
            guideTitle.textContent = '상점 이용 안내'; guide.className = 'rl-shop-guide';
            help.before(guide); guide.append(guideTitle, help);
        }
        var groups = Array.from(body.querySelectorAll('.rl-plan-group, .rl-shop-row'));
        var buyForm = body.querySelector('form.rl-planform');
        if (buyForm) {
            var select = buyForm.querySelector('.rl-item-pick');
            if (select) select.previousElementSibling.appendChild(select);
            var checkout = document.createElement('section'); checkout.dataset.rlTitle = '장바구니 확인 · 구매';
            checkout.append(buyForm.querySelector('[data-plan-sum]'), buyForm.querySelector('button[type=submit]'));
            buyForm.appendChild(checkout);
            var lastGroup = groups.findIndex(function (g) { return !buyForm.contains(g); });
            groups.splice(lastGroup < 0 ? groups.length : lastGroup, 0, checkout);
        }
        deck(body, groups, key + ':shop', null);
        // 상점 페이지를 다시 열 때 브라우저가 긴 위치로 점프하지 않게 한다.
        if (location.hash === '#rl-shop') history.replaceState(null, '', location.pathname + location.search);
    }
    root.classList.add('rl-flow-ready');
    // 장면마다 박스 높이를 바꾸지 않아요. 긴 장면만 안쪽에서 스크롤해요.
    var frame = stage.querySelector(':scope > .rl-deck-viewport');
    var sizeFrame = function () {
        if (!frame) return;
        var bottom = window.matchMedia('(max-width: 767px)').matches ? 90 : 24;
        var height = Math.max(bottom === 90 ? 300 : 240, Math.min(760, window.innerHeight - frame.getBoundingClientRect().top - bottom));
        stage.style.setProperty('--rl-scene-height', Math.round(height) + 'px');
        stage.classList.toggle('rl-short-frame', height < 350);
    };
    requestAnimationFrame(sizeFrame);
    if (document.fonts) document.fonts.ready.then(sizeFrame);
    var resizeFrame;
    window.addEventListener('resize', function () {
        cancelAnimationFrame(resizeFrame); resizeFrame = requestAnimationFrame(sizeFrame);
    });
    // 안내 문구(예: 익스트림 사건에 먼저 답해 주세요)가 생기면 틀이 그만큼 아래로 밀리니 높이를 다시 맞춘다 —
    // 안 그러면 선택 카드가 접힌 선 아래로 나가고, 카드 위의 휠은 페이지로 넘어가지 않아 내릴 수 없다.
    var deckStatus = stage.querySelector(':scope > .rl-deck-status');
    if (deckStatus && window.ResizeObserver) {
        new ResizeObserver(function () { requestAnimationFrame(sizeFrame); }).observe(deckStatus);
    }
})();
