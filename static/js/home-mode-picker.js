(function () {
    'use strict';
    var dialog = document.getElementById('tc-mode-picker');
    var trigger = document.querySelector('[data-tc-mode-open]');
    if (!dialog || !trigger) return;
    function close() { if (dialog.open) dialog.close(); }
    trigger.addEventListener('click', function () {
        if (typeof dialog.showModal !== 'function') { window.location.href = dialog.dataset.gameCenter; return; }
        if (dialog.open) return;
        dialog.showModal();
        document.documentElement.classList.add('tc-mode-open');
        trigger.setAttribute('aria-expanded', 'true');
    });
    dialog.querySelector('[data-tc-mode-close]').addEventListener('click', close);
    dialog.addEventListener('keydown', function (event) {
        if (event.key !== 'Tab') return;
        var items = dialog.querySelectorAll('button:not([disabled]), a[href]');
        var first = items[0], last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    dialog.addEventListener('click', function (event) {
        if (event.target.closest('a')) { close(); return; }
        if (event.target !== dialog) return;
        var box = dialog.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) close();
    });
    dialog.addEventListener('close', function () {
        document.documentElement.classList.remove('tc-mode-open');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.focus({preventScroll: true});
    });
    window.addEventListener('pagehide', close);
})();
