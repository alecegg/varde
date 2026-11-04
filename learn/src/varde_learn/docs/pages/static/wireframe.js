// wireframe: enhance the server-drawn SVG frames of a `wireframe` block. Pan and zoom
// come from viewport.js (one shared bar: + - Fit); double-tap or double-click fits.
// Regions are the controls: select one (click, tap, Enter, Space) and an announced panel
// reads its kind and notes while its notes-list entries get a heavy edge. Arrow keys
// move between regions in reading order, Home and End jump, Escape clears.
// No layout runs in the browser.
import { control, make, keepInside } from './dom.js';
import { mountViewport } from './viewport.js';

const HINT = 'Select a region to read its notes.';
const MIN_FIT = 0.5;
const SCROLLBAR = 18;
const ZOOM_IN = 1.25;
const ZOOM_OUT = 0.8;
const TAP_MS = 350;
const TAP_PX = 30;
const ROLE = / vw-(sel|hot)/g;
const STEP = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };

function labelOf(region) {
  const title = region.querySelector('title');
  return title ? title.textContent : region.dataset.region;
}

function setRole(node, role) {
  node.setAttribute('class', node.getAttribute('class').replace(ROLE, '') + role);
}

// Size the svg to the width: never above 1:1, never below `floor` (a scale).
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

// Two taps close together fit the view; pinches and drags never count as taps.
function bindDoubleTap(svg, fit) {
  let last = null;
  let multi = false;
  let down = 0;
  svg.addEventListener('dblclick', (event) => { event.preventDefault(); fit(); });
  svg.addEventListener('pointerdown', (event) => {
    down += 1;
    if (down > 1) multi = true;
    svg.dataset.tapX = String(event.clientX);
    svg.dataset.tapY = String(event.clientY);
  });
  svg.addEventListener('pointercancel', () => { down = 0; multi = false; });
  svg.addEventListener('pointerup', (event) => {
    down = Math.max(0, down - 1);
    const clean = !multi;
    if (down === 0) multi = false;
    if (event.pointerType !== 'touch' || !clean) return;
    const moved = Math.hypot(event.clientX - Number(svg.dataset.tapX), event.clientY - Number(svg.dataset.tapY));
    if (moved > TAP_PX) { last = null; return; }
    const again = last && event.timeStamp - last.t < TAP_MS && Math.hypot(event.clientX - last.x, event.clientY - last.y) < TAP_PX;
    last = again ? null : { t: event.timeStamp, x: event.clientX, y: event.clientY };
    if (again) fit();
  });
}

function readFrame(fig, index) {
  const view = fig.querySelector('.vw-view');
  const svg = view && view.querySelector('svg');
  if (!svg) return null;
  const regions = Array.from(svg.querySelectorAll('.vw-region'));
  const notes = Array.from(fig.querySelectorAll('.vw-note'));
  const caption = fig.querySelector('figcaption');
  return { index, view, svg, regions, notes, caption: caption ? caption.textContent : '' };
}

function noteText(note) {
  const label = note.querySelector('strong');
  return note.textContent.slice(label ? label.textContent.length + 2 : 0);
}

function describe(frame, region) {
  const found = frame.notes.filter((note) => note.dataset.region === region.dataset.region);
  const said = found.length
    ? found.map((note) => 'Note ' + note.value + ': ' + noteText(note) + '.').join(' ')
    : 'No notes.';
  const prefix = frame.caption ? frame.caption + ': ' : '';
  return prefix + labelOf(region) + '. ' + said;
}

