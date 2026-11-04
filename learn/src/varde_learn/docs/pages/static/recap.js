// Host component runtime. One hydration loop keyed by `data-component`, one
// shared `$` form-state helper, one answer bridge (`postAnswer`) using the page
// token. Component props arrive only as a `data-props` attribute (JSON, escaped
// by the server); they are parsed with JSON.parse, then reduced to a per-
// component whitelist of keys and types. All text goes through textContent; no
// inline script, no eval, no HTML built from data.
//
// Loaded as a classic deferred script (the page shell and static map are
// owned by other files), so it shares code through `window.varde`, not imports.
(() => {
  'use strict';
  const page = document.querySelector('main[data-role="page"]');
  if (!page) return;

  // ---- props: parse, then whitelist -----------------------------------------

  // Port of pages/render.py classify_url; tests/docs/fixtures/url-vectors.json is
  // run against both, so they cannot drift. Returns 'link', 'relative' or 'text'.
  const SAFE_URL = /^(https?:\/\/[A-Za-z0-9\-._~:/?#[\]@!$&()*+,;=%]+|#[A-Za-z0-9\-._~:/?#%]*)$/;
  // Python `\s` plus the ASCII control range and DEL (not JS `\s`: it differs).
  const STRIP = /[\u0000-\u0020\u007f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/g;

  // HTML entity decoding like Python html.unescape. A `<title>` is RCDATA: it
  // decodes entities and never builds elements; `<` is escaped so the text
  // cannot close it. Raw NUL is dropped first (the parser would rewrite it).
  function unescapeEntities(text) {
    const clean = text.replace(/\u0000/g, '');
    if (!clean.includes('&')) return clean;
    const markup = '<!doctype html><title>' + clean.replace(/</g, '&lt;') + '</title>';
    const title = new DOMParser().parseFromString(markup, 'text/html').querySelector('title');
    return title ? title.textContent : clean;
  }

  function classifyUrl(url) {
    const stripped = unescapeEntities(url).replace(STRIP, '');
    if (SAFE_URL.test(url) && stripped === url) return 'link';
    if (!stripped || stripped.startsWith('//') || stripped.startsWith('\\') || stripped.includes('\\')) return 'text';
    const head = stripped.split(/[/?#]/, 1)[0];
    return head.includes(':') || /[^\u0000-\u007f]/.test(stripped) ? 'text' : 'relative';
  }

  // The value when it is a link or relative reference, else null.
  function safeUrl(value) {
    if (typeof value !== 'string') return null;
    return classifyUrl(value) === 'text' ? null : value;
  }

  const TYPES = {
    string: (v) => (typeof v === 'string' ? v : undefined),
    number: (v) => (typeof v === 'number' && Number.isFinite(v) ? v : undefined),
    boolean: (v) => (typeof v === 'boolean' ? v : undefined),
    url: (v) => safeUrl(v) ?? undefined,
    strings: (v) => (Array.isArray(v) && v.every((x) => typeof x === 'string') ? v.slice() : undefined),
    fields: (v) => (Array.isArray(v) && v.length <= 50 ? readFields(v) : undefined),
  };

  const FIELD_TYPES = ['text', 'number', 'select', 'checkbox'];
  const FIELD_NAME = /^[a-z][a-z0-9_-]{0,47}$/; // the server's rule; bars `__proto__`

  // Form field descriptors: only name, type, required, min and max survive; one
  // bad entry rejects the list, so the form never sends a partial answer.
  function readFields(list) {
    const fields = [];
    for (const raw of list) {
      if (raw === null || typeof raw !== 'object' || typeof raw.name !== 'string') return undefined;
      if (!FIELD_TYPES.includes(raw.type) || !FIELD_NAME.test(raw.name)) return undefined;
      const field = { name: raw.name, type: raw.type, required: raw.required === true };
      for (const key of ['min', 'max']) {
        if (typeof raw[key] === 'number' && Number.isFinite(raw[key])) field[key] = raw[key];
      }
      fields.push(field);
    }
    return fields;
  }

  // `schema` maps key -> type name above. Unknown keys and wrong types are dropped.
  function readProps(element, schema) {
    const props = {};
    let raw;
    try {
      raw = JSON.parse(element.getAttribute('data-props') || '{}');
    } catch (error) {
      return props;
    }
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return props;
    for (const [key, type] of Object.entries(schema)) {
      if (!Object.prototype.hasOwnProperty.call(raw, key)) continue;
      const value = TYPES[type](raw[key]);
      if (value !== undefined) props[key] = value;
    }
    return props;
  }

  // ---- `$` form state ---------------------------------------------------------

  const values = new Map();
  const watchers = new Map();

  const formState = {
    get: (name) => values.get(name),
    set(name, value) {
      values.set(name, value);
      for (const watcher of watchers.get(name) || []) {
        try {
          watcher(value);
        } catch (error) {
          console.error(error);
        }
      }
    },
    watch(name, watcher) {
      if (!watchers.has(name)) watchers.set(name, new Set());
      watchers.get(name).add(watcher);
      return () => {
        const set = watchers.get(name);
        set.delete(watcher);
        if (!set.size) watchers.delete(name);
      };
    },
  };

  // ---- answer bridge ----------------------------------------------------------

  function setNote(container, selector, message) {
    const note = container && container.querySelector(selector);
    if (note) note.textContent = message;
  }

  // `item` = { kind, id, anchor }. Input components post one unified row
  // `{ kind: 'answer', item, value, text, anchor }`, validated by the server
  // against the component's own props. A recap `drift` judgment is page state,
  // not an answer, and keeps its own row. Returns true when stored; a failure
  // is written to `note` (a { container, selector } pair).
  async function postAnswer(item, value, text, note) {
    const token = document.querySelector('meta[name="varde-token"]');
    const headers = { 'Content-Type': 'application/json', 'X-Varde-Token': token ? token.content : '' };
    const payload = item.kind === 'drift'
      ? { anchor: item.anchor, kind: 'drift', item: item.id, verdict: value, text: text || '' }
      : { anchor: item.anchor, kind: 'answer', item: item.id, value, text: text || '' };
    const report = (message) => note && setNote(note.container, note.selector, message);
    report('');
    try {
      const response = await fetch('/comments', { method: 'POST', headers, body: JSON.stringify(payload) });
      if (response.ok) return true;
      report('Not saved (' + response.status + ').');
    } catch (error) {
      report('Not saved: server unreachable.');
    }
    return false;
  }

  // ---- hydration loop ---------------------------------------------------------

  const registry = new Map();

  // hydrator: { props: schema, hydrate(element, props) }. A component may also
  // hydrate markup the server renders without `data-props`.
  function register(name, hydrator) {
    registry.set(name, hydrator);
  }

  function hydrate(scope) {
    for (const element of scope.querySelectorAll('[data-component]:not([data-hydrated])')) {
      const hydrator = registry.get(element.dataset.component);
      if (!hydrator) continue;
      element.dataset.hydrated = '1';
      hydrator.hydrate(element, readProps(element, hydrator.props || {}));
    }
  }

  window.varde = Object.freeze({ readProps, classifyUrl, safeUrl, formState, postAnswer, register, hydrate });

  // ---- built-in components: recap drift buttons and decision verdicts ---------

  function itemOf(kind, entry) {
    const block = entry.closest('.block');
    return block ? { kind, id: entry.dataset.item, anchor: block.dataset.anchor } : null;
  }

  // test_pages_decision pins this local name in `decide`.
  const post = postAnswer;

  async function judge(button) {
    const recap = button.closest('.recap');
    const entry = button.closest('.recap-item');
    const item = recap && entry && itemOf('drift', entry);
    if (!item) return;
    const verdict = button.dataset.verdict;
    if (!(await postAnswer(item, verdict, '', { container: recap, selector: '.recap-error' }))) return;
    entry.querySelector('.recap-state').textContent = verdict;
    entry.dataset.verdict = verdict;
  }

  async function decide(entry, verdict, text) {
    const decision = entry.closest('.decision');
    const item = decision && itemOf('decision', entry);
    if (!item) return;
    const controls = entry.querySelectorAll('button');
    controls.forEach((control) => { control.disabled = true; });
    const saved = await post(item, verdict, text, { container: decision, selector: '.decision-error' });
    controls.forEach((control) => { control.disabled = false; });
    if (!saved) return;
    entry.querySelector('.decision-state').textContent = verdict;
    entry.dataset.verdict = verdict;
    const field = entry.querySelector('.decision-comment');
    if (field) field.hidden = true;
  }

  function chooseDecision(button) {
    const entry = button.closest('.decision-item');
    if (!entry) return;
    if (button.dataset.verdict !== 'commented') return decide(entry, button.dataset.verdict, '');
    const field = entry.querySelector('.decision-comment');
    if (!field) return;
    field.hidden = false;
    const area = field.querySelector('.decision-text');
    if (area) area.focus();
  }

  function sendComment(button) {
    const entry = button.closest('.decision-item');
    const area = entry && entry.querySelector('.decision-text');
    if (!area) return;
    if (!area.value.trim()) return setNote(entry.closest('.decision'), '.decision-error', 'A comment needs text.');
    decide(entry, 'commented', area.value);
  }

  // ---- input components: choice, form, comment --------------------------------

  // Posts one unified `answer` row for the widget `root`; the server validates it
  // against the component's own props. Returns true when stored.
  async function sendAnswer(root, kind, value, text) {
    const entry = root.querySelector('.' + kind + '-item');
    const block = root.closest('.block');
    if (!entry || !block) return false;
    const note = { container: root, selector: '.' + kind + '-error' };
    // Only controls that were live are paused and restored: read-only ones stay off.
    const controls = Array.from(root.querySelectorAll('button, input, select, textarea')).filter((control) => !control.disabled);
    const focused = controls.find((control) => control === document.activeElement);
    controls.forEach((control) => { control.disabled = true; });
    const saved = await postAnswer({ kind: 'answer', id: entry.dataset.item, anchor: block.dataset.anchor }, value, text, note);
    controls.forEach((control) => { control.disabled = false; });
    if (focused) focused.focus(); // disabling dropped focus to the body
    if (saved) setNote(root, '.' + kind + '-state', 'Sent');
    return saved;
  }

  // Shows `message`, ties it to `control` with aria-describedby and moves focus there.
  function fail(root, kind, message, control) {
    setNote(root, '.' + kind + '-error', message);
    const note = root.querySelector('.' + kind + '-error');
    if (!control) return;
    if (note && note.id) control.setAttribute('aria-describedby', note.id);
    control.focus();
  }

  function onSubmit(root, kind, handler) {
    const form = root.querySelector('form');
    if (!form) return;
    const clear = () => setNote(root, '.' + kind + '-state', '');
    form.addEventListener('input', clear);
    form.addEventListener('change', clear);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      handler(form);
    });
  }

  // Shared with `inputs_ordered.js`, which loads after this file.
  window.varde = Object.freeze({ ...window.varde, inputs: Object.freeze({ sendAnswer, onSubmit, fail }) });

  function textOf(root, kind) {
    const area = root.querySelector('.' + kind + '-text');
    return area ? area.value : '';
  }

  // Clears a choice error: text, aria-invalid on the options and the group link.
  function clearChoiceError(root) {
    setNote(root, '.choice-error', '');
    root.querySelectorAll('.choice-option input').forEach((input) => input.removeAttribute('aria-invalid'));
  }

  register('choice', {
    props: { multiple: 'boolean', comment: 'boolean' },
    hydrate(root, props) {
      const group = root.querySelector('.choice-group');
      if (group) group.addEventListener('change', () => clearChoiceError(root));
      onSubmit(root, 'choice', (form) => {
        const picked = Array.from(form.querySelectorAll('input:checked')).map((input) => input.value);
        if (!picked.length) {
          const options = form.querySelectorAll('.choice-option input');
          options.forEach((input) => input.setAttribute('aria-invalid', 'true'));
          return fail(root, 'choice', 'Pick an option.', options[0]);
        }
        clearChoiceError(root);
        sendAnswer(root, 'choice', props.multiple ? picked : picked[0], textOf(root, 'choice'));
      });
    },
  });

  // Auto-grow only where `field-sizing: content` is missing; one read, one write per input.
  function autoGrow(area) {
    if (CSS.supports('field-sizing', 'content')) return;
    area.style.blockSize = 'auto';
    area.style.blockSize = area.scrollHeight + 'px';
  }

  // Updates the visible counter always; the live region speaks only at 80% and 100%.
  function countComment(root, area, state) {
    const max = area.maxLength;
    const length = area.value.length;
    const count = root.querySelector('.comment-count');
    if (count) count.textContent = length + ' / ' + max;
    const level = length >= max ? 2 : length >= max * 0.8 ? 1 : 0;
    if (level === state.level) return;
    state.level = level;
    const announce = root.querySelector('.comment-announce');
    if (announce) announce.textContent = level === 2 ? 'Character limit reached.' : level === 1 ? (max - length) + ' characters left.' : '';
  }

  register('comment', {
    hydrate(root) {
      const area = root.querySelector('.comment-text');
      const state = { level: 0 };
      if (area) area.addEventListener('input', () => { countComment(root, area, state); autoGrow(area); });
      onSubmit(root, 'comment', async () => {
        const text = textOf(root, 'comment');
        if (!text.trim()) return fail(root, 'comment', 'A comment needs text.', area);
        setNote(root, '.comment-state', 'Sending...');
        const saved = await sendAnswer(root, 'comment', 'commented', text);
        if (!saved) setNote(root, '.comment-state', '');
      });
    },
  });

  // The value of one form control, or an Error (with `control`) naming what is wrong.
  function fieldValue(field, control) {
    const bad = (message) => Object.assign(new Error(message), { control });
    if (!control) return bad('Form is incomplete.');
    if (field.type === 'checkbox') {
      return field.required && !control.checked ? bad(field.name + ' must be ticked.') : control.checked;
    }
    if (field.type !== 'number') {
      return field.required && !control.value.trim() ? bad(field.name + ' is required.') : control.value;
    }
    if (!control.value.trim()) return field.required ? bad(field.name + ' is required.') : null;
    const number = Number(control.value);
    if (!Number.isFinite(number)) return bad(field.name + ' must be a number.');
    if (field.min !== undefined && number < field.min) return bad(field.name + ' is below ' + field.min + '.');
    if (field.max !== undefined && number > field.max) return bad(field.name + ' is above ' + field.max + '.');
    return number;
  }

  // True when a required field is still empty (unticked, blank or unselected).
  function unfilled(field, control) {
    if (!field.required || !control) return false;
    return field.type === 'checkbox' ? !control.checked : !control.value.trim();
  }

  function showRemaining(root, fields, controls) {
    const count = fields.filter((field) => unfilled(field, controls.get(field.name))).length;
    if (!fields.some((field) => field.required)) return;
    const text = count ? count + ' required ' + (count === 1 ? 'field' : 'fields') + ' left' : 'All required fields filled';
    setNote(root, '.form-remaining', text);
  }

  // Marks `control` invalid and keeps its hint beside the error in aria-describedby.
  function markInvalid(root, control) {
    const note = root.querySelector('.form-error');
    const hint = (control.dataset.hint || '');
    control.setAttribute('aria-invalid', 'true');
    if (note && note.id) control.setAttribute('aria-describedby', (hint + ' ' + note.id).trim());
  }

  register('form', {
    props: { fields: 'fields' },
    hydrate(root, props) {
      const fields = props.fields || [];
      const controls = new Map();
      root.querySelectorAll('[data-field]').forEach((control) => {
        controls.set(control.dataset.field, control);
        control.dataset.hint = control.getAttribute('aria-describedby') || '';
      });
      const update = (event) => {
        const target = event && event.target;
        if (target && target.removeAttribute) {
          target.removeAttribute('aria-invalid');
          if (target.dataset && 'hint' in target.dataset) {
            if (target.dataset.hint) target.setAttribute('aria-describedby', target.dataset.hint);
            else target.removeAttribute('aria-describedby');
          }
        }
        if (!root.querySelector('[aria-invalid]')) setNote(root, '.form-error', '');
        showRemaining(root, fields, controls);
      };
      root.addEventListener('input', update);
      root.addEventListener('change', update);
      showRemaining(root, fields, controls);
      onSubmit(root, 'form', () => {
        const value = Object.create(null);
        for (const field of fields) {
          const got = fieldValue(field, controls.get(field.name));
          if (got instanceof Error) {
            fail(root, 'form', got.message, got.control);
            if (got.control) markInvalid(root, got.control);
            return;
          }
          value[field.name] = got;
        }
        sendAnswer(root, 'form', value, '');
      });
    },
  });

  // One delegated click handler: it keeps working when app.js swaps blocks.
  register('answers', {
    hydrate(root) {
      root.addEventListener('click', (event) => {
        const target = event.target instanceof Element ? event.target : null;
        const verdict = target && target.closest('.recap-verdict');
        if (verdict) return judge(verdict);
        const choice = target && target.closest('.decision-verdict');
        if (choice) return chooseDecision(choice);
        const send = target && target.closest('.decision-send');
        if (send) sendComment(send);
      });
    },
  });
  // Temporary: the page root carries no `data-component` because server markup
  // is not emitted yet; the assembler should write it, then drop this line.
  page.dataset.component = 'answers';
  hydrate(document);
  new MutationObserver(() => hydrate(document)).observe(page, { childList: true, subtree: true });
})();
