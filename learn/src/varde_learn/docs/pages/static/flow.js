// flow: enhance the server-laid-out SVG of a `flow` block. Pan and zoom come from
// viewport.js (its Reset button becomes the one shared Fit button). Selecting a step
// highlights what must come before it (dotted outline) and what follows (heavy
// outline) and says so in the readout; arrow keys on a step follow its edges.
// No layout runs in the browser.
import { control, make, keepInside } from './dom.js';
import { mountViewport } from './viewport.js';

const HINT = 'Select a step to see what comes before and after it.';
const FOLLOW = { ArrowRight: 'out', ArrowDown: 'out', ArrowLeft: 'in', ArrowUp: 'in' };
const MIN_FIT = 0.25; // the whole flow fits the width down to the viewport's own minimum zoom
const SCROLLBAR = 18;
const ZOOM_IN = 1.25;
const ZOOM_OUT = 0.8;
const ROLE = / vd-(sel|dim)| vf-(up|down)/g;

function readEdges(view) {
  const out = new Map();
  const into = new Map();
  for (const edge of view.querySelectorAll('.vd-edge')) {
    const { from, to } = edge.dataset;
    if (!out.has(from)) out.set(from, []);
    if (!into.has(to)) into.set(to, []);
    out.get(from).push(to);
    into.get(to).push(from);
  }
  return { out, into };
}

function reachable(start, edges) {
  const seen = new Set();
  const queue = [start];
  while (queue.length) {
    for (const id of edges.get(queue.shift()) || []) {
      if (seen.has(id)) continue;
      seen.add(id);
      queue.push(id);
    }
  }
  seen.delete(start);
  return seen;
}

function labelOf(node) {
  const title = node.querySelector('title');
  return title ? title.textContent : node.dataset.id;
}

function naming(ids, byId) {
  return ids.length ? ids.map((id) => labelOf(byId.get(id))).join(', ') : 'none';
}

// Size the svg to the width, never above 1:1 and never below `floor` (a scale).
function fitWidth(svg, available, floor) {
  if (!svg.dataset.natW) {
    svg.dataset.natW = svg.getAttribute('width');
    svg.dataset.natH = svg.getAttribute('height');
  }
  const natW = Number(svg.dataset.natW);
  const natH = Number(svg.dataset.natH);
  const scale = Math.min(1, Math.max(floor, available / natW));
  svg.setAttribute('width', String(Math.round(natW * scale)));
  svg.setAttribute('height', String(Math.round(natH * scale)));
}

function setRole(node, role) {
  node.setAttribute('class', node.getAttribute('class').replace(ROLE, '') + role);
}

