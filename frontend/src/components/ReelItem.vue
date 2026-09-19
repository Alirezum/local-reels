<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { canSeek, canTrackPlayback, formatPlaybackTime, seekTarget } from '../playback.js'

const props = defineProps({
  video: { type: Object, required: true },
  index: { type: Number, required: true },
  active: { type: Boolean, default: false },
  mount: { type: Boolean, default: true },
  rotation: { type: Number, default: 0 },
  muted: { type: Boolean, default: true },
})

const emit = defineEmits(['state', 'error', 'favorite', 'block'])

const videoEl = ref(null)
const playing = ref(false)
const failed = ref(false)
const waiting = ref(true)
const seeking = ref(false)
const currentTime = ref(0)
const duration = ref(NaN)
const readyState = ref(0)
const playbackMessage = ref('')
let tracking = false
let playRequest = 0
let disposed = false

const isImage = computed(() => props.video.type === 'image')
const progress = computed(() => Number.isFinite(duration.value) && duration.value > 0
  ? Math.min(100, Math.max(0, currentTime.value / duration.value * 100)) : 0)
const seekable = computed(() => canSeek({
  active: props.active,
  mounted: props.mount && !!videoEl.value,
  isImage: isImage.value,
  failed: failed.value,
  readyState: readyState.value,
  duration: duration.value,
  currentTime: currentTime.value,
}))
const status = computed(() => playbackMessage.value || (seeking.value ? 'Seeking…' : waiting.value ? 'Loading…' : ''))
const rotClass = computed(() =>
  props.rotation === 90 ? 'rot-90' : props.rotation === 180 ? 'rot-180' : props.rotation === 270 ? 'rot-270' : '',
)

function setTracking(value) {
  tracking = value
  emit('state', { index: props.index, playing: value })
}

function mediaState() {
  const v = videoEl.value
  return {
    active: props.active && !disposed,
    mounted: props.mount && !!v,
    isImage: isImage.value,
    failed: failed.value,
    duration: v?.duration,
    currentTime: v?.currentTime,
    readyState: v?.readyState ?? 0,
    paused: v?.paused ?? true,
    ended: v?.ended ?? false,
    seeking: seeking.value || !!v?.seeking,
    waiting: waiting.value,
  }
}

function isCurrentEvent(event) {
  return !disposed && props.mount && event.target === videoEl.value
}

function syncTime() {
  const v = videoEl.value
  if (!v) return
  duration.value = v.duration
  currentTime.value = Number.isFinite(v.currentTime) ? v.currentTime : 0
  readyState.value = v.readyState
}

function requestPlay() {
  const v = videoEl.value
  if (!v || !props.active || !props.mount || failed.value || disposed) return
  const request = ++playRequest
  playbackMessage.value = ''
  v.play().catch((error) => {
    if (request !== playRequest || videoEl.value !== v || !props.active || !props.mount || disposed) return
    playing.value = false
    setTracking(false)
    if (error.name === 'AbortError') return
    if (v.error) onError()
    else {
      waiting.value = false
      playbackMessage.value = error.name === 'NotAllowedError' ? 'Press Play to start' : 'Playback interrupted. Press Play to retry.'
    }
  })
}

watch([() => props.active, () => props.mount, videoEl], ([active, mount, v], previous) => {
  ++playRequest
  setTracking(false)
  playing.value = false
  if (previous?.[2] && previous[2] !== v) previous[2].pause()
  if (v !== previous?.[2] || mount !== previous?.[1]) {
    failed.value = false
    playbackMessage.value = ''
    waiting.value = true
    seeking.value = false
    currentTime.value = 0
    duration.value = NaN
    readyState.value = 0
  }
  if (isImage.value) {
    setTracking(active && mount && !failed.value)
    return
  }
  if (!v) return
  v.muted = props.muted
  syncTime()
  if (active && mount) requestPlay()
  else {
    v.pause()
    if (v.readyState >= 1 && Number.isFinite(v.duration) && v.duration > 0) v.currentTime = 0
    currentTime.value = 0
  }
}, { flush: 'post', immediate: true })

watch(() => props.muted, (muted) => {
  if (videoEl.value) videoEl.value.muted = muted
})

onBeforeUnmount(() => {
  disposed = true
  ++playRequest
  setTracking(false)
  videoEl.value?.pause()
})

function toggle() {
  const v = videoEl.value
  if (!canSeek(mediaState())) return
  if (v.paused) requestPlay()
  else {
    ++playRequest
    v.pause()
    playing.value = false
    setTracking(false)
  }
}

function seekBy(delta) {
  const v = videoEl.value
  const target = seekTarget(mediaState(), delta)
  if (target === null || target === v.currentTime) return
  seeking.value = true
  setTracking(false)
  try {
    v.currentTime = target
    syncTime()
    playbackMessage.value = ''
  } catch {
    seeking.value = false
    playbackMessage.value = 'Seeking is unavailable for this file'
  }
}

function onPlay(event) {
  if (!isCurrentEvent(event)) return
  if (!props.active) {
    event.target.pause()
    return
  }
  playing.value = !event.target.paused
  setTracking(false)
}

