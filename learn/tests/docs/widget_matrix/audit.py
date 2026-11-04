"""Test-side DOM audit: plain JS strings run with `page.evaluate`.

`COLLECT_JS` takes a scope `{inside, outside}` (a CSS selector the element must
be inside, or one it must be outside) and returns the snapshot that
`checks.run_checks` reads. `FIRST_FOCUS_JS` and `FOCUS_JS` drive the tab walk.
The JS only measures; every pass or fail decision is Python in `checks.py`.
"""

SHARED_JS = r"""
const CONTROL_SEL = 'a[href], button, input:not([type=hidden]), select, textarea, summary, ' +
  '[role=button], [role=slider], [role=checkbox], [role=radio], [role=tab], ' +
  '[role=menuitem], [role=switch], [role=link], [tabindex]:not([tabindex="-1"])';
const inScope = (el, scope) => scope.inside ? !!el.closest(scope.inside) : !el.closest(scope.outside);
const rectOf = (el) => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; };
const visible = (el) => {
  const cs = getComputedStyle(el), r = el.getBoundingClientRect();
  return cs.visibility !== 'hidden' && cs.display !== 'none' && (r.width > 0 && r.height > 0);
};
const pathOf = (el) => {
  const parts = [];
  for (let n = el; n && n.nodeType === 1 && parts.length < 4; n = n.parentElement) {
    let part = n.tagName.toLowerCase();
    if (n.id) { parts.push(part + '#' + n.id); break; }
    if (n.classList.length) part += '.' + [...n.classList].slice(0, 2).join('.');
    parts.push(part);
  }
  return parts.reverse().join(' > ');
};
const bgLayers = (el) => {
  const layers = []; let hidden = false;
  for (let n = el; n; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (cs.backgroundImage !== 'none') hidden = true;
    if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent') layers.push(cs.backgroundColor);
  }
  return {layers, hidden};
};
const opacityOf = (el) => { let o = 1; for (let n = el; n; n = n.parentElement) o *= parseFloat(getComputedStyle(n).opacity); return o; };
const labelOf = (el) => (el.labels && el.labels.length ? el.labels[0] : el.closest('label'));
const textOf = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim();
const nameOf = (el) => {
  const by = el.getAttribute('aria-labelledby');
  if (by) return by.split(/\s+/).map((id) => { const t = document.getElementById(id); return t ? textOf(t) : ''; }).join(' ').trim();
  const aria = el.getAttribute('aria-label');
  if (aria && aria.trim()) return aria.trim();
  if (el.tagName === 'INPUT' && ['submit', 'button', 'reset'].includes(el.type)) return el.value || '';
  const label = labelOf(el);
  if (label) { const clone = label.cloneNode(true); clone.querySelectorAll('input,select,textarea').forEach((n) => n.remove()); const t = textOf(clone); if (t) return t; }
  if (['A', 'BUTTON', 'SUMMARY'].includes(el.tagName) || el.getAttribute('role')) return textOf(el) || el.getAttribute('title') || '';
  return el.getAttribute('title') || '';
};
const roleOf = (el) => {
  const explicit = el.getAttribute('role');
  if (explicit) return explicit.split(/\s+/)[0];
  const t = el.tagName;
  if (t === 'A') return 'link';
  if (t === 'BUTTON' || t === 'SUMMARY') return 'button';
  if (t === 'SELECT') return 'combobox';
  if (t === 'TEXTAREA') return 'textbox';
  if (t !== 'INPUT') return '';
  const kind = {checkbox: 'checkbox', radio: 'radio', range: 'slider', number: 'spinbutton', submit: 'button', button: 'button', reset: 'button'}[el.type];
  return kind || 'textbox';
};
const groupNameOf = (el) => {
  const group = el.closest('fieldset, [role=radiogroup], [role=group]');
  if (!group) return '';
  const aria = group.getAttribute('aria-label');
  if (aria) return aria;
  const legend = group.tagName === 'FIELDSET' ? group.querySelector(':scope > legend') : null;
  return legend ? textOf(legend) : '';
};
// The part of a target a pointer can reach: scroll containers clip what is scrolled out.
const reachOf = (el, r) => {
  let x0 = r.x, y0 = r.y, x1 = r.x + r.w, y1 = r.y + r.h;
  for (let n = el.parentElement; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
    const cs = getComputedStyle(n);
    if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
    const b = n.getBoundingClientRect();
    x0 = Math.max(x0, b.left); y0 = Math.max(y0, b.top); x1 = Math.min(x1, b.right); y1 = Math.min(y1, b.bottom);
  }
  return {x: x0, y: y0, w: Math.max(0, x1 - x0), h: Math.max(0, y1 - y0)};
};
const isInline = (el) => !!el.closest('p, li, td, dd, blockquote') && el.tagName === 'A' && getComputedStyle(el).display === 'inline';
"""

