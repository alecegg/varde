#!/usr/bin/env node
import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { findSettingsCardWrapper, hasInsetDescendantContent } from './walk-mobile-ui-heuristics.mjs';

const [startUrl, outputArg = 'mobile-ui-walk'] = process.argv.slice(2);
if (!startUrl) {
  console.error('Usage: node walk-mobile-ui.mjs <url> [output-directory]');
  process.exit(2);
}

const require = createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../../runner/ui/package.json'));
const { chromium, webkit, devices } = require('playwright');
const start = new URL(startUrl);
const discoveryOnly = process.env.VARDE_UX_DISCOVERY_ONLY === '1';
const output = path.resolve(outputArg);
const screenshots = path.join(output, 'screenshots');
await fs.mkdir(screenshots, { recursive: true });

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
let webkitBrowser;
if (!discoveryOnly) {
  try {
    webkitBrowser = await webkit.launch({ headless: true });
  } catch (error) {
    await browser.close();
    throw new Error(`WebKit is required for the mobile UI walk but could not launch: ${error.message}`, { cause: error });
  }
}
const webkitStatus = discoveryOnly ? 'not needed for route discovery' : 'tested';
const context = await browser.newContext({
  ...devices['iPhone 13'],
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 1,
  isMobile: true,
  hasTouch: true,
});
await context.addInitScript(() => {
  let viewportHeight = window.innerHeight;
  const syntheticViewport = new EventTarget();
  Object.defineProperties(syntheticViewport, {
    height: { get: () => viewportHeight },
    offsetTop: { get: () => 0 },
    offsetLeft: { get: () => 0 },
    width: { get: () => window.innerWidth },
    scale: { get: () => 1 },
    pageLeft: { get: () => window.scrollX },
    pageTop: { get: () => window.scrollY },
  });
  Object.defineProperty(window, 'visualViewport', { configurable: true, value: syntheticViewport });
  window.setSyntheticKeyboardHeight = (height) => {
    viewportHeight = height;
    syntheticViewport.dispatchEvent(new Event('resize'));
    syntheticViewport.dispatchEvent(new Event('scroll'));
  };
  document.addEventListener('submit', (event) => event.preventDefault(), true);
});
const blockedWrites = [];
await context.route('**/*', (route) => {
  const request = route.request();
  if (['GET', 'HEAD', 'OPTIONS'].includes(request.method())) return route.continue();
  blockedWrites.push(`${request.method()} ${request.url()}`);
  return route.fulfill({ status: 503, body: 'blocked by walk-mobile-ui (read-only)' });
});
const page = await context.newPage();
page.setDefaultTimeout(5000);
if (discoveryOnly) page.setDefaultNavigationTimeout(3000);
const safeAreaSession = await context.newCDPSession(page);
await safeAreaSession.send('Emulation.setSafeAreaInsetsOverride', {
  insets: { top: 44, bottom: 34, left: 0, right: 0 },
});
const findings = [];
const keyboardChecks = [];
const routes = new Set();
const discoveredTemplates = new Set();
const hostDevRows = new Set();
const checkedAppearanceRoutes = new Set();
const healthMenuEntries = new Set();
let headerStatusFound = false;
const configuredMaxRoutes = Number.parseInt(process.env.VARDE_UX_MAX_ROUTES || (discoveryOnly ? '1000' : '100'), 10);
if (!Number.isInteger(configuredMaxRoutes) || configuredMaxRoutes < 1) throw new Error('VARDE_UX_MAX_ROUTES must be a positive integer');
const maxRoutes = configuredMaxRoutes;
const safeTop = 44;
const safeBottom = 34;
const syntheticViewportHeight = 420;
const realDeviceCheckpoints = [
  'Keyboard open and close.',
  'Focus without page scroll shift.',
  'Multiline composer cap and overflow.',
  'Rotation while the keyboard is open.',
  'Home indicator and safe-area behavior.',
];
findings.push({
  item: 4,
  route: 'all',
  selector: 'REAL-DEVICE CHECKPOINT REQUIRED',
  details: 'Chromium and WebKit geometry checks do not prove iOS Safari keyboard behavior.',
  checkpoints: realDeviceCheckpoints,
});

function record(item, route, selector, details, baselineItem) {
  if (baselineItem && findings.some((finding) => finding.baselineItem === baselineItem
      && finding.route === route && finding.selector === selector && finding.details === details)) return;
  findings.push({ item, ...(baselineItem ? { baselineItem } : {}), route, selector, details });
}

function routeKey(url) {
  const normalized = new URL(url);
  normalized.hash = '';
  if (normalized.pathname.length > 1) normalized.pathname = normalized.pathname.replace(/\/+$/, '');
  return normalized.href;
}

function discoveryKey(url) {
  const normalized = new URL(routeKey(url));
  const parts = normalized.pathname.split('/');
  if (['plans', 'threads', 'roles'].includes(parts[1]) && parts.length > 2) parts[2] = '<id>';
  normalized.pathname = parts.join('/');
  return normalized.href;
}

async function addSafeAreaGuides(targetPage) {
  await targetPage.addStyleTag({ content: `
    .walk-safe-area-guide { position: fixed; left: 0; right: 0; z-index: 2147483647; pointer-events: none; background: rgb(255 0 0 / 12%); }
    #walk-safe-area-top { top: 0; height: ${safeTop}px; }
    #walk-safe-area-bottom { bottom: 0; height: ${safeBottom}px; }
  ` });
  await targetPage.evaluate(() => {
    for (const id of ['walk-safe-area-top', 'walk-safe-area-bottom']) {
      const guide = document.createElement('div');
      guide.id = id;
      guide.className = 'walk-safe-area-guide';
      guide.setAttribute('aria-hidden', 'true');
      document.body.append(guide);
    }
  });
}

