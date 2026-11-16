/* Workspace shell. Simulation facts and playback belong to DAYAN_RESULTS. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  let toastTimer, previousFocus;
  function notice(text) {
    $('#toast').textContent = text;
    $('#toast').classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 3800);
  }
  function openModal(title, html) {
    previousFocus = document.activeElement;
    $('#modalTitle').textContent = title;
    $('#modalBody').innerHTML = html;
    $('#modalBackdrop').classList.add('open');
    $('#closeModal').focus();
  }
  function closeModal() {
    $('#modalBackdrop').classList.remove('open');
    if (previousFocus?.isConnected) previousFocus.focus();
  }
  window.DAYAN_MODAL = openModal;
  window.DAYAN_CLOSE_MODAL = closeModal;
  window.DAYAN_NOTICE = notice;
  window.DAYAN_EVENT = (type, title, description) => window.DAYAN_RESULTS?.addEvent(type, title, description);
  window.drawDashComparison = () => window.DAYAN_RESULTS?.paint();
  window.DAYAN_DASH = () => window.DAYAN_RESULTS?.paint();
  $('#closeModal').addEventListener('click', closeModal);
  $('#modalBackdrop').addEventListener('click', event => {
    if (event.target === $('#modalBackdrop')) closeModal();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeModal();
    if (event.key !== 'Tab' || !$('#modalBackdrop').classList.contains('open')) return;
    const controls = [...$('.modal').querySelectorAll('button,input,select,textarea,a[href],summary')].filter(element => !element.disabled && element.checkVisibility());
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
  $('#fullscreen').addEventListener('click', async () => {
    try { if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen(); }
    catch { notice('当前浏览器无法进入全屏。'); }
  });
  $('#modelButton').addEventListener('click', () => window.switchPage?.('models'));
  document.addEventListener('visibilitychange', () => { if (window.DAYAN_RESULTS) window.DAYAN_RESULTS.lastWall = null; });
  function frame(time) { window.DAYAN_RESULTS?.tick(time); requestAnimationFrame(frame); }
  requestAnimationFrame(frame);
})();
