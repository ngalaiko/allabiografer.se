const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function synopsis(storage = new Map(), href = 'https://allabiografer.se/stad/varberg/capitol-varberg/', blocked = false) {
  const location = new URL(href);
  const classes = new Set();
  const paragraph = { scrollHeight: 100, clientHeight: 40, classList: {
    add: value => classes.add(value),
    remove: value => classes.delete(value),
    toggle: (value, enabled) => enabled ? classes.add(value) : classes.delete(value),
  } };
  const button = { dataset: { more: 'digger' }, attributes: {},
    getAttribute: () => 'synopsis-digger',
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, handler) { this[name] = handler; },
  };
  vm.runInNewContext(fs.readFileSync('static/i/synopsis.js', 'utf8'), {
    URL, location, document: {
      querySelectorAll: () => [button], getElementById: () => paragraph,
      createElement: () => ({ getContext: () => ({ measureText: () => ({ width: 60 }) }) }),
      createRange: () => ({ selectNodeContents() {}, getClientRects: () => Array(4).fill({ width: 200 }) }),
    },
    getComputedStyle: () => ({ font: '16px sans-serif' }),
    localStorage: {
      getItem(key) { if (blocked) throw Error('blocked'); return storage.get(key) ?? null; },
      setItem(key, value) { if (blocked) throw Error('blocked'); storage.set(key, value); },
    },
    history: { replaceState(state, title, url) { location.href = url.href; } },
    ResizeObserver: class { observe() {} }, addEventListener() {},
  });
  return { button, location };
}

test('expansion survives reload and collapse without changing the URL', () => {
  const storage = new Map();
  const first = synopsis(storage);
  first.button.click();
  assert.equal(first.location.search, '');
  const second = synopsis(storage);
  assert.equal(second.button.attributes['aria-expanded'], 'true');
  second.button.click();
  assert.equal(synopsis(storage).button.attributes['aria-expanded'], 'false');
});

test('expansion is scoped to the page', () => {
  const storage = new Map();
  synopsis(storage).button.click();
  assert.equal(synopsis(storage, 'https://allabiografer.se/film/digger/').button.attributes['aria-expanded'], 'false');
});

test('unavailable storage still allows toggling', () => {
  const page = synopsis(new Map(), undefined, true);
  page.button.click();
  assert.equal(page.button.attributes['aria-expanded'], 'true');
  assert.equal(page.location.search, '');
});

test('legacy expansion parameters are removed without losing other URL parts', () => {
  const page = synopsis(new Map(), 'https://allabiografer.se/film/digger/?expanded=digger&view=selected#times');
  assert.equal(page.location.search, '?view=selected');
  assert.equal(page.location.hash, '#times');
});

test('external link activation adds one source and preserves query and fragment', () => {
  const handlers = {};
  vm.runInNewContext(fs.readFileSync('static/i/links.js', 'utf8'), {
    URL, location: new URL('https://allabiografer.se/'),
    document: { addEventListener(name, handler, capture) {
      assert.equal(capture, true);
      handlers[name] = handler;
    } },
  });
  for (const event of ['click', 'auxclick', 'contextmenu']) {
    const link = { href: 'https://tickets.example/buy?id=42&utm_source=old#seat' };
    handlers[event]({ target: { closest: () => link } });
    handlers[event]({ target: { closest: () => link } });
    assert.equal(link.href, 'https://tickets.example/buy?id=42&utm_source=allabiografer.se#seat');
  }
  for (const href of ['https://allabiografer.se/film/digger/', 'mailto:hello@example.com', 'blob:https://allabiografer.se/id', 'tel:123']) {
    const link = { href };
    handlers.click({ target: { closest: () => link } });
    assert.equal(link.href, href);
  }
  handlers.click({ target: { closest: () => null } });
});
