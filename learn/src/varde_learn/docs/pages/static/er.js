// er: the data-model graph layout is complete without this script (drawing, relation
// list, cards). This adds highlighting: hovering a card or box, or focusing inside a card,
// marks that entity's relations in the drawing and the list. Hooks are `data-entity`
// (one entity) and `data-ends` ("source target"); only classes change, never `style`.

function related(block, entity) {
  const near = new Set([entity]);
  for (const node of block.querySelectorAll('[data-ends]')) {
    const ends = node.dataset.ends.split(' ');
    if (ends.includes(entity)) ends.forEach((end) => near.add(end));
  }
  return near;
}

export function enhanceEr(block) {
  if (!block.classList.contains('vd-er')) return;
  let current = '';
  function mark(entity) {
    if (entity === current) return;
    current = entity;
    const near = entity ? related(block, entity) : new Set();
    block.classList.toggle('vd-er-active', Boolean(entity));
    for (const node of block.querySelectorAll('[data-entity]')) {
      node.classList.toggle('vd-er-on', node.dataset.entity === entity);
      node.classList.toggle('vd-er-near', node.dataset.entity !== entity && near.has(node.dataset.entity));
    }
    for (const node of block.querySelectorAll('[data-ends]')) {
      node.classList.toggle('vd-er-hot', Boolean(entity) && node.dataset.ends.split(' ').includes(entity));
    }
  }
  for (const node of block.querySelectorAll('[data-entity]')) {
    const entity = node.dataset.entity;
    node.addEventListener('pointerenter', () => mark(entity));
    node.addEventListener('pointerleave', () => mark(''));
    // Focus listeners only on HTML cards: Chromium makes an SVG element with focus listeners focusable.
    if (node instanceof SVGElement) continue;
    node.addEventListener('focusin', () => mark(entity));
    node.addEventListener('focusout', (event) => {
      if (!node.contains(event.relatedTarget)) mark('');
    });
  }
}
