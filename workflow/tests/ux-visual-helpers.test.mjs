import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { spawn } from 'node:child_process';
import test from 'node:test';
import { deflateSync } from 'node:zlib';
import { countEmptyStateFlashes, findBottomControls, formatLoadingReport, formatTileIndex, headerHeight, hasBottomControls, isNearSingleColour, jpegHeight, jpegWidth, normalizePng, pngHeight, pngWidth, routeList, routeTemplate, selectRouteSamples, shouldDropTile, tileDimensions, tileGrid, tileIsValid, tileViewportPosition } from '../src/varde_workflow/skills/varde-review-ui/scripts/ux-visual-helpers.mjs';
import { scratchRunnerEnvironment, seedScratchData } from '../src/varde_workflow/skills/varde-review-ui/scripts/ux-seed-runner.mjs';

test('tiling covers the image with bounded edge tiles', () => {
  const tiles = tileGrid(800, 900, 390, 422);
  assert.deepEqual(tiles.map(({ x, y, width, height }) => [x, y, width, height]), [
    [0, 0, 390, 422], [390, 0, 390, 422], [780, 0, 20, 422],
    [0, 478, 390, 422], [390, 478, 390, 422], [780, 478, 20, 422],
  ]);
  assert.throws(() => tileGrid(0, 10, 2, 2), RangeError);
});

test('desktop tile halves overlap at the gutter and mobile tiles retain viewport width', () => {
  assert.deepEqual(tileGrid(1280, 500, 540, 500, 32, 320).map(({ x, width }) => [x, width]), [[0, 540], [320, 540], [740, 540]]);
  assert.equal(tileGrid(1280, 1118, 540, 500, 32).filter(({ row }) => row === 2).every(({ height }) => height === 500), true);
  assert.deepEqual(tileGrid(390, 1200, 390, 540).map(({ x, y, width }) => [x, y, width]), [[0, 0, 390], [0, 660, 390]]);
});

test('short final rows overlap a full-height row for a wide range of page heights', () => {
  for (let height = 501; height <= 6000; height += 1) {
    const tiles = tileGrid(390, height, 390, 500);
    assert.ok(tiles.every(({ width, height: tileHeight }) => width <= 540 && tileHeight <= 540), `oversized tile at page height ${height}`);
    assert.ok(tiles.every(({ width, height: tileHeight }) => width / tileHeight >= 0.5 && width / tileHeight <= 2), `bad tile ratio at page height ${height}`);
    assert.equal(Math.max(...tiles.map(({ y, height: tileHeight }) => y + tileHeight)), height, `page bottom not covered at ${height}`);
  }
});

test('header geometry ignores full-screen fixed shells and detects bottom action bars', () => {
  const viewport = { width: 390, height: 844 };
  assert.equal(headerHeight([
    { position: 'fixed', top: 0, width: 390, height: 844 },
    { position: 'sticky', top: 0, width: 390, height: 60 },
  ], viewport), 60);
  assert.equal(hasBottomControls([
    { position: 'fixed', top: 0, bottom: 844, width: 390, height: 844 },
    { position: 'sticky', top: 792, bottom: 844, width: 390, height: 52 },
  ], viewport), true);
  assert.equal(hasBottomControls([
    { position: 'sticky', top: 652, bottom: 714, width: 880, height: 62 },
  ], { width: 1280, height: 800 }), true, 'a sticky bar can sit above the viewport edge inside its scroll panel');
  assert.equal(findBottomControls([
    { position: 'sticky', left: 393, top: 739, bottom: 800, width: 814, height: 61 },
  ], { width: 1280, height: 800 }).left, 393);
});

test('PNG dimension verifier reads scale-1 dimensions', () => {
  const png = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(png, 0);
  png.writeUInt32BE(390, 16);
  png.writeUInt32BE(540, 20);
  assert.equal(pngWidth(png), 390);
  assert.equal(pngHeight(png), 540);
  assert.equal(pngWidth(Buffer.from('not a PNG')), 0);
});

