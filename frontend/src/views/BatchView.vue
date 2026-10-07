<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import ReelItem from '../components/ReelItem.vue'
import { api } from '../api.js'
import { useMediaControls } from '../composables/useMediaControls.js'
import { useReelObserver } from '../composables/useReelObserver.js'
import { useTransportClock } from '../composables/useTransportClock.js'
import { useWatchTracker } from '../composables/useWatchTracker.js'
import { keyboardAction } from '../playback.js'
import { formatPlaybackTime } from '../utils/format.js'
import { buildMediaUrl, scrollFeedBy, topFolderName } from '../utils/media.js'

const MOUNT_WINDOW = 2 // only active ± this render a real <video>/<img>
const AHEAD = 8 // queue the next shuffled round when this few slides remain
const MAX_SLIDES = 120 // trim slides far behind so an endless session stays light
const SIZE_KEY = 'lr.batchSize'
const FOLDER_KEY = 'lr.batchFolder'

function todayDate() {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

const batchDate = todayDate()

const feedEl = ref(null)
const reelComps = ref([])
const videos = ref([])
const activeIndex = ref(0)
const loading = ref(true)
const loadError = ref('')
const config = ref(null)
const brokenIds = new Set()
const folders = ref([])
const moveMenuOpen = ref(false)
const moving = ref(false)
const moveError = ref('')

// Batch state: 'loading' | 'feed' | 'choice' | 'setup' | 'empty'
const phase = ref('loading')
const batch = ref(null) // { date, size, folder, videos }
const previous = ref(null)
const newSize = ref(Number(localStorage.getItem(SIZE_KEY)) || 10)
const newFolder = ref(localStorage.getItem(FOLDER_KEY) || '')
const busy = ref(false)
const actionError = ref('')

const tracker = useWatchTracker()
let loadVersion = 0
let nextQueueKey = 0
let disposed = false

const activeVideo = computed(() => videos.value[activeIndex.value] ?? null)
const {
  transportTime,
  transportPlaying,
  startTransportClock,
  stopTransportClock,
  transportAction,
} = useTransportClock({ reelComps, activeIndex, activeVideo })
const { muted, rotations, toggleMute, rotationFor, rotateActive, toggleFavorite } =
  useMediaControls({ videos, activeIndex })

function onObserverIndex(idx) {
  if (idx !== activeIndex.value) {
    tracker.setPlaying(false)
    tracker.setActive(videos.value[idx]?.id ?? null)
    activeIndex.value = idx
  }
}

const { bindObserver, disconnectObserver } = useReelObserver({
  feedEl,
  isDisposed: () => disposed,
  isLoading: () => loading.value,
  onActiveIndex: onObserverIndex,
})

const scopeLabel = computed(() => batch.value?.folder || 'All folders')
const positionLabel = computed(() => {
  const total = batch.value?.videos.length ?? 0
  if (!videos.value.length || !total) return '0/0'
  return `${(activeIndex.value % total) + 1}/${total}`
})

function shuffledRound(pool) {
  const usable = pool.filter((v) => !brokenIds.has(v.id))
  const source = usable.length ? usable : [...pool]
  const round = [...source]
  for (let i = round.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[round[i], round[j]] = [round[j], round[i]]
  }
  // Avoid playing the same video twice in a row across the round boundary.
  const lastId = videos.value[videos.value.length - 1]?.id
  if (round.length > 1 && lastId && round[0].id === lastId) {
    const swap = round.findIndex((v) => v.id !== lastId)
    if (swap > 0) [round[0], round[swap]] = [round[swap], round[0]]
  }
  return round.map((video) => ({ ...video, queueKey: ++nextQueueKey }))
}

function trimFront() {
  const excess = videos.value.length - MAX_SLIDES
  if (excess <= 0) return 0
  videos.value = videos.value.slice(excess)
  activeIndex.value = Math.max(0, activeIndex.value - excess)
  return excess
}

function syncScrollAfterTrim(excess) {
  const feed = feedEl.value
  if (excess > 0 && feed) feed.scrollTop -= excess * feed.clientHeight
}

function appendRound() {
  const pool = batch.value?.videos ?? []
  if (!pool.length) return false
  videos.value = [...videos.value, ...shuffledRound(pool)]
  return true
}

let appending = false
async function maybeAppendRound() {
  if (disposed || phase.value !== 'feed' || appending || !videos.value.length) return
  if (videos.value.length - activeIndex.value - 1 > AHEAD) return
  appending = true
  try {
    if (!appendRound()) return
    const trimmed = trimFront()
    await nextTick()
    if (disposed) return
    syncScrollAfterTrim(trimmed)
    bindObserver()
  } finally {
    appending = false
  }
}

watch(activeIndex, maybeAppendRound)

async function loadFolders(version = loadVersion) {
  try {
    const result = await api.folders()
    if (!disposed && version === loadVersion) folders.value = result
  } catch {
    if (!disposed && version === loadVersion) folders.value = []
  }
}

async function enterFeed(updated, version) {
  if (disposed || version !== loadVersion) return
  batch.value = updated
  videos.value = []
  activeIndex.value = 0
  tracker.setPlaying(false)
  const round = shuffledRound(updated.videos)
  videos.value = round
  tracker.setActive(round[0]?.id ?? null)
  // Render the feed first: bindObserver needs feedEl to exist.
  phase.value = round.length ? 'feed' : 'empty'
  if (!round.length) return
  disconnectObserver()
  await nextTick()
  if (disposed || version !== loadVersion) return
  bindObserver()
  tracker.setPlaying(reelComps.value[0]?.isTracking() ?? false)
  maybeAppendRound()
}

async function load() {
  const version = ++loadVersion
  loading.value = true
  loadError.value = ''
  phase.value = 'loading'
  disconnectObserver()
  tracker.setPlaying(false)
  tracker.setActive(null)
  videos.value = []
  activeIndex.value = 0
  batch.value = null
  previous.value = null
  try {
    const result = await api.getConfig()
    if (disposed || version !== loadVersion) return
    config.value = result
    await loadFolders(version)
    if (disposed || version !== loadVersion) return
    try {
      const today = await api.batchGet(batchDate)
      await enterFeed(today, version)
    } catch (e) {
      if (e.status !== 404) throw e
      if (disposed || version !== loadVersion) return
      try {
        previous.value = await api.batchPrevious(batchDate)
        if (disposed || version !== loadVersion) return
        phase.value = 'choice'
      } catch (prevErr) {
        if (prevErr.status !== 404) throw prevErr
        if (disposed || version !== loadVersion) return
        phase.value = 'setup'
      }
    }
  } catch (e) {
    if (!disposed && version === loadVersion) loadError.value = e.message
  } finally {
    if (!disposed && version === loadVersion) loading.value = false
  }
}

function clampSize(value) {
  const n = Math.floor(Number(value))
  if (!Number.isFinite(n)) return 10
  return Math.min(500, Math.max(1, n))
}

async function createNew() {
  if (busy.value) return
  busy.value = true
  actionError.value = ''
  const version = loadVersion
  const size = clampSize(newSize.value)
  newSize.value = size
  try {
    const created = await api.batchNew(batchDate, size, newFolder.value || undefined)
    localStorage.setItem(SIZE_KEY, String(size))
    localStorage.setItem(FOLDER_KEY, newFolder.value || '')
    await enterFeed(created, version)
  } catch (e) {
    if (!disposed && version === loadVersion) actionError.value = e.message
  } finally {
    if (!disposed) busy.value = false
  }
}

async function continueLast() {
  if (busy.value || !previous.value) return
  busy.value = true
  actionError.value = ''
  const version = loadVersion
  try {
    const continued = await api.batchContinue(batchDate, previous.value.date)
    await enterFeed(continued, version)
  } catch (e) {
    if (!disposed && version === loadVersion) actionError.value = e.message
  } finally {
    if (!disposed) busy.value = false
  }
}

function openSetup() {
  actionError.value = ''
  phase.value = 'setup'
}

function cancelSetup() {
  actionError.value = ''
  phase.value = videos.value.length ? 'feed' : 'empty'
}

async function addRandom() {
  if (busy.value || !batch.value) return
  busy.value = true
  actionError.value = ''
  const version = loadVersion
  try {
    const updated = await api.batchAddRandom(batchDate)
    if (disposed || version !== loadVersion) return
    batch.value = updated
    if (phase.value !== 'feed') {
      // Refilling an emptied batch: start a fresh shuffled round.
      activeIndex.value = 0
      tracker.setPlaying(false)
      const round = shuffledRound(updated.videos)
      videos.value = round
      if (!round.length) return
      tracker.setActive(round[0]?.id ?? null)
      phase.value = 'feed'
      await nextTick()
      if (disposed || version !== loadVersion) return
      bindObserver()
      tracker.setPlaying(reelComps.value[0]?.isTracking() ?? false)
      maybeAppendRound()
      return
    }
    // Slip the new video(s) in right after the current slide so they show
    // up promptly; later rounds pick up the full updated batch anyway.
    const known = new Set(videos.value.map((v) => v.id))
    const fresh = updated.videos
      .filter((v) => !known.has(v.id))
      .map((v) => ({ ...v, queueKey: ++nextQueueKey }))
    if (!fresh.length) return
    videos.value = [
      ...videos.value.slice(0, activeIndex.value + 1),
      ...fresh,
      ...videos.value.slice(activeIndex.value + 1),
    ]
    const trimmed = trimFront()
    await nextTick()
    if (disposed || version !== loadVersion) return
    syncScrollAfterTrim(trimmed)
    bindObserver()
  } catch (e) {
    if (!disposed && version === loadVersion) actionError.value = e.message
  } finally {
    if (!disposed) busy.value = false
  }
}

async function dropFromView(videoId) {
  tracker.setPlaying(false)
  videos.value = videos.value.filter((v) => v.id !== videoId)
  if (activeIndex.value > videos.value.length - 1) activeIndex.value = Math.max(0, videos.value.length - 1)
  tracker.setActive(videos.value[activeIndex.value]?.id ?? null)
  await nextTick()
  if (disposed) return
  bindObserver()
  const feed = feedEl.value
  if (feed) feed.scrollTo({ top: activeIndex.value * feed.clientHeight })
  tracker.setPlaying(reelComps.value[activeIndex.value]?.isTracking() ?? false)
}

async function removeCurrent() {
  const video = activeVideo.value
  if (!video || busy.value || !batch.value) return
  busy.value = true
  actionError.value = ''
  try {
    const updated = await api.batchRemove(batchDate, video.id)
    batch.value = updated
    await dropFromView(video.id)
    if (!videos.value.length) phase.value = 'empty'
  } catch (e) {
    actionError.value = e.message
  } finally {
    busy.value = false
  }
}

function onReelState({ index, playing }) {
  if (!disposed && index === activeIndex.value) {
    tracker.setActive(videos.value[index]?.id ?? null)
    tracker.setPlaying(playing)
  }
}

function onReelError(video) {
  brokenIds.add(video.id)
}

async function onBlock(video) {
  try {
    await api.setFlags(video.id, { blocked: true })
  } catch {
    return
  }
  brokenIds.add(video.id)
  await dropFromView(video.id)
  if (!videos.value.length) phase.value = 'empty'
  loadFolders()
}

async function moveActiveTo(folder) {
  const video = activeVideo.value
  if (!video || moving.value) return
  moving.value = true
  moveError.value = ''
  const oldId = video.id
  const version = loadVersion
  try {
    const moved = await tracker.relocate(oldId, () => api.moveVideo(oldId, folder))
    if (disposed || version !== loadVersion) return
    const url = buildMediaUrl(moved.relpath)
    for (const item of videos.value) {
      if (item.id === oldId) Object.assign(item, { id: moved.id, relpath: moved.relpath, url })
    }
    // A move gives the file a new ID: swap it inside the stored batch too,
    // otherwise future rounds (and tomorrow's reload) lose this video.
    if (batch.value) {
      for (const item of batch.value.videos) {
        if (item.id === oldId) Object.assign(item, { id: moved.id, relpath: moved.relpath, url })
      }
      try {
        const updated = await api.batchReplace(batchDate, oldId, moved.id)
        if (!disposed && version === loadVersion) batch.value = updated
      } catch (e) {
        if (!disposed && version === loadVersion) {
          actionError.value = 'Moved, but the batch bookmark could not be updated — reload to resync.'
        }
      }
    }
    if (oldId in rotations.value) {
      rotations.value[moved.id] = rotations.value[oldId]
      delete rotations.value[oldId]
    }
    brokenIds.delete(oldId)
    moveMenuOpen.value = false
    loadFolders(version)
  } catch (e) {
    if (!disposed && version === loadVersion) moveError.value = e.message || 'Could not move this file'
  } finally {
    if (!disposed) moving.value = false
  }
}

function scrollByOne(delta) {
  scrollFeedBy(feedEl, delta)
}

function onKeydown(ev) {
  const action = keyboardAction(ev)
  if (!action || disposed || loading.value || phase.value !== 'feed' || !videos.value.length) return
  if (action === 'backward' || action === 'forward' || action === 'toggle') {
    transportAction(action)
    return
  }
  if (action === 'order') return
  ev.preventDefault()
  if (action === 'next') scrollByOne(1)
  else if (action === 'previous') scrollByOne(-1)
  else if (action === 'mute') toggleMute()
  else if (action === 'rotate') rotateActive()
}

function toggleMoveMenu() {
  moveError.value = ''
  moveMenuOpen.value = !moveMenuOpen.value
  if (moveMenuOpen.value) loadFolders()
}

function onGlobalClick(ev) {
  if (moveMenuOpen.value && !ev.target.closest?.('.move-menu')) moveMenuOpen.value = false
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('click', onGlobalClick)
  startTransportClock()
})

