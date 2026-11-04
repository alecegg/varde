import test from 'node:test';
import assert from 'node:assert/strict';
import { CSRF_HEADER, csrfFetch, isSameOrigin, isWrite, loadPairing, parsePairing, submitPairing, withCsrf } from './pairing.ts';

test('only writes carry the CSRF header, and only when a token exists', () => {
  assert.equal(isWrite(undefined), false);
  assert.equal(isWrite('get'), false);
  assert.equal(isWrite('POST'), true);
  assert.equal(isWrite('DELETE'), true);
  assert.equal(withCsrf({ method: 'GET' }, 'tok').headers, undefined);
  assert.equal(withCsrf({ method: 'POST' }, null).headers, undefined);
  const init = withCsrf({ method: 'POST', headers: { 'content-type': 'application/json' } }, 'tok');
  assert.equal(new Headers(init.headers).get(CSRF_HEADER), 'tok');
  assert.equal(new Headers(init.headers).get('content-type'), 'application/json');
});

test('the wrapped fetch adds the token to same-origin writes only', async () => {
  const seen = [];
  const wrapped = csrfFetch(async (url, init) => { seen.push([url, init]); return {}; }, () => 'tok', 'http://127.0.0.1:8765');
  await wrapped('/api/x', { method: 'POST' });
  await wrapped('/api/x');
  await wrapped('https://example.com/y', { method: 'POST' });
  await wrapped('//example.com/y', { method: 'POST' });
  assert.equal(new Headers(seen[0][1].headers).get(CSRF_HEADER), 'tok');
  assert.equal(seen[1][1], undefined);
  assert.equal(seen[2][1].headers, undefined);
  assert.equal(seen[3][1].headers, undefined);
  assert.equal(isSameOrigin('http://127.0.0.1:8765/a', 'http://127.0.0.1:8765'), true);
});

test('a missing pairing route means no enforcement; otherwise the state is reported', () => {
  assert.deepEqual(parsePairing(404, null), { enforced: false, paired: true, csrf: null });
  assert.deepEqual(parsePairing(200, { paired: false, csrf: null }), { enforced: true, paired: false, csrf: null });
  assert.deepEqual(parsePairing(200, { paired: true, csrf: 'c' }), { enforced: true, paired: true, csrf: 'c' });
});

test('an explicitly disabled gate does not require pairing', () => {
  assert.deepEqual(parsePairing(200, { enforced: false, paired: false, csrf: null }), {
    enforced: false,
    paired: false,
    csrf: null
  });
});

test('pairing loads the state, posts the code, and surfaces a refusal', async () => {
  const calls = [];
  const fake = (responses) => async (url, init = {}) => {
    calls.push([url, init]);
    const next = responses.shift();
    return { ok: next.status < 400, status: next.status, json: async () => next.body };
  };
  assert.deepEqual(await loadPairing(fake([{ status: 200, body: { paired: false, csrf: null } }])), { enforced: true, paired: false, csrf: null });
  const paired = await submitPairing(fake([{ status: 200, body: { paired: true, csrf: 'c' } }]), 'ABCD-2345');
  assert.deepEqual(paired, { enforced: true, paired: true, csrf: 'c' });
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body), { code: 'ABCD-2345' });
  await assert.rejects(submitPairing(fake([{ status: 403, body: { error: 'pairing code refused' } }]), 'bad'), /pairing code refused/);
});
