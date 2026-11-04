// Pan and zoom for any SVG inside a frame: mountViewport(frame, svg, {minScale, maxScale}).
// Pointer pan, Ctrl+wheel zoom, two-pointer pinch, +, - and Reset buttons, arrow,
// plus, minus and 0 keys on the focused frame. touch-action keeps one-finger page scroll.
import { control, make } from './dom.js';

const KEY_STEP = 24;
const BUTTON_IN = 1.25;
const BUTTON_OUT = 0.8;
const WHEEL_STEP = 1.2;
const DRAG_THRESHOLD = 4;

function readViewBox(svg) {
  const [x, y, w, h] = svg.getAttribute('viewBox').split(/\s+/).map(Number);
  return { x, y, w, h };
}

function motionFor(svg, home, limits) {
  const view = Object.assign({}, home);
  const apply = () => svg.setAttribute('viewBox', [view.x, view.y, view.w, view.h].join(' '));
  function zoom(factor, cx, cy) {
    const scale = Math.min(limits.max, Math.max(limits.min, home.w / view.w * factor));
    const w = home.w / scale;
    const h = home.h / scale;
    const fx = cx === undefined ? 0.5 : (cx - view.x) / view.w;
    const fy = cy === undefined ? 0.5 : (cy - view.y) / view.h;
    view.x += (view.w - w) * fx;
    view.y += (view.h - h) * fy;
    view.w = w;
    view.h = h;
    apply();
  }
  function pan(dx, dy) {
    view.x -= dx;
    view.y -= dy;
    apply();
  }
  function reset() {
    Object.assign(view, home);
    apply();
  }
  return { zoom, pan, reset, view };
}

function toView(svg, motion, clientX, clientY) {
  const box = svg.getBoundingClientRect();
  return {
    x: motion.view.x + (clientX - box.left) / (box.width || 1) * motion.view.w,
    y: motion.view.y + (clientY - box.top) / (box.height || 1) * motion.view.h,
  };
}

function bindPointer(svg, motion) {
  const touches = new Map();
  let drag = null;
  let pinchFrom = 0;
  const spread = () => {
    const [a, b] = Array.from(touches.values());
    return Math.hypot(a.x - b.x, a.y - b.y) || 1;
  };
  svg.addEventListener('pointerdown', (event) => {
    touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
    drag = { x: event.clientX, y: event.clientY, moved: touches.size > 1 };
    if (touches.size === 2) pinchFrom = spread();
  });
  svg.addEventListener('pointermove', (event) => {
    if (touches.has(event.pointerId)) touches.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (touches.size === 2) {
      const now = spread();
      const [a, b] = Array.from(touches.values());
      const mid = toView(svg, motion, (a.x + b.x) / 2, (a.y + b.y) / 2);
      motion.zoom(now / pinchFrom, mid.x, mid.y);
      pinchFrom = now;
      drag.moved = true;
      return;
    }
    if (!drag || !(event.buttons & 1)) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (!drag.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD) return;
    drag.moved = true;
    const unit = motion.view.w / (svg.getBoundingClientRect().width || 1);
    motion.pan(dx * unit, dy * unit);
    drag.x = event.clientX;
    drag.y = event.clientY;
  });
  const end = (event) => {
    touches.delete(event.pointerId);
    if (touches.size === 1 && drag) {
      const [rest] = Array.from(touches.values());
      drag.x = rest.x;
      drag.y = rest.y;
    }
    if (touches.size > 0) return;
    setTimeout(() => { drag = null; }, 0);
  };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
  svg.addEventListener('click', (event) => {
    if (drag && drag.moved) event.stopPropagation();
  }, true);
  svg.addEventListener('wheel', (event) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    const at = toView(svg, motion, event.clientX, event.clientY);
    motion.zoom(event.deltaY < 0 ? WHEEL_STEP : 1 / WHEEL_STEP, at.x, at.y);
  }, { passive: false });
}

function bindKeys(frame, motion) {
  frame.addEventListener('keydown', (event) => {
    if (event.target !== frame) return;
    const keys = {
      ArrowLeft: () => motion.pan(KEY_STEP, 0), ArrowRight: () => motion.pan(-KEY_STEP, 0),
      ArrowUp: () => motion.pan(0, KEY_STEP), ArrowDown: () => motion.pan(0, -KEY_STEP),
      '+': () => motion.zoom(BUTTON_IN), '=': () => motion.zoom(BUTTON_IN),
      '-': () => motion.zoom(BUTTON_OUT), '0': motion.reset,
    };
    if (!keys[event.key]) return;
    event.preventDefault();
    keys[event.key]();
  });
}

// The frame must already be in the document: the control bar goes just before it.
export function mountViewport(frame, svg, options) {
  const limits = { min: 0.25, max: 8 };
  if (options && options.minScale !== undefined) limits.min = options.minScale;
  if (options && options.maxScale !== undefined) limits.max = options.maxScale;
  const motion = motionFor(svg, readViewBox(svg), limits);
  const bar = make('div', 'vb-flowbar');
  bar.append(
    control('+', () => motion.zoom(BUTTON_IN), 'vb-ctl', 'Zoom in'),
    control('−', () => motion.zoom(BUTTON_OUT), 'vb-ctl', 'Zoom out'),
    control('Reset', motion.reset, 'vb-ctl', 'Reset view'),
  );
  svg.style.touchAction = 'pan-x pan-y';
  bindPointer(svg, motion);
  bindKeys(frame, motion);
  frame.before(bar);
  return Object.assign({ bar }, motion);
}
