(function () {
    'use strict';
    document.querySelectorAll('[data-re-media-choice]').forEach(function (button) {
        button.addEventListener('click', function () {
            button.closest('.re-media').querySelector('[data-re-media-status]').textContent = '“' + button.dataset.reMediaChoice + '”를 골랐어요. 실제 게임에서는 이 각오가 기사에 남아요.';
        });
    });
})();
