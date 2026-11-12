(function () {
  'use strict';
  var form = document.querySelector('[data-meeting-review]');
  if (!form) return;
  var rows = Array.from(form.querySelectorAll('[data-decision]'));
  var status = form.querySelector('[data-review-status]');
  var summary = form.querySelector('[data-review-summary]');
  var list = form.querySelector('[data-review-summary-list]');
  var save = form.querySelector('[data-review-save]');
  var submitting = false;

  function selection(row) { return row.querySelector('input[type="radio"]:checked'); }
  function changed(row) {
    var pick = selection(row), note = row.querySelector('textarea');
    return (pick ? pick.value : '') !== row.dataset.savedKey || note.value !== note.dataset.savedNote;
  }
  function dirty() { return rows.some(changed); }
  window.officeMeetingReview = { dirty: dirty };

  function update() {
    var chosen = 0, modified = 0;
    list.replaceChildren();
    rows.forEach(function (row) {
      var pick = selection(row), change = changed(row), state = row.querySelector('.mr-state');
      modified += change ? 1 : 0;
      state.textContent = change ? '미저장' : row.dataset.savedKey ? '저장됨' : '미결정';
      row.classList.toggle('mr-modified', change);
      row.querySelectorAll('.mr-option').forEach(function (label) {
        label.classList.toggle('mr-selected', label.querySelector('input').checked);
      });
      if (!pick) return;
      chosen += 1;
      var item = document.createElement('li'), title = document.createElement('b');
      title.textContent = row.dataset.title + ': ' + pick.closest('label').querySelector('[data-option-title]').textContent;
      item.appendChild(title);
      var note = row.querySelector('textarea').value.trim();
      if (note) { var text = document.createElement('p'); text.textContent = note; item.appendChild(text); }
      list.appendChild(item);
    });
    summary.hidden = chosen === 0;
    status.textContent = '주제 선택 ' + chosen + '/' + rows.length + '개 · 미저장 변경 ' + modified + '개';
  }
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  form.addEventListener('submit', function (event) {
    if (submitting) { event.preventDefault(); return; }
    submitting = true;
    save.disabled = true;
    save.textContent = '선택·의견 저장 중…';
    form.setAttribute('aria-busy', 'true');
  });
  window.addEventListener('beforeunload', function (event) {
    if (!submitting && dirty()) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pageshow', function () {
    submitting = false;
    save.disabled = false;
    save.textContent = '선택·의견 한 번에 저장';
    form.removeAttribute('aria-busy');
    update();
  });
  update();
  var error = form.querySelector('.mr-error');
  if (error) { error.tabIndex = -1; error.focus(); }
})();