test('PNG normalization removes metadata and combines image data into one verified stream', () => {
  const source = makePngWithMetadata();
  const normalized = normalizePng(source);
  const chunks = readPngChunks(normalized);
  assert.deepEqual(chunks.map(({ type }) => type), ['IHDR', 'IDAT', 'IEND']);
  assert.equal(pngWidth(normalized), 1);
  assert.equal(pngHeight(normalized), 1);
  assert.equal(chunks[1].data.length, 13);
});

function makePngWithMetadata() {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(1, 0);
  header.writeUInt32BE(1, 4);
  header[8] = 8;
  header[9] = 6;
  const imageData = deflateSync(Buffer.from([0, 10, 20, 30, 255]));
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    makePngChunk('IHDR', header), makePngChunk('eXIf', Buffer.from('metadata')),
    makePngChunk('IDAT', imageData.subarray(0, 2)), makePngChunk('IDAT', imageData.subarray(2)),
    makePngChunk('IEND', Buffer.alloc(0)),
  ]);
}

function makePngChunk(type, data) {
  const chunk = Buffer.alloc(data.length + 12);
  chunk.writeUInt32BE(data.length, 0);
  chunk.write(type, 4, 'ascii');
  data.copy(chunk, 8);
  chunk.writeUInt32BE(pngCrc32(chunk.subarray(4, data.length + 8)), data.length + 8);
  return chunk;
}

function pngCrc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function readPngChunks(bytes) {
  const chunks = [];
  for (let offset = 8; offset < bytes.length;) {
    const length = bytes.readUInt32BE(offset);
    chunks.push({ type: bytes.toString('ascii', offset + 4, offset + 8), data: bytes.subarray(offset + 8, offset + 8 + length) });
    offset += length + 12;
  }
  return chunks;
}

test('tile crops use document offsets when the page cannot scroll to a tile', () => {
  assert.deepEqual(tileViewportPosition(422, 844, 844), { scrollTop: 422, clipY: 0, minPageHeight: 1266 });
  assert.deepEqual(tileViewportPosition(844, 1500, 844), { scrollTop: 844, clipY: 0, minPageHeight: 1688 });
  assert.deepEqual(tileViewportPosition(540, 1500, 844, 56), { scrollTop: 484, clipY: 56, minPageHeight: 1500 });
  assert.deepEqual(tileViewportPosition(0, 1500, 844, 56), { scrollTop: 0, clipY: 0, minPageHeight: 1500 });
});

test('JPEG width verification reads the encoded frame header', () => {
  const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xc0, 0x00, 0x0b, 0x08, 0x00, 0x02, 0x00, 0x03, 0x01, 0x11, 0x00, 0xff, 0xd9]);
  assert.equal(jpegWidth(jpeg), 3);
  assert.equal(jpegHeight(jpeg), 2);
  assert.equal(jpegWidth(Buffer.from('not a jpeg')), 0);
});

test('route sampling groups dynamic instances while preserving settings sections', () => {
  assert.equal(routeTemplate('http://example.test/plans/plan-1'), '/plans/<id>');
  assert.equal(routeTemplate('http://example.test/threads/plan:plan-1'), '/threads/<id>');
  assert.equal(routeTemplate('http://example.test/profile/agent-1'), '/profile/<id>');
  assert.equal(routeTemplate('http://example.test/settings/role-types'), '/settings/<id>');
  assert.equal(routeTemplate('http://example.test/thread/manager'), '/thread/<id>');
});

test('tile dimensions meet the image API viewability limits by padding extreme ratios', () => {
  for (const [width, height] of [[1280, 400], [390, 56], [20, 422]]) {
    const dimensions = tileDimensions(width, height);
    assert.ok(tileIsValid({ ...dimensions, bytes: 1000 }));
  }
  assert.equal(tileIsValid({ width: 541, height: 400, bytes: 1000 }), false);
  assert.equal(tileIsValid({ width: 400, height: 200, bytes: 150001 }), false);
  assert.equal(tileIsValid({ width: 400, height: 100, bytes: 1000 }), false);
});

