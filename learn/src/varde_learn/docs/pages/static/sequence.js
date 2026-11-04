// sequence: the block is complete without this script (drawing, ordered step list). This adds
// a link between the two: hovering a drawing row or a list item, or focusing an item, marks
// its row, arrow and item, and says the step in an aria-live readout. Arrow keys move
// between items (Home and End jump), Escape clears. Hooks are `data-step`; only classes change.

export function enhanceSequence(block) {
  if (!block.classList.contains('vd-sequence')) return;
  const items = [...block.querySelectorAll('li[data-step]')];
  if (!items.length) return;
  const readout = document.createElement('p');
  readout.className = 'vd-sequence-readout';
  readout.setAttribute('aria-live', 'polite');
  block.querySelector('.vd-sequence-steps').before(readout);
  let current = '';
  function mark(step) {
    if (step === current) return;
    current = step;
    for (const node of block.querySelectorAll('[data-step]')) {
      node.classList.toggle('vd-sequence-on', node.dataset.step === step);
    }
    const item = items.find((li) => li.dataset.step === step);
    readout.textContent = item ? `Step ${Number(step) + 1} of ${items.length}: ${item.textContent}` : '';
  }
  function roving(active) {
    items.forEach((li) => { li.tabIndex = li === active ? 0 : -1; });
  }
  roving(items[0]);
  for (const node of block.querySelectorAll('[data-step]')) {
    node.addEventListener('pointerenter', () => mark(node.dataset.step));
    node.addEventListener('pointerleave', () => mark(''));
  }
  for (const li of items) {
    li.addEventListener('focusin', () => { roving(li); mark(li.dataset.step); });
    li.addEventListener('focusout', () => mark(''));
  }
  const MOVES = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
  block.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { mark(''); return; }
    const li = event.target.closest?.('li[data-step]');
    if (!li) return;
    const here = items.indexOf(li);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : here + (MOVES[event.key] ?? 0);
    if (!(event.key in MOVES) && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    items[Math.min(Math.max(next, 0), items.length - 1)].focus();
  });
}
