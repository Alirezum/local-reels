<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { formatDuration } from '../api.js'

const props = defineProps({
  video: { type: Object, required: true },
  index: { type: Number, required: true },
  active: { type: Boolean, default: false },
  mount: { type: Boolean, default: true },
  rotation: { type: Number, default: 0 },
  muted: { type: Boolean, default: true },
})

const emit = defineEmits(['state', 'error'])

const videoEl = ref(null)
const playing = ref(false)
const failed = ref(false)
const progress = ref(0)

const isImage = computed(() => props.video.type === 'image')

const rotClass = computed(() =>
  props.rotation === 90 ? 'rot-90' : props.rotation === 180 ? 'rot-180' : props.rotation === 270 ? 'rot-270' : '',
)

function syncMuted() {
  if (videoEl.value) videoEl.value.muted = props.muted
}

function onActiveChange(isActive) {
  if (isImage.value) {
    // An image has no play state; it counts as "playing" while it is the
    // active slide, and the user swipes away whenever they like.
    playing.value = isActive
    emit('state', { index: props.index, playing: isActive })
    return
  }
  const v = videoEl.value
  if (!v) return
  if (isActive) {
    failed.value = false
    v.play().catch(() => {
      failed.value = true
      emit('error', props.video)
    })
  } else {
    v.pause()
    v.currentTime = 0
    progress.value = 0
  }
}

onMounted(() => {
  syncMuted()
  onActiveChange(props.active)
})

watch(() => props.active, onActiveChange)
watch(() => props.muted, syncMuted)

function toggle() {
  const v = videoEl.value
  if (!v || isImage.value) return
  if (v.paused) v.play().catch(() => (failed.value = true))
  else v.pause()
}

function onPlay() {
  playing.value = true
  emit('state', { index: props.index, playing: true })
}

function onPause() {
  playing.value = false
  emit('state', { index: props.index, playing: false })
}

function onError() {
  failed.value = true
  emit('error', props.video)
}

function onTime() {
  const v = videoEl.value
  if (!v) return
  const d = v.duration
  progress.value = Number.isFinite(d) && d > 0 ? (v.currentTime / d) * 100 : 0
}

defineExpose({ toggle })
</script>

<template>
  <section class="reel" :data-index="index">
    <template v-if="mount">
      <img
        v-if="isImage"
        class="reel-image"
        :class="rotClass"
        :src="video.url"
        :alt="video.filename"
        loading="lazy"
        @error="onError"
      />
      <video
        v-else
        ref="videoEl"
        class="reel-video"
        :class="rotClass"
        :src="video.url"
        loop
        playsinline
        preload="metadata"
        :muted="muted"
        @play="onPlay"
        @pause="onPause"
        @click="toggle"
        @error="onError"
        @timeupdate="onTime"
      />
    </template>

    <div v-if="failed && mount" class="reel-error">
      <span>⚠️ Couldn’t load this file</span>
      <small>{{ video.relpath }}</small>
    </div>

    <div v-else-if="mount && !isImage && !playing" class="play-badge" aria-hidden="true">▶</div>

    <div v-if="mount" class="reel-meta">
      <span class="reel-name">{{ video.relpath }}</span>
      <span v-if="!isImage && video.duration > 0" class="reel-duration">
        {{ formatDuration(video.duration) }}
      </span>
      <span v-else-if="isImage" class="reel-duration">photo</span>
    </div>

    <div v-if="mount && !isImage" class="progress">
      <div class="progress-bar" :style="{ width: progress + '%' }" />
    </div>
  </section>
</template>