test('uniform crop detection rejects near-empty tiles and keeps varied content', () => {
  assert.equal(isNearSingleColour(Array(95).fill('background').concat(Array(5).fill('text'))), true);
  assert.equal(isNearSingleColour(Array(90).fill('background').concat(Array(10).fill('text'))), false);
});

test('blank and skeleton-only tiles are dropped while white tiles with text are kept', () => {
  const whiteSamples = Array(98).fill('white').concat(Array(2).fill('gray'));
  assert.equal(shouldDropTile(whiteSamples, ''), true);
  assert.equal(shouldDropTile(whiteSamples, 'Loading plans...'), true);
  assert.equal(shouldDropTile(whiteSamples, 'Plans · 1 in progress'), false);
  assert.equal(shouldDropTile(Array(100).fill('white'), 'Settings'), false);
});

test('route list strips hashes and trailing slashes and rejects off-origin URLs', () => {
  assert.deepEqual(routeList(['/plans/#x', 'http://example.test/settings/', 'https://elsewhere.test/'], 'http://example.test'), [
    'http://example.test/plans', 'http://example.test/settings',
  ]);
});

test('requested tile routes are normalized and must be discovered', () => {
  const discovered = ['http://example.test/', 'http://example.test/chat', 'http://example.test/plans'];
  assert.deepEqual(selectRouteSamples(discovered, ['/chat/', '/plans'], 'http://example.test'), [
    'http://example.test/chat', 'http://example.test/plans',
  ]);
  assert.throws(() => selectRouteSamples(discovered, ['/settings/runner'], 'http://example.test'), /not discovered/);
});

test('empty-state detector counts brief empty periods that recover', () => {
  assert.equal(countEmptyStateFlashes([false, true, true, false, false]), 1);
  assert.equal(countEmptyStateFlashes([false, true, true, true, true, true, true, false]), 0);
  assert.equal(countEmptyStateFlashes([true, true, false]), 0, 'initial empty state is not a flash');
});

