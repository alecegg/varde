// Per-block action menu: one always-visible button per block opens a popup of
// entries chosen by block type. ES module loaded by app.js; createElement and
// textContent only. ENTRIES mirrors actions.menu_entries (allow_edit true; the
// server refuses an edit it does not allow); a Python test fails on drift.
export const ENTRIES = {"prose": ["comment", "suggest", "edit", "copy", "copy-link"], "heading": ["comment", "suggest", "edit", "copy", "copy-link"], "list": ["comment", "suggest", "edit", "copy", "copy-link"], "table": ["comment", "suggest", "edit", "copy", "copy-link"], "code": ["comment", "edit", "copy", "copy-link"], "widget": ["comment", "edit", "copy-link"], "decision": ["comment", "edit", "copy-link"], "visual": ["comment", "edit", "copy", "copy-link"], "status": ["comment", "edit", "copy-link"], "part": ["comment", "copy", "copy-link"], "error": ["comment", "edit", "copy", "copy-link"]};

const LABELS = { comment: 'Comment', suggest: 'Suggest', edit: 'Edit', copy: 'Copy', 'copy-link': 'Copy link' };
let current = null; // { button, popup }

export function blockType(block) {
  if (block.dataset.blockType) return block.dataset.blockType;
  return block.dataset.part ? 'part' : 'prose';
}

export function entriesFor(block) {
  const ids = ENTRIES[blockType(block)] || ENTRIES.prose;
  return block.id ? ids : ids.filter((id) => id !== 'copy-link');
}

function copyText(block) {
  const marked = block.querySelector('[data-copy]');
  if (marked) return marked.dataset.copy;
  const clone = block.cloneNode(true);
  for (const node of clone.querySelectorAll('.menu-btn')) node.remove();
  return clone.textContent.replace(/\s+/g, ' ').trim();
}

function linkOf(block) {
  return location.origin + location.pathname + location.search + '#' + block.id;
}

function announce(message) {
  let region = document.querySelector('.menu-live');
  if (!region) {
    region = document.createElement('div');
    region.className = 'menu-live';
    region.setAttribute('role', 'status');
    region.setAttribute('aria-live', 'polite');
    document.body.append(region);
  }
  region.textContent = message;
}

function fallbackCopy(text) {
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('aria-hidden', 'true');
  area.className = 'menu-copy-buffer';
  document.body.append(area);
  area.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (error) { ok = false; }
  area.remove();
  return ok;
}

async function copy(text) {
  let ok = false;
  if (window.isSecureContext && navigator.clipboard) {
    try { await navigator.clipboard.writeText(text); ok = true; } catch (error) { ok = false; }
  }
  if (!ok) ok = fallbackCopy(text);
  announce(ok ? 'Copied' : 'Copy failed');
}

export function closeMenu(restoreFocus) {
  if (!current) return;
  const { button, popup } = current;
  current = null;
  popup.remove();
  button.setAttribute('aria-expanded', 'false');
  if (restoreFocus) button.focus();
}

function runEntry(id, block, handlers) {
  if (id === 'comment') handlers.comment(block);
  else if (id === 'suggest' || id === 'edit') handlers.edit(block, id);
  else if (id === 'copy') copy(copyText(block));
  else if (id === 'copy-link') copy(linkOf(block));
}

function place(button, popup) {
  const anchor = button.getBoundingClientRect();
  const box = popup.getBoundingClientRect();
  const room = window.innerHeight - anchor.bottom;
  const top = room < box.height && anchor.top > room ? anchor.top - box.height : anchor.bottom;
  const left = Math.min(Math.max(anchor.right - box.width, 0), window.innerWidth - box.width);
  popup.style.insetBlockStart = Math.max(top, 0) + 'px';
  popup.style.insetInlineStart = Math.max(left, 0) + 'px';
}

function onKey(event, items) {
  const index = items.indexOf(document.activeElement);
  const last = items.length - 1;
  const moves = { ArrowDown: (index + 1) % items.length, ArrowUp: (index + last) % items.length, Home: 0, End: last };
  if (event.key === 'Escape') { event.preventDefault(); closeMenu(true); return; }
  if (event.key === 'Tab') { closeMenu(false); return; }
  if (!(event.key in moves)) return;
  event.preventDefault();
  items[moves[event.key]].focus();
}

function openMenu(block, button, handlers, focusLast) {
  closeMenu(false);
  const popup = document.createElement('div');
  popup.className = 'menu-popup';
  popup.setAttribute('role', 'menu');
  popup.setAttribute('aria-label', 'Actions');
  const items = entriesFor(block).map((id) => {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'menu-item';
    item.setAttribute('role', 'menuitem');
    item.tabIndex = -1;
    item.dataset.entry = id;
    item.textContent = LABELS[id];
    item.addEventListener('click', () => {
      closeMenu(id === 'comment' || id === 'copy' || id === 'copy-link');
      runEntry(id, block, handlers);
    });
    return item;
  });
  popup.append(...items);
  popup.addEventListener('keydown', (event) => onKey(event, items));
  document.body.append(popup);
  place(button, popup);
  button.setAttribute('aria-expanded', 'true');
  current = { button, popup };
  items[focusLast ? items.length - 1 : 0].focus();
}

// A rule or other decoration-only block has nothing to act on.
export function hasContent(block) {
  if (block.querySelector('[data-copy], .vb, input, select, textarea, img, svg')) return true;
  return block.textContent.trim() !== '';
}

export function mountMenu(block, handlers) {
  if (block.querySelector(':scope > .menu-btn') || !hasContent(block)) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'menu-btn';
  button.textContent = '⋯';
  const label = block.textContent.replace(/\s+/g, ' ').trim().slice(0, 40);
  button.setAttribute('aria-label', 'Actions for ' + (label || 'block'));
  button.setAttribute('aria-haspopup', 'menu');
  button.setAttribute('aria-expanded', 'false');
  button.addEventListener('click', () => {
    if (current && current.button === button) closeMenu(true);
    else openMenu(block, button, handlers, false);
  });
  button.addEventListener('keydown', (event) => {
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    openMenu(block, button, handlers, event.key === 'ArrowUp');
  });
  block.classList.add('has-menu');
  block.append(button);
}

document.addEventListener('pointerdown', (event) => {
  if (!current) return;
  if (current.popup.contains(event.target) || current.button.contains(event.target)) return;
  closeMenu(false);
});
window.addEventListener('resize', () => closeMenu(false));
document.addEventListener('scroll', () => closeMenu(false), true);
