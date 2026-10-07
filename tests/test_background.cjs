const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/background.js'), 'utf8');
function setup() {
  let next = 0, ticks = 0, time = 0, enabled = true, unity = true;
  const callbacks = new Map(), cancelled = [], errors = [];
  const window = {document:{hidden:true},
    requestAnimationFrame(callback) {
      assert.equal(this, window);
      if (typeof callback !== 'function') throw new TypeError('Invalid callback');
      callbacks.set(++next, callback); return next;
    },
    cancelAnimationFrame(id) {assert.equal(this, window); cancelled.push(id);},
    __mjAutoplay:{getStatus:() => ({enabled}), tick:() => ticks++},
    __mjUnityTransport:{isUnity:() => unity}};
  const context = {window, location:{hostname:'game.maj-soul.com'}, performance:{now:() => time},
    console:{error:(...args) => errors.push(args)}};
  vm.runInNewContext(source, context);
  return {window, callbacks, cancelled, errors, context,
    pulse(ms = 250) {time += ms; window.__mjBackground.pulse();},
    setEnabled(value) {enabled = value;}, setUnity(value) {unity = value;}, ticks:() => ticks};
}
test('hidden Unity frames and autoplay advance when the native animation clock is suspended', () => {
  const h = setup(), seen = [];
  function frame(time) {assert.equal(this, h.window); seen.push(time); h.window.requestAnimationFrame(frame);}
  const id = h.window.requestAnimationFrame(frame);
  h.pulse(38 * 60 * 1000);
  assert.deepEqual(seen, [2280000], 'a long suspension produces one current frame, not a catch-up burst');
  assert.deepEqual(h.cancelled, [id]); assert.equal(h.ticks(), 1);
  h.callbacks.get(id)(2280001);
  assert.equal(seen.length, 1, 'a late native callback cannot execute the same frame twice');
  h.pulse(); assert.deepEqual(seen, [2280000, 2280250]);
});
test('visible, disabled, and non-Unity pages keep the native frame schedule', () => {
  for (const change of [h => {h.window.document.hidden = false;}, h => h.setEnabled(false), h => h.setUnity(false)]) {
    const h = setup(), seen = []; change(h);
    const id = h.window.requestAnimationFrame(t => seen.push(t));
    h.pulse(); assert.deepEqual(seen, []); assert.equal(h.ticks(), 0);
    h.callbacks.get(id)(300); assert.deepEqual(seen, [300]);
    assert.deepEqual(h.cancelled, []);
  }
});
test('cancellation works before a pulse and between callbacks in the same pulse', () => {
  const h = setup(), seen = [];
  const first = h.window.requestAnimationFrame(() => seen.push('cancelled'));
  h.window.cancelAnimationFrame(first);
  h.window.requestAnimationFrame(() => {seen.push('first'); h.window.cancelAnimationFrame(last);});
  const last = h.window.requestAnimationFrame(() => seen.push('last'));
  h.pulse(); assert.deepEqual(seen, ['first']);
  h.callbacks.get(first)(251); h.callbacks.get(last)(251); assert.deepEqual(seen, ['first']);
});
test('native completion before a pulse is not repeated, and cancelled recursion stays cancelled', () => {
  const h = setup(), seen = [];
  const id = h.window.requestAnimationFrame(t => seen.push(t));
  h.callbacks.get(id)(100); h.pulse(); assert.deepEqual(seen, [100]);
  h.window.requestAnimationFrame(() => {
    const child = h.window.requestAnimationFrame(() => seen.push('child'));
    h.window.cancelAnimationFrame(child);
  });
  h.pulse(); h.pulse(); assert.deepEqual(seen, [100]);
});
test('turning autoplay off during a background frame stops the remaining pulse immediately', () => {
  const h = setup(), seen = [];
  h.window.requestAnimationFrame(() => {seen.push('first'); h.setEnabled(false);});
  const last = h.window.requestAnimationFrame(() => seen.push('last'));
  h.pulse(); assert.deepEqual(seen, ['first']); assert.equal(h.ticks(), 0);
  h.window.document.hidden = false; h.callbacks.get(last)(300);
  assert.deepEqual(seen, ['first','last'], 'remaining frames still belong to the native scheduler');
});
test('one failing callback does not starve the next frame or autoplay scheduler', () => {
  const h = setup(), seen = [];
  h.window.requestAnimationFrame(() => {throw new Error('game frame failed');});
  h.window.requestAnimationFrame(() => seen.push('next'));
  h.pulse(); assert.deepEqual(seen, ['next']); assert.equal(h.errors.length, 1); assert.equal(h.ticks(), 1);
});
test('invalid callbacks retain native validation and reinjection does not wrap frames twice', () => {
  const h = setup(), request = h.window.requestAnimationFrame;
  assert.throws(() => request(null), TypeError);
  vm.runInNewContext(source, h.context);
  assert.equal(h.window.requestAnimationFrame, request);
});
test('a recursive pulse cannot drain frames requested during the current frame', () => {
  const h = setup(), seen = [];
  h.window.requestAnimationFrame(() => {
    seen.push('first'); h.window.requestAnimationFrame(() => seen.push('next'));
    h.window.__mjBackground.pulse();
  });
  h.pulse(); assert.deepEqual(seen, ['first']); assert.equal(h.ticks(), 1);
  h.pulse(); assert.deepEqual(seen, ['first','next']); assert.equal(h.ticks(), 2);
});
