import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium } from 'playwright';

const host = '127.0.0.1';
const port = 4174;
const origin = `http://${host}:${port}`;
const routes = ['/', '/chat/needs', '/thread/manager', '/threads/example', '/settings'];
const uiRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const cachedChromium = resolve(process.env.PLAYWRIGHT_BROWSERS_PATH ?? '', 'chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing');
const server = spawn(process.execPath, [resolve(uiRoot, 'node_modules/vite/bin/vite.js'), '--host', host, '--port', String(port), '--strictPort'], {
  cwd: uiRoot,
  stdio: 'ignore',
  env: process.env,
});
let browser;

async function waitForServer() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(origin);
      if (response.ok) return;
    } catch { /* Vite is still starting. */ }
    await delay(250);
  }
  throw new Error(`Vite did not start at ${origin}`);
}

try {
  await waitForServer();
  browser = await chromium.launch({ headless: true, executablePath: cachedChromium });
  for (const theme of ['light', 'dark']) {
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 },
      screen: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      deviceScaleFactor: 3,
    });

    for (const route of routes) {
      const page = await context.newPage();
      const cdp = await context.newCDPSession(page);
      await cdp.send('Emulation.setSafeAreaInsetsOverride', { insets: { top: 47, right: 0, bottom: 34, left: 0 } });
      await page.addInitScript((mode) => localStorage.setItem('varde:theme', mode), theme);
      const iconChoice = theme === 'dark' ? 'dark' : 'slate-bronze';
      await page.route('**/api/settings', (route) => route.fulfill({ json: { app_icon: iconChoice } }));
      await page.goto(`${origin}${route}`, { waitUntil: 'domcontentloaded' });

      const header = page.locator('.app-header');
      await header.waitFor();
      assert.equal(await header.count(), 1, `${theme} ${route}: expected one shared header`);
      assert.equal(await header.locator('.health').getAttribute('href'), '/settings/status');
      const expectedIcon = iconChoice === 'dark' ? '/icons/dark/favicon-32.png' : '/favicon.svg';
      await page.waitForFunction((expected) => document.querySelector('.wordmark img')?.getAttribute('src') === expected, expectedIcon);
      await page.waitForFunction(() => {
        const image = document.querySelector('.wordmark img');
        return image?.complete && image.naturalWidth > 0;
      });
      assert.ok(await header.locator('.wordmark img').evaluate((image) => image.complete && image.naturalWidth > 0), `${theme} ${route}: app icon failed to load`);
      assert.match(await page.locator('meta[name="viewport"]').getAttribute('content'), /viewport-fit=cover/);

      const metrics = await header.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const left = element.querySelector('.side.left').getBoundingClientRect();
        const right = element.querySelector('.side.right').getBoundingClientRect();
        const title = element.querySelector('.title').getBoundingClientRect();
        const menu = element.querySelector('.menu-button').getBoundingClientRect();
        return {
          x: rect.x,
          width: rect.width,
          paddingLeft: parseFloat(style.paddingLeft),
          paddingRight: parseFloat(style.paddingRight),
          paddingTop: parseFloat(style.paddingTop),
          leftWidth: left.width,
          rightWidth: right.width,
          titleCenter: title.x + title.width / 2,
          menu: { x: menu.x, y: menu.y, width: menu.width, height: menu.height },
          scrollWidth: document.documentElement.scrollWidth,
        };
      });
      assert.ok(metrics.paddingLeft >= 16 && metrics.paddingRight >= 16, `${theme} ${route}: header gutter below 16px`);
      assert.ok(metrics.paddingTop >= 47, `${theme} ${route}: header safe top below 47px`);
      assert.ok(Math.abs(metrics.leftWidth - metrics.rightWidth) <= 0.5, `${theme} ${route}: unequal header side slots`);
      assert.ok(Math.abs(metrics.titleCenter - 195) <= 1, `${theme} ${route}: title is off center`);
      assert.equal(metrics.menu.width, 44);
      assert.equal(metrics.menu.height, 44);
      assert.ok(metrics.menu.x >= 16);
      assert.ok(metrics.scrollWidth <= 390, `${theme} ${route}: horizontal overflow ${metrics.scrollWidth}`);
      const hamburgerPath = await header.locator('.menu-button svg path').getAttribute('d');
      const bars = [...hamburgerPath.matchAll(/M(\d+)\s(\d+)h(\d+)/g)].map(([, x, y, width]) => ({ x: Number(x), y: Number(y), width: Number(width) }));
      assert.equal(bars.length, 3, `${theme} ${route}: expected three hamburger bars`);
      assert.deepEqual(bars.map(({ x, width }) => [x, width]), [[4, 16], [4, 16], [4, 16]]);
      assert.deepEqual([bars[1].y - bars[0].y, bars[2].y - bars[1].y], [6, 6]);
      if (route === '/') {
        assert.equal(await page.locator('.chat-list .top').count(), 0, 'landing still renders its duplicate header');
        assert.ok(await page.getByRole('link', { name: 'New conversation' }).isVisible(), 'new conversation action is missing');
        assert.ok(await page.getByRole('button', { name: 'Edit' }).isVisible(), 'chat list edit controls are missing');
      }

      const panelButton = page.getByRole('button', { name: 'Open menu' });
      await panelButton.click();
      const panel = page.locator('.menu-panel');
      await panel.waitFor({ state: 'visible' });
      const menuMetrics = await panel.evaluate((element) => {
        const style = getComputedStyle(element);
        return {
          paddingTop: parseFloat(style.paddingTop),
          paddingRight: parseFloat(style.paddingRight),
          paddingBottom: parseFloat(style.paddingBottom),
          paddingLeft: parseFloat(style.paddingLeft),
          scrollWidth: document.documentElement.scrollWidth,
        };
      });
      assert.ok(menuMetrics.paddingTop >= 47 && menuMetrics.paddingBottom >= 34, `${theme} ${route}: menu ignored safe area`);
      assert.ok(menuMetrics.paddingLeft >= 16 && menuMetrics.paddingRight >= 16, `${theme} ${route}: menu gutter below 16px`);
      assert.ok(menuMetrics.scrollWidth <= 390, `${theme} ${route}: menu has horizontal overflow`);
      await page.keyboard.press('Escape');
      await panel.waitFor({ state: 'hidden' });
      console.log(`${theme} ${route}: ${JSON.stringify(metrics)}`);
      await page.close();
    }
    await context.close();
  }

  const desktop = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await desktop.goto(`${origin}/settings`, { waitUntil: 'domcontentloaded' });
  await desktop.locator('.app-header').waitFor();
  assert.equal(await desktop.locator('.app-header .health').count(), 1);
  assert.equal(await desktop.locator('.desktop-chat-sidebar .health').count(), 0);
  assert.equal(await desktop.getByRole('button', { name: 'Open menu' }).isVisible(), false);
  console.log('desktop /settings: shared status stays in header; desktop sidebar retains its navigation');
  await desktop.goto(`${origin}/thread/manager`, { waitUntil: 'domcontentloaded' });
  await desktop.locator('.chat-shell.thread-route').waitFor();
  const desktopThreadBounds = await desktop.evaluate(() => {
    const sidebar = document.querySelector('.desktop-chat-sidebar').getBoundingClientRect();
    const shell = document.querySelector('.chat-shell.thread-route').getBoundingClientRect();
    return { sidebarRight: sidebar.right, shellLeft: shell.left, shellRight: shell.right, viewportWidth: innerWidth };
  });
  assert.ok(desktopThreadBounds.shellLeft >= desktopThreadBounds.sidebarRight, `desktop thread overlaps sidebar: ${JSON.stringify(desktopThreadBounds)}`);
  assert.ok(desktopThreadBounds.shellRight <= desktopThreadBounds.viewportWidth, `desktop thread exceeds viewport: ${JSON.stringify(desktopThreadBounds)}`);
  console.log(`desktop /thread/manager: shell clears sidebar ${JSON.stringify(desktopThreadBounds)}`);
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