function onPlaying(event) {
  if (!isCurrentEvent(event)) return
  if (!props.active) {
    event.target.pause()
    return
  }
  waiting.value = false
  seeking.value = event.target.seeking
  playing.value = !event.target.paused
  playbackMessage.value = ''
  syncTime()
  setTracking(canTrackPlayback(mediaState()))
}

function onPause(event) {
  if (!isCurrentEvent(event)) return
  playing.value = false
  setTracking(false)
}

function onWaiting(event) {
  if (!isCurrentEvent(event)) return
  waiting.value = true
  setTracking(false)
}

function onSeeking(event) {
  if (!isCurrentEvent(event)) return
  seeking.value = true
  setTracking(false)
}

function onSeeked(event) {
  if (!isCurrentEvent(event)) return
  seeking.value = event.target.seeking
  waiting.value = event.target.readyState < 3
  playing.value = !event.target.paused
  syncTime()
  setTracking(canTrackPlayback(mediaState()))
}

function onLoaded(event) {
  if (!isCurrentEvent(event)) return
  syncTime()
  if (event.target.paused && event.target.readyState >= 2) waiting.value = false
}

function onImageLoad() {
  if (!props.mount || disposed) return
  waiting.value = false
}

function onError() {
  if (!props.mount || disposed) return
  failed.value = true
  waiting.value = false
  playing.value = false
  setTracking(false)
  emit('error', props.video)
}

function isTracking() {
  return tracking && (isImage.value
    ? props.active && props.mount && !failed.value && !disposed
    : canTrackPlayback(mediaState()))
}

defineExpose({ toggle, seekBy, isTracking })
</script>

<template>
  <section class="reel" :class="{ 'reel--transport': active && mount && !isImage }" :data-index="index" :aria-label="video.filename">
    <template v-if="mount">
      <img
        v-if="isImage"
        class="reel-image"
        :class="rotClass"
        :src="video.url"
        :alt="video.filename"
        loading="lazy"
        @load="onImageLoad"
        @error="onError"
      />
      <video
        v-else
        ref="videoEl"
        class="reel-video"
        :class="rotClass"
        :src="video.url"
        :aria-label="video.filename"
        loop
        playsinline
        preload="metadata"
        :muted="muted"
        @play="onPlay"
        @playing="onPlaying"
        @pause="onPause"
        @ended="onPause"
        @waiting="onWaiting"
        @seeking="onSeeking"
        @seeked="onSeeked"
        @loadedmetadata="onLoaded"
        @loadeddata="onLoaded"
        @durationchange="onLoaded"
        @click="toggle"
        @error="onError"
        @timeupdate="syncTime"
      />
    </template>

    <div v-if="failed && mount" class="reel-error" :role="active ? 'status' : undefined">
      <span>Couldn’t load this file</span>
      <small>{{ video.relpath }}</small>
      <small>Move to the next item to keep browsing.</small>
    </div>

    <div v-else-if="active && mount && status" class="reel-status" role="status">{{ status }}</div>

    <div v-if="mount" class="reel-meta">
      <span class="reel-name" :title="video.relpath">{{ video.relpath }}</span>
      <span v-if="isImage" class="reel-duration">Photo</span>
    </div>

    <div v-if="active && mount" class="reel-actions" role="group" aria-label="Media actions">
      <button
        type="button"
        class="action-btn"
        :class="{ 'action-btn--on': video.favorite }"
        :aria-pressed="!!video.favorite"
        aria-label="Favorite"
        :title="video.favorite ? 'Remove from favorites' : 'Add to favorites'"
        @click.stop="emit('favorite', video)"
      >
        <svg width="22" height="22" viewBox="0 0 24 24" :fill="video.favorite ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" />
        </svg>
      </button>
      <button type="button" class="action-btn" aria-label="Hide this file from the feed" title="Don’t show this again" @click.stop="emit('block', video)">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="9" /><path d="m6 6 12 12" />
        </svg>
      </button>
    </div>

    <div v-if="active && mount && !isImage" class="player-transport" role="group" aria-label="Video playback controls" @click.stop>
      <button type="button" class="fav-filter-btn transport-btn" :disabled="!seekable" aria-label="Seek backward 5 seconds" title="Back 5 seconds (Left arrow)" @click="seekBy(-5)">-5s</button>
      <button type="button" class="fav-filter-btn transport-btn transport-btn--primary" :disabled="!seekable" :aria-label="playing ? 'Pause video' : 'Play video'" title="Play or pause (Space)" @click="toggle">{{ playing ? 'Pause' : 'Play' }}</button>
      <button type="button" class="fav-filter-btn transport-btn" :disabled="!seekable" aria-label="Seek forward 5 seconds" title="Forward 5 seconds (Right arrow)" @click="seekBy(5)">+5s</button>
      <span class="transport-time" :aria-label="`Elapsed ${formatPlaybackTime(currentTime)} of ${formatPlaybackTime(duration)}`">{{ formatPlaybackTime(currentTime) }} / {{ formatPlaybackTime(duration) }}</span>
    </div>

    <div v-if="mount && !isImage" class="progress" aria-hidden="true">
      <div class="progress-bar" :style="{ width: progress + '%' }" />
    </div>
  </section>
</template>