export function enhanceFlow(block) {
  if (!block.classList.contains('flow')) return;
  const view = block.querySelector('.vd-view');
  const host = block.querySelector('.vd-views');
  const svg = view && view.querySelector('svg');
  if (!svg || !host) return;
  const nodes = Array.from(view.querySelectorAll('.vd-node'));
  const byId = new Map(nodes.map((n) => [n.dataset.id, n]));
  const { out, into } = readEdges(view);
  const readout = make('p', 'vd-detail', HINT);
  readout.setAttribute('role', 'status');
  readout.setAttribute('aria-live', 'polite');
  host.after(readout);
  const state = { selected: null, hover: null, focus: null };
  const cycle = new Map();

  function paint() {
    const id = state.hover || state.focus || state.selected;
    const before = id ? reachable(id, into) : new Set();
    const after = id ? reachable(id, out) : new Set();
    for (const [name, node] of byId) {
      const role = !id ? '' : name === id ? ' vd-sel' : before.has(name) ? ' vf-up' : after.has(name) ? ' vf-down' : ' vd-dim';
      setRole(node, role);
      node.setAttribute('aria-pressed', String(name === state.selected));
    }
    const upSet = new Set([...before, id]);
    const downSet = new Set([...after, id]);
    for (const edge of view.querySelectorAll('.vd-edge')) {
      const { from, to } = edge.dataset;
      const hot = id && ((upSet.has(from) && upSet.has(to)) || (downSet.has(from) && downSet.has(to)));
      const base = edge.getAttribute('class').replace(/ vd-(hot|dim)/g, '');
      edge.setAttribute('class', base + (!id ? '' : hot ? ' vd-hot' : ' vd-dim'));
    }
  }

  function describe(id) {
    const before = reachable(id, into);
    const after = reachable(id, out);
    return labelOf(byId.get(id)) + '. Before it: ' + naming([...before], byId) + '. After it: ' + naming([...after], byId) + '.';
  }

  function select(node) {
    const id = node.dataset.id;
    state.selected = state.selected === id ? null : id;
    readout.textContent = state.selected ? describe(id) : HINT;
    paint();
  }

  function follow(node, direction) {
    const ids = (direction === 'out' ? out : into).get(node.dataset.id) || [];
    if (!ids.length) return;
    const key = direction + node.dataset.id;
    const count = cycle.get(key) || 0;
    cycle.set(key, count + 1);
    byId.get(ids[count % ids.length]).focus();
  }

  function refit() {
    fitWidth(svg, host.clientWidth - SCROLLBAR, MIN_FIT);
  }

  svg.setAttribute('role', 'group');
  view.tabIndex = 0;
  view.setAttribute('role', 'region');
  view.setAttribute('aria-label', 'Flow: arrow keys pan, plus and minus zoom, 0 fits to view');
  for (const node of nodes) {
    node.setAttribute('role', 'button');
    node.setAttribute('tabindex', '-1');
    node.setAttribute('aria-pressed', 'false');
    node.setAttribute('aria-label', labelOf(node) + ', step');
  }
  if (nodes[0]) nodes[0].setAttribute('tabindex', '0');
  const viewport = mountViewport(view, svg, { minScale: 0.25, maxScale: 8 });
  viewport.bar.remove(); // one bar below acts on the view

  view.addEventListener('focusin', (event) => {
    const target = event.target.closest('.vd-node');
    if (!target) return;
    for (const other of view.querySelectorAll('[tabindex="0"]')) if (other !== view) other.setAttribute('tabindex', '-1');
    target.setAttribute('tabindex', '0');
    keepInside(view, target);
    state.focus = target.dataset.id;
    paint();
  });
  view.addEventListener('focusout', () => { state.focus = null; paint(); });
  view.addEventListener('pointerover', (event) => {
    const node = event.target.closest('.vd-node');
    state.hover = node ? node.dataset.id : null;
    paint();
  });
  view.addEventListener('pointerleave', () => { state.hover = null; paint(); });
  view.addEventListener('click', (event) => {
    const node = event.target.closest('.vd-node');
    if (node) select(node);
  });
  view.addEventListener('keydown', (event) => {
    const node = event.target.closest('.vd-node');
    if (!node || event.target !== node) return;
    const activate = event.key === 'Enter' || event.key === ' ';
    const direction = FOLLOW[event.key];
    if (!activate && !direction && event.key !== 'Escape') return;
    event.preventDefault();
    if (event.key === 'Escape') {
      state.selected = null;
      readout.textContent = HINT;
      paint();
    } else if (activate) {
      select(node);
    } else {
      follow(node, direction);
    }
  });

  const bar = make('div', 'vb-controls vb-flowbar');
  bar.append(
    control('+', () => viewport.zoom(ZOOM_IN), 'vb-ctl', 'Zoom in'),
    control('−', () => viewport.zoom(ZOOM_OUT), 'vb-ctl', 'Zoom out'),
    control('Fit', () => { refit(); viewport.reset(); view.scrollTo(0, 0); }, 'vb-ctl', 'Fit whole flow'),
  );
  host.before(bar);
  refit();
  window.addEventListener('resize', refit);
}
