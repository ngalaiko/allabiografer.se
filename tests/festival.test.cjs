const { test } = require('node:test');
const assert = require('node:assert/strict');
const { calendar, conflicts } = require('../static/i/festival.js');

const first = { id: 'a', title: 'Film; ett, två\nTre', venue: 'Bio', url: 'https://example.com/',
  start: '2026-11-11T23:30:00+01:00', end: '2026-11-12T01:30:00+01:00' };

test('calendar exports UTC, stable IDs, escaped text, and UTF-8 line folding', () => {
  const event = { ...first, venue: 'Göteborg '.repeat(30) };
  const result = calendar({ slug: 'festival', year: 2026 }, [event], new Date('2026-09-28T00:00:00Z'));
  const unfolded = result.replace(/\r\n /g, '');
  assert.match(unfolded, /DTSTART:20261111T223000Z/);
  assert.match(unfolded, /DTEND:20261112T003000Z/);
  assert.match(unfolded, /DTSTAMP:20260928T000000Z/);
  assert.match(unfolded, /UID:festival-2026-a@allabiografer.se/);
  assert.ok(unfolded.includes('SUMMARY:Film\\; ett\\, två\\nTre'));
  assert.ok(unfolded.includes('LOCATION:' + event.venue));
  assert.ok(result.split('\r\n').every(line => Buffer.byteLength(line) <= 75));
});

test('overlaps cross midnight; adjacent screenings do not overlap', () => {
  const overlapping = { ...first, id: 'b', start: '2026-11-12T01:00:00+01:00', end: '2026-11-12T02:00:00+01:00' };
  const adjacent = { ...overlapping, id: 'c', start: overlapping.end, end: '2026-11-12T03:00:00+01:00' };
  assert.deepEqual([...conflicts([first, overlapping, adjacent])], ['a', 'b']);
  assert.deepEqual([...conflicts([{ ...first, end: null }, overlapping])], []);
});

test('unknown duration has no fabricated calendar end', () => {
  assert.ok(!calendar({ slug: 'festival', year: 2026 }, [{ ...first, end: null }]).includes('DTEND'));
});
