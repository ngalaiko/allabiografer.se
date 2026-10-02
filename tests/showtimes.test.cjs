const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('showtimes turn grey on load, as time passes, and when the tab resumes', () => {
  let now = Date.parse('2026-10-02T19:32:00Z');
  const entries = ['2026-10-02T21:30:00+02:00', '2026-10-02T21:35:00+02:00',
    '2026-10-03T13:00:00+02:00'].map(start => ({
    dataset: { start }, past: false,
    classList: { toggle(name, value) { assert.equal(name, 'past'); this.owner.past = value; } },
  }));
  for (const entry of entries) entry.classList.owner = entry;
  let tick;
  const handlers = {};
  vm.runInNewContext(fs.readFileSync('static/i/showtimes.js', 'utf8'), {
    Date: class extends Date { static now() { return now; } },
    document: { querySelectorAll: () => entries, addEventListener: (name, fn) => { handlers[name] = fn; } },
    setInterval(fn, delay) { assert.ok(delay <= 60000); tick = fn; },
  });
  assert.deepEqual(entries.map(entry => entry.past), [true, false, false]);
  now = Date.parse('2026-10-02T19:35:00Z');
  tick();
  assert.deepEqual(entries.map(entry => entry.past), [true, true, false]);
  now = Date.parse('2026-10-03T11:01:00Z');
  handlers.visibilitychange();
  assert.ok(entries.every(entry => entry.past));
});
