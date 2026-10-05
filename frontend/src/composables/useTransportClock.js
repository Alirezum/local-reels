import { computed, ref } from 'vue'

/**
 * Shared play/pause/seek clock for the feed views.
 *
 * Reads the active reel's <video> element a few times per second so the
 * side-rail transport buttons and clock stay in sync with real playback.
 */
export function useTransportClock({ reelComps, activeIndex, activeVideo }) {
  const available = computed(
    () => !!activeVideo.value && activeVideo.value.type !== 'image',
  )
  const transportTime = ref({ current: 0, duration: NaN })
  const transportPlaying = ref(false)
  let transportTimer = 0

  function syncTransportClock() {
    const comp = reelComps.value[activeIndex.value]
    const video = comp?.videoEl ?? null
    if (available.value && video && Number.isFinite(video.duration)) {
      transportTime.value = { current: video.currentTime, duration: video.duration }
      transportPlaying.value = !video.paused && !video.ended
    } else {
      transportTime.value = { current: 0, duration: NaN }
      transportPlaying.value = false
    }
  }

  function startTransportClock() {
    stopTransportClock()
    transportTimer = window.setInterval(syncTransportClock, 500)
  }

  function stopTransportClock() {
    if (transportTimer) {
      window.clearInterval(transportTimer)
      transportTimer = 0
    }
  }

  function transportAction(action) {
    if (!available.value) return
    const active = reelComps.value[activeIndex.value]
    if (action === 'backward') active?.seekBy(-5)
    else if (action === 'forward') active?.seekBy(5)
    else if (action === 'toggle') active?.toggle()
  }

  return {
    transportTime,
    transportPlaying,
    syncTransportClock,
    startTransportClock,
    stopTransportClock,
    transportAction,
  }
}
