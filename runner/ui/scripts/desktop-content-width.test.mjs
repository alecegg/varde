import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const baseUrl = process.argv[2] ?? process.env.VARDE_UI_BASE_URL;
assert.ok(baseUrl, 'Pass the scratch runner URL as an argument or set VARDE_UI_BASE_URL.');

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  for (const [route, selector] of [
    ['/settings', '.settings-overview'],
    ['/plans', '.plans-page'],
    ['/chat/needs', '.needs-page'],
  ]) {
    await page.goto(new URL(route, baseUrl).href);
    await page.locator(selector).waitFor();
    const measurements = await page.evaluate(({ contentSelector, route }) => {
      const pane = document.querySelector('.shell-content');
      const content = document.querySelector(contentSelector);
      const header = document.querySelector('.shell-content .app-header, .chat-shell > .app-header');
      const needsCard = route === '/chat/needs' ? document.querySelector('.chat-list') : null;
      const box = (element) => {
        const { x, width } = element.getBoundingClientRect();
        return { x, width };
      };
      return { pane: box(pane), content: box(content), header: box(header), needsCard: needsCard && box(needsCard), headerBackground: getComputedStyle(header).backgroundColor };
    }, { contentSelector: selector, route });

    assert.ok(measurements.content.width >= 600, `${route} content is too narrow: ${JSON.stringify(measurements)}`);
    assert.ok(measurements.content.width <= 880, `${route} content exceeds 880px: ${JSON.stringify(measurements)}`);
    assert.ok(Math.abs(measurements.content.width - Math.min(measurements.pane.width - 64, 880)) <= 1, `${route} content does not fill the pane up to 880px: ${JSON.stringify(measurements)}`);
    assert.ok(Math.abs(measurements.content.width - measurements.header.width) <= 1, `${route} header and content widths differ: ${JSON.stringify(measurements)}`);
    assert.ok(Math.abs(measurements.content.x - measurements.header.x) <= 1, `${route} header and content do not align: ${JSON.stringify(measurements)}`);
    assert.notEqual(measurements.headerBackground, 'rgba(0, 0, 0, 0)', `${route} header is transparent`);
    if (measurements.needsCard) assert.ok(Math.abs(measurements.needsCard.width - measurements.content.width) <= 1, `Needs-you card does not fill the column: ${JSON.stringify(measurements)}`);
  }
} finally {
  await browser.close();
}
