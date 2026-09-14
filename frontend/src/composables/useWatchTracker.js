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

  function sample() {
    const now = performance.now()
    if (playing && document.visibilityState === 'visible') {
      accumulated += Math.min(now - lastSample, 2000) / 1000
    }
    lastSample = now
  }

  async function flush(keepalive = false) {
    sample()
    if (!currentId || accumulated < 0.5) {
      accumulated = 0
      return
    }
    const duration = Math.min(Math.round(accumulated * 10) / 10, 3600)
    const end = Date.now() / 1000
    accumulated = 0
    try {
      await api.recordWatch(
        { video_id: currentId, start_time: end - duration, end_time: end, duration_watched: duration },
        keepalive,
      )
    } catch {
      // Losing a few seconds of stats is acceptable; never block playback.
    }
  }

  function setActive(videoId) {
    if (videoId === currentId) return
    flush(false)
    currentId = videoId ?? null
    accumulated = 0
    lastSample = performance.now()
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

  return { setActive, setPlaying }
}
