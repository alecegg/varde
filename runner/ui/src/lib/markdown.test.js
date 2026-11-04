import test from 'node:test';
import assert from 'node:assert/strict';
import { renderMarkdown } from './markdown.ts';

test('renders task lists as disabled checkboxes', () => {
  assert.equal(
    renderMarkdown('- [ ] Pending task\n- [x] Finished task'),
    '<ul><li class="task-list-item"><input type="checkbox" disabled> Pending task</li><li class="task-list-item"><input type="checkbox" disabled checked> Finished task</li></ul>',
  );
});

test('omits headings without content before the next heading', () => {
  assert.equal(renderMarkdown('## Progress\n\n## Tasks\n- [ ] Ship it'), '<h3>Tasks</h3><ul><li class="task-list-item"><input type="checkbox" disabled> Ship it</li></ul>');
});

test('keeps parent headings that contain nested sections', () => {
  assert.equal(renderMarkdown('## Plan\n### Tasks\n- [ ] Ship it'), '<h3>Plan</h3><h4>Tasks</h4><ul><li class="task-list-item"><input type="checkbox" disabled> Ship it</li></ul>');
});
