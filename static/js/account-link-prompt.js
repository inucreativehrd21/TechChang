(function () {
    'use strict';
    var dialog = document.getElementById('account-link-prompt');
    if (!dialog || typeof dialog.showModal !== 'function') return;
    var previousFocus = document.activeElement;
    dialog.querySelector('[data-link-prompt-close]').addEventListener('click', function () {
        dialog.close();
    });
    dialog.addEventListener('keydown', function (event) {
        if (event.key !== 'Tab') return;
        var first = dialog.querySelector('a');
        var last = dialog.querySelector('[data-link-prompt-close]');
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });
    dialog.addEventListener('close', function () {
        if (previousFocus && typeof previousFocus.focus === 'function') previousFocus.focus();
    });
    dialog.showModal();
}());