onBeforeUnmount(() => {
  disposed = true
  ++loadVersion
  disconnectObserver()
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('click', onGlobalClick)
  stopTransportClock()
})
</script>

<template>
  <div class="reels-page">
    <h1 class="brand">Local Reels · Batch</h1>

    <div v-if="phase === 'feed' && batch" class="batch-bar" role="status" aria-label="Batch progress">
      <span class="batch-chip">{{ positionLabel }} · {{ scopeLabel }}</span>
      <button type="button" class="batch-btn" :disabled="busy" title="Add one random video to this batch" @click="addRandom">
        {{ busy ? '…' : '+ Add' }}
      </button>
      <button type="button" class="batch-btn" :disabled="busy" title="Start over with a new set" @click="openSetup">
        New set
      </button>
    </div>
    <p v-if="actionError && phase === 'feed'" class="batch-error" role="alert">{{ actionError }}</p>

    <main v-if="phase === 'feed' && videos.length" ref="feedEl" class="feed" aria-label="Daily batch feed" :aria-busy="loading">
      <ReelItem
        v-for="(video, i) in videos"
        :key="video.queueKey"
        :ref="(c) => (reelComps[i] = c)"
        :video="video"
        :index="i"
        :active="i === activeIndex"
        :mount="Math.abs(i - activeIndex) <= MOUNT_WINDOW"
        :rotation="rotationFor(video)"
        :muted="muted"
        @state="onReelState"
        @error="onReelError"
      />
    </main>

    <nav v-if="phase === 'feed' && videos.length" class="side-rail side-rail--left" aria-label="Batch navigation">
      <button
        type="button"
        class="icon-btn"
        aria-label="Previous media"
        title="Previous (Up arrow)"
        :disabled="activeIndex === 0"
        @click="scrollByOne(-1)"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m6 15 6-6 6 6" /></svg>
      </button>
      <button
        type="button"
        class="icon-btn"
        aria-label="Next media"
        title="Next (Down arrow)"
        :disabled="activeIndex >= videos.length - 1"
        @click="scrollByOne(1)"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      <span class="rail-divider" aria-hidden="true" />
      <RouterLink to="/" class="icon-btn" aria-label="Back to full feed" title="Back to full feed">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M4 11 12 4l8 7" /><path d="M6 10v10h12V10" />
        </svg>
      </RouterLink>
    </nav>

    <nav v-if="phase === 'feed' && videos.length" class="side-rail side-rail--right" aria-label="Playback and media actions">
      <button type="button" class="icon-btn" aria-label="Rotate active media 90 degrees" title="Rotate active (R)" :disabled="!videos.length || loading" @click="rotateActive">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7" />
        </svg>
      </button>
      <button type="button" class="icon-btn" aria-label="Mute audio" :aria-pressed="muted" :title="muted ? 'Unmute (M)' : 'Mute (M)'" @click="toggleMute">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M11 4 5 9H2v6h3l6 5Z" />
          <path v-if="muted" d="m16 9 6 6m0-6-6 6" />
          <path v-else d="M15 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14" />
        </svg>
      </button>
      <RouterLink to="/dashboard" class="icon-btn" aria-label="Open dashboard" title="Dashboard">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M3 3v18h18M7 17v-6m5 6V6m5 11V9" />
        </svg>
      </RouterLink>
      <span class="rail-divider" aria-hidden="true" />
      <button
        type="button"
        class="icon-btn transport-icon-btn"
        :disabled="loading"
        aria-label="Seek backward 5 seconds"
        title="Back 5 seconds (Left arrow)"
        @click="transportAction('backward')"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M11 9 4 12l7 3v-2.5c3.5 0 6.5 1 8.5 3.5C18.5 11.5 15 9.5 14 9.3" />
        </svg>
      </button>
      <button
        type="button"
        class="icon-btn transport-icon-btn"
        :disabled="loading"
        :aria-label="transportPlaying ? 'Pause video' : 'Play video'"
        :title="transportPlaying ? 'Pause (Space)' : 'Play (Space)'"
        @click="transportAction('toggle')"
      >
        <svg v-if="transportPlaying" width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
          <rect x="7" y="5" width="3.5" height="14" rx="1" /><rect x="13.5" y="5" width="3.5" height="14" rx="1" />
        </svg>
        <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false">
          <path d="M8 5.5v13l10-6.5Z" />
        </svg>
      </button>
      <button
        type="button"
        class="icon-btn transport-icon-btn"
        :disabled="loading"
        aria-label="Seek forward 5 seconds"
        title="Forward 5 seconds (Right arrow)"
        @click="transportAction('forward')"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="m13 9 7 3-7 3v-2.5c-3.5 0-6.5 1-8.5 3.5C5.5 11.5 9 9.5 10 9.3" />
        </svg>
      </button>
      <span class="rail-divider" aria-hidden="true" />
      <button
        type="button"
        class="icon-btn"
        :class="{ 'icon-btn--on': activeVideo?.favorite }"
        :aria-pressed="!!activeVideo?.favorite"
        :disabled="!activeVideo"
        aria-label="Favorite"
        :title="activeVideo?.favorite ? 'Remove from favorites' : 'Add to favorites'"
        @click="activeVideo && toggleFavorite(activeVideo)"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" :fill="activeVideo?.favorite ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z" />
        </svg>
      </button>
      <button
        type="button"
        class="icon-btn"
        :disabled="!activeVideo"
        aria-label="Hide this file from the feed"
        title="Don’t show this again"
        @click="activeVideo && onBlock(activeVideo)"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="9" /><path d="m6 6 12 12" />
        </svg>
      </button>
      <button
        type="button"
        class="icon-btn"
        :disabled="!activeVideo || busy"
        aria-label="Remove from today's batch"
        title="Remove from today's batch"
        @click="removeCurrent"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <circle cx="12" cy="12" r="9" /><path d="M8 12h8" />
        </svg>
      </button>
      <div class="move-menu">
        <button
          type="button"
          class="icon-btn"
          aria-haspopup="menu"
          :aria-expanded="moveMenuOpen"
          aria-label="Move to folder"
          title="Move to another folder"
          :disabled="!activeVideo || moving"
          @click.stop="toggleMoveMenu"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
            <path d="M3 7V5h6l2 2h10v12H3Z" />
            <path d="M9 14h6m0 0-2-2m2 2-2 2" />
          </svg>
        </button>
        <div v-if="moveMenuOpen" class="folder-popover" role="menu" aria-label="Move to folder">
          <p class="move-title">Move “{{ activeVideo?.filename }}” to:</p>
          <p v-if="moving" class="folder-move-busy" role="status">Moving…</p>
          <p v-else-if="moveError" class="folder-move-error" role="alert">{{ moveError }}</p>
          <button v-if="topFolderName(activeVideo)" type="button" class="folder-item" @click="moveActiveTo('')">
            (root)
          </button>
          <button
            v-for="f in folders.filter((f) => f.name !== topFolderName(activeVideo))"
            :key="f.name"
            type="button"
            class="folder-item"
            @click="moveActiveTo(f.name)"
          >
            {{ f.name }} <span class="folder-count">{{ f.count }}</span>
          </button>
        </div>
      </div>
      <span class="transport-clock" aria-hidden="true">{{ formatPlaybackTime(transportTime.current) }} / {{ formatPlaybackTime(transportTime.duration) }}</span>
    </nav>

    <div v-if="phase === 'loading'" class="feed-state" role="status">
      <span class="spinner" aria-hidden="true" />
      <p>Loading today's batch…</p>
    </div>

    <div v-else-if="loadError" class="feed-state" role="alert">
      <p class="state-title">Couldn’t reach the server</p>
      <p class="state-hint">{{ loadError }}</p>
      <button class="retry-btn" @click="load">Retry</button>
    </div>

    <div v-else-if="phase === 'empty'" class="feed-state">
      <p class="state-title">Today's batch is empty</p>
      <p class="state-hint">Files may have been moved or hidden — or you removed every video.</p>
      <p v-if="actionError" class="folder-move-error" role="alert">{{ actionError }}</p>
      <button class="retry-btn" :disabled="busy" @click="openSetup">Start a new set</button>
      <button v-if="batch" class="retry-btn" :disabled="busy" @click="addRandom">Add a random video</button>
      <RouterLink to="/" class="retry-btn">Back to full feed</RouterLink>
    </div>

    <div v-if="phase === 'choice' || phase === 'setup'" class="batch-modal" role="dialog" aria-modal="true" aria-label="Today's batch">
      <div class="batch-card">
        <template v-if="phase === 'choice' && previous">
          <p class="state-title">Today's batch</p>
          <p class="state-hint">
            Last time ({{ previous.date }}): {{ previous.videos.length }} videos{{ previous.folder ? ` from “${previous.folder}”` : '' }}.
            Continue with those or start a fresh random set?
          </p>
          <p v-if="actionError" class="folder-move-error" role="alert">{{ actionError }}</p>
          <div class="batch-row">
            <button class="retry-btn" :disabled="busy" @click="continueLast">
              {{ busy ? 'Loading…' : 'Continue last time' }}
            </button>
            <button class="retry-btn" :disabled="busy" @click="openSetup">New set</button>
          </div>
        </template>
        <template v-else>
          <p class="state-title">New batch for {{ batchDate }}</p>
          <p class="state-hint">Pick how many random videos to watch today.</p>
          <label class="batch-label" for="batch-size">Videos</label>
          <input
            id="batch-size"
            v-model.number="newSize"
            class="batch-input"
            type="number"
            min="1"
            max="500"
            step="1"
          />
          <label class="batch-label" for="batch-folder">From</label>
          <select id="batch-folder" v-model="newFolder" class="batch-input">
            <option value="">Whole library</option>
            <option v-for="f in folders" :key="f.name" :value="f.name">
              {{ f.name }} ({{ f.count }})
            </option>
          </select>
          <p v-if="actionError" class="folder-move-error" role="alert">{{ actionError }}</p>
          <div class="batch-row">
            <button class="retry-btn" :disabled="busy" @click="createNew">
              {{ busy ? 'Picking…' : 'Start batch' }}
            </button>
            <button v-if="videos.length" class="retry-btn" :disabled="busy" @click="cancelSetup">Cancel</button>
            <RouterLink to="/" class="retry-btn">Full feed</RouterLink>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>