async function settle(targetPage) {
  // SPA routes render after domcontentloaded; wait for visible text, then a short quiet period.
  await targetPage.waitForFunction(() => document.body?.innerText.trim().length > 0, null, { timeout: 8000 }).catch(() => {});
  await targetPage.waitForTimeout(500);
  await targetPage.evaluate(() => document.fonts?.ready);
}

async function visit(url) {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  if (discoveryOnly) {
    await page.waitForLoadState('networkidle', { timeout: 3000 }).catch(() => {});
    await page.waitForTimeout(500);
  }
  else {
    await settle(page);
    await addSafeAreaGuides(page);
  }
  const currentRoute = routeKey(page.url());
  routes.add(currentRoute);
  return currentRoute;
}

async function linksOnPage() {
  return page.locator('a[href]').evaluateAll((anchors) => anchors
    .map((anchor) => anchor.href)
    .filter((href) => href && new URL(href).origin === location.origin));
}

async function firstDetailLinkOnListPage(route) {
  const pathname = new URL(route).pathname;
  const listRoute = /^\/(?:plans|roles|queue)\/?$/.test(pathname);
  if (!listRoute) return null;
  const prefix = pathname.replace(/\/$/, '') + '/';
  await page.waitForFunction((expectedPrefix) => [...document.querySelectorAll('main a[href], article a[href], [role="main"] a[href]')]
    .some((anchor) => new URL(anchor.href).pathname.startsWith(expectedPrefix)), prefix, { timeout: 5000 }).catch(() => {});
  return page.locator('main a[href], article a[href], [role="main"] a[href]')
    .evaluateAll((anchors, expectedPrefix) => anchors.map((anchor) => anchor.href)
      .find((href) => new URL(href).pathname.startsWith(expectedPrefix)), prefix)
    .catch(() => null);
}

const labelVariants = new Map();
const iconFamilies = { glyph: new Set(), svg: new Set() };

async function collectIcons(route) {
  const found = await page.evaluate(() => [...document.querySelectorAll('a, button')].filter((element) => element.offsetWidth).map((element) => {
    const label = element.getAttribute('aria-label') || element.innerText.trim().split('\n')[0];
    const text = element.innerText.trim();
    const leading = text.match(/^[^\p{L}\p{N}\s]/u)?.[0];
    return { label, text: text.slice(0, 12), glyph: leading || null, svg: element.querySelector('svg') ? 1 : 0 };
  }));
  for (const { label, text, glyph, svg } of found) {
    if (glyph) iconFamilies.glyph.add(`${glyph} (${route.replace(start.origin, '')})`);
    if (svg) iconFamilies.svg.add(`${label.slice(0, 24)} (${route.replace(start.origin, '')})`);
    if (/menu/i.test(label)) {
      if (!labelVariants.has(label)) labelVariants.set(label, new Map());
      labelVariants.get(label).set(text || '(icon)', route);
    }
  }
}

