import test from 'node:test';
import assert from 'node:assert/strict';
import { guardOk, identityDescription, modelChoices, preserveUnmanagedToml, roleType, summarizeRoleChanges, toToml } from './roles.ts';

const data = {
  providers: { claude: [{ id: 'claude-sonnet-5-5' }], codex: [{ id: 'gpt-6-luna' }], pi: [{ id: 'deepseek/deepseek-v4-flash' }] },
  fallback: {}, models_by_harness: {}, harnesses: ['codex-app-server', 'pi', 'claude-sdk'], native_harnesses: [], error: null,
};
const model = (harness, name, reasoning_effort = 'medium') => ({ harness, model: name, reasoning_effort });

test('identity descriptions are the source for role text and missing roles stay empty', () => {
  const identities = [{ id: 'builder', description: 'Implements one task at a time.' }];
  assert.equal(identityDescription(identities, 'builder'), 'Implements one task at a time.');
  assert.equal(identityDescription(identities, 'missing'), '');
});

test('guard eligibility follows capability data rather than harness names', () => {
  const types = {
    standard: { ...model('claude-sdk', 'claude-sonnet-5-5'), fallback: [], guard_eligible: false },
    light: { ...model('codex-app-server', 'gpt-6-luna'), fallback: [], guard_eligible: true },
  };
  assert.equal(guardOk(types, { type: 'standard', enabled: true, ...model('claude-sdk', 'claude-sonnet-5-5') }), false);
  assert.equal(guardOk(types, { type: 'light', enabled: true, ...model('codex-app-server', 'gpt-6-luna') }), true);
  assert.equal(modelChoices(data, model('claude-sdk', 'claude-sonnet-5-5')).length, 3);
});

test('model choices include each harness', () => {
  const choices = modelChoices(data, model('pi', 'deepseek/deepseek-v4-flash'));
  assert.deepEqual(new Set(choices.map((choice) => choice.value.split('::')[0])), new Set(['codex-app-server', 'pi', 'claude-sdk']));
});

test('role preview summaries describe changes in plain language', () => {
  const before = '[roles.guard]\ntype = "standard"\nenabled = false\n';
  const after = '[roles.guard]\ntype = "safe"\nenabled = true\n';
  assert.deepEqual(summarizeRoleChanges(before, after), {
    lines: ['Guard: turned on', 'Guard: type changed from Standard to Safe'],
    unrelated: [],
  });
});

test('role preview treats an unset guard as turned off', () => {
  assert.deepEqual(summarizeRoleChanges('[roles.guard]\ntype = "light"\n', '[roles.guard]\ntype = "light"\nenabled = false\n'), {
    lines: ['Guard: turned off'],
    unrelated: [],
  });
});

test('native harness catalogs come from config and available harnesses come from API data', () => {
  const choices = modelChoices({
    ...data,
    harnesses: ['claude-sdk', 'opencode-http'],
    native_harnesses: ['claude-sdk', 'opencode-http'],
    models_by_harness: { 'claude-sdk': [{ id: 'claude-sonnet-5-5' }], 'opencode-http': [{ id: 'opencode-go/deepseek-v4.1-flash' }] },
  }, model('claude-sdk', 'claude-sonnet-5-5'));
  assert.deepEqual(choices.map((choice) => choice.value), ['claude-sdk::claude-sonnet-5-5', 'opencode-http::opencode-go/deepseek-v4.1-flash']);
});

test('toToml emits shared types, role mappings and guard enabled state', () => {
  const types = { standard: { ...model('claude-sdk', 'claude-sonnet-5-5'), fallback: [model('pi', 'deepseek', 'high')] } };
  const roles = { guard: { type: 'standard', harness: 'claude-sdk', model: 'claude-sonnet-5-5', reasoning_effort: 'medium', enabled: false } };
  const result = toToml(types, roles);
  assert.match(result, /\[types\.standard\]/);
  assert.match(result, /\[\[types\.standard\.fallback\]\]/);
  assert.match(result, /\[roles\.guard\]\ntype = "standard"\nenabled = false/);
  assert.doesNotMatch(result, /\[roles\.guard\.fallback\]/);
});

test('toToml supports multiple types, fallback chains, null role types, and quoted strings', () => {
  const types = {
    standard: { ...model('claude-sdk', 'claude-sonnet-5-5'), fallback: [model('pi', 'deepseek', 'high'), model('codex-app-server', 'gpt-6-luna', 'low')] },
    heavy: { ...model('claude-sdk', 'claude-sonnet-5-5', 'high'), fallback: [] },
  };
  const roles = {
    planner: { type: null, ...model('claude-sdk', 'claude-sonnet-5-5') },
    guard: { type: 'standard', ...model('claude-sdk', 'claude-sonnet-5-5'), enabled: true },
  };
  const result = toToml(types, roles);
  assert.match(result, /\[\[types\.standard\.fallback\]\][\s\S]*\[\[types\.standard\.fallback\]\]/);
  assert.match(result, /\[types\.heavy\]/);
  assert.match(result, /\[roles\.planner\]\ntype = "standard"/);
  assert.match(result, /\[roles\.guard\]\ntype = "standard"\nenabled = true/);
  assert.match(toToml({ named: { ...model('pi', 'model "quoted"'), fallback: [] } }, {}), /model = "model \\\"quoted\\\""/);
  assert.equal(roleType(roles.planner, types), 'standard');
});

