// Input components `ranking` and `slider`. Loads after `recap.js` (which hosts
// `window.varde` and the send/submit/focus helpers shared with `choice`). The
// server writes all markup; props are the slider's three numbers only. Text goes
// through textContent; no inline script or style, no HTML built from data.
(() => {
  'use strict';
  const host = window.varde;
  if (!host) return console.error('inputs_ordered.js: window.varde is missing');
  if (!host.inputs) {
    // A stale or reordered `recap.js`: say so on the widget instead of staying dead.
    console.error('inputs_ordered.js: window.varde.inputs is missing');
    for (const name of ['ranking', 'slider']) {
      host.register(name, {
        hydrate(root) {
          const note = root.querySelector('.' + name + '-error');
          if (note) note.textContent = 'This input could not start; reload the page.';
        },
      });
    }
    return host.hydrate(document);
  }
  const { sendAnswer, onSubmit, fail } = host.inputs;

  // ---- ranking ----------------------------------------------------------------

  function announce(root, message) {
    const live = root.querySelector('.ranking-live');
    if (!live) return;
    live.textContent = ''; // clear first so an identical message is announced again
    requestAnimationFrame(() => { live.textContent = message; });
  }

  function positionText(list, row) {
    const rows = Array.from(list.children);
    return row.dataset.label + ' is at position ' + (rows.indexOf(row) + 1) + ' of ' + rows.length + '.';
  }

  function moveRow(root, list, row, direction, button) {
    const rows = Array.from(list.children);
    const target = rows[rows.indexOf(row) + direction];
    if (!target) return announce(root, positionText(list, row) + (direction < 0 ? ' Already first.' : ' Already last.'));
    list.insertBefore(row, direction < 0 ? target : target.nextSibling);
    if (button) button.focus(); // the moved row's own button keeps focus
    announce(root, positionText(list, row));
  }

  // Drag and drop is an extra path; the buttons are the keyboard and touch path.
  function enableDrag(root, list) {
    let dragged = null;
    const clear = () => list.querySelectorAll('.over').forEach((row) => row.classList.remove('over', 'over-before', 'over-after'));
    // Pointer drag only for a fine pointer; touch and keyboard use the buttons.
    if (!window.matchMedia('(pointer: fine)').matches) return;
    for (const row of list.children) row.draggable = true;
    list.addEventListener('dragstart', (event) => {
      // Controls are paused while a send is in flight: the list must not change.
      if (list.querySelector('.ranking-move:disabled')) return event.preventDefault();
      dragged = event.target instanceof Element ? event.target.closest('.ranking-row') : null;
      if (!dragged) return;
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', ''); // Firefox starts no drag without data
      dragged.classList.add('dragging');
    });
    list.addEventListener('dragover', (event) => {
      const over = event.target instanceof Element ? event.target.closest('.ranking-row') : null;
      if (!dragged || !over) return;
      event.preventDefault();
      clear();
      if (over === dragged) return;
      const before = Array.from(list.children).indexOf(over) < Array.from(list.children).indexOf(dragged);
      over.classList.add('over', before ? 'over-before' : 'over-after');
    });
    list.addEventListener('drop', (event) => {
      const over = event.target instanceof Element ? event.target.closest('.ranking-row') : null;
      if (!dragged || !over) return;
      event.preventDefault();
      if (over !== dragged) {
        const rows = Array.from(list.children);
        const after = rows.indexOf(dragged) < rows.indexOf(over);
        list.insertBefore(dragged, after ? over.nextSibling : over);
        announce(root, positionText(list, dragged));
      }
      clear();
    });
    list.addEventListener('dragend', () => {
      if (dragged) dragged.classList.remove('dragging');
      dragged = null;
      clear();
    });
  }

  host.register('ranking', {
    hydrate(root) {
      const list = root.querySelector('.ranking-list');
      if (!list) return;
      const buttons = Array.from(list.querySelectorAll('.ranking-move'));
      const live = buttons.length > 0 && buttons.every((button) => !button.disabled);
      if (live) {
        list.addEventListener('click', (event) => {
          const button = event.target instanceof Element ? event.target.closest('.ranking-move') : null;
          const row = button && button.closest('.ranking-row');
          if (row && !button.disabled) moveRow(root, list, row, Number(button.dataset.dir), button);
        });
        enableDrag(root, list);
      }
      onSubmit(root, 'ranking', () => {
        const ids = Array.from(list.children).map((row) => row.dataset.id);
        sendAnswer(root, 'ranking', ids, '');
      });
    },
  });

  // ---- slider -----------------------------------------------------------------

  // True when `value` lies in [min, max] and is a whole number of steps from min.
  // The spacing of doubles near `x`; the server allows 2 of them as slack.
  function ulp(x) {
    const size = Math.abs(x);
    return size === 0 ? Number.MIN_VALUE : Math.pow(2, Math.floor(Math.log2(size)) - 52);
  }

  function onRange(props, value) {
    if (!Number.isFinite(value) || value < props.min || value > props.max) return false;
    const steps = (value - props.min) / props.step;
    const slack = Math.max(1e-9 * props.step, 2 * ulp(Math.max(Math.abs(props.min), Math.abs(props.max))));
    return Math.abs(steps - Math.round(steps)) * props.step <= slack;
  }

  host.register('slider', {
    props: { min: 'number', max: 'number', step: 'number' },
    hydrate(root, props) {
      const input = root.querySelector('.slider-input');
      const shown = root.querySelector('.slider-value');
      if (!input) return;
      const usable = props.min !== undefined && props.max !== undefined && props.step > 0 && props.min < props.max;
      let moved = false;
      // Fill ratio 0..1 for the track; a CSSOM custom property, never a style attribute.
      const setFill = () => {
        const span = props.max - props.min;
        if (!(span > 0)) return;
        const ratio = (input.valueAsNumber - props.min) / span;
        input.style.setProperty('--vd-fill', String(Math.min(1, Math.max(0, ratio))));
      };
      setFill();
      input.addEventListener('input', () => {
        moved = true;
        const text = String(input.valueAsNumber); // replaces "Not chosen yet"
        input.removeAttribute('aria-valuetext'); // the native value now says the same
        input.dataset.moved = '';
        if (shown) {
          shown.textContent = text;
          shown.dataset.chosen = '';
        }
        setFill();
      });
      onSubmit(root, 'slider', () => {
        if (!usable) return fail(root, 'slider', 'Slider is incomplete.', input);
        if (!moved) return fail(root, 'slider', 'Move the slider to choose a value.', input);
        const value = input.valueAsNumber;
        if (!onRange(props, value)) return fail(root, 'slider', 'Choose a value on the scale.', input);
        sendAnswer(root, 'slider', value, '');
      });
    },
  });

  host.hydrate(document);
})();