export function enhanceWireframe(block) {
  if (!block.classList.contains('wireframe')) return;
  const host = block.querySelector('.vw-frames');
  if (!host) return;
  const frames = Array.from(host.querySelectorAll('.vw-fig')).map(readFrame).filter(Boolean);
  if (!frames.length) return;
  const readout = make('p', 'vw-detail', HINT);
  readout.setAttribute('role', 'status');
  readout.setAttribute('aria-live', 'polite');
  host.after(readout);
  const state = { selected: null, hover: null, focus: null };

  function paint() {
    const chosen = state.hover || state.focus || state.selected;
    for (const frame of frames) {
      for (const region of frame.regions) {
        const key = frame.index + ':' + region.dataset.region;
        const role = key === state.selected ? ' vw-sel' : key === chosen ? ' vw-hot' : '';
        setRole(region, role);
        region.setAttribute('aria-pressed', String(key === state.selected));
      }
      for (const note of frame.notes) {
        const on = state.selected === frame.index + ':' + note.dataset.region;
        note.classList.toggle('vw-note-on', on);
      }
    }
  }

  function select(frame, region) {
    const key = frame.index + ':' + region.dataset.region;
    state.selected = state.selected === key ? null : key;
    readout.textContent = state.selected ? describe(frame, region) : HINT;
    paint();
  }

  function clear() {
    state.selected = null;
    readout.textContent = HINT;
    paint();
  }

  function move(frame, region, key) {
    const list = frame.regions;
    const at = list.indexOf(region);
    let next = at + (STEP[key] || 0);
    if (key === 'Home') next = 0;
    if (key === 'End') next = list.length - 1;
    list[(next + list.length) % list.length].focus();
  }

  const viewports = frames.map((frame) => {
    const { view, svg, regions } = frame;
    svg.setAttribute('role', 'group');
    view.setAttribute('aria-label', labelOf(svg) + ' (arrow keys pan, plus and minus zoom, 0 fits to view)');
    for (const region of regions) {
      region.setAttribute('role', 'button');
      region.setAttribute('tabindex', '-1');
      region.setAttribute('aria-pressed', 'false');
      region.setAttribute('aria-label', labelOf(region) + ', region');
    }
    if (regions[0]) regions[0].setAttribute('tabindex', '0');
    const viewport = mountViewport(view, svg, { minScale: 0.25, maxScale: 8 });
    viewport.bar.remove(); // one bar above the frames acts on every view
    view.addEventListener('focusin', (event) => {
      const target = event.target.closest('.vw-region');
      if (!target) return;
      for (const other of regions) other.setAttribute('tabindex', other === target ? '0' : '-1');
      keepInside(view, target, { margin: 8 });
      state.focus = frame.index + ':' + target.dataset.region;
      paint();
    });
    view.addEventListener('focusout', () => { state.focus = null; paint(); });
    view.addEventListener('pointerover', (event) => {
      const target = event.target.closest('.vw-region');
      state.hover = target ? frame.index + ':' + target.dataset.region : null;
      paint();
    });
    view.addEventListener('pointerleave', () => { state.hover = null; paint(); });
    view.addEventListener('click', (event) => {
      const target = event.target.closest('.vw-region');
      if (target) select(frame, target);
    });
    view.addEventListener('keydown', (event) => {
      const target = event.target.closest('.vw-region');
      if (!target || event.target !== target) return;
      const activate = event.key === 'Enter' || event.key === ' ';
      const moves = STEP[event.key] || event.key === 'Home' || event.key === 'End';
      if (!activate && !moves && event.key !== 'Escape') return;
      event.preventDefault();
      if (event.key === 'Escape') clear();
      else if (activate) select(frame, target);
      else move(frame, target, event.key);
    });
    return viewport;
  });

  function fit() {
    for (const [i, frame] of frames.entries()) {
      fitWidth(frame.svg, frame.view.clientWidth - SCROLLBAR, MIN_FIT);
      viewports[i].reset();
      frame.view.scrollTo(0, 0);
    }
  }

  for (const frame of frames) bindDoubleTap(frame.svg, fit);
  const bar = make('div', 'vb-controls vb-flowbar');
  bar.append(
    control('+', () => viewports.forEach((v) => v.zoom(ZOOM_IN)), 'vb-ctl', 'Zoom in'),
    control('−', () => viewports.forEach((v) => v.zoom(ZOOM_OUT)), 'vb-ctl', 'Zoom out'),
    control('Fit', fit, 'vb-ctl', 'Fit whole wireframe'),
  );
  host.before(bar);
}
