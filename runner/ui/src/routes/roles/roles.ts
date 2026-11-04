export type Choice = { id: string; label?: string; thinkingOptions?: Choice[]; defaultThinkingOptionId?: string };
export type ProviderModel = Choice;
export type Model = { harness: string; model: string; reasoning_effort: string };
export type Fallback = Model;
export type ModelType = Model & { fallback: Fallback[]; guard_eligible?: boolean };
export type Role = { type: string | null; harness: string; model: string; reasoning_effort: string; enabled?: boolean };
export type ModelData = { providers: Record<string, ProviderModel[]>; fallback: Record<string, { id: string }[]>; models_by_harness: Record<string, { id: string }[]>; harnesses: string[]; native_harnesses: string[]; error: string | null };

export const efforts = ['low', 'medium', 'high', 'xhigh'];
export const defaultFallback: Model = { harness: 'opencode-http', model: 'opencode-go/deepseek-v4.1-flash', reasoning_effort: 'high' };

export function identityDescription(identities: { id: string; description: string }[], role: string): string {
  return identities.find((identity) => identity.id === role)?.description ?? '';
}

export function providerId(harness: string) { return ({ 'codex-app-server': 'codex', pi: 'pi', 'claude-sdk': 'claude' } as Record<string, string>)[harness] ?? ''; }
export function optionText(item: ProviderModel) { return item.label ?? item.id.split('/').at(-1) ?? item.id; }
function catalogFor(data: ModelData, harness: string): ProviderModel[] {
  if (data.native_harnesses?.includes(harness)) return data.models_by_harness[harness] ?? [];
  const provider = providerId(harness);
  const catalog = data.providers[provider] ?? [];
  return catalog.length ? catalog : data.fallback[provider] ?? [];
}
export function modelChoices(data: ModelData, current: Model) {
  const choices = (data.harnesses ?? []).flatMap((harness) => catalogFor(data, harness).map((item) => ({ value: `${harness}::${item.id}`, label: optionText(item) })));
  if (!choices.some((choice) => choice.value === modelValue(current))) choices.unshift({ value: modelValue(current), label: optionText({ id: current.model }) });
  return choices;
}
export function modelValue(model: Model) { return `${model.harness}::${model.model}`; }
export function effortOptions(data: ModelData, model: Model) {
  const item = catalogFor(data, model.harness).find((entry) => entry.id === model.model);
  const options = item?.thinkingOptions?.map((option) => option.id) ?? efforts;
  return options.includes(model.reasoning_effort) ? options : [model.reasoning_effort, ...options];
}
export function applyChoice(data: ModelData, model: Model, value: string) {
  const [harness, ...rest] = value.split('::'); model.harness = harness; model.model = rest.join('::');
  const item = catalogFor(data, harness).find((entry) => entry.id === model.model);
  const allowed = item?.thinkingOptions?.map((option) => option.id);
  if (!allowed?.length || allowed.includes(model.reasoning_effort)) return;
  model.reasoning_effort = item?.defaultThinkingOptionId && allowed.includes(item.defaultThinkingOptionId) ? item.defaultThinkingOptionId : allowed[0];
}
export function guardOk(types: Record<string, ModelType>, role: Role) {
  return !role.enabled || !role.type || types[role.type]?.guard_eligible === true;
}
export function roleType(role: Role, types: Record<string, ModelType>) {
  return role.type && types[role.type] ? role.type : Object.keys(types)[0] ?? '';
}
function quoted(value: string) { return JSON.stringify(value); }
function modelFields(model: Model) { return `harness = ${quoted(model.harness)}\nmodel = ${quoted(model.model)}\nreasoning_effort = ${quoted(model.reasoning_effort)}`; }
type TomlTable = { name: string; array: boolean; start: number; end: number };

