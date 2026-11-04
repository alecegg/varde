import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';
import { chromium, devices, webkit } from 'playwright';

const port = 4174;
const origin = `http://127.0.0.1:${port}`;
const server = spawn('./node_modules/.bin/vite', ['dev', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
  stdio: ['ignore', 'pipe', 'pipe'],
  env: process.env,
});
server.stdout.on('data', (chunk) => process.stdout.write(chunk));
server.stderr.on('data', (chunk) => process.stderr.write(chunk));

let browser;
try {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(origin);
      if (response.ok) break;
    } catch { /* Wait for Vite to bind its port. */ }
    await delay(250);
  }

  for (const { name, engine, device } of [
    { name: 'Chromium', engine: chromium, device: {} },
    { name: 'WebKit', engine: webkit, device: devices['iPhone 15'] },
  ]) {
    browser = await engine.launch({
      headless: true,
      ...(engine === chromium && process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {}),
    });
    const context = await browser.newContext({
      ...device,
      viewport: { width: 390, height: 844 },
      isMobile: true,
      hasTouch: true,
      deviceScaleFactor: 3,
    });
    await context.addInitScript(() => {
      let height = 844;
      const viewport = new EventTarget();
      Object.defineProperties(viewport, {
        height: { get: () => height },
        offsetTop: { get: () => 0 },
        width: { get: () => window.innerWidth },
      });
      Object.defineProperty(window, 'visualViewport', { configurable: true, value: viewport });
      window.setSyntheticKeyboardHeight = (value) => {
        height = value;
        viewport.dispatchEvent(new Event('resize'));
        viewport.dispatchEvent(new Event('scroll'));
      };
    });
    const page = await context.newPage();
    page.on('pageerror', (error) => console.error('browser page error:', error.message));
    page.on('console', (message) => { if (message.type() === 'error') console.error('browser console error:', message.text()); });
    let managerEnabled = true;
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      let payload = {};
      if (url.pathname === '/api/pairing') payload = { enforced: false, paired: true };
      if (url.pathname === '/api/roles') payload = { roles: { 'manager-bot': { enabled: managerEnabled } } };
      if (url.pathname === '/api/needs-you-count') payload = { needs_you_count: 0 };
      if (url.pathname === '/api/home') payload = { roles: [] };
      if (url.pathname === '/api/chat') payload = {
        messages: [], latest_seq: 0,
        thread: { key: url.searchParams.get('thread'), kind: url.searchParams.get('thread') === 'main' ? 'main' : 'instance', label: null, state: 'running' },
        bot: { state: 'running', context_pct: null, generation: 0 },
      };
      if (url.pathname === '/api/threads') payload = [];
      if (url.pathname === '/api/instance-threads') payload = { threads: [
        { thread_key: 'instance:worker-1', agent_id: 'worker-1', plan_id: null, role: 'worker', label: 'Worker', state: 'running', last_activity: '2026-10-28T08:00:00Z' },
        { thread_key: 'instance:worker-2', agent_id: 'worker-2', plan_id: null, role: 'worker', label: 'Worker', state: 'idle', last_activity: '2026-10-28T09:00:00Z' },
      ] };
      if (url.pathname === '/api/pins') payload = { pins: ['worker-1'] };
      if (url.pathname === '/api/agents') payload = [
        { agent_id: 'worker-1', name: 'Worker', harness: 'codex', role: 'worker', workspace: null, launched_by: null, root_launched_by: null, lifecycle: 'running', idle_status: null, capabilities: {}, pending_requests: [{ request_id: 'approval-1', kind: 'approval', summary: 'Approve?' }] },
        { agent_id: 'worker-2', name: 'Worker', harness: 'codex', role: 'worker', workspace: null, launched_by: null, root_launched_by: null, lifecycle: 'idle', idle_status: null, capabilities: {}, pending_requests: [] },
      ];
      if (url.pathname === '/api/bot/audit') payload = [];
      await route.fulfill({
        status: 200,
        contentType: url.pathname === '/api/chat/stream' ? 'text/event-stream' : 'application/json',
        body: url.pathname === '/api/chat/stream' ? ': connected\n\n' : JSON.stringify(payload),
      });
    });
    await page.route('**/events', (route) => route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': connected\n\n' }));
    await page.goto(`${origin}/thread/manager`);
    const composer = page.locator('#chat-message');
    try {
      await composer.waitFor({ state: 'visible', timeout: 8000 });
    } catch (error) {
      console.error('chat page body:', (await page.locator('body').innerText()).slice(0, 1200));
      throw error;
    }
    assert.equal(await composer.isEnabled(), true, 'an enabled Manager role should have an enabled composer');
    const statusContent = await page.locator('.status-row > *').first().boundingBox();
    assert.ok(statusContent, 'Manager status row should be visible');
    assert.equal(statusContent.x, 16, 'Manager status content should use a 16px gutter');
    assert.equal(await page.locator('[data-pinned-content]').count(), 0, 'the chat should not show the pinned idle status banner');

    const before = await page.evaluate(() => ({
      width: window.innerWidth,
      documentWidth: document.documentElement.scrollWidth,
      documentHeight: document.documentElement.scrollHeight,
      composer: document.querySelector('.composer').getBoundingClientRect().toJSON(),
      input: document.querySelector('#chat-message').getBoundingClientRect().toJSON(),
      send: document.querySelector('.send').getBoundingClientRect().toJSON(),
    }));
    assert.equal(before.width, 390);
    assert.equal(before.documentWidth, 390, 'thread layout should not create horizontal overflow');
    assert.equal(before.documentHeight, 844, 'thread should fit the mobile viewport without document scrolling');
    assert.equal(before.composer.left, 0);
    assert.equal(before.composer.right, 390);
    assert.equal(before.input.left, 16);
    assert.equal(before.send.right, 374, 'composer controls should keep equal 16px side insets');

    const inputBounds = await composer.boundingBox();
    if (!inputBounds) throw new Error('composer has no visible bounds');
    assert.ok(inputBounds.y >= 0 && inputBounds.y + inputBounds.height <= 844, 'composer should begin inside the visible page');
    await composer.evaluate((input) => input.focus({ preventScroll: true }));
    await page.evaluate(() => window.setSyntheticKeyboardHeight(420));
    const afterFocus = await page.evaluate(() => {
      const input = document.querySelector('#chat-message');
      const rect = input.getBoundingClientRect();
      return {
        scrollX: window.scrollX,
        scrollY: window.scrollY,
        fontSize: Number.parseFloat(getComputedStyle(input).fontSize),
        composerBottom: document.querySelector('.composer').getBoundingClientRect().bottom,
        viewportBottom: window.visualViewport.offsetTop + window.visualViewport.height,
      };
    });
    assert.equal(afterFocus.scrollX, 0, 'focus should not move the page horizontally');
    assert.equal(afterFocus.scrollY, 0, 'focus should not move the page vertically');
    assert.ok(afterFocus.fontSize >= 16, 'composer text should be at least 16px');
    assert.ok(afterFocus.composerBottom <= afterFocus.viewportBottom, 'composer should stay above the synthetic keyboard edge');

    await composer.fill(Array.from({ length: 12 }, (_, index) => `message line ${index + 1}`).join('\n'));
    const sizing = await composer.evaluate((input) => ({
      height: input.clientHeight,
      scrollHeight: input.scrollHeight,
      lineHeight: Number.parseFloat(getComputedStyle(input).lineHeight),
      overflowY: getComputedStyle(input).overflowY,
    }));
    assert.ok(sizing.height >= sizing.lineHeight * 5, 'composer should grow to five lines');
    assert.ok(sizing.height <= sizing.lineHeight * 5 + 30, 'composer height should cap near five lines');
    assert.ok(sizing.scrollHeight > sizing.height, 'extra lines should scroll inside the textarea');
    assert.equal(sizing.overflowY, 'auto');

    managerEnabled = false;
    await page.reload();
    await composer.waitFor({ state: 'visible' });
    await page.waitForFunction(() => document.querySelector('#chat-message')?.disabled, undefined, { timeout: 3000 });
    assert.equal(await composer.isDisabled(), true, 'a disabled role should disable its composer');
    assert.equal(await page.getByRole('link', { name: 'Start' }).getAttribute('href'), '/settings');
    assert.equal(await page.locator('.notice').count(), 1, 'Manager disabled state should show one explanation');
    const settingsLink = page.locator('.notice').getByRole('link', { name: 'Open Settings' });
    assert.equal(await settingsLink.getAttribute('href'), '/settings');
    assert.equal((await settingsLink.boundingBox()).x, 16, 'Manager disabled notice link should align with the 16px gutter');
    assert.match(await page.locator('.notice').innerText(), /Manager bot is off\. Start it to chat\./);
    await settingsLink.click();
    await page.waitForURL('**/settings', { timeout: 3000 });
    await page.goto(`${origin}/thread/worker-2`);
    await composer.waitFor({ state: 'visible' });
    assert.equal(await composer.isEnabled(), true, 'an enabled non-Manager role should have an enabled composer');
    const activity = page.locator('.instance-activity');
    assert.equal(await activity.count(), 1, 'instances sharing a role should appear inside the role chat');
    assert.match(await activity.innerText(), /2 instances · 1 pending/);
    await page.setViewportSize({ width: 1440, height: 900 });
    const desktopBounds = await page.evaluate(() => ({
      shell: document.querySelector('.chat-shell').getBoundingClientRect().toJSON(),
      sidebar: document.querySelector('.desktop-chat-sidebar').getBoundingClientRect().toJSON(),
    }));
    assert.ok(desktopBounds.shell.left >= desktopBounds.sidebar.right, 'fixed thread shell should start after the desktop sidebar');
    await page.setViewportSize({ width: 390, height: 844 });
    for (const route of ['/', '/chat']) {
      await page.goto(`${origin}${route}`);
      const editButton = page.locator('.pin-section > .pin-heading button');
      if (await editButton.innerText() === 'Edit') await editButton.click();
      const pinToggle = page.locator('.pin-toggle').first();
      const target = await pinToggle.boundingBox();
      assert.ok(target && target.width >= 44 && target.height >= 44, `${route} pinned-chat action should have a 44px target`);
    }
    console.log(`PASS chat mobile Playwright checks (390x844 ${name}; synthetic visualViewport only)`);
    await context.close();
    await browser.close();
    browser = undefined;
  }
} finally {
  await browser?.close();
  server.kill('SIGTERM');
}
