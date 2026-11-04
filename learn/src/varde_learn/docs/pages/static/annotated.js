// annotated-code: the page is complete without this script (pins and notes link by href,
// quiet stretches fold in native <details>). This adds the Copy button on the code, a
// highlight of a note's lines while its note or pin is hovered or focused, focus that
// follows a pin or note link, and opens every fold for printing.
import { enhanceCode } from './code.js';

function setActive(block, note, on) {
  const from = Number(note.dataset.from);
  const to = Number(note.dataset.to);
  for (const line of block.querySelectorAll('.vd-code-line')) {
    const n = Number(line.dataset.line);
    if (on && n >= from && n <= to) line.setAttribute('data-active', '1');
    else line.removeAttribute('data-active');
  }
}

function followLinks(block) {
  block.addEventListener('click', (event) => {
    const link = event.target.closest('.vd-annotated-pin, .vd-annotated-back');
    if (!link || !block.contains(link)) return;
    const target = block.querySelector(link.getAttribute('href'));
    if (target) setTimeout(() => target.focus({ preventScroll: true }), 0);
  });
}

function highlightOnNote(block) {
  const notes = [...block.querySelectorAll('.vd-annotated-note')];
  const byNumber = new Map(notes.map((note) => [note.id.split('-').pop(), note]));
  const watch = (element, note) => {
    for (const [on, type] of [[true, 'mouseenter'], [true, 'focus'], [false, 'mouseleave'], [false, 'blur']]) {
      element.addEventListener(type, () => setActive(block, note, on));
    }
  };
  for (const note of notes) watch(note, note);
  for (const pin of block.querySelectorAll('.vd-annotated-pin')) {
    watch(pin, byNumber.get(pin.id.split('-').pop()));
  }
}

function openFoldsForPrint(block) {
  let reopened = [];
  window.addEventListener('beforeprint', () => {
    reopened = [...block.querySelectorAll('details.vd-annotated-fold:not([open])')];
    for (const fold of reopened) fold.open = true;
  });
  window.addEventListener('afterprint', () => {
    for (const fold of reopened) fold.open = false;
    reopened = [];
  });
}

export function enhanceAnnotated(block) {
  if (!block.classList.contains('vd-annotated-code')) return;
  const panel = block.querySelector('.vd-code');
  if (panel) enhanceCode(panel);
  highlightOnNote(block);
  followLinks(block);
  openFoldsForPrint(block);
}
