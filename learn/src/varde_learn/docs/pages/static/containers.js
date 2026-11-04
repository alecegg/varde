// Tabs container: turns the server-rendered stacked panels into a tablist.
// Without this script every panel shows under its heading. createElement and
// textContent only; the columns container needs no script.
import { make } from './dom.js';

const KEYS = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
let serial = 0;

function select(tabs, panels, index) {
  tabs.forEach((tab, i) => {
    tab.setAttribute('aria-selected', String(i === index));
    tab.tabIndex = i === index ? 0 : -1;
    panels[i].hidden = i !== index;
  });
}

function onKey(event, tabs, panels) {
  const current = tabs.indexOf(event.currentTarget);
  let next = current + (KEYS[event.key] || 0);
  if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = tabs.length - 1;
  else if (!(event.key in KEYS)) return;
  event.preventDefault();
  next = (next + tabs.length) % tabs.length;
  select(tabs, panels, next);
  tabs[next].focus();
}

function makeTab(panel, heading, id, index) {
  const tab = make('button', 'vd-ctabs-tab', heading.textContent);
  tab.type = 'button';
  tab.id = id + '-t' + index;
  tab.setAttribute('role', 'tab');
  tab.setAttribute('aria-controls', panel.id);
  panel.setAttribute('role', 'tabpanel');
  panel.setAttribute('aria-labelledby', tab.id);
  return tab;
}

export function enhanceContainers(block) {
  if (!block.classList.contains('vd-ctabs')) return;
  const panels = Array.from(block.querySelectorAll(':scope > .vd-ctabs-panel'));
  const headings = panels.map((panel) => panel.querySelector(':scope > .vd-containers-label'));
  if (!panels.length || headings.includes(null)) return;
  const id = 'vd-ctabs-' + serial++;
  panels.forEach((panel, i) => { panel.id = id + '-p' + i; });
  const tabs = panels.map((panel, i) => makeTab(panel, headings[i], id, i));
  const list = make('div', 'vd-ctabs-list');
  list.setAttribute('role', 'tablist');
  list.setAttribute('aria-label', block.getAttribute('aria-label') || 'Tabs');
  const region = make('div', 'vd-ctabs-scroll');
  region.setAttribute('role', 'region');
  region.setAttribute('aria-label', 'Tab list');
  region.tabIndex = 0;
  tabs.forEach((tab) => {
    tab.addEventListener('keydown', (event) => onKey(event, tabs, panels));
    tab.addEventListener('click', () => select(tabs, panels, tabs.indexOf(tab)));
    list.append(tab);
  });
  region.append(list);
  block.prepend(region);
  block.classList.add('vd-ctabs-on');
  select(tabs, panels, 0);
}
