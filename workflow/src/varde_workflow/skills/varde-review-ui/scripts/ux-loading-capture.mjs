#!/usr/bin/env node
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import os from 'node:os';
import { countEmptyStateFlashes, formatLoadingReport, isEmptyLoadingState, routeList, tileGrid } from './ux-visual-helpers.mjs';
import { fileURLToPath } from 'node:url';
const [startUrl, outputArg = 'ux-loading-capture'] = process.argv.slice(2);
if (!startUrl) throw new Error('Usage: node ux-loading-capture.mjs <url> [output-directory]');
const output = path.resolve(outputArg); await fs.mkdir(output, { recursive: true });
const discoveryDir = process.env.VARDE_UX_SINGLE_ROUTE === '1' ? null : await fs.mkdtemp(path.join(os.tmpdir(), 'varde-route-walk-'));
let routes; let routeLimitReached = false;
if (discoveryDir) {
  const walkPath = new URL('./walk-mobile-ui.mjs', import.meta.url).pathname;
  const walk = spawnSync(process.execPath, [walkPath, startUrl, discoveryDir], { encoding: 'utf8', env: { ...process.env, VARDE_UX_DISCOVERY_ONLY: '1', VARDE_UX_MAX_ROUTES: process.env.VARDE_UX_MAX_ROUTES || '1000' } });
  if (walk.status !== 0) throw new Error(`Route discovery walk failed: ${walk.stderr || walk.stdout}`);
  const discovery = JSON.parse(await fs.readFile(path.join(discoveryDir, 'findings.json'), 'utf8'));
  routes = routeList(discovery.routes, startUrl);
  routeLimitReached = discovery.routeLimitReached;
} else routes = routeList([startUrl], startUrl);
const require = createRequire(path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../../../../runner/ui/package.json')); const { chromium } = require('playwright');
const browser = await chromium.launch({ headless: true }); const results = [];
try {
  for (const route of routes) {
    const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const navigation = await page.goto(route, { waitUntil: 'domcontentloaded' });
    const popoverState = await page.evaluate(() => {
      const hasTrigger = document.querySelector('[aria-haspopup],[data-popover-trigger],[data-dialog-trigger],[data-sdk-review-trigger]') !== null;
      const open = [...document.querySelectorAll('dialog[open],[popover]:popover-open,[aria-expanded="true"]')]
        .filter((element) => element.checkVisibility?.() !== false);
      return { hasTrigger, openOnLoad: open.length > 0, openElements: open.map((element) => element.getAttribute('aria-label') || element.textContent?.trim().slice(0, 80) || element.tagName) };
    });
    const frames = []; const emptyFrames = []; let statusFrames = 0; let sawEmptyState = false;
    await page.addInitScript(() => { window.__uxShifts = 0; new PerformanceObserver((entries) => { for (const entry of entries.getEntries()) if (!entry.hadRecentInput) window.__uxShifts += entry.value; }).observe({ type: 'layout-shift', buffered: true }); });
    const start = Date.now(); let firstContentMs = null;
    for (let elapsed = 0; elapsed <= 3000; elapsed += 100) {
      const frame = path.join(output, `frame-${String(results.length + 1).padStart(2, '0')}-${String(elapsed).padStart(4, '0')}.png`);
      const state = await page.evaluate(() => ({ text: document.querySelector('main')?.innerText || '', shift: window.__uxShifts || 0 }));
      if (firstContentMs === null && state.text.trim()) firstContentMs = elapsed;
      const emptyState = isEmptyLoadingState(state.text);
      emptyFrames.push(emptyState); sawEmptyState ||= emptyState;
      if (elapsed >= 1000 && /\b(Online|Retrying|Connecting)\b/i.test(state.text)) statusFrames += 1;
      await page.screenshot({ path: frame }); frames.push(frame);
      await page.waitForTimeout(Math.max(0, start + elapsed + 100 - Date.now()));
    }
    const layoutShift = await page.evaluate(() => window.__uxShifts || 0);
    for (const frame of frames) {
      const elapsed = Number(path.basename(frame).match(/-(\d{4})\.png$/)?.[1] || 0);
      for (const tile of tileGrid(390, 844, 390, 422)) {
        const target = path.join(output, `frame-${String(results.length + 1).padStart(2, '0')}-${String(elapsed).padStart(4, '0')}-tile-${tile.row + 1}.png`);
        const crop = spawnSync('sips', ['--cropToHeightWidth', String(tile.height), String(tile.width), '--cropOffset', String(tile.y), '0', '--out', target, frame], { encoding: 'utf8' });
        if (crop.status !== 0) throw new Error(`Could not tile frame ${frame}: ${crop.stderr}`);
      }
    }
    const emptyStateFlashes = countEmptyStateFlashes(emptyFrames);
    results.push({ route, status: navigation?.status(), firstContentMs, layoutShift, emptyStateFlashes, observedEmptyState: sawEmptyState, persistentStatus: statusFrames >= 15, popoverTrigger: popoverState.hasTrigger, popoverOpenOnLoad: popoverState.openOnLoad, openElements: popoverState.openElements, frames: frames.map((frame) => path.basename(frame)), tilePattern: 'frame-*-tile-{1,2}.png' }); await page.close();
  }
} finally { await browser.close(); if (discoveryDir) await fs.rm(discoveryDir, { recursive: true, force: true }); }
await fs.writeFile(path.join(output, 'report.json'), JSON.stringify({ intervalMs: 100, durationMs: 3000, routeLimitReached, routes: results }, null, 2));
await fs.writeFile(path.join(output, 'report.md'), formatLoadingReport(results, routeLimitReached));
if (results.some((result) => result.popoverTrigger && result.popoverOpenOnLoad)) throw new Error('A page with a popover/dialog trigger was open on load; see report.json.');
console.log(JSON.stringify({ routes: results.length, output }, null, 2));
