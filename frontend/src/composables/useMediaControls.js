import { ref } from 'vue'

import { api } from '../api.js'

/**
 * Shared mute / rotate / favorite controls for the feed views.
 *
 * Muted preference persists in localStorage; rotations live only for this
 * browser session. Favorite toggles optimistically and rolls back on error.
 */
export function useMediaControls({ videos, activeIndex }) {
  const muted = ref(localStorage.getItem('lr.muted') !== '0')
  const rotations = ref({}) // video id -> degrees

  function toggleMute() {
    muted.value = !muted.value
    localStorage.setItem('lr.muted', muted.value ? '1' : '0')
  }

  function rotationFor(video) {
    return video ? rotations.value[video.id] || 0 : 0
  }

  function rotateActive() {
    const video = videos.value[activeIndex.value]
    if (!video) return
    rotations.value = { ...rotations.value, [video.id]: (rotationFor(video) + 90) % 360 }
  }

  async function toggleFavorite(video) {
    const next = !video.favorite
    videos.value.forEach((v) => {
      if (v.id === video.id) v.favorite = next
    })
    try {
      await api.setFlags(video.id, { favorite: next })
    } catch {
      videos.value.forEach((v) => {
        if (v.id === video.id) v.favorite = !next
      })
    }
  }

  return { muted, rotations, toggleMute, rotationFor, rotateActive, toggleFavorite }
}
