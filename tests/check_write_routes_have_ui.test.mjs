import assert from 'node:assert/strict';
import test from 'node:test';
import { collectWriteCalls, covered } from './check_write_routes_have_ui.mjs';

test('a read-only call or a write to a different method does not satisfy the guard', () => {
  const calls = collectWriteCalls(`
    api('/api/example');
    api('/api/example', {method: 'PUT'});
    ibApi('/api/read-only', null);
  `);
  assert.equal(covered('POST /api/example', calls), false);
  assert.equal(covered('PUT /api/example', calls), true);
  assert.equal(covered('POST /api/read-only', calls), false);
});

test('finite action branches and tuple dispatch preserve actual write routes', () => {
  const calls = collectWriteCalls(`
    function draft(edit) {
      return edit ? ['patch', {}] : ['new', {}];
    }
    function submit(id, choice, edit) {
      const [target, body] = draft(edit);
      api('/api/example/' + target, {method: 'POST', body});
      if (choice === 'release' || choice === 'reject') {
        ibApi(\`/api/inbox/\${id}/\${choice}\`, {});
      }
    }
  `);
  assert.deepEqual([...calls].sort(), [
    'POST /api/example/new', 'POST /api/example/patch',
    'POST /api/inbox/{value}/reject', 'POST /api/inbox/{value}/release',
  ]);
  assert.equal(covered('POST /api/inbox/{item_id}/release', calls), true);
  assert.equal(covered('POST /api/inbox/{item_id}/accept', calls), false);
});