test('tile index lists every tile under its route, viewport, and scheme', () => {
  assert.match(formatTileIndex([{ route: 'http://example.test/plans', viewport: '390x844 webkit', scheme: 'dark', files: [{ jpeg: 'tile-1.jpg', jpegBytes: 100, jpegWidth: 390 }, { jpeg: 'tile-2.jpg', jpegBytes: 100, jpegWidth: 390 }] }]), /## http:\/\/example\.test\/plans · 390x844 webkit · dark[\s\S]*tile-1\.jpg[\s\S]*tile-2\.jpg/);
});

test('tile index labels PNGs and calls out sticky bottom controls', () => {
  const index = formatTileIndex([{ route: '/settings/model-types', viewport: '390x844 webkit', scheme: 'light', files: [{ kind: 'PNG', name: 'model-types-sticky-bottom.png', bytes: 1000, width: 390, height: 540, stickyBottom: true }] }]);
  assert.match(index, /PNG: \[model-types-sticky-bottom\.png\]/);
  assert.match(index, /sticky\/fixed bottom controls visible/);
});

test('tile index reports loading timeouts and oversized JPEGs', () => {
  const index = formatTileIndex([{ route: 'http://example.test', viewport: '390x844 webkit', scheme: 'light', loaded: false, files: [{ jpeg: 'large.jpg', jpegBytes: 150001, jpegWidth: 900, jpegHeight: 400, jpegSuspicious: true, stillLoading: true }] }]);
  assert.match(index, /still loading \(timeout\)/);
  assert.match(index, /large\.jpg/);
  assert.match(index, /150001 bytes, 900×400px/);
  assert.match(index, /still loading/);
  assert.match(index, /violates viewability limits/);
});

test('tile index reports truncation and the unviewable count', () => {
  const index = formatTileIndex([{ route: '/plans', viewport: '390x844 webkit', scheme: 'light', truncatedTiles: 3, files: [] }]);
  assert.match(index, /Unviewable tiles: 0/);
  assert.match(index, /Truncated 3 tiles/);
});

test('tile script discovers dynamic route families through its entry point', async () => {
  const links = {
    '/': ['/plans', '/roles', '/chat/needs?item=fixture-need', '/threads/plan:fixture-thread'],
    '/plans': ['/plans/fixture-plan', '/plans/second-plan'],
    '/roles': ['/settings/role-types'],
  };
  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    const hrefs = [...(links[pathname] || []), ...(links['/'] || [])];
    response.writeHead(200, { 'content-type': 'text/html' });
    response.end(`<main></main><script>setTimeout(() => { document.querySelector('main').innerHTML = ${JSON.stringify(hrefs.map((href) => `<a href="${href}">${href}</a>`).join(''))}; }, 750)</script>`);
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'varde-ux-route-discovery-'));
  try {
    const output = path.join(scratch, 'tiles');
    const script = new URL('../src/varde_workflow/skills/varde-review-ui/scripts/ux-tile-shots.mjs', import.meta.url).pathname;
    const result = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [script, `http://127.0.0.1:${address.port}/`, output], {
        env: { ...process.env, VARDE_UX_DISCOVERY_ONLY: '1', VARDE_UX_MAX_ROUTES: '100' },
        stdio: ['ignore', 'pipe', 'pipe'],
      });
      let stdout = '';
      let stderr = '';
      const timeout = setTimeout(() => child.kill('SIGKILL'), 30000);
      child.stdout.setEncoding('utf8').on('data', (chunk) => { stdout += chunk; });
      child.stderr.setEncoding('utf8').on('data', (chunk) => { stderr += chunk; });
      child.once('error', reject);
      child.once('close', (code) => {
        clearTimeout(timeout);
        resolve({ code, stdout, stderr });
      });
    });
    assert.equal(result.code, 0, result.stderr || result.stdout);
    const { routes } = JSON.parse(await fs.readFile(path.join(output, 'discovered-routes.json'), 'utf8'));
    const index = await fs.readFile(path.join(output, 'index.md'), 'utf8');
    assert.doesNotMatch(index, /\/profile\/<id>: No route instance was discoverable/);
    assert.doesNotMatch(index, /\/threads\/<id>: No route instance was discoverable/);
    assert.equal(routes.filter((found) => new URL(found).pathname.startsWith('/plans/')).length, 2, 'keep one discovered plan detail and the seeded route');
    assert.ok(routes.some((found) => new URL(found).pathname === '/plans/ux-review-seed-agent'));
    for (const route of ['/plans/fixture-plan', '/settings/role-types', '/settings/review', '/settings/harnesses', '/threads/plan:fixture-thread', '/chat/needs?item=fixture-need']) {
      assert.ok(routes.some((found) => new URL(found).pathname + new URL(found).search === route), `missing discovered route ${route}; found: ${routes.join(', ')}`);
      assert.ok(index.includes(`http://127.0.0.1:${address.port}${route}`), `index missing discovered route ${route}`);
    }
  } finally {
    await new Promise((resolve) => server.close(resolve));
    await fs.rm(scratch, { recursive: true, force: true });
  }
});

test('tile sample explicitly maps required app route templates and records exclusions', async () => {
  const script = await fs.readFile(new URL('../src/varde_workflow/skills/varde-review-ui/scripts/ux-tile-shots.mjs', import.meta.url), 'utf8');
  const routeFiles = await fs.readdir(new URL('../../runner/ui/src/routes', import.meta.url), { recursive: true });
  assert.ok(routeFiles.some((file) => file === 'jobs/+page.svelte'));
  assert.ok(routeFiles.some((file) => file === 'threads/[id]/+page.svelte'));
  assert.ok(routeFiles.some((file) => file === 'profile/[agentId]/+page.svelte'));
  assert.ok(script.includes("'/threads/plan:ux-review-seed-agent'"));
  assert.ok(script.includes("'/profile/ux-review-seed-agent'"));
  assert.ok(script.includes("'/settings/review'"));
  assert.ok(script.includes("'/settings/role-types'"));
  assert.ok(script.includes("'/settings/model-types'"));
  assert.ok(script.includes("'/jobs'"));
  assert.match(script, /Excluded route templates/);
  assert.match(script, /No matching page route exists under runner\/ui\/src\/routes/);
});

