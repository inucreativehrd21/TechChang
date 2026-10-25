// 며칠 — 저장 시 서버 검증에서 오류가 난 폼이 다시 그려지면 첫 오류 칸으로 초점을 옮긴다.
// 인라인 스크립트를 쓰지 않는다(CSP script-src 'self' 로 허용되는 정적 파일).
(function () {
    var first = document.querySelector(
        '.mc-field-invalid input, .mc-field-invalid textarea, .mc-field-invalid select'
    );
    if (first) {
        first.focus();
    }
})();