async function inspectLayout(route) {
  const result = await page.evaluate(({ safeTop: top, safeBottom: bottom, routePath }) => {
    const visible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const controls = [...document.querySelectorAll(
      'a[href], button, input, select, textarea, summary, [contenteditable="true"], [role="button"], [role="link"], [role="tab"], [role="checkbox"], [role="switch"], [tabindex]:not([tabindex="-1"])',
    )].filter(visible);
    const problems = [];
    const edgeCandidates = [];
    let headerStatus = false;
    const hostRows = [];
    const menuHealthRows = [];
    const settingsCard = { found: false, groups: [], candidates: [] };
    const appearance = { found: false, options: null };
    const content = [...document.querySelectorAll('main, article, section, form, h1, h2, h3, p, li, label')]
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return visible(element) && rect.width > 1 && rect.height > 1 && element.innerText.trim();
      });
    const safeAreaProbe = document.createElement('div');
    safeAreaProbe.style.cssText = 'position:fixed;visibility:hidden;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)';
    document.body.append(safeAreaProbe);
    const measuredSafeTop = Number.parseFloat(getComputedStyle(safeAreaProbe).paddingTop);
    const measuredSafeBottom = Number.parseFloat(getComputedStyle(safeAreaProbe).paddingBottom);
    safeAreaProbe.remove();
    if (measuredSafeTop !== top || measuredSafeBottom !== bottom) {
      problems.push({ item: 1, selector: 'safe-area-env', details: `Safe-area env measured ${measuredSafeTop}px top and ${measuredSafeBottom}px bottom; expected ${top}px and ${bottom}px.` });
    }
    for (const [index, element] of content.entries()) {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      const left = rect.left + Number.parseFloat(style.paddingLeft || 0);
      const right = innerWidth - rect.right + Number.parseFloat(style.paddingRight || 0);
      const textWalker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
      const descendants = [];
      while (textWalker.nextNode()) {
        const text = textWalker.currentNode;
        const textElement = text.parentElement;
        if (!text.textContent.trim() || !textElement || textElement.closest('[aria-hidden="true"], .visually-hidden, .sr-only')) continue;
        const textRect = textElement.getBoundingClientRect();
        const textStyle = getComputedStyle(textElement);
        if (!visible(textElement) || textRect.width <= 1 || textRect.height <= 1) continue;
        descendants.push({
          leftInset: textRect.left + Number.parseFloat(textStyle.paddingLeft || 0),
          rightInset: innerWidth - textRect.right + Number.parseFloat(textStyle.paddingRight || 0),
        });
      }
      edgeCandidates.push({
        left: rect.left,
        right: rect.right,
        viewportWidth: innerWidth,
        leftInset: left,
        rightInset: right,
        descendants,
        selector: `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}[${index}]`,
      });
    }
    for (const [index, element] of controls.entries()) {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      const selector = `${element.tagName.toLowerCase()}${element.id ? `#${element.id}` : ''}[${index}]`;
      if (rect.width < 44 || rect.height < 44) {
        problems.push({ item: 2, selector, details: `Touch target is ${Math.round(rect.width)}×${Math.round(rect.height)} CSS px.` });
      }
      if (rect.left < 16 || rect.right > innerWidth - 16) {
        problems.push({ item: 3, selector, details: 'Control is less than 16 px from a horizontal viewport edge.' });
      }
      if (style.position === 'fixed' && (rect.top < top || rect.bottom > innerHeight - bottom)) {
        problems.push({ item: 1, selector, details: 'Fixed control overlaps the simulated safe-area band.' });
      }
      if (element.matches('input:not([type="checkbox"]):not([type="radio"]), textarea, select')
          && Number.parseFloat(style.fontSize) < 16) {
        problems.push({ item: 10, selector, details: `Input text is ${style.fontSize}; mobile form controls need at least 16 px.` });
      }
      if (element.matches(':disabled, [aria-disabled="true"]')) {
        const scope = element.closest('fieldset, form, [role="group"], li, section, article') || element.parentElement;
        const explanation = (scope.innerText || '').trim();
        const hasPath = Boolean(scope.querySelector('a[href], button:not(:disabled)'));
        if (explanation.length < 20 || !hasPath) {
          problems.push({ item: 8, selector, details: 'Disabled control lacks nearby explanatory text or an enabled next-step link/button.' });
        }
      }
    }
    const chatAnchors = [...document.querySelectorAll('main a[href]')]
      .filter((element) => /\/(?:chat|thread)\//i.test(element.href));
    const agentRowElements = [...document.querySelectorAll('main .agent-list li, main [class*="agent" i] li, main [data-agent-row]')];
    const chatRowElements = [...new Set([...chatAnchors, ...agentRowElements])];
    const chatRows = chatRowElements
      .filter(visible)
      .map((element) => ({
        element,
        label: (element.getAttribute('aria-label') || element.querySelector('strong, h2, h3, h4, a[href]')?.innerText || element.innerText || '').trim().replace(/\s+/g, ' '),
        href: element.matches('a[href]') ? element.href : '',
      })).filter(({ label }) => Boolean(label));
    const numberedChatRows = chatRows.filter(({ label }) => /\d\s*$/.test(label));
    for (const row of numberedChatRows) {
      problems.push({ item: 6, baselineItem: 7, selector: `chat-row "${row.label}"`, details: 'Chat-list row label ends in a number; review whether the number is needed or identifies duplicate instances.' });
    }
    const rowsByRole = new Map();
    for (const row of chatRows) {
      const role = row.label.replace(/[\s#_-]*\d+\s*$/, '').trim().toLowerCase();
      if (!role) continue;
      rowsByRole.set(role, (rowsByRole.get(role) || 0) + 1);
    }
    for (const [role, count] of rowsByRole) {
      if (count > 1) problems.push({ item: 6, baselineItem: 7, selector: `chat-role "${role}"`, details: `${count} chat-list rows share the same role label; review whether each row needs a distinct, user-facing name.` });
    }
    const rosterSection = [...document.querySelectorAll('main section')]
      .find((section) => /\broster\b/i.test(section.querySelector('h1, h2, h3, [role="heading"]')?.innerText || ''));
    if (rosterSection) {
      for (const row of rosterSection.querySelectorAll('li')) {
        const role = row.querySelector('strong')?.innerText.trim();
        const countText = [...row.querySelectorAll('span')].map((span) => span.innerText.trim()).find((text) => /^\d+$/.test(text));
        const count = Number(countText);
        if (role && count > 1) {
          problems.push({ item: 6, baselineItem: 7, selector: `roster-role "${role}"`, details: `${role} summarizes ${count} agent instances in one row; review whether individual rows need distinct names.` });
        }
      }
    }
    if (/^\/settings(?:\/|$)/.test(routePath)) {
      const hostPattern = /\b(?:localhost|local|127(?:\.\d{1,3}){3}|port|path|socket|host|debug|dev(?:elopment)?|worktree|token\s+(?:path|file))\b|~\/|(?:^|\s)\/(?:Users|home|tmp|etc|var|opt)\/[\w./-]+/i;
      const settingRows = [...document.querySelectorAll('li, tr, [role="row"], [data-setting], [class*="setting-row" i], [class*="setting-item" i], label, p, span')]
        .filter(visible)
        .map((element) => ({ element, text: (element.innerText || '').trim().replace(/\s+/g, ' ') }))
        .filter(({ text }) => text && hostPattern.test(text));
      for (const [index, row] of settingRows.entries()) {
        const selector = row.element.id ? `#${row.element.id}` : `${row.element.tagName.toLowerCase()}[${index}]`;
        hostRows.push({ selector, text: row.text.slice(0, 180) });
      }
      const headingCandidates = [...document.querySelectorAll('main h2, main h3, main h4, main [role="heading"]')]
        .filter(visible);
      const cardCandidates = [...document.querySelectorAll('main article, main section, main div')].map((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const opaqueBackground = style.backgroundColor !== 'rgba(0, 0, 0, 0)'
          && !/rgba\([^)]*,\s*0\s*\)$/.test(style.backgroundColor);
        const hasBorder = ['Top', 'Right', 'Bottom', 'Left'].some((side) => Number.parseFloat(style[`border${side}Width`]) > 0
          && style[`border${side}Style`] !== 'none');
        return {
          element,
          visible: visible(element),
          width: rect.width,
          height: rect.height,
          viewportWidth: innerWidth,
          headingCount: headingCandidates.filter((heading) => element.contains(heading)).length,
          paddingInline: Math.min(Number.parseFloat(style.paddingLeft) || 0, Number.parseFloat(style.paddingRight) || 0),
          borderRadius: Number.parseFloat(style.borderRadius) || 0,
          opaqueBackground,
          hasBorder,
          groups: [...element.querySelectorAll('h2, h3, h4, [role="heading"]')]
            .filter(visible).map((heading) => heading.innerText.trim()).filter(Boolean).slice(0, 6),
        };
      });
      settingsCard.candidates = cardCandidates;
      const isAppearance = /(?:display|appearance)/i.test(routePath)
        || [...document.querySelectorAll('main h1, main h2, main h3')].some((heading) => /\bappearance\b/i.test(heading.innerText));
      if (isAppearance) {
        appearance.found = true;
        const appIconText = [...document.querySelectorAll('main label, main legend, main h2, main h3, main h4, main p, main span')]
          .find((element) => /app\s*icon/i.test(element.innerText || ''));
        if (appIconText) {
          const group = appIconText.closest('fieldset, [role="group"], section, article, li') || appIconText.parentElement;
          const choices = group?.querySelectorAll('input[type="radio"], [role="radio"], [role="option"], button') || [];
          appearance.options = new Set([...choices].filter(visible).map((choice) => choice.getAttribute('value') || choice.getAttribute('aria-label') || choice.innerText.trim())).size;
        } else {
          appearance.options = 0;
        }
      }
    }
    const composerRects = [...document.querySelectorAll('textarea')].filter(visible).map((element) => element.closest('form')?.getBoundingClientRect() ?? element.getBoundingClientRect());
    for (const composer of composerRects) {
      const strip = [...document.querySelectorAll('a, button, [role="status"], [role="alert"], div, p')].find((element) => {
        const rect = element.getBoundingClientRect();
        const words = element.innerText.trim().split(/\s+/).filter(Boolean).length;
        const leaf = !element.querySelector('textarea, form, header');
        return visible(element) && leaf && words > 0 && words <= 3 && rect.width >= 300
          && rect.bottom <= composer.top + 1 && composer.top - rect.bottom <= 16 && rect.height <= 80;
      });
      if (strip) problems.push({ item: 7, selector: `${strip.tagName.toLowerCase()} "${strip.innerText.trim()}"`, details: 'Short status strip sits directly above the composer; confirm it is current, actionable, and not repeated elsewhere.' });
    }
    const statusPattern = /\b(?:online|offline|running|idle|starting|paused|connected|disconnected|healthy|unhealthy|error|failed|unavailable)\b/i;
    for (const header of [...document.querySelectorAll('header')].filter(visible)) {
      const menu = [...header.querySelectorAll('button, a')].some((element) => /menu/i.test(element.getAttribute('aria-label') || ''));
      const back = [...header.querySelectorAll('button, a')].some((element) => /^back\b/i.test(element.getAttribute('aria-label') || ''));
      if (menu && back) problems.push({ item: 5, selector: 'header', details: 'Header shows both a menu control and a Back control: two primary navigation systems in one view.' });
      headerStatus ||= Boolean(header.querySelector('[role="status"], [aria-live], [data-status], [aria-label*="status" i], [aria-label*="health" i], [title*="status" i]'))
        || [...header.querySelectorAll('p, [role="status"], [data-status]')].some((element) => statusPattern.test(element.innerText));
      const menuEntries = header.querySelectorAll('[role="menuitem"], nav a, nav button');
      for (const entry of menuEntries) {
        const label = (entry.getAttribute('aria-label') || entry.innerText || '').trim();
        if (/\b(?:health|status)\b/i.test(label)) menuHealthRows.push(label);
      }
    }
    for (const menu of document.querySelectorAll('[role="menu"], .menu-panel, [role="dialog"]')) {
      if (!visible(menu)) continue;
      for (const entry of menu.querySelectorAll('[role="menuitem"], a, button')) {
        const label = (entry.getAttribute('aria-label') || entry.innerText || '').trim();
        if (/\b(?:health|status)\b/i.test(label)) menuHealthRows.push(label);
      }
    }
    for (const [index, element] of [...document.querySelectorAll('main section, main a, main form, main ul, main ol')].entries()) {
      if (!visible(element)) continue;
      const rect = element.getBoundingClientRect();
      let carded = false;
      for (let ancestor = element.parentElement; ancestor && ancestor !== document.body; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor);
        if (style.backgroundColor !== 'rgba(0, 0, 0, 0)' && Number.parseFloat(style.borderRadius) >= 8) carded = true;
      }
      const offGutter = rect.left > 1 && Math.abs(rect.left - 16) > 1 || (innerWidth - rect.right > 1 && Math.abs(innerWidth - rect.right - 16) > 1);
      if (!carded && rect.width >= 250 && rect.width < innerWidth - 1 && offGutter) {
        problems.push({ item: 3, selector: `${element.tagName.toLowerCase()}[${index}]`, details: `Content block is inset ${Math.round(rect.left)} px left and ${Math.round(innerWidth - rect.right)} px right; the standard gutter is 16 px (extra wrapper or padding?).` });
      }
    }
    for (const [index, element] of [...document.querySelectorAll('input:not([type="checkbox"]):not([type="radio"]), textarea, select')].filter(visible).entries()) {
      const rect = element.getBoundingClientRect();
      const selector = `${element.tagName.toLowerCase()}[${index}]`;
      const isTextarea = element.matches('textarea');
      const heightOutsideTarget = rect.height < 44 || rect.height > 48;
      if (heightOutsideTarget) {
        const target = isTextarea && rect.height > 160 ? '44–48 px and no taller than 160 px' : '44–48 px';
        problems.push({ item: 10, baselineItem: 10, selector, details: `Input is ${Math.round(rect.height)} px tall; expected ${target}.` });
      }
      const container = element.parentElement?.getBoundingClientRect();
      if (container && rect.width > container.width + 1) {
        problems.push({ item: 10, baselineItem: 10, selector, details: `Input width ${Math.round(rect.width)} px exceeds its parent container width ${Math.round(container.width)} px.` });
      }
    }
    const menuButtons = [...document.querySelectorAll('header button, header a, button')]
      .filter((element) => visible(element) && /menu|hamburger/i.test(`${element.getAttribute('aria-label') || ''} ${element.title || ''}`));
    for (const [index, button] of menuButtons.entries()) {
      const buttonRect = button.getBoundingClientRect();
      const bars = [];
      for (const element of button.querySelectorAll('span, i, div')) {
        const rect = element.getBoundingClientRect();
        if (rect.width >= 12 && rect.height > 0 && rect.height <= 4) bars.push({ left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom });
      }
      for (const line of button.querySelectorAll('svg line, svg rect, svg path')) {
        try {
          const box = line.getBBox();
          const matrix = line.getScreenCTM();
          if (!matrix) continue;
          const points = [[box.x, box.y], [box.x + box.width, box.y], [box.x, box.y + box.height], [box.x + box.width, box.y + box.height]]
            .map(([x, y]) => new DOMPoint(x, y).matrixTransform(matrix));
          const xs = points.map((point) => point.x);
          const ys = points.map((point) => point.y);
          const rect = { left: Math.min(...xs), right: Math.max(...xs), top: Math.min(...ys), bottom: Math.max(...ys) };
          if (rect.right - rect.left >= 12 && rect.bottom - rect.top <= 4) bars.push(rect);
        } catch { /* Non-geometric or detached SVG nodes cannot define icon bars. */ }
      }
      bars.sort((a, b) => a.top - b.top);
      if (bars.length < 2) {
        const range = document.createRange();
        range.selectNodeContents(button);
        const iconRect = range.getBoundingClientRect();
        if (iconRect.width > 0 && iconRect.height > 0) {
          const centerOffsetX = (iconRect.left + iconRect.right - buttonRect.left - buttonRect.right) / 2;
          const centerOffsetY = (iconRect.top + iconRect.bottom - buttonRect.top - buttonRect.bottom) / 2;
          if (routePath === '/' && index === 0) {
            problems.push({ item: 9, baselineItem: 11, selector: `menu-button[${index}]`, details: `Menu icon has no separately measurable bars; glyph center offset is ${centerOffsetX.toFixed(1)}×${centerOffsetY.toFixed(1)} px. Review bar lengths and gaps visually.` });
          }
        }
        continue;
      }
      const lengths = bars.map((bar) => bar.right - bar.left);
      const gaps = bars.slice(1).map((bar, barIndex) => bar.top - bars[barIndex].bottom);
      const centerX = bars.reduce((sum, bar) => sum + (bar.left + bar.right) / 2, 0) / bars.length;
      const stackTop = Math.min(...bars.map((bar) => bar.top));
      const stackBottom = Math.max(...bars.map((bar) => bar.bottom));
      const centerOffsetX = centerX - (buttonRect.left + buttonRect.right) / 2;
      const centerOffsetY = (stackTop + stackBottom) / 2 - (buttonRect.top + buttonRect.bottom) / 2;
      const lengthSpread = Math.max(...lengths) - Math.min(...lengths);
      const gapSpread = gaps.length > 1 ? Math.max(...gaps) - Math.min(...gaps) : 0;
      if (lengthSpread > 1.5 || gapSpread > 1.5 || Math.abs(centerOffsetX) > 2 || Math.abs(centerOffsetY) > 2) {
        problems.push({ item: 9, baselineItem: 11, selector: `menu-button[${index}]`, details: `Menu icon bars: length spread ${lengthSpread.toFixed(1)} px, gap spread ${gapSpread.toFixed(1)} px, center offset ${centerOffsetX.toFixed(1)}×${centerOffsetY.toFixed(1)} px.` });
      }
    }
    for (const parent of document.querySelectorAll('main *')) {
      const rows = [...parent.children].filter((child) => visible(child) && (child.innerText || '').trim());
      const signature = rows.length ? `${rows[0].tagName}.${rows[0].className}` : '';
      const similar = rows.filter((row) => `${row.tagName}.${row.className}` === signature);
      if (similar.length >= 15) {
        problems.push({ item: 5, selector: `${parent.tagName.toLowerCase()}>${rows[0].tagName.toLowerCase()} x${similar.length}`, details: `${similar.length} sibling rows with identical structure (one row per instance); group by role or plan with counts, and cap or paginate the list.` });
        break;
      }
    }
    if (document.documentElement.scrollHeight > innerHeight * 3) {
      problems.push({ item: 5, selector: 'document', details: `Page is ${document.documentElement.scrollHeight} px tall (${(document.documentElement.scrollHeight / innerHeight).toFixed(1)} screens); group, collapse, or paginate long lists.` });
    }
    if (document.documentElement.scrollWidth > innerWidth + 1 || document.body.scrollWidth > innerWidth + 1) {
      problems.push({ item: 11, selector: 'document', details: `Horizontal overflow: scrollWidth ${Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)} px, viewport ${innerWidth} px.` });
    }
    return { problems, edgeCandidates, headerStatus, hostRows, menuHealthRows, settingsCard, appearance };
  }, { safeTop, safeBottom, routePath: new URL(route).pathname });
  for (const candidate of result.edgeCandidates) {
    if (hasInsetDescendantContent(candidate)) continue;
    if (candidate.leftInset < 16 || candidate.rightInset < 16) {
      result.problems.push({ item: 3, selector: candidate.selector, details: 'Text-bearing content has less than 16 px horizontal edge padding.' });
    }
  }
  delete result.edgeCandidates;
  const wrapperCard = findSettingsCardWrapper(result.settingsCard.candidates);
  if (wrapperCard) {
    result.settingsCard.found = true;
    result.settingsCard.groups = wrapperCard.groups;
  }
  result.problems.forEach(({ item, baselineItem, selector, details }) => record(item, route, selector, details, baselineItem));
  headerStatusFound ||= result.headerStatus;
  for (const row of result.hostRows) hostDevRows.add(`${route} ${row.selector}: ${row.text}`);
  for (const label of result.menuHealthRows) healthMenuEntries.add(label);
  if (result.settingsCard.found) {
    record(3, route, 'settings-card', `One bordered/background settings container wraps multiple group headings: ${result.settingsCard.groups.join('; ')}.`, 8);
  }
  if (result.appearance.found) {
    checkedAppearanceRoutes.add(route);
    if (result.appearance.options !== 2) {
      record(8, route, 'app-icon-choice', `Settings > Appearance needs an app-icon choice with exactly 2 options; found ${result.appearance.options ?? 0}.`, 13);
    }
  }
}