test('unmanaged TOML sections and top-level comments survive composition', () => {
  const source = '# keep this note\nversion = 1\nmax_no_progress_restarts = 7\n\n[claude_cli]\nenabled = true\n\n[codex_app_server]\nbinary = "/custom/codex"\n\n[policy]\nnever_models = ["custom"]\nallow_fallback_only_on = ["provider_limit"]\ncreate_paseo_projects = false\n\n[types.old]\nharness = "pi"\n';
  const retained = preserveUnmanagedToml(source);
  assert.match(retained, /# keep this note/);
  assert.match(retained, /max_no_progress_restarts = 7/);
  assert.match(retained, /enabled = true/);
  assert.match(retained, /binary = "\/custom\/codex"/);
  assert.match(retained, /never_models = \["custom"\]/);
  assert.doesNotMatch(retained, /\[types\.old\]/);
  const composed = toToml({ named: { ...model('pi', 'deepseek'), fallback: [] } }, {}, source);
  assert.match(composed, /max_no_progress_restarts = 7/);
  assert.match(composed, /binary = "\/custom\/codex"/);
  assert.match(composed, /never_models = \["custom"\]/);
  assert.match(composed, /# keep this note/);
});

test('guard validation follows its selected type', () => {
  const types = { standard: { ...model('claude-sdk', 'claude-sonnet-5-5'), fallback: [], guard_eligible: false }, light: { ...model('pi', 'deepseek'), fallback: [], guard_eligible: true } };
  assert.equal(guardOk(types, { type: 'standard', enabled: true, ...model('claude-sdk', 'claude-sonnet-5-5') }), false);
  assert.equal(guardOk(types, { type: 'light', enabled: true, ...model('pi', 'deepseek') }), true);
});

const auditSource = `# audit seed
[policy]
never_models = ["*-sol"]
allow_fallback_only_on = ["provider_limit"]

[types.light]
harness = "pi"
model = "deepseek"
reasoning_effort = "low"

[types.heavy]
harness = "claude-sdk"
model = "claude-sonnet-5-5"
reasoning_effort = "high"

[roles.builder]
type = "light" # builder mapping

[roles.manager-bot]
type = "light"
enabled = false
`;
const auditTypes = {
  light: { ...model('pi', 'deepseek', 'low'), fallback: [] },
  heavy: { ...model('claude-sdk', 'claude-sonnet-5-5', 'high'), fallback: [] },
};
const auditRoles = {
  builder: { type: 'light', ...model('pi', 'deepseek', 'low') },
  'manager-bot': { type: 'light', ...model('pi', 'deepseek', 'low'), enabled: false },
};

test('toToml patches a role type in place and keeps unrelated role fields', () => {
  const changedRoles = { ...auditRoles, builder: { ...auditRoles.builder, type: 'heavy' } };
  const result = toToml(auditTypes, changedRoles, auditSource);
  const changedLines = auditSource.split('\n').filter((line, index) => line !== result.split('\n')[index]);

  assert.deepEqual(changedLines, ['type = "light" # builder mapping']);
  assert.equal(result, auditSource.replace('type = "light" # builder mapping', 'type = "heavy" # builder mapping'));
  assert.match(result, /\[policy\][\s\S]*\[types\.light\]/);
  assert.match(result, /\[roles\.manager-bot\]\ntype = "light"\nenabled = false/);
});

test('toToml returns an unchanged source byte-for-byte', () => {
  assert.equal(toToml(auditTypes, auditRoles, auditSource), auditSource);
});

test('toToml removes the final fallback table and preserves unrelated settings', () => {
  const source = `# keep policy before types
[policy]
never_models = ["*-sol"]
allow_fallback_only_on = ["provider_limit"]

[types.light]
harness = "pi"
model = "deepseek"
reasoning_effort = "low"

[[types.light.fallback]]
harness = "claude-sdk"
model = "claude-sonnet-5-5"
reasoning_effort = "high"

[roles.manager-bot]
type = "light"
enabled = false
`;
  const changedTypes = {
    ...auditTypes,
    light: { ...auditTypes.light, fallback: [] },
  };
  const result = toToml(changedTypes, auditRoles, source);

  assert.doesNotMatch(result, /\[\[types\.light\.fallback\]\]/);
  assert.match(result, /\[policy\][\s\S]*\[types\.light\]/);
  assert.match(result, /\[types\.light\][\s\S]*\[roles\.manager-bot\]/);
  assert.match(result, /\[roles\.manager-bot\]\ntype = "light"\nenabled = false/);
  assert.match(result, /never_models = \["\*-sol"\][\s\S]*allow_fallback_only_on = \["provider_limit"\]/);
});

test('toToml patches changed type fields and appends new tables after the source', () => {
  const changedTypes = {
    ...auditTypes,
    light: { ...auditTypes.light, model: 'deepseek-v2' },
    newType: { ...model('pi', 'new-model'), fallback: [] },
  };
  const changedRoles = {
    ...auditRoles,
    planner: { type: 'newType', ...model('pi', 'new-model') },
  };
  const result = toToml(changedTypes, changedRoles, auditSource);

  assert.match(result, /\[types\.light\]\nharness = "pi"\nmodel = "deepseek-v2"/);
  assert.ok(result.indexOf('[types.newType]') > result.indexOf('[roles.manager-bot]'));
  assert.ok(result.indexOf('[roles.planner]') > result.indexOf('[types.newType]'));
  assert.match(result, /\[roles\.planner\]\ntype = "newType"/);
  assert.match(result, /\[roles\.manager-bot\]\ntype = "light"\nenabled = false/);
});
