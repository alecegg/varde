#!/usr/bin/env node
import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const [target, outputArg = 'ux-preflight'] = process.argv.slice(2);
if (!target) {
  console.error('Usage: node ux-preflight.mjs <scratch-runner-url> [output-directory]');
  process.exit(2);
}
let url;
try {
  url = new URL(target);
} catch {
  console.error('BLOCKED: provide a valid scratch runner URL.');
  process.exit(1);
}
if (!['http:', 'https:'].includes(url.protocol)) {
  console.error('BLOCKED: scratch runner URL must use HTTP or HTTPS.');
  process.exit(1);
}
if (url.port === '8765') {
  console.error('BLOCKED: port 8765 is reserved for the live runner.');
  process.exit(1);
}

let playwright;
try {
  const packagePath = new URL('../../../../../../runner/ui/package.json', import.meta.url);
  playwright = createRequire(fileURLToPath(packagePath))('playwright');
} catch (error) {
  console.error(`BLOCKED: Playwright is unavailable: ${error.message}`);
  process.exit(1);
}
const { chromium, webkit, devices } = playwright;
const output = path.resolve(outputArg);
try {
  await fs.mkdir(output, { recursive: true });
} catch (error) {
  console.error(`BLOCKED: screenshot output is unavailable: ${error.message}`);
  process.exit(1);
}
let chromiumBrowser;
let webkitBrowser;
try {
  chromiumBrowser = await chromium.launch({ headless: true });
  webkitBrowser = await webkit.launch({ headless: true });
  const contexts = [
    { browser: chromiumBrowser, name: 'chromium', options: {} },
    { browser: webkitBrowser, name: 'webkit-iphone', options: devices['iPhone 13'] },
  ];
  for (const { browser, name, options } of contexts) {
    const page = await browser.newPage({ ...options, viewport: { width: 390, height: 844 } });
    const response = await page.goto(url.href, { waitUntil: 'networkidle', timeout: 15000 });
    if (!response?.ok()) throw new Error(`${name}: scratch runner returned ${response?.status() ?? 'no response'}`);
    await page.waitForFunction(() => document.body?.innerText.trim().length > 0, null, { timeout: 10000 });
    await page.evaluate(() => document.fonts?.ready);
    await page.waitForTimeout(500);
    const rendered = await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width = innerWidth; canvas.height = innerHeight;
      const context = canvas.getContext('2d'); if (!context) return false;
      context.fillStyle = getComputedStyle(document.body).backgroundColor || 'white'; context.fillRect(0, 0, canvas.width, canvas.height);
      const nodes = [...document.body.querySelectorAll('body,body *')].filter((node) => {
        const rect = node.getBoundingClientRect(); const style = getComputedStyle(node);
        return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
      });
      return document.body.innerText.trim().length > 0 && nodes.length > 3;
    });
    if (!rendered) throw new Error(`${name}: screenshot appears blank (no rendered page content)`);
    await page.screenshot({ path: path.join(output, `${name}.png`) });
    const menu = page.getByRole('button', { name: /menu|navigation|open/i }).first();
    const target = await menu.isVisible().catch(() => false)
      ? menu
      : page.locator('button:visible:not(:disabled), a:visible[href]').first();
    if (await target.count() === 0) throw new Error(`${name}: no visible interactive control to drive`);
    await target.click();
    await page.close();
  }
} catch (error) {
  console.error(`BLOCKED: ${error.message}`);
  process.exitCode = 1;
} finally {
  await Promise.all([chromiumBrowser?.close(), webkitBrowser?.close()]);
}
if (!process.exitCode) {
  console.log(`Preflight passed. Inspect and record both screenshots in ${output}; visual viewing is required.`);
}
