// chart: tooltip, live readout, legend toggles and keyboard reading over the server SVG.
// The SVG and the data table are complete without this script; hooks are the
// `data-series` / `data-index` attributes and classes (vb-on lit, vb-off hidden).
import { make, svgNode } from './dom.js';

const OFF = 'vb-off';
const ON = 'vb-on';
const START = 'Hover, focus or tap a point.';
const PAD = 8;
const LINE = 19;
const LIMIT = 28;

const clip = (text) => (text.length > LIMIT ? `${text.slice(0, LIMIT - 1)}…` : text);
const live = (mark) => !mark.classList.contains(OFF);

// "series / label / value" from a mark's aria-label.
const parts = (mark) => (mark.getAttribute('aria-label') || '').split(' / ');

function columnLines(group) {
  if (!group.length) return ['No series shown.'];
  const label = parts(group[0])[1] || '';
  return [label, ...group.map((mark) => `${parts(mark)[0]}: ${parts(mark)[2]}`)];
}

function pointLines(mark) {
  const [name, label, value] = parts(mark);
  return [name, `${label}: ${value}`];
}

export function enhanceChart(block) {
  const svg = block.querySelector('svg.vb-chart');
  const plot = block.querySelector('.vb-plot');
  if (!svg || !plot) return;
  const title = svg.getAttribute('aria-label') || 'Chart';
  const marks = Array.from(svg.querySelectorAll('.vb-mark'));
  const columns = Array.from(svg.querySelectorAll('.vb-col'));
  const perIndex = new Map();
  for (const mark of marks) {
    const key = mark.dataset.index;
    perIndex.set(key, [...(perIndex.get(key) || []), mark]);
  }
  const byColumn = columns.length > 0;
  const readout = make('p', 'vb-readout', START);
  readout.setAttribute('aria-live', 'polite');
  plot.after(readout);
  plot.setAttribute('role', 'region');
  plot.setAttribute('tabindex', '0');
  plot.setAttribute('aria-label', `${title} (arrow keys read values)`);

  const box = svgNode('rect', {}, 'vb-tip-box');
  const label = svgNode('text', {}, 'vb-tip-text');
  const tip = svgNode('g', { 'aria-hidden': 'true' }, 'vb-tip');
  tip.append(box, label);
  let lit = [];
  let cursor = -1;

  const groups = () => (byColumn
    ? columns.map((col) => (perIndex.get(col.dataset.index) || []).filter(live))
    : marks.filter(live).map((mark) => [mark]));

  function unlight() {
    for (const mark of lit) mark.classList.remove(ON);
    lit = [];
    tip.remove();
  }

  function place(group, lines) {
    label.replaceChildren(...lines.map((text, n) => {
      const row = svgNode('tspan', { x: PAD, y: PAD + LINE * (n + 1) - 5 });
      row.textContent = clip(text);
      return row;
    }));
    svg.append(tip);
    const text = label.getBBox();
    const width = text.width + PAD * 2;
    const height = text.height + PAD * 2;
    box.setAttribute('width', width);
    box.setAttribute('height', height);
    const view = svg.viewBox.baseVal;
    const spots = group.map((mark) => mark.getBBox());
    if (!spots.length) return;
    const left = Math.min(...spots.map((s) => s.x));
    const right = Math.max(...spots.map((s) => s.x + s.width));
    const top = Math.min(...spots.map((s) => s.y));
    const bottom = Math.max(...spots.map((s) => s.y + s.height));
    const room = (right + 10 + width <= view.width - 2);
    const x = Math.max(2, Math.min(room ? right + 10 : left - 10 - width, view.width - width - 2));
    const above = top - height - 8;
    const y = Math.max(2, Math.min(above >= 2 ? above : bottom + 8, view.height - height - 2));
    tip.setAttribute('transform', `translate(${x.toFixed(1)} ${y.toFixed(1)})`);
  }

  function show(index) {
    const list = groups();
    if (!list.length) return;
    unlight();
    cursor = Math.max(0, Math.min(index, list.length - 1));
    const group = list[cursor];
    lit = group;
    for (const mark of group) mark.classList.add(ON);
    const lines = byColumn ? columnLines(group) : pointLines(group[0]);
    readout.textContent = byColumn
      ? `${lines[0]}: ${lines.slice(1).join('; ')}`
      : parts(group[0]).join(' / ');
    place(group, lines);
  }

  function clear() {
    unlight();
    cursor = -1;
    readout.textContent = START;
  }

  // Events: pins and lines in the SVG, and the Events list whose items become buttons.
  const shapesOf = (n) => Array.from(svg.querySelectorAll(`[data-event="${n}"]`));

  function showEvent(item) {
    unlight();
    cursor = -1;
    const group = shapesOf(item.dataset.event);
    lit = group;
    for (const node of group) node.classList.add(ON);
    const { event: n, kind, where, tone } = item.dataset;
    const label = item.querySelector('.vb-ev-label')?.textContent || '';
    readout.textContent = `Event ${n} / ${label} / ${kind}, ${where}, ${tone}`;
    const lines = [label, where, `${kind}, ${tone}`];
    place(group, lines);
  }

  const eventOf = (target) => target.closest('[data-event]');
  const pick = (event) => {
    const hit = eventOf(event.target);
    if (hit) showEvent(block.querySelector(`.vb-events li[data-event="${hit.dataset.event}"]`));
  };
  svg.addEventListener('pointerover', pick);
  svg.addEventListener('click', pick);
  for (const item of block.querySelectorAll('.vb-events li[data-event]')) {
    const button = make('button', 'vb-ev-btn');
    button.type = 'button';
    button.append(...item.childNodes);
    item.append(button);
    const lightItem = (on) => item.classList.toggle(ON, on);
    button.addEventListener('focus', () => { lightItem(true); showEvent(item); });
    button.addEventListener('blur', () => { lightItem(false); unlight(); });
    button.addEventListener('pointerenter', () => showEvent(item));
    button.addEventListener('pointerleave', (event) => {
      if (event.pointerType === 'mouse' && document.activeElement !== button) unlight();
    });
    button.addEventListener('click', () => showEvent(item));
    button.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') clear();
    });
  }

  function indexOf(target) {
    const hit = target.closest('.vb-mark, .vb-col');
    if (!hit) return -1;
    if (byColumn) return Number(hit.dataset.index);
    return groups().findIndex((group) => group[0] === hit.closest('.vb-mark'));
  }

  const point = (event) => {
    const index = indexOf(event.target);
    if (index >= 0) show(index);
  };
  svg.addEventListener('pointerover', point);
  svg.addEventListener('click', point);
  svg.addEventListener('pointerleave', (event) => {
    if (event.pointerType === 'mouse') unlight();
  });

  plot.addEventListener('focus', () => {
    if (plot.matches(':focus-visible') && cursor < 0) show(0);
  });
  plot.addEventListener('keydown', (event) => {
    const last = groups().length - 1;
    const moves = {
      ArrowRight: cursor + 1, ArrowDown: cursor + 1, ArrowLeft: cursor - 1, ArrowUp: cursor - 1,
      Home: 0, End: last,
    };
    if (event.key === 'Escape') {
      clear();
      return;
    }
    if (!(event.key in moves) || last < 0) return;
    event.preventDefault();
    show(moves[event.key]);
  });

  for (const item of block.querySelectorAll('.vb-legend li[data-series]')) {
    const button = make('button', 'vb-series-toggle');
    button.type = 'button';
    button.setAttribute('aria-pressed', 'true');
    button.append(...item.childNodes);
    item.append(button);
    button.addEventListener('click', () => {
      const hide = button.getAttribute('aria-pressed') === 'true';
      button.setAttribute('aria-pressed', hide ? 'false' : 'true');
      for (const node of block.querySelectorAll(`[data-series="${item.dataset.series}"]`)) {
        if (!node.closest('.vb-legend')) node.classList.toggle(OFF, hide);
      }
      if (cursor >= 0) show(cursor);
    });
  }
}

// Print shows the data table too: open every closed one for the print, then restore.
let reopened = [];
window.addEventListener('beforeprint', () => {
  reopened = Array.from(document.querySelectorAll('.chart details.vb-data:not([open])'));
  for (const details of reopened) details.open = true;
});
window.addEventListener('afterprint', () => {
  for (const details of reopened) details.open = false;
  reopened = [];
});