COLLECT_JS = (
    "(scope) => {"
    + SHARED_JS
    + r"""
const root = document.documentElement;
const all = [...document.querySelectorAll('*')].filter((el) => inScope(el, scope) && el.closest('head') === null);
const shown = all.filter(visible);

const controls = [];
for (const el of shown.filter((n) => n.matches(CONTROL_SEL))) {
  if (el.disabled || el.getAttribute('aria-hidden') === 'true') continue;
  // A focusable scroll region legitimately contains targets; it is not a target itself.
  if (el.matches('[role=region][tabindex]')) continue;
  const label = el.tagName === 'INPUT' ? labelOf(el) : null;
  const own = rectOf(el), lab = label && visible(label) ? rectOf(label) : null;
  const target = lab && lab.w * lab.h > own.w * own.h ? lab : own;
  controls.push({sel: pathOf(el), role: roleOf(el), name: nameOf(el), groupName: el.type === 'radio' ? groupNameOf(el) : '',
    inline: isInline(el), target, reach: reachOf(el, target)});
}

const texts = [];
const seen = new Set();
const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
for (let node = walker.nextNode(); node; node = walker.nextNode()) {
  const el = node.parentElement;
  if (!el || seen.has(el) || !node.textContent.trim() || !inScope(el, scope) || !visible(el)) continue;
  if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(el.tagName) || el.closest('[disabled]')) continue;
  seen.add(el);
  const cs = getComputedStyle(el), {layers, hidden} = bgLayers(el);
  const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700;
  texts.push({sel: pathOf(el), text: node.textContent.trim().slice(0, 30), fg: cs.color, bgs: layers,
    unverifiable: hidden, opacity: opacityOf(el), large: size >= 24 || (bold && size >= 18.66)});
}

// Runs between spaces, hyphens, slashes and angle brackets (the natural break points) broken one or two letters per line: a 4+ letter word whose pieces average 3 characters or fewer. Screen-reader-only text (clipped to a point) is not on screen.
const srOnly = (el) => {
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    const cs = getComputedStyle(n), r = n.getBoundingClientRect();
    if (r.width <= 2 || r.height <= 2 || cs.clipPath.startsWith('inset(50%') || cs.clip.replace(/\s/g, '') === 'rect(0px,0px,0px,0px)') return true;
  }
  return false;
};
const brokenWord = (el) => {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let worst = null;
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    for (const m of node.data.matchAll(/[^\s\-–—\/<>]{4,}/g)) {
      const range = document.createRange();
      range.setStart(node, m.index);
      range.setEnd(node, m.index + m[0].length);
      const tops = [...range.getClientRects()].filter((r) => r.width > 0).map((r) => r.top).sort((a, b) => a - b);
      let lines = 0, last = -1e9;
      for (const top of tops) { if (top - last > 4) lines += 1; last = top; }
      if (lines > 1 && (!worst || m[0].length / lines < worst.length / worst.lines)) worst = {text: m[0], length: m[0].length, lines};
    }
  }
  return worst;
};
const charWrap = [];
for (const el of shown.filter((n) => n.matches('td, th, .vb-badge, h1, h2, h3, h4, h5, h6, .ranking-text, .choice-label, .vd-hdr-item'))) {
  if (srOnly(el)) continue;
  const word = brokenWord(el);
  if (word) charWrap.push({sel: pathOf(el), text: word.text.slice(0, 30), length: word.length, lines: word.lines});
}

// An ISO date (2026-11-04) cut at a hyphen is unreadable: it must stay on one line.
const splitDates = [];
for (const el of shown.filter((n) => n.matches('.vd-hdr-item, td, th, p, li, dd'))) {
  if (srOnly(el)) continue;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    for (const m of node.data.matchAll(/\d{4}-\d{2}-\d{2}/g)) {
      const range = document.createRange();
      range.setStart(node, m.index);
      range.setEnd(node, m.index + m[0].length);
      const tops = [...range.getClientRects()].filter((r) => r.width > 0).map((r) => r.top);
      if (tops.length && Math.max(...tops) - Math.min(...tops) > 4) splitDates.push({sel: pathOf(el), text: m[0]});
    }
  }
}

// A pin (annotated code or diff marker) must not sit on top of the code text of its own line.
const pinOverlap = [];
for (const pin of shown.filter((n) => n.matches('.vd-annotated-pin, .vd-diff-pin'))) {
  const line = pin.closest('.vd-code-line, .vd-diff-text');
  if (!line) continue;
  const pr = pin.getBoundingClientRect();
  const walker = document.createTreeWalker(line, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (!node.data.trim() || pin.contains(node) || pin.parentElement.contains(node)) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const hit = [...range.getClientRects()].some((r) => r.width > 1 && r.height > 1
      && r.left < pr.right - 1 && pr.left < r.right - 1 && r.top < pr.bottom - 1 && pr.top < r.bottom - 1);
    if (hit) { pinOverlap.push({sel: pathOf(pin), text: node.data.trim().slice(0, 30)}); break; }
  }
}

const nontext = [];
const field = shown.filter((n) => n.matches('input:not([type=hidden]), select, textarea, button, [role=button]'));
for (const el of field) {
  const cs = getComputedStyle(el), width = parseFloat(cs.borderTopWidth);
  const {layers, hidden} = bgLayers(el.parentElement || el);
  if (width > 0 && cs.borderTopStyle !== 'none') nontext.push({sel: pathOf(el), kind: 'border', color: cs.borderTopColor, bgs: layers, unverifiable: hidden});
  if (el.type === 'range') {
    const thumb = getComputedStyle(el, '::-webkit-slider-thumb');
    const color = thumb.backgroundColor !== 'rgba(0, 0, 0, 0)' ? thumb.backgroundColor : thumb.borderTopColor;
    nontext.push({sel: pathOf(el), kind: 'slider thumb', color, bgs: layers, unverifiable: hidden});
  }
}
for (const el of shown.filter((n) => n.matches('label') && n.querySelector('input'))) {
  const cs = getComputedStyle(el), {layers, hidden} = bgLayers(el.parentElement);
  if (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none')
    nontext.push({sel: pathOf(el), kind: 'option border', color: cs.borderTopColor, bgs: layers, unverifiable: hidden});
}

const selected = [];
const marked = shown.filter((n) => n.matches('[aria-selected=true], [aria-checked=true], [aria-pressed=true], [aria-current=true]'));
for (const input of shown.filter((n) => n.matches('input:checked'))) marked.push(labelOf(input) || input);
for (const el of marked) {
  const cs = getComputedStyle(el), glyph = (p) => { const c = getComputedStyle(el, p).content; return c !== 'none' && c !== 'normal' && c !== '""'; };
  selected.push({sel: pathOf(el), borderWidth: parseFloat(cs.borderTopWidth) || 0, glyph: glyph('::before') || glyph('::after')});
}

const bordersLost = [];
for (const el of field) {
  const cs = getComputedStyle(el);
  const none = parseFloat(cs.borderTopWidth) === 0 || cs.borderTopStyle === 'none';
  if (none && cs.appearance === 'none' && !el.matches('[type=range]')) bordersLost.push({sel: pathOf(el), kind: 'control'});
}

const wide = [];
const rootWidth = root.clientWidth;
for (const el of shown) {
  const cs = getComputedStyle(el), r = el.getBoundingClientRect();
  if (cs.position === 'fixed' || el.tagName === 'HTML' || el.tagName === 'BODY') continue;
  let parent = el.parentElement;
  while (parent && getComputedStyle(parent).display === 'inline') parent = parent.parentElement;
  if (!parent) continue;
  let scroller = false;
  for (let n = parent; n && n !== root; n = n.parentElement) { const ox = getComputedStyle(n).overflowX; if (ox === 'auto' || ox === 'scroll') scroller = true; }
  if (scroller) continue;
  const pr = parent.getBoundingClientRect(), limit = cs.position === 'absolute' ? rootWidth : pr.right;
  if (r.right > limit + 1 || (cs.position !== 'absolute' && r.left < pr.left - 1)) wide.push({sel: pathOf(el), width: r.width, container: pr.width});
}

const clipped = shown.filter((n) => /^(hidden|clip|auto|scroll)$/.test(getComputedStyle(n).overflowX) && n.scrollWidth > n.clientWidth + 1 && n !== document.body && n !== root)
  .map((n) => ({sel: pathOf(n)}));

const ids = {}, dupIds = [];
document.querySelectorAll('[id]').forEach((n) => { ids[n.id] = (ids[n.id] || 0) + 1; });
for (const id in ids) if (ids[id] > 1) dupIds.push(id);

const imagesWithoutAlt = shown.filter((n) => n.tagName === 'IMG' && n.getAttribute('alt') === null).map(pathOf);
const aria = [], badRefs = [];
for (const el of all) {
  for (const attr of el.getAttributeNames()) {
    if (attr.startsWith('aria-')) aria.push({sel: pathOf(el), attr, value: el.getAttribute(attr)});
    if (['aria-labelledby', 'aria-describedby', 'aria-controls', 'aria-owns'].includes(attr))
      for (const id of el.getAttribute(attr).split(/\s+/).filter(Boolean)) if (!document.getElementById(id)) badRefs.push({sel: pathOf(el), attr});
  }
  if (el.hasAttribute('role')) aria.push({sel: pathOf(el), attr: 'role', value: el.getAttribute('role')});
}

const series = [...document.querySelectorAll('[data-series]')].filter((n) => inScope(n, scope)).map((n) => ({
  id: n.dataset.series, label: n.getAttribute('aria-label') || textOf(n), marker: n.dataset.marker || '',
  dash: n.dataset.dash || '', pattern: n.dataset.pattern || ''}));
const richRoots = shown.filter((n) => n.matches('.vb') && !n.parentElement.closest('.vb')).map((n) => ({
  sel: pathOf(n), hasTable: !!n.querySelector('table'),
  hasAlt: n.matches('.callout, .choice, .form') || !!n.querySelector('figcaption, [role=img][aria-label], details, .vb-alt, noscript') || (n.getAttribute('role') === 'img' && !!n.getAttribute('aria-label'))}));

return {doc: {scrollWidth: root.scrollWidth, clientWidth: root.clientWidth, lang: root.lang, title: document.title},
  controls, texts, charWrap, splitDates, pinOverlap, nontext, selected, bordersLost, wide, clipped, dupIds, imagesWithoutAlt, aria, badRefs, series, richRoots,
  tabbable: controls.length};
}"""
)

