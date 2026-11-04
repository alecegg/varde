// ui-states and wireframe tabs: one tile at a time.
import { make } from './dom.js';

function selectTab(tabs, tiles, index) {
  tabs.forEach((tab, i) => {
    tab.setAttribute('aria-selected', String(i === index));
    tab.tabIndex = i === index ? 0 : -1;
    tiles[i].hidden = i !== index;
  });
}

function onTabKey(event, tabs, tiles) {
  const current = tabs.indexOf(document.activeElement);
  const moves = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  let next = current + (moves[event.key] || 0);
  if (event.key === 'Home') next = 0;
  if (event.key === 'End') next = tabs.length - 1;
  if (next === current || current < 0) return;
  event.preventDefault();
  next = (next + tabs.length) % tabs.length;
  selectTab(tabs, tiles, next);
  tabs[next].focus();
}

let serial = 0;

export function enhanceStates(block) {
  for (const grid of block.querySelectorAll('.vb-grid')) {
    if (grid.dataset.layout === 'grid') continue; // asked for the wrapped grid
    const tiles = Array.from(grid.querySelectorAll(':scope > .vb-state'));
    if (tiles.length < 2) continue;
    const list = make('div', 'vb-tabs');
    list.setAttribute('role', 'tablist');
    list.setAttribute('aria-label', 'Screen states');
    serial += 1;
    const tabs = tiles.map((tile) => {
      const heading = tile.querySelector('h5');
      const tab = make('button', 'vb-tab', heading ? heading.textContent : 'state');
      tab.type = 'button';
      tab.setAttribute('role', 'tab');
      return tab;
    });
    tabs.forEach((tab, index) => {
      const id = 'vb-st-' + serial + '-' + index;
      tab.id = id + '-tab';
      tab.setAttribute('aria-controls', id);
      tab.addEventListener('click', () => selectTab(tabs, tiles, index));
      tiles[index].id = id;
      tiles[index].tabIndex = 0;
      tiles[index].setAttribute('role', 'tabpanel');
      tiles[index].setAttribute('aria-labelledby', id + '-tab');
    });
    list.append(...tabs);
    list.addEventListener('keydown', (event) => onTabKey(event, tabs, tiles));
    grid.before(list);
    selectTab(tabs, tiles, 0);
  }
}