function tableHeaders(lines: string[]): TomlTable[] {
  const found: Omit<TomlTable, 'end'>[] = [];
  lines.forEach((line, start) => {
    const match = line.match(/^\s*(\[\[([^\]]+)\]\]|\[([^\]]+)\])\s*(?:#.*)?(?:\r?\n)?$/);
    if (!match) return;
    const name = (match[2] ?? match[3]).replace(/["']/g, '');
    found.push({ name, array: Boolean(match[2]), start });
  });
  return found.map((table, index) => ({
    ...table,
    end: found[index + 1]?.start ?? lines.length,
  }));
}

function tomlString(value: string): string | null {
  const text = value.trim();
  if (text.startsWith('"') && text.endsWith('"')) {
    try { return JSON.parse(text) as string; }
    catch { return null; }
  }
  if (text.startsWith("'") && text.endsWith("'")) return text.slice(1, -1);
  return null;
}

function splitTomlComment(value: string): [string, string] {
  let quote = '';
  let escaped = false;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (escaped) { escaped = false; continue; }
    if (quote === '"' && character === '\\') { escaped = true; continue; }
    if ((character === '"' || character === "'") && (!quote || quote === character)) {
      quote = quote ? '' : character;
      continue;
    }
    if (character === '#' && !quote) {
      let start = index;
      while (start > 0 && /\s/.test(value[start - 1])) start -= 1;
      return [value.slice(0, start), value.slice(start)];
    }
  }
  return [value, ''];
}

function patchTable(lines: string[], fields: Record<string, string>): string[] {
  const seen = new Set<string>();
  const patched = lines.map((line) => {
    const match = line.match(/^(\s*)([\w-]+)(\s*=\s*)(.*?)(\r?\n)?$/);
    if (!match || !(match[2] in fields)) return line;
    const [, indent, key, assignment, rawValue, ending = ''] = match;
    seen.add(key);
    const [value, comment] = splitTomlComment(rawValue);
    if (tomlString(value) === fields[key]) return line;
    return `${indent}${key}${assignment}${quoted(fields[key])}${comment}${ending}`;
  });
  const missing = Object.entries(fields).filter(([key]) => !seen.has(key));
  if (missing.length === 0) return patched;
  let insertAt = patched.length;
  while (insertAt > 1 && /^\s*(?:#.*)?(?:\r?\n)?$/.test(patched[insertAt - 1])) insertAt -= 1;
  const ending = patched.find((line) => line.endsWith('\r\n')) ? '\r\n' : '\n';
  const additions = missing.map(([key, value]) => `${key} = ${quoted(value)}${ending}`);
  if (insertAt > 0 && !patched[insertAt - 1].endsWith('\n')) patched[insertAt - 1] += ending;
  patched.splice(insertAt, 0, ...additions);
  return patched;
}

function appendType(name: string, type: ModelType): string {
  let result = `[types.${name}]\n${modelFields(type)}\n\n`;
  for (const fallback of type.fallback) result += `[[types.${name}.fallback]]\n${modelFields(fallback)}\n\n`;
  return result;
}

function appendRole(name: string, role: Role, types: Record<string, ModelType>): string {
  let result = `[roles.${name}]\ntype = ${quoted(roleType(role, types))}\n`;
  if (name === 'guard') result += `enabled = ${Boolean(role.enabled)}\n`;
  return `${result}\n`;
}

function patchToml(types: Record<string, ModelType>, roles: Record<string, Role>, source: string): string {
  const lines = source.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  const tables = tableHeaders(lines);
  const patches = new Map<number, Record<string, string>>();
  const removals = new Set<number>();
  const append: string[] = [];

  for (const [name, type] of Object.entries(types)) {
    const baseName = `types.${name}`;
    const base = tables.find((table) => !table.array && table.name === baseName);
    if (!base) { append.push(appendType(name, type)); continue; }
    patches.set(base.start, { harness: type.harness, model: type.model, reasoning_effort: type.reasoning_effort });
    const fallbacks = tables.filter((table) => table.array && table.name === `${baseName}.fallback`);
    type.fallback.forEach((fallback, index) => {
      const table = fallbacks[index];
      if (table) patches.set(table.start, { harness: fallback.harness, model: fallback.model, reasoning_effort: fallback.reasoning_effort });
      else append.push(`[[${baseName}.fallback]]\n${modelFields(fallback)}\n\n`);
    });
    for (const table of fallbacks.slice(type.fallback.length)) removals.add(table.start);
  }

  for (const [name, role] of Object.entries(roles)) {
    const table = tables.find((item) => !item.array && item.name === `roles.${name}`);
    const type = roleType(role, types);
    if (table) patches.set(table.start, { ...(patches.get(table.start) ?? {}), type });
    else append.push(appendRole(name, role, types));
  }

  for (const table of [...tables].reverse()) {
    if (removals.has(table.start)) {
      lines.splice(table.start, table.end - table.start);
      continue;
    }
    const fields = patches.get(table.start);
    if (fields) lines.splice(table.start, table.end - table.start, ...patchTable(lines.slice(table.start, table.end), fields));
  }
  if (append.length === 0) return lines.join('');
  const prefix = lines.join('');
  const separator = prefix.length === 0 ? '' : prefix.endsWith('\n\n') ? '' : prefix.endsWith('\n') ? '\n' : '\n\n';
  return `${prefix}${separator}${append.join('')}`;
}

export function preserveUnmanagedToml(source: string) {
  const blocks: string[] = [];
  let current = '';
  let managed = false;
  for (const line of source.split(/(?<=\n)/)) {
    const header = line.match(/^\s*\[\[?\s*([\w."'-]+?)\s*\]\]?/);
    if (header) {
      if (current && !managed) blocks.push(current);
      current = '';
      const root = header[1].replace(/["']/g, '').split('.')[0];
      managed = root === 'roles' || root === 'types';
    }
    current += line;
  }
  if (current && !managed) blocks.push(current);
  return blocks.join('').trim();
}
export function toToml(types: Record<string, ModelType>, roles: Record<string, Role>, source = '') {
  if (source) return patchToml(types, roles, source);
  const preserved = preserveUnmanagedToml(source);
  const lines = preserved ? [preserved, ''] : [
    'version = 1', 'max_no_progress_restarts = 3', '', '[claude_cli]', 'enabled = false', '',
    '[claude_sdk]', 'enabled = true', 'stream_idle_timeout_s = 300', '',
    '[codex_app_server]', 'enabled = true', '', '[pi_rpc]', 'enabled = true', '',
    '[opencode_http]', 'enabled = true', '', '[policy]', 'never_models = ["*-sol"]',
    'allow_fallback_only_on = ["provider_limit"]', 'create_paseo_projects = false', '',
  ];
  for (const [name, type] of Object.entries(types)) {
    lines.push(`[types.${name}]`, modelFields(type), '');
    for (const fallback of type.fallback) lines.push(`[[types.${name}.fallback]]`, modelFields(fallback), '');
  }
  for (const [name, role] of Object.entries(roles)) {
    lines.push(`[roles.${name}]`, `type = ${quoted(roleType(role, types))}`);
    if (name === 'guard') lines.push(`enabled = ${Boolean(role.enabled)}`);
    lines.push('');
  }
  return lines.join('\n');
}

export function summarizeRoleChanges(before: string, after: string): { lines: string[]; unrelated: string[] } {
  const entries = (source: string) => {
    const values = new Map<string, string>();
    let section = '';
    for (const line of source.split(/\r?\n/)) {
      const header = line.match(/^\s*\[\[?\s*([\w."'-]+?)\s*\]\]?/);
      if (header) { section = header[1].replace(/["']/g, ''); continue; }
      const assignment = line.match(/^\s*([\w-]+)\s*=\s*(.*)$/);
      if (!assignment) continue;
      const raw = assignment[2];
      let quote = '';
      let escaped = false;
      let end = raw.length;
      for (let index = 0; index < raw.length; index += 1) {
        const character = raw[index];
        if (escaped) { escaped = false; continue; }
        if (quote === '"' && character === '\\') { escaped = true; continue; }
        if ((character === '"' || character === "'") && (!quote || quote === character)) quote = quote ? '' : character;
        else if (character === '#' && !quote) { end = index; break; }
      }
      values.set(section ? `${section}.${assignment[1]}` : assignment[1], raw.slice(0, end).trim());
    }
    return values;
  };
  const display = (value: string | undefined) => {
    if (value === undefined) return 'unset';
    if (value.startsWith('"') && value.endsWith('"')) {
      try { return JSON.parse(value) as string; }
      catch { return value; }
    }
    return value.startsWith("'") && value.endsWith("'") ? value.slice(1, -1) : value;
  };
  const oldValues = entries(before);
  const newValues = entries(after);
  const title = (value: string) => value.replaceAll('_', ' ').replaceAll('-', ' ').replace(/\b\w/g, (character) => character.toUpperCase());
  const changed = (label: string, oldValue: string | undefined, newValue: string | undefined) =>
    `${label} changed from ${display(oldValue)} to ${display(newValue)}`;
  const lines: string[] = [];
  const unrelated: string[] = [];
  for (const key of [...new Set([...oldValues.keys(), ...newValues.keys()])].sort()) {
    const oldValue = oldValues.get(key);
    const newValue = newValues.get(key);
    if (oldValue === newValue) continue;
    const roleField = key.match(/^roles\.([^.]+)\.([^.]+)$/);
    const typeField = key.match(/^types\.([^.]+)\.([^.]+)$/);
    if (roleField && roleField[2] === 'enabled') {
      lines.push(`${title(roleField[1])}: turned ${newValue === 'true' ? 'on' : 'off'}`);
      continue;
    }
    if (roleField && roleField[2] === 'type') {
      const roleName = title(roleField[1]);
      if (newValue === undefined) lines.push(`${roleName}: no type assigned`);
      else if (oldValue === undefined) lines.push(`${roleName}: assigned to the ${title(display(newValue))} type`);
      else lines.push(`${roleName}: type changed from ${title(display(oldValue))} to ${title(display(newValue))}`);
      continue;
    }
    if (typeField) {
      const fieldName: Record<string, string> = { harness: 'execution environment', model: 'model', reasoning_effort: 'reasoning level' };
      lines.push(changed(`${title(typeField[1])} type ${fieldName[typeField[2]] ?? title(typeField[2])}`, oldValue, newValue));
      continue;
    }
    lines.push(changed(key.replaceAll('.', ' ').replaceAll('_', ' '), oldValue, newValue));
  }
  return { lines, unrelated };
}