test('loading report includes timings, layout shift, empty state, and status', () => {
  const report = formatLoadingReport([{ route: '/plans', firstContentMs: 200, layoutShift: 0.12345, emptyStateFlashes: 1, persistentStatus: true }]);
  assert.match(report, /\/plans \| 200 \| 0\.1235 \| 1 \| yes \| no \| no/);
  assert.match(formatLoadingReport([], true), /configured limit; additional routes may remain queued/);
});

test('scratch runner cannot inherit an ambient Paseo identity or endpoint', () => {
  const env = scratchRunnerEnvironment({ PASEO_URL: 'ws://live.example/ws', PASEO_AGENT_ID: 'live-agent', SAFE_VALUE: 'kept' }, '/scratch/working', '/scratch', '/scratch/config');
  assert.equal(env.PASEO_URL, 'ws://127.0.0.1:1/ws');
  assert.equal(env.PASEO_AGENT_ID, undefined);
  assert.equal(env.SAFE_VALUE, 'kept');
  assert.equal(env.VARDE_WORKING_DIR, '/scratch/working');
  assert.equal(env.VARDE_PLANS_BACKEND, 'files');
});

test('scratch seed writes an answerable Needs-you record and an editable role config', async () => {
  const scratch = await fs.mkdtemp(path.join(os.tmpdir(), 'varde-ux-seed-test-'));
  const working = path.join(scratch, 'working');
  const config = path.join(scratch, 'config');
  try {
    await fs.mkdir(path.join(working, 'plans'), { recursive: true });
    await fs.writeFile(path.join(working, 'plans', 'untouched.md'), 'source plan');
    await seedScratchData(working, config);

    const inboxPath = path.join(working, '.cache', 'inbox', 'messages.jsonl');
    const records = (await fs.readFile(inboxPath, 'utf8')).trim().split('\n').map(JSON.parse);
    assert.equal(records.length, 1);
    assert.equal(records[0].kind, 'needs-user');
    assert.equal(records[0].to, 'main');
    assert.equal(records[0].from, 'ux-review-seed-agent');

    const inbox = path.join(working, '.cache', 'inbox');
    const [bindingFile] = await fs.readdir(path.join(inbox, 'bindings'));
    const binding = JSON.parse(await fs.readFile(path.join(inbox, 'bindings', bindingFile), 'utf8'));
    const current = JSON.parse(await fs.readFile(path.join(inbox, 'addresses', records[0].from, 'current'), 'utf8'));
    assert.equal(binding.address, records[0].from);
    assert.equal(binding.plan_id, 'ux-review-seed-agent');
    assert.equal(current.session_key, bindingFile.slice(0, -'.json'.length));
    const plan = await fs.readFile(path.join(working, 'plans', 'ux-review-seed-agent', 'plan.md'), 'utf8');
    assert.match(plan, /status: active/);
    assert.match(plan, /assigned_to: ux-review-seed-agent/);

    const notes = JSON.parse(await fs.readFile(records[0].notes, 'utf8'));
    assert.ok(notes.asked);
    assert.ok(notes.why);
    assert.ok(notes.options.length >= 2);
    assert.ok(notes.options.every((option) => option.id && option.label));

    const roleConfig = await fs.readFile(path.join(config, 'runner.toml'), 'utf8');
    assert.match(roleConfig, /\[roles\.builder\]/);
    assert.match(roleConfig, /\[types\.review\]/);
    assert.match(roleConfig, /\[roles\.reviewer\]/);
    assert.match(roleConfig, /type = "light"/);
    assert.match(roleConfig, /allow_fallback_only_on = \["provider_limit"\]/);
    assert.match(roleConfig, /create_paseo_projects = false/);
    assert.equal(await fs.readFile(path.join(working, 'plans', 'untouched.md'), 'utf8'), 'source plan');

    await seedScratchData(working, config);
    const repeatedRecords = (await fs.readFile(inboxPath, 'utf8')).trim().split('\n');
    assert.equal(repeatedRecords.length, 1, 'repeated setup does not duplicate the seed message');
  } finally {
    await fs.rm(scratch, { recursive: true, force: true });
  }
});
