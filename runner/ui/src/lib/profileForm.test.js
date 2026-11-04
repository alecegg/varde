import test from 'node:test';
import assert from 'node:assert/strict';
import { serverErrors, validateProfile } from './profileForm.ts';
import { IdentitySaveError, profileHref, saveIdentity } from './identitiesApi.ts';

const valid = { name: 'Builder', label: 'build', description: 'Build things' };

test('profile validation accepts each inclusive field limit', () => {
  assert.deepEqual(validateProfile({ name: 'n'.repeat(40), label: 'l'.repeat(24), description: 'd'.repeat(280) }), {});
});

test('profile validation reports empty and overlong fields individually', () => {
  assert.deepEqual(validateProfile({ name: '', label: 'l'.repeat(25), description: 'd'.repeat(281) }), {
    name: 'Name must be 1 to 40 characters',
    label: 'Label must be 1 to 24 characters',
    description: 'Description must be at most 280 characters',
  });
  assert.deepEqual(validateProfile(valid), {});
});

test('serverErrors maps a 400 errors object to field messages', () => {
  assert.deepEqual(serverErrors({ errors: { name: 'required', label: 'too long', ignored: 1 } }), { name: 'required', label: 'too long' });
  assert.deepEqual(serverErrors({ error: 'unavailable' }), {});
});

test('profileHref encodes the identity id as one path segment', () => {
  assert.equal(profileHref('role/name'), '/agents/profile/role%2Fname');
});

test('saveIdentity treats a server failure as a general save error', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ error: 'could not save identity' }), { status: 500 });
  try {
    await assert.rejects(saveIdentity('builder', valid), (error) => {
      assert.equal(error instanceof IdentitySaveError, false);
      assert.match(error.message, /500/);
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('saveIdentity keeps validation errors as field errors', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ errors: { name: 'already used' } }), { status: 400 });
  try {
    await assert.rejects(saveIdentity('builder', valid), (error) => {
      assert.ok(error instanceof IdentitySaveError);
      assert.deepEqual(error.errors, { name: 'already used' });
      return true;
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
