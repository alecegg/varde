// table and data-model: sort, filter, wrap toggle, scroll hint, relations.
import { make, control, keepInside } from './dom.js';

const MIN_ROWS_FOR_FILTER = 3;

function cellValue(row, column) {
  const cell = row.cells[column];
  if (!cell) return '';
  const glyph = cell.querySelector('.vb-status-glyph');
  const text = cell.textContent.trim();
  return glyph ? text.slice(glyph.textContent.length).trim() : text;
}

function compareCells(a, b) {
  const na = Number(a);
  const nb = Number(b);
  if (a !== '' && b !== '' && !Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

function dataRows(body) {
  return Array.from(body.rows).filter((row) => !row.classList.contains('vb-group-head'));
}

// Rows sort inside their own tbody, so a group keeps its header and its rows.
// direction: 1 ascending, -1 descending, 0 as authored.
function applySort(table, state, column, direction) {
  state.direction = direction;
  state.column = direction === 0 ? -1 : column;
  for (const body of table.tBodies) {
    const head = Array.from(body.rows).filter((row) => row.classList.contains('vb-group-head'));
    const rows = state.original.get(body).slice();
    if (direction !== 0) {
      rows.sort((x, y) => direction * compareCells(cellValue(x, column), cellValue(y, column)));
    }
    body.replaceChildren(...head, ...rows);
  }
  table.tHead.querySelectorAll('th').forEach((th, index) => {
    const active = direction !== 0 && index === column;
    th.setAttribute('aria-sort', active ? (direction === 1 ? 'ascending' : 'descending') : 'none');
  });
  if (state.picker) state.picker.value = direction === 0 ? '' : column + ':' + direction;
}

function cycleSort(table, state, column) {
  const direction = state.column === column ? (state.direction + 2) % 3 - 1 : 1;
  applySort(table, state, column, direction);
}

function makeSortable(table) {
  const original = new Map(Array.from(table.tBodies, (body) => [body, dataRows(body)]));
  const state = { column: -1, direction: 0, original, picker: null };
  table.tHead.querySelectorAll('th').forEach((th, index) => {
    if (!th.textContent.trim()) return;
    const button = make('button', 'vb-sort');
    button.type = 'button';
    button.append(...th.childNodes);
    button.addEventListener('click', () => cycleSort(table, state, index));
    th.append(button);
    th.setAttribute('aria-sort', 'none');
  });
  return state;
}

// Stack mode hides the header (and its buttons), so phones sort through a select.
function sortPicker(table, state) {
  const label = make('label', 'vb-sortpick');
  const select = make('select', 'vb-sortselect');
  select.append(new Option('As authored', ''));
  table.tHead.querySelectorAll('th').forEach((th, index) => {
    const name = th.textContent.trim();
    if (!name) return;
    select.append(new Option(name + ', ascending', index + ':1'));
    select.append(new Option(name + ', descending', index + ':-1'));
  });
  select.addEventListener('change', () => {
    const [column, direction] = select.value ? select.value.split(':').map(Number) : [-1, 0];
    applySort(table, state, column, direction);
  });
  state.picker = select;
  label.append('Sort by ', select);
  return label;
}

function filterRows(table, needle) {
  let shown = 0;
  for (const body of table.tBodies) {
    let visible = 0;
    for (const row of dataRows(body)) {
      const hit = !needle || row.textContent.toLowerCase().includes(needle);
      row.hidden = !hit;
      if (hit) visible += 1;
    }
    const head = body.querySelector('.vb-group-head');
    if (head) head.hidden = visible === 0;
    shown += visible;
  }
  return shown;
}

function filterField(table, total) {
  const input = make('input', 'vb-filter');
  input.type = 'search';
  input.placeholder = 'Filter rows';
  input.setAttribute('aria-label', 'Filter rows');
  const status = make('span', 'vb-filter-status');
  status.setAttribute('aria-live', 'polite');
  input.addEventListener('input', () => {
    const needle = input.value.trim().toLowerCase();
    const shown = filterRows(table, needle);
    status.textContent = needle ? shown + ' of ' + total + ' rows' : '';
  });
  return [input, status];
}

function wrapToggle(region) {
  const button = control('Wrap text', () => {
    const wrapped = region.classList.toggle('vb-nowrap');
    button.setAttribute('aria-pressed', String(!wrapped));
  }, 'vb-ctl vb-wrap-toggle');
  button.setAttribute('aria-pressed', 'true');
  return button;
}

function scrollHint(region) {
  const hint = make('span', 'vb-scrollhint', 'Scrolls sideways');
  const update = () => { hint.hidden = region.scrollWidth <= region.clientWidth + 1; };
  update();
  window.addEventListener('resize', update);
  region.addEventListener('click', update);
  if (typeof ResizeObserver === 'function') new ResizeObserver(update).observe(region);
  return hint;
}

// Chromium does not scroll to a focused control in the sticky header, so do it here.
function keepFocusVisible(table, region) {
  region.addEventListener('focusin', (event) => {
    const target = event.target;
    if (target === region) return;
    const inHead = table.tHead.contains(target);
    const header = table.tHead.getBoundingClientRect().height;
    keepInside(region, target, { insetTop: inHead ? 0 : header, vertical: !inHead });
  });
}

function addToolbar(table, state) {
  const region = table.closest('.vb-scroll');
  if (!region) return;
  const total = Array.from(table.tBodies).reduce((sum, body) => sum + dataRows(body).length, 0);
  keepFocusVisible(table, region);
  const bar = make('div', 'vb-filterbar');
  if (total >= MIN_ROWS_FOR_FILTER) bar.append(...filterField(table, total));
  if (table.classList.contains('vb-table-stack')) bar.append(sortPicker(table, state));
  bar.append(wrapToggle(region), scrollHint(region));
  // After the region: rows scrolled out of it keep their boxes above, so a bar above would sit under them.
  region.after(bar);
}

function collapseRelations(list) {
  const count = list.children.length;
  const button = control('Relations (' + count + ')', () => {
    list.hidden = !list.hidden;
    button.setAttribute('aria-expanded', String(!list.hidden));
  }, 'vb-ctl vb-toggle');
  button.setAttribute('aria-expanded', 'true');
  list.before(button);
}

export function enhanceTables(block) {
  for (const table of block.querySelectorAll('table.vb-table')) {
    if (!table.tHead || !table.tBodies[0]) continue;
    addToolbar(table, makeSortable(table));
  }
  for (const list of block.querySelectorAll('.vb-relations')) collapseRelations(list);
}
