import test from 'node:test'
import assert from 'node:assert/strict'
import { canSeek, canTrackPlayback, formatPlaybackTime, keyboardAction, seekTarget } from '../src/playback.js'

const ready = Object.freeze({
  active: true,
  mounted: true,
  isImage: false,
  failed: false,
  readyState: 4,
  duration: 60,
  currentTime: 20,
  paused: false,
  ended: false,
  seeking: false,
  waiting: false,
})

test('seeks five seconds in either direction and clamps to media bounds', () => {
  assert.equal(seekTarget(ready, -5), 15)
  assert.equal(seekTarget(ready, 5), 25)
  assert.equal(seekTarget({ ...ready, currentTime: 2 }, -5), 0)
  assert.equal(seekTarget({ ...ready, currentTime: 58 }, 5), 60)
  assert.equal(seekTarget({ ...ready, duration: 2.5, currentTime: 1 }, 5), 2.5)
  assert.equal(seekTarget({ ...ready, duration: 2.5, currentTime: 1 }, -5), 0)
  assert.equal(seekTarget({ ...ready, currentTime: 0 }, -5), 0)
  assert.equal(seekTarget({ ...ready, currentTime: 60 }, 5), 60)
})

test('rejects unloaded, failed, image, inactive and unmounted media', () => {
  for (const invalid of [{ readyState: 0 }, { failed: true }, { isImage: true }, { active: false }, { mounted: false }]) {
    const state = { ...ready, ...invalid }
    assert.equal(canSeek(state), false)
    assert.equal(seekTarget(state, 5), null)
  }
  assert.equal(canSeek({ ...ready, readyState: 1 }), true)
})

test('rejects invalid durations, current times and offsets', () => {
  for (const duration of [NaN, Infinity, -Infinity, 0, -1, undefined, null]) {
    assert.equal(seekTarget({ ...ready, duration }, 5), null)
  }
  for (const value of [NaN, Infinity, -Infinity, undefined]) {
    assert.equal(seekTarget({ ...ready, currentTime: value }, 5), null)
    assert.equal(seekTarget(ready, value), null)
  }
})

test('paused and playing seeks produce the same target without changing state', () => {
  for (const paused of [true, false]) {
    const state = Object.freeze({ ...ready, paused })
    assert.equal(seekTarget(state, 5), 25)
    assert.equal(state.paused, paused)
    assert.equal(state.currentTime, 20)
  }
})

test('tracking is suppressed while seeking or waiting and requires ready active playback', () => {
  assert.equal(canTrackPlayback(ready), true)
  for (const invalid of [
    { paused: true }, { ended: true }, { seeking: true }, { waiting: true },
    { active: false }, { mounted: false }, { failed: true }, { isImage: true }, { readyState: 2 },
  ]) assert.equal(canTrackPlayback({ ...ready, ...invalid }), false)
  assert.equal(canTrackPlayback({ ...ready, seeking: false, waiting: false, readyState: 3 }), true)
})

test('keyboard maps transport and existing feed shortcuts', () => {
  for (const [key, action] of Object.entries({
    ArrowLeft: 'backward', ArrowRight: 'forward', ArrowUp: 'previous', ArrowDown: 'next',
    ' ': 'toggle', m: 'mute', r: 'rotate', s: 'order',
  })) assert.equal(keyboardAction({ key }), action)
  assert.equal(keyboardAction({ key: 'Escape' }), null)
})

test('keyboard ignores modifiers, composition and handled events', () => {
  for (const flag of ['altKey', 'ctrlKey', 'metaKey', 'shiftKey', 'isComposing', 'defaultPrevented']) {
    assert.equal(keyboardAction({ key: 'ArrowRight', [flag]: true }), null)
  }
  assert.equal(keyboardAction({ key: ' ', repeat: true }), null)
  assert.equal(keyboardAction({ key: 'ArrowLeft', repeat: true }), 'backward')
})

test('keyboard ignores interactive ancestors and editable or shadow targets', () => {
  for (const selector of ['input', 'textarea', 'select', 'button', 'a', 'summary', 'video', '[role="slider"]', '[role="button"]']) {
    const target = { closest: (selectors) => selectors.split(', ').includes(selector) ? {} : null }
    assert.equal(keyboardAction({ key: 'ArrowRight', target }), null)
  }
  assert.equal(keyboardAction({ key: 'ArrowRight', target: { isContentEditable: true } }), null)
  assert.equal(keyboardAction({ key: 'ArrowRight', composedPath: () => [{}, { isContentEditable: true }] }), null)
  assert.equal(keyboardAction({ key: 'ArrowRight', target: { closest: () => null } }), 'forward')
})

test('clock displays elapsed and duration safely', () => {
  assert.equal(formatPlaybackTime(0), '0:00')
  assert.equal(formatPlaybackTime(65.9), '1:05')
  assert.equal(formatPlaybackTime(3661), '1:01:01')
  for (const invalid of [NaN, Infinity, undefined, -1]) assert.equal(formatPlaybackTime(invalid), '--:--')
})