async function inspectContrast(route, colorScheme) {
  await page.emulateMedia({ colorScheme });
  await page.evaluate(() => new Promise(requestAnimationFrame));
  const contrastProblems = await page.evaluate(() => {
    const rgb = (value) => {
      const components = value.match(/[\d.]+/g)?.map(Number);
      if (components?.length === 4 && components[3] < 1) return null;
      const channels = components?.slice(0, 3);
      return channels?.length === 3 ? channels : null;
    };
    const luminance = (channels) => channels.map((channel) => {
      const value = channel / 255;
      return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
    const visible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const textElements = [...document.querySelectorAll('body *')].filter((element) => visible(element)
      && [...element.childNodes].some((node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim()));
    const problems = [];
    for (const element of textElements) {
      const foreground = rgb(getComputedStyle(element).color);
      if (!foreground) continue;
      let background = null;
      for (let ancestor = element; ancestor; ancestor = ancestor.parentElement) {
        background = rgb(getComputedStyle(ancestor).backgroundColor);
        if (background && getComputedStyle(ancestor).backgroundColor !== 'rgba(0, 0, 0, 0)') break;
        background = null;
      }
      background ||= matchMedia('(prefers-color-scheme: dark)').matches ? [0, 0, 0] : [255, 255, 255];
      const ratio = (Math.max(luminance(foreground), luminance(background)) + 0.05)
        / (Math.min(luminance(foreground), luminance(background)) + 0.05);
      if (ratio < 4.5) {
        const label = element.id ? `#${element.id}` : element.tagName.toLowerCase();
        problems.push({ selector: label, details: `Text contrast is ${ratio.toFixed(2)}:1 against the nearest opaque background.` });
      }
    }
    return problems.slice(0, 30);
  });
  contrastProblems.forEach(({ selector, details }) => record(12, route, selector, details));
}

async function runSyntheticKeyboardCheck(targetPage, route, control, label, engine, index) {
  await targetPage.evaluate(() => window.scrollTo(0, 0));
  await targetPage.evaluate(() => new Promise(requestAnimationFrame));
  const initialScroll = await targetPage.evaluate(() => ({ x: scrollX, y: scrollY }));
  await control.click({ timeout: 2500 }).catch((error) => {
    record(6, route, label, `Input could not be tapped: ${error.message.split('\n')[0]}`);
  });
  await control.evaluate((element) => element.focus({ preventScroll: true }));
  const focusScroll = await targetPage.evaluate(() => ({ x: scrollX, y: scrollY }));
  const isTextarea = await control.evaluate((element) => element.matches('textarea'));
  const simulation = await targetPage.evaluate((height) => {
    if (typeof window.setSyntheticKeyboardHeight !== 'function') return { supported: false };
    window.setSyntheticKeyboardHeight(height);
    return { supported: true };
  }, syntheticViewportHeight);

  const sample = async () => control.evaluate((element) => {
    const composer = element.closest('form, [data-composer], .composer') || element;
    const rect = composer.getBoundingClientRect();
    const action = element.closest('form')?.querySelector('button[type="submit"], input[type="submit"]');
    const actionRect = action?.getBoundingClientRect();
    return {
      top: rect.top,
      bottom: rect.bottom,
      height: rect.height,
      actionBottom: actionRect?.bottom ?? null,
      fontSize: Number.parseFloat(getComputedStyle(element).fontSize),
      viewportHeight: window.visualViewport.height,
      viewportBottom: window.visualViewport.offsetTop + window.visualViewport.height,
      scrollX,
      scrollY,
    };
  });
  const failures = [];
  if (isTextarea) {
    const grown = await control.evaluate(async (element) => {
      if (element.disabled) return null;
      const before = element.getBoundingClientRect().height;
      const original = element.value;
      element.value = 'line 1\nline 2\nline 3\nline 4';
      element.dispatchEvent(new Event('input', { bubbles: true }));
      await new Promise(requestAnimationFrame);
      const after = element.getBoundingClientRect().height;
      element.value = original;
      element.dispatchEvent(new Event('input', { bubbles: true }));
      return { before, after };
    });
    if (grown && grown.after <= grown.before + 2) failures.push(`Composer stays ${Math.round(grown.before)} px tall with 4 lines of text (one line only).`);
  }
  let first;
  let second;
  let closed;
  if (!simulation.supported) {
    failures.push(`${engine} could not replace the visualViewport property with the synthetic height.`);
  } else {
    try {
      await targetPage.evaluate(() => new Promise(requestAnimationFrame));
      first = await sample();
      await targetPage.evaluate(() => new Promise(requestAnimationFrame));
      second = await sample();
      if (second.viewportHeight !== syntheticViewportHeight || second.bottom > second.viewportBottom + 1) {
        failures.push(`Composer bottom ${second.bottom}px exceeds synthetic visual viewport bottom ${second.viewportBottom}px.`);
      }
      if (second.actionBottom !== null && second.actionBottom > second.viewportBottom + 1) {
        failures.push(`Associated form action bottom ${second.actionBottom}px exceeds synthetic visual viewport bottom ${second.viewportBottom}px.`);
      }
      if (initialScroll.x !== 0 || initialScroll.y !== 0 || focusScroll.x !== 0 || focusScroll.y !== 0 || second.scrollX !== 0 || second.scrollY !== 0) {
        failures.push(`Page scroll changed from 0 (initial ${initialScroll.x},${initialScroll.y}; focus ${focusScroll.x},${focusScroll.y}; synthetic ${second.scrollX},${second.scrollY}).`);
      }
      if (isTextarea && second.fontSize < 16) {
        failures.push(`Textarea computed font size is ${second.fontSize}px; expected at least 16px.`);
      }
      if (Math.abs(first.top - second.top) > 1 || Math.abs(first.bottom - second.bottom) > 1) {
        failures.push('Composer geometry did not settle within 1px across animation frames.');
      }
      for (const colorScheme of ['light', 'dark']) {
        await targetPage.emulateMedia({ colorScheme });
        await targetPage.evaluate(() => new Promise(requestAnimationFrame));
        const name = createHash('sha256').update(route).digest('hex').slice(0, 16);
        await targetPage.screenshot({
          path: path.join(screenshots, `${name}-${engine}-keyboard-synthetic-${index}-${colorScheme}-390x420.png`),
          clip: { x: 0, y: 0, width: 390, height: syntheticViewportHeight },
        });
      }
    } finally {
      await targetPage.evaluate((height) => window.setSyntheticKeyboardHeight(height), 844);
      await targetPage.evaluate(() => new Promise(requestAnimationFrame));
      closed = await sample();
    }
    if (closed.viewportHeight <= syntheticViewportHeight) failures.push('Synthetic visual viewport did not restore after keyboard close.');
    if (closed.scrollX !== 0 || closed.scrollY !== 0) failures.push(`Page scroll after synthetic keyboard close is ${closed.scrollX},${closed.scrollY}.`);
  }
  const result = { route, selector: label, engine, syntheticVisualViewportHeight: syntheticViewportHeight, result: failures.length ? 'fail' : 'pass', failures };
  keyboardChecks.push(result);
  if (failures.length) record(4, route, label, `Synthetic ${engine} keyboard check failed: ${failures.join(' ')}`);
}

async function screenshot(route, colorScheme) {
  await page.emulateMedia({ colorScheme });
  const name = createHash('sha256').update(route).digest('hex').slice(0, 16);
  await page.screenshot({ path: path.join(screenshots, `${name}-${colorScheme}-390x844.png`), fullPage: true });
}

async function inspectOpenMenu(route) {
  const labels = await page.evaluate(() => {
    const visible = (element) => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    };
    const surfaces = [...document.querySelectorAll('[role="menu"], .menu-panel, [role="dialog"], header nav, header [role="navigation"]')].filter(visible);
    return surfaces.flatMap((surface) => [...surface.querySelectorAll('[role="menuitem"], a, button')]
      .filter(visible).map((entry) => (entry.getAttribute('aria-label') || entry.innerText || '').trim()))
      .filter((label) => /\b(?:health|status)\b/i.test(label));
  });
  for (const label of labels) healthMenuEntries.add(`${route}: ${label}`);
}

async function interact(route) {
  const selector = 'a[href], button, input, select, textarea, summary, [contenteditable="true"], [role="button"], [role="link"], [role="tab"], [role="checkbox"], [role="switch"], [tabindex]:not([tabindex="-1"])';
  const count = await page.locator(selector).count();
  let dirty = true;
  for (let index = 0; index < count; index += 1) {
    try {
    if (dirty || page.url() !== route) await visit(route);
    dirty = false;
    const control = page.locator(selector).nth(index);
    if (!(await control.isVisible().catch(() => false))) continue;
    const label = await control.evaluate((element) => element.getAttribute('aria-label')
      || element.innerText?.trim() || element.getAttribute('name') || element.tagName.toLowerCase());
    const disabled = await control.evaluate((element) => element.matches(':disabled, [aria-disabled="true"]'));
    const isComposerControl = await control.evaluate((element) => element.matches('#chat-message, .composer textarea, [data-composer]'));
    if (disabled && !isComposerControl) continue;
    const isInput = await control.evaluate((element) => element.matches('input, textarea, select, [contenteditable="true"]'));
    if (isInput) {
      const isComposer = isComposerControl;
      if (isComposer) {
        await runSyntheticKeyboardCheck(page, route, control, label, 'chromium', index);
      } else {
        await control.click({ timeout: 2500 }).catch((error) => {
          record(6, route, label, `Input could not be tapped: ${error.message.split('\n')[0]}`);
        });
        await control.focus();
      }
      dirty = isComposer;
      continue;
    }
    const before = await page.locator('body').innerText().catch(() => '');
    const beforeHtml = await page.locator('body').innerHTML().catch(() => '');
    const beforeUrl = page.url();
    await control.click({ timeout: 2500 }).catch((error) => {
      record(6, route, label, `Control could not be tapped: ${error.message.split('\n')[0]}`);
    });
    await page.waitForTimeout(150);
    const after = await page.locator('body').innerText().catch(() => '');
    const afterHtml = await page.locator('body').innerHTML().catch(() => '');
    dirty = beforeUrl !== page.url() || beforeHtml !== afterHtml;
    if (beforeUrl === page.url() && beforeHtml !== afterHtml) {
      await collectIcons(route);
      await inspectOpenMenu(route);
      await inspectLayout(route);
    }
    if (beforeUrl === page.url() && before === after && beforeHtml === afterHtml) {
      record(6, route, label, 'Tap produced no URL or visible text change; inspect for an expected state change or remove the dead control.');
    }
    } catch (error) {
      dirty = true;
      record(6, route, `control[${index}]`, `Control changed or detached during the walk: ${error.message.split('\n')[0]}`);
    }
  }
}

async function inspectWebkitKeyboardRoutes() {
  if (!webkitBrowser) return;
  for (const route of routes) {
    const webkitContext = await webkitBrowser.newContext({
      ...devices['iPhone 13'],
      viewport: { width: 390, height: 844 },
      deviceScaleFactor: 1,
    });
    await webkitContext.addInitScript(() => {
      let viewportHeight = window.innerHeight;
      const syntheticViewport = new EventTarget();
      Object.defineProperties(syntheticViewport, {
        height: { get: () => viewportHeight },
        offsetTop: { get: () => 0 },
        offsetLeft: { get: () => 0 },
        width: { get: () => window.innerWidth },
        scale: { get: () => 1 },
        pageLeft: { get: () => window.scrollX },
        pageTop: { get: () => window.scrollY },
      });
      Object.defineProperty(window, 'visualViewport', { configurable: true, value: syntheticViewport });
      window.setSyntheticKeyboardHeight = (height) => {
        viewportHeight = height;
        syntheticViewport.dispatchEvent(new Event('resize'));
        syntheticViewport.dispatchEvent(new Event('scroll'));
      };
      document.addEventListener('submit', (event) => event.preventDefault(), true);
    });
    await webkitContext.route('**/*', (requestRoute) => {
      const request = requestRoute.request();
      if (['GET', 'HEAD', 'OPTIONS'].includes(request.method())) return requestRoute.continue();
      blockedWrites.push(`${request.method()} ${request.url()}`);
      return requestRoute.fulfill({ status: 503, body: 'blocked by walk-mobile-ui (read-only)' });
    });
    const webkitPage = await webkitContext.newPage();
    try {
      await webkitPage.goto(route, { waitUntil: 'domcontentloaded' });
    } catch (error) {
      await webkitContext.close();
      record(6, route, 'navigation', `WebKit route failed to load: ${error.message.split('\n')[0]}`);
      continue;
    }
    await settle(webkitPage);
    await addSafeAreaGuides(webkitPage);
    for (const colorScheme of ['light', 'dark']) {
      await webkitPage.emulateMedia({ colorScheme });
      const name = createHash('sha256').update(route).digest('hex').slice(0, 16);
      await webkitPage.screenshot({ path: path.join(screenshots, `${name}-webkit-${colorScheme}-390x844.png`), fullPage: true });
    }
    const composers = webkitPage.locator('#chat-message, .composer textarea, [data-composer]');
    const count = await composers.count();
    for (let index = 0; index < count; index += 1) {
      await runSyntheticKeyboardCheck(webkitPage, route, composers.nth(index), `composer[${index}]`, 'webkit', index);
    }
    await webkitContext.close();
  }
}

try {
  const queue = [routeKey(start.href)];
  while (queue.length && routes.size < maxRoutes) {
    const route = queue.shift();
    if (routes.has(route)) continue;
    if (discoveryOnly && discoveredTemplates.has(discoveryKey(route))) continue;
    let current;
    try {
      current = await visit(route);
      routes.add(route);
      if (discoveryOnly) discoveredTemplates.add(discoveryKey(route));
    } catch (error) {
      routes.add(route);
      record(6, route, 'navigation', `Route failed to load: ${error.message.split('\n')[0]}`);
      continue;
    }
    if (discoveryOnly) {
      const links = await linksOnPage();
      const firstDetail = await firstDetailLinkOnListPage(current);
      if (firstDetail) links.push(firstDetail);
      for (const link of links) {
        const key = routeKey(link);
        const template = discoveryKey(key);
        if (!discoveredTemplates.has(template) && !queue.some((queued) => discoveryKey(queued) === template)) queue.push(key);
      }
      continue;
    }
    await inspectLayout(current);
    await collectIcons(current);
    await screenshot(current, 'light');
    await screenshot(current, 'dark');
    await inspectContrast(current, 'light');
    await inspectContrast(current, 'dark');
    for (const link of await linksOnPage()) {
      const key = routeKey(link);
      if (!routes.has(key) && !queue.includes(key)) queue.push(key);
    }
    await interact(current);
  }
  if (!discoveryOnly) await inspectWebkitKeyboardRoutes();
  for (const [label, variants] of labelVariants) {
    if (variants.size > 1) record(9, 'all', label, `Same control renders differently across routes: ${[...variants].map(([text, route]) => `"${text}" on ${route.replace(start.origin, '')}`).join('; ')}.`);
  }
  if (iconFamilies.glyph.size && iconFamilies.svg.size) {
    record(9, 'all', 'icons', `Mixed icon families: text glyphs (${[...iconFamilies.glyph].slice(0, 8).join(', ')}) and SVG icons (${[...iconFamilies.svg].slice(0, 4).join(', ')}).`);
  }
  for (const row of hostDevRows) {
    const separator = row.indexOf(' ');
    const route = row.slice(0, separator);
    const details = row.slice(separator + 1);
    record(8, route, 'settings-row', `review: host/dev-specific — ${details}`, 9);
  }
  for (const label of healthMenuEntries) {
    record(5, 'all', 'menu-entry', `Health/status entry appears in a menu: ${label}.`, 14);
  }
  if (!headerStatusFound) {
    record(5, start.href, 'header-status', 'No status/health indicator was found in any visible header.', 14);
  }
  if (!checkedAppearanceRoutes.size) {
    record(8, 'all', 'appearance-route', 'Settings > Appearance route was not discovered, so its app-icon choice could not be checked.', 13);
  }
  const baselineRuleSummary = [7, 8, 9, 10, 11, 13, 14].map((baselineItem) => {
    const count = findings.filter((finding) => finding.baselineItem === baselineItem).length;
    return { item: baselineItem, status: count ? 'fired' : 'clear', findings: count };
  });
  const report = {
    viewport: '390x844 CSS px (Chromium iPhone 13 emulation)',
    keyboardSimulation: `synthetic visualViewport.height=${syntheticViewportHeight}px; no operating-system keyboard is shown`,
    safeAreaSimulation: { method: 'Chromium Emulation.setSafeAreaInsetsOverride', top: safeTop, bottom: safeBottom },
    browserCoverage: { chromium: 'tested', webkit: webkitStatus, webkitRoutes: [...routes] },
    realDeviceCheckpoints,
    routeLimitReached: routes.size >= maxRoutes && queue.length > 0,
    routes: [...routes],
    screenshots: 'screenshots/',
    blockedWrites,
    keyboardChecks,
    baselineRuleSummary,
    findings,
  };
  await fs.writeFile(path.join(output, 'findings.json'), `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify({ routes: routes.size, findings: findings.length, output }, null, 2));
} finally {
  await webkitBrowser?.close().catch(() => {});
  await browser.close();
}