FIRST_FOCUS_JS = (
    "(scope) => {"
    + SHARED_JS
    + r"""
const first = [...document.querySelectorAll(CONTROL_SEL)].find((el) => inScope(el, scope) && visible(el) && !el.disabled && el.tabIndex >= 0);
if (!first) return false;
first.scrollIntoView({block: 'nearest'});
first.focus();
return true;
}"""
)

FOCUS_JS = (
    "(scope) => {"
    + SHARED_JS
    + r"""
const el = document.activeElement;
if (!el || el === document.body || !inScope(el, scope)) return null;
const own = getComputedStyle(el), r = el.getBoundingClientRect();
// A range input draws its ring on the thumb pseudo-element; getComputedStyle cannot read that
// pseudo in Chromium, so read the matching stylesheet rule instead.
const thumbRule = (() => {
  if (!el.matches('input[type=range]') || own.outlineStyle !== 'none') return null;
  const walk = (rules) => { for (const r of rules) {
    if (r.cssRules && !(r.media && /forced-colors|print/.test(r.media.mediaText))) { const f = walk(r.cssRules); if (f) return f; }
    if (!r.selectorText || !r.selectorText.includes('::-webkit-slider-thumb')) continue;
    for (const sel of r.selectorText.split(',')) {
      const base = sel.replace('::-webkit-slider-thumb', '').trim();
      if (base.includes('::') || !el.matches(base)) continue;
      if (/\d+(\.\d+)?px/.test(r.style.getPropertyValue('outline')) || r.style.outlineStyle === 'solid') return r.style;
    }
  } return null; };
  for (const sheet of document.styleSheets) { const f = walk(sheet.cssRules); if (f) return f; }
  return null;
})();
const cs = thumbRule ? {outlineStyle: 'solid', outlineWidth: (thumbRule.getPropertyValue('outline').match(/(\d+(?:\.\d+)?)px/) || ['', '0'])[1] + 'px', outlineOffset: thumbRule.outlineOffset || '2px', outlineColor: getComputedStyle(el).getPropertyValue('--vd-focus-ring').trim() || 'rgb(0,0,0)', boxShadow: 'none'} : own;
const outlineWidth = parseFloat(cs.outlineWidth) || 0;
const shadow = cs.boxShadow === 'none' ? [] : cs.boxShadow.split(/,(?![^(]*\))/).map((s) => s.trim());
const parts = (s) => s.replace(/rgba?\([^)]*\)|color\([^)]*\)/g, '').trim().split(/\s+/).map(parseFloat);
const shadowWidth = shadow.reduce((m, s) => { const p = parts(s); return Math.max(m, (p[3] || 0) + (p[2] || 0)); }, 0);
const shadowColor = shadow.length ? (shadow[0].match(/rgba?\([^)]*\)|color\([^)]*\)/) || [''])[0] : '';
const outlineOn = cs.outlineStyle !== 'none' && outlineWidth > 0;
const reach = (outlineOn ? Math.max(outlineWidth + (parseFloat(cs.outlineOffset) || 0), 0) : 0) + shadowWidth;
let clipped = false;
for (let n = el.parentElement; n && n !== document.documentElement; n = n.parentElement) {
  const o = getComputedStyle(n);
  if (/^(visible)$/.test(o.overflowX) && /^(visible)$/.test(o.overflowY)) continue;
  const a = n.getBoundingClientRect();
  if (r.left - reach < a.left - 0.5 || r.right + reach > a.right + 0.5 || r.top - reach < a.top - 0.5 || r.bottom + reach > a.bottom + 0.5) { clipped = true; break; }
}
let obscuredBy = '';
for (const n of document.querySelectorAll('*')) {
  const p = getComputedStyle(n).position;
  if ((p !== 'fixed' && p !== 'sticky') || n.contains(el) || el.contains(n) || !visible(n)) continue;
  const a = n.getBoundingClientRect();
  if (Math.min(a.right, r.right) - Math.max(a.left, r.left) > 1 && Math.min(a.bottom, r.bottom) - Math.max(a.top, r.top) > 1) { obscuredBy = pathOf(n); break; }
}
const inside = bgLayers(el), outside = bgLayers(el.parentElement || el);
return {sel: pathOf(el), outline: {style: cs.outlineStyle, width: outlineWidth, color: cs.outlineColor},
  shadowWidth, ringColor: outlineOn ? cs.outlineColor : shadowColor, clipped, obscuredBy,
  // The browser decides how far focus scrolls (Chrome leaves a partly visible field in place), so the
  // element must start inside the viewport; fully off-screen focus is the defect.
  inView: r.top < innerHeight && r.bottom > 0 && (r.left + r.right) / 2 >= 0 && (r.left + r.right) / 2 <= innerWidth,
  insideBgs: inside.layers, outsideBgs: outside.layers};
}"""
)
# ruff: noqa: E501
