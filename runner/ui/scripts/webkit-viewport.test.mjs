import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { devices, webkit } from 'playwright';

test('WebKit iPhone 15 layout follows a shrunken visual viewport', async () => {
  const browser = await webkit.launch();
  const directory = await mkdtemp(path.join(os.tmpdir(), 'varde-webkit-'));
  const page = await browser.newPage({ ...devices['iPhone 15'] });

  try {
    await writeFile(
      path.join(directory, 'index.html'),
      `<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
       <div id="composer" style="position:fixed;bottom:0">Composer</div>
       <script>
         const originalViewport = window.visualViewport;
         window.fitComposer = () => {
           document.querySelector('#composer').style.bottom =
             (window.innerHeight - window.visualViewport.height) + 'px';
         };
         originalViewport.addEventListener('resize', window.fitComposer);
         window.fitComposer();
       </script>`,
    );
    await page.goto(`file://${path.join(directory, 'index.html')}`);
    const initial = await page.evaluate(() => ({
      width: window.innerWidth,
      visualHeight: window.visualViewport.height,
      innerHeight: window.innerHeight,
    }));
    assert.equal(initial.width, devices['iPhone 15'].viewport.width);
    assert.equal(initial.visualHeight, initial.innerHeight);

    await page.evaluate(() => {
      const originalViewport = window.visualViewport;
      Object.defineProperty(window, 'visualViewport', {
        configurable: true,
        value: { height: 420, width: originalViewport.width },
      });
      originalViewport.dispatchEvent(new Event('resize'));
    });

    assert.equal(await page.locator('#composer').evaluate((node) => node.style.bottom), `${initial.innerHeight - 420}px`);
    console.log(`PASS WebKit iPhone 15: ${initial.width}x${initial.innerHeight} visual viewport shrank to 420px`);
  } finally {
    await page.close();
    await browser.close();
    await rm(directory, { recursive: true, force: true });
  }
});
