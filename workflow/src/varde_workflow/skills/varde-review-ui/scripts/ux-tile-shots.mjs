#!/usr/bin/env node
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { findBottomControls, formatTileIndex, headerHeight as calculateHeaderHeight, normalizePng, pngHeight, pngWidth, routeList, routeTemplate, selectRouteSamples, tileGrid, tileIsValid, tileViewportPosition, shouldDropTile } from './ux-visual-helpers.mjs';
import { fileURLToPath } from 'node:url';
const [startUrl, outputArg = 'ux-tile-shots'] = process.argv.slice(2);
if (!startUrl) throw new Error('Usage: node ux-tile-shots.mjs <url> [output-directory]');
const output = path.resolve(outputArg); await fs.mkdir(output, { recursive: true });
const routeLimit = process.env.VARDE_UX_MAX_ROUTES || '1000';
const discoveryDir = await fs.mkdtemp(path.join(os.tmpdir(), 'varde-route-walk-'));
const walkPath = new URL('./walk-mobile-ui.mjs', import.meta.url).pathname;
const walk = spawnSync(process.execPath, [walkPath, startUrl, discoveryDir], { encoding: 'utf8', env: { ...process.env, VARDE_UX_DISCOVERY_ONLY: '1', VARDE_UX_MAX_ROUTES: routeLimit } });
if (walk.status !== 0) throw new Error(`Route discovery walk failed: ${walk.stderr || walk.stdout}`);
const discovery = JSON.parse(await fs.readFile(path.join(discoveryDir, 'findings.json'), 'utf8'));
const discoveredRoutes = routeList(discovery.routes, startUrl);
const representatives = new Map();
for (const route of discoveredRoutes) if (!representatives.has(routeTemplate(route))) representatives.set(routeTemplate(route), route);
const routeRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../../runner/ui/src/routes');
async function pageTemplates(directory = routeRoot, parent = '') {
  const templates = [];
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    const segment = /^\[.*\]$/.test(entry.name) ? '<id>' : entry.name;
    const route = `${parent}/${segment}`;
    const child = path.join(directory, entry.name);
    if ((await fs.readdir(child)).includes('+page.svelte')) templates.push(route.replace(/\[[^\]]+\]/g, '<id>') || '/');
    templates.push(...await pageTemplates(child, route));
  }
  return templates;
}
const appTemplates = [...new Set(await pageTemplates())];
const requiredSamples = [
  '/plans/ux-review-seed-agent',
  '/thread/manager',
  '/threads/plan:ux-review-seed-agent',
  '/profile/ux-review-seed-agent',
  '/jobs',
  '/settings/display',
  '/settings/harnesses',
  '/settings/model-types',
  '/settings/review',
  '/settings/role-types',
  '/settings/runner',
  '/settings/status',
];
for (const sample of requiredSamples) {
  const template = routeTemplate(new URL(sample, startUrl));
  const sampleUrl = new URL(sample, startUrl).href;
  if (appTemplates.includes(template) && ![...representatives.values()].includes(sampleUrl)) {
    representatives.set(`${template}:${sample}`, sampleUrl);
  }
}
const representedTemplates = new Set([...representatives.keys()].map((key) => key.split(':')[0]));
const excludedTemplates = appTemplates.filter((template) => !representedTemplates.has(template));
const unavailableRequiredTemplates = ['/roles/<id>'].filter((template) => !appTemplates.includes(template));
const exclusions = [...excludedTemplates.map((template) => `${template}: No route instance was discoverable from the app entry point.`), ...unavailableRequiredTemplates.map((template) => `${template}: No matching page route exists under runner/ui/src/routes.`)];
const routes = selectRouteSamples([...representatives.values()], process.env.VARDE_UX_CAPTURE_ROUTES?.split(',').map((route) => route.trim()).filter(Boolean), startUrl);
if (process.env.VARDE_UX_DISCOVERY_ONLY === '1') {
  await fs.writeFile(path.join(output, 'discovered-routes.json'), `${JSON.stringify({ routes, routeLimitReached: discovery.routeLimitReached }, null, 2)}\n`);
  await fs.writeFile(path.join(output, 'index.md'), `# Discovered UX routes\n\n${discovery.routeLimitReached ? `> Route discovery reached its ${routeLimit}-route cap.\n\n` : ''}## Excluded route templates\n\n${exclusions.map((item) => `- ${item}`).join('\n') || '- None.'}\n\n${routes.map((route) => `- ${route}`).join('\n')}\n`);
  await fs.rm(discoveryDir, { recursive: true, force: true });
  console.log(JSON.stringify({ routes: routes.length, routeLimitReached: discovery.routeLimitReached, output }, null, 2));
  process.exit(0);
}
const require = createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../../runner/ui/package.json')); const { chromium, webkit, devices } = require('playwright');
const browsers = { chromium: await chromium.launch({ headless: true, args: ['--no-sandbox'] }), webkit: await webkit.launch({ headless: true }) };
const entries = [];
try {
  for (const route of routes) for (const [browserName, viewport, mobile] of [['webkit', { width: 390, height: 844 }, true], ['chromium', { width: 1280, height: 800 }, false], ['webkit', { width: 1280, height: 800 }, false]]) for (const scheme of ['light', 'dark']) {
    const browser = browsers[browserName];
    const context = await browser.newContext({ ...(mobile ? devices['iPhone 13'] : {}), viewport, isMobile: mobile, hasTouch: mobile, deviceScaleFactor: 1, colorScheme: scheme });
    const page = await context.newPage(); await page.goto(route, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 4000 }).catch(() => {});
    await page.waitForFunction(() => document.body?.innerText.trim().length > 0, null, { timeout: 5000 }).catch(() => {});
    const loaded = await page.waitForFunction(() => {
      if (!document.body?.innerText.trim()) return false;
      const skeleton = document.querySelector('.skeleton, [class*="skeleton"], .loading-list, .loading-status, .loading-sweep, .loading-review');
      const skeletonSelector = '.skeleton, [class*="skeleton"], .loading-list, .loading-status, .loading-sweep, .loading-review';
      const visibleText = [...document.querySelectorAll('body *')].filter((element) => {
        if (element.children.length || element.closest(skeletonSelector)) return false;
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0
          && !/^\s*loading\b/i.test(element.textContent || '');
      }).map((element) => element.textContent).join(' ');
      const ariaBusy = Boolean(document.querySelector('[aria-busy="true"]'));
      const hasLoadingText = [...document.querySelectorAll('body *')].some((element) => element.children.length === 0 && /^\s*loading\b/i.test(element.textContent || ''));
      return Boolean(visibleText.trim()) && !skeleton && !ariaBusy && !hasLoadingText;
    }, null, { timeout: 30000 }).then(() => true).catch(() => false);
    await page.evaluate(() => document.fonts?.ready); await page.waitForTimeout(250);
    const routeSlug = new URL(route).pathname.replace(/[^a-z0-9]+/gi, '_') || 'home';
    const routeId = createHash('sha1').update(route).digest('hex').slice(0, 8);
    const image = path.join(output, `${routeSlug}-${routeId}-${browserName}-${viewport.width}x${viewport.height}-${scheme}.png`);
    const dimensions = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight }));
    const headerCandidates = await page.evaluate(() => {
      return [...document.querySelectorAll('body *')].map((element) => {
        const position = getComputedStyle(element).position;
        const rect = element.getBoundingClientRect();
        return { position, top: rect.top, width: rect.width, height: rect.height };
      });
    });
    const headerHeight = calculateHeaderHeight(headerCandidates, viewport);
    const tileWidth = mobile ? viewport.width : 540; const tileHeight = Math.min(500, viewport.height - headerHeight);
    const files = []; let droppedUniformTiles = 0;
    const generatedTiles = tileGrid(dimensions.width, dimensions.height, tileWidth, tileHeight, mobile ? 0 : 32, mobile ? 0 : 320);
    const allTiles = generatedTiles.slice(0, 8);
    const truncatedTiles = generatedTiles.length - allTiles.length;
    for (const tile of allTiles) {
      const file = path.join(output, `${path.basename(image, '.png')}-r${tile.row + 1}-c${tile.column + 1}.png`);
      const position = tileViewportPosition(tile.y, dimensions.height, viewport.height, headerHeight);
      const keepHeader = tile.row === 0 && tile.column === 0;
      await page.evaluate(({ y, minPageHeight, hideSticky }) => {
        if (hideSticky) {
          const style = document.createElement('style');
          style.textContent = '[data-varde-hidden-for-tile]{visibility:hidden!important}';
          document.head.append(style);
          for (const element of document.querySelectorAll('body *')) {
            const position = getComputedStyle(element).position;
            const height = element.getBoundingClientRect().height;
            if ((position === 'fixed' || position === 'sticky') && height > 0 && height < innerHeight * 0.3) element.setAttribute('data-varde-hidden-for-tile', '');
          }
        }
        document.documentElement.style.minHeight = `${minPageHeight}px`;
        window.scrollTo(0, y);
      }, { y: position.scrollTop, minPageHeight: position.minPageHeight, hideSticky: !keepHeader });
      await page.waitForTimeout(50);
      const clipY = keepHeader ? 0 : position.clipY;
      const clip = { x: tile.x, y: clipY, width: Math.min(tile.width, viewport.width - tile.x), height: Math.min(tile.height, viewport.height - clipY) };
      const png = file;
      let pngBytes = await page.screenshot({ type: 'png', clip });
      let dropTile = false;
      {
        const tileContent = await page.evaluate(async ({ data, clip }) => {
          const image = new Image(); image.src = `data:image/png;base64,${data}`; await image.decode();
          const canvas = document.createElement('canvas'); canvas.width = image.width; canvas.height = image.height;
          const context = canvas.getContext('2d'); context.drawImage(image, 0, 0);
          const colours = []; const { data: pixels } = context.getImageData(0, 0, image.width, image.height);
          for (let y = 0; y < image.height; y += 12) for (let x = 0; x < image.width; x += 12) {
            const offset = (y * image.width + x) * 4; colours.push(`${pixels[offset] >> 4},${pixels[offset + 1] >> 4},${pixels[offset + 2] >> 4}`);
          }
          const skeletonSelector = '.skeleton, [class*="skeleton"], .loading-list, .loading-status, .loading-sweep, .loading-review';
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          const visibleText = [];
          while (walker.nextNode()) {
            const node = walker.currentNode; const text = node.textContent.trim(); const parent = node.parentElement;
            if (!text || !parent || parent.closest(skeletonSelector) || /^loading\b/i.test(text)) continue;
            const style = getComputedStyle(parent); const rect = document.createRange(); rect.selectNodeContents(node);
            const bounds = rect.getBoundingClientRect();
            if (style.visibility === 'hidden' || style.display === 'none' || bounds.width === 0 || bounds.height === 0) continue;
            if (bounds.right > clip.x && bounds.left < clip.x + clip.width && bounds.bottom > clip.y && bounds.top < clip.y + clip.height) visibleText.push(text);
          }
          return { colours, visibleText: visibleText.join(' ') };
        }, { data: pngBytes.toString('base64'), clip });
        if (shouldDropTile(tileContent.colours, tileContent.visibleText)) {
          droppedUniformTiles += 1;
          dropTile = true;
          break;
        }
      }
      if (dropTile) continue;
      if (pngBytes.length > 150_000) {
        const compressed = await page.evaluate(async ({ data }) => {
          const image = new Image(); image.src = `data:image/png;base64,${data}`; await image.decode();
          for (let scale = 0.95; scale >= 0.4; scale -= 0.05) {
            const canvas = document.createElement('canvas');
            canvas.width = Math.round(image.width * scale); canvas.height = Math.round(image.height * scale);
            const context = canvas.getContext('2d'); context.drawImage(image, 0, 0, canvas.width, canvas.height);
            const encoded = canvas.toDataURL('image/png').split(',')[1];
            if (Math.floor(encoded.length * 3 / 4) <= 150_000) return encoded;
          }
          return '';
        }, { data: pngBytes.toString('base64') });
        pngBytes = Buffer.from(compressed, 'base64');
      }
      pngBytes = normalizePng(pngBytes);
      const tileDimensions = { width: pngWidth(pngBytes), height: pngHeight(pngBytes), bytes: pngBytes.length };
      if (!tileIsValid(tileDimensions)) throw new Error(`PNG tile violates viewability limits: ${path.basename(png)} ${JSON.stringify(tileDimensions)}`);
      await fs.writeFile(png, pngBytes);
      files.push({ name: path.basename(png), kind: 'PNG', bytes: pngBytes.length, width: tileDimensions.width, height: tileDimensions.height, stillLoading: !loaded, captureValid: true });
    }
    await page.evaluate(() => {
      for (const element of document.querySelectorAll('[data-varde-hidden-for-tile]')) element.removeAttribute('data-varde-hidden-for-tile');
      for (const style of document.querySelectorAll('style')) if (style.textContent.includes('data-varde-hidden-for-tile')) style.remove();
      for (const element of document.querySelectorAll('body *')) {
        if (element.scrollHeight > element.clientHeight + 4) element.scrollTop = element.scrollHeight;
      }
      document.documentElement.style.minHeight = '';
      window.scrollTo(0, 0);
    });
    await page.waitForTimeout(50);
    const bottomCandidates = await page.evaluate(() => [...document.querySelectorAll('body *')].map((element) => {
      const style = getComputedStyle(element); const rect = element.getBoundingClientRect();
      return { position: style.position, left: rect.left, top: rect.top, bottom: rect.bottom, width: rect.width, height: rect.height };
    }));
    const bottomControl = findBottomControls(bottomCandidates, viewport);
    if (bottomControl) {
      const x = mobile ? 0 : Math.min(Math.max(0, bottomControl.left), viewport.width - tileWidth);
      const stickyHeight = 500;
      const stickyClip = { x, y: Math.max(0, viewport.height - stickyHeight), width: Math.min(tileWidth, viewport.width - x), height: Math.min(stickyHeight, viewport.height) };
      const stickyPath = path.join(output, `${path.basename(image, '.png')}-sticky-bottom.png`);
      const stickyBytes = normalizePng(await page.screenshot({ type: 'png', clip: stickyClip }));
      const stickyDimensions = { width: pngWidth(stickyBytes), height: pngHeight(stickyBytes), bytes: stickyBytes.length };
      if (!tileIsValid(stickyDimensions)) throw new Error(`Sticky bottom PNG violates viewability limits: ${path.basename(stickyPath)}`);
      await fs.writeFile(stickyPath, stickyBytes);
      files.push({ name: path.basename(stickyPath), kind: 'PNG', bytes: stickyBytes.length, width: stickyDimensions.width, height: stickyDimensions.height, stickyBottom: true });
    }
    entries.push({ route, viewport: `${viewport.width}x${viewport.height} ${browserName}`, scheme, loaded, files, truncatedTiles, droppedUniformTiles });
    await context.close();
  }
} finally { await Promise.all(Object.values(browsers).map((browser) => browser.close())); await fs.rm(discoveryDir, { recursive: true, force: true }); }
for (const entry of entries) for (const tile of entry.files) tile.suspicious = !tileIsValid(tile);
const index = `${formatTileIndex(entries)}\n## Excluded route templates\n\n${exclusions.map((item) => `- ${item}`).join('\n') || '- None.'}\n`;
await fs.writeFile(path.join(output, 'index.md'), `${discovery.routeLimitReached ? `> Route discovery reached its ${routeLimit}-route cap. Start from other entry routes to expand coverage.\n\n` : ''}${index}`);
if (entries.some((entry) => entry.files.some((file) => file.suspicious))) throw new Error('One or more generated tiles violate viewability limits; see index.md for validation details.');
console.log(JSON.stringify({ routes: routes.length, routeLimitReached: discovery.routeLimitReached, captures: entries.length, output }, null, 2));
