import { onBeforeUnmount, onMounted } from 'vue'
import { api } from '../api.js'

/**
 * Accumulates real watch time for the currently active reel and flushes it to
 * POST /api/watch every ~5 seconds, on video switches, tab hides, and unload.
 */
export function useWatchTracker() {
  let currentId = null
  let playing = false
  let accumulated = 0
  let lastSample = performance.now()
  let timer = null
  const pending = new Set()
  const moves = new Map()

  async function record(payload, keepalive) {
    const move = moves.get(payload.video_id)
    if (move) payload.video_id = await move
    const request = api.recordWatch(payload, keepalive)
    pending.add(request)
    try {
      await request
    } finally {
      pending.delete(request)
    }
  }

  async function relocate(videoId, move) {
    let release
    moves.set(videoId, new Promise((resolve) => { release = resolve }))
    let nextId = videoId
    try {
      await Promise.allSettled([...pending])
      const result = await move()
      nextId = result.id
      if (currentId === videoId) currentId = nextId
      return result
    } finally {
      moves.delete(videoId)
      release(nextId)
    }
  }

  function sample() {
    const now = performance.now()
    if (playing && document.visibilityState === 'visible') {
      accumulated += Math.min(now - lastSample, 2000) / 1000
    }
    lastSample = now
  }

  // Capture the pending watch time synchronously and switch state in one
  // step, so rapid video switches can't interleave attribution. The network
  // send happens afterwards without blocking the switch.
  function takePending() {
    sample()
    if (!currentId || accumulated < 0.5) {
      accumulated = 0
      return null
    }
    const duration = Math.min(Math.round(accumulated * 10) / 10, 3600)
    const end = Date.now() / 1000
    const payload = {
      video_id: currentId,
      start_time: end - duration,
      end_time: end,
      duration_watched: duration,
    }
    accumulated = 0
    return payload
  }

  async function send(payload, keepalive) {
    try {
      await record(payload, keepalive)
    } catch {
      // Losing a few seconds of stats is acceptable; never block playback.
    }
  }

  function flush(keepalive = false) {
    const payload = takePending()
    if (payload) void send(payload, keepalive)
  }

  function setActive(videoId) {
    if (videoId === currentId) return
    const payload = takePending()
    currentId = videoId ?? null
    accumulated = 0
    lastSample = performance.now()
    if (payload) void send(payload, false)
  }

  function setPlaying(value) {
    if (playing === value) return
    sample()
    playing = value
  }

  function onVisibility() {
    if (document.visibilityState === 'hidden') flush(true)
  }

  function onPageHide() {
    flush(true)
  }

  onMounted(() => {
    lastSample = performance.now()
    timer = setInterval(() => {
      sample()
      if (accumulated >= 5) flush(false)
    }, 1000)
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pagehide', onPageHide)
  })

  onBeforeUnmount(() => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisibility)
    window.removeEventListener('pagehide', onPageHide)
    flush(true)
  })

  return { setActive, setPlaying, relocate }
}
