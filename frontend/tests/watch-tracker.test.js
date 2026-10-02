import test from 'node:test'
import assert from 'node:assert/strict'
import { api } from '../src/api.js'
import { useWatchTracker } from '../src/composables/useWatchTracker.js'

if (typeof globalThis.document === 'undefined') {
  globalThis.document = {
    visibilityState: 'visible',
    addEventListener: () => {},
    removeEventListener: () => {},
  }
}
if (typeof globalThis.window === 'undefined') {
  globalThis.window = { addEventListener: () => {}, removeEventListener: () => {} }
}

const realNow = performance.now.bind(performance)
let mockNow = 1000000
performance.now = () => mockNow
test.after(() => { performance.now = realNow })

function advance(ms) {
  mockNow += ms
}

function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

test('relocate waits for in-flight writes before moving', async () => {
  const tracker = useWatchTracker()
  const original = api.recordWatch
  const gate = deferred()
  const seen = []
  api.recordWatch = async (payload) => {
    seen.push(payload.video_id)
    await gate.promise
    return {}
  }
  try {
    tracker.setActive('old')
    tracker.setPlaying(true)
    advance(2000)
    tracker.setActive('other')
    await new Promise((r) => setTimeout(r, 20))
    assert.deepEqual(seen, ['old'])
    let moveStarted = false
    const relocated = tracker.relocate('old', async () => {
      moveStarted = true
      return { id: 'new', relpath: 'F/new.mp4' }
    })
    const noop = relocated.then(() => {}, () => {})
    await new Promise((r) => setTimeout(r, 20))
    assert.equal(moveStarted, false)
    gate.resolve()
    const result = await relocated
    await noop
    assert.equal(result.id, 'new')
    assert.equal(moveStarted, true)
  } finally {
    api.recordWatch = original
  }
})

test('writes during a move use the new id on success and keep navigation', async () => {
  const tracker = useWatchTracker()
  const original = api.recordWatch
  const seen = []
  api.recordWatch = async (payload) => { seen.push(payload.video_id); return {} }
  try {
    tracker.setActive('old')
    tracker.setPlaying(true)
    advance(2000)
    const gate = deferred()
    const relocated = tracker.relocate('old', () => gate.promise)
    const noop = relocated.then(() => {}, () => {})
    tracker.setActive('other')
    await new Promise((r) => setTimeout(r, 20))
    assert.equal(seen.length, 0)
    gate.resolve({ id: 'new', relpath: 'F/new.mp4' })
    assert.equal((await relocated).id, 'new')
    await noop
    await new Promise((r) => setTimeout(r, 20))
    assert.ok(seen.includes('new'), `expected a write with new id, saw ${JSON.stringify(seen)}`)
  } finally {
    api.recordWatch = original
  }
})

test('rapid switches attribute time to the correct videos', async () => {
  const tracker = useWatchTracker()
  const original = api.recordWatch
  const seen = []
  api.recordWatch = async (payload) => { seen.push({ ...payload }); return {} }
  try {
    tracker.setActive('a')
    tracker.setPlaying(true)
    advance(1500)
    tracker.setActive('b')
    advance(1200)
    tracker.setActive('c')
    await new Promise((r) => setTimeout(r, 20))
    assert.equal(seen.length, 2)
    assert.deepEqual(
      seen.map((p) => [p.video_id, p.duration_watched]),
      [['a', 1.5], ['b', 1.2]],
    )
  } finally {
    api.recordWatch = original
  }
})

test('writes during a failed move fall back to the old id', async () => {
  const tracker = useWatchTracker()
  const original = api.recordWatch
  const seen = []
  api.recordWatch = async (payload) => { seen.push(payload.video_id); return {} }
  try {
    tracker.setActive('old')
    tracker.setPlaying(true)
    advance(2000)
    const relocated = tracker.relocate('old', async () => {
      await new Promise((r) => setTimeout(r, 10))
      throw new Error('nope')
    })
    const noop = relocated.then(() => {}, () => {})
    tracker.setActive('other')
    await assert.rejects(relocated, /nope/)
    await noop
    await new Promise((r) => setTimeout(r, 20))
    assert.ok(seen.length > 0)
    assert.ok(seen.every((id) => id === 'old'), `expected only old id, saw ${JSON.stringify(seen)}`)
  } finally {
    api.recordWatch = original
  }
})
