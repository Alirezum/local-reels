<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import ConfigPanel from '../components/ConfigPanel.vue'
import ReelItem from '../components/ReelItem.vue'
import { api } from '../api.js'
import { useMediaControls } from '../composables/useMediaControls.js'
import { useReelObserver } from '../composables/useReelObserver.js'
import { useTransportClock } from '../composables/useTransportClock.js'
import { useWatchTracker } from '../composables/useWatchTracker.js'
import { formatPlaybackTime, keyboardAction } from '../playback.js'
import { buildMediaUrl, scrollFeedBy, topFolderName } from '../utils/media.js'

const BATCH = 25 // slides fetched per request
const AHEAD = 8 // append the next batch when this few slides remain
const MOUNT_WINDOW = 2 // only active ± this render a real <video>/<img>

const feedEl = ref(null)
const reelComps = ref([])
const videos = ref([])
const activeIndex = ref(0)
const order = ref(localStorage.getItem('lr.order') === 'random' ? 'random' : 'weighted')
const loading = ref(true)
const loadError = ref('')
const config = ref(null)
const brokenIds = new Set()
const folders = ref([])
function readStoredFolders() {
  try {
    const raw = localStorage.getItem('lr.folders')
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((f) => typeof f === 'string' && f) : []
  } catch {
    return []
  }
}
const activeFolders = ref(readStoredFolders()) // [] = all
const favoritesOnly = ref(false)
const folderMenuOpen = ref(false)
const folderMenuBtn = ref(null)
const moveMenuOpen = ref(false)
const moving = ref(false)
const moveError = ref('')

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

const filterActive = computed(() => activeFolders.value.length > 0 || favoritesOnly.value)

function currentFilters() {
  return {
    folders: activeFolders.value.length ? [...activeFolders.value] : undefined,
    favorites: favoritesOnly.value,
  }
}

function persistFolders() {
  try {
    localStorage.setItem('lr.folders', JSON.stringify(activeFolders.value))
  } catch {
    // non-fatal: filtering still works for this session
  }
}

async function fetchBatch(version = loadVersion) {
  const fresh = await api.randomVideos(BATCH, order.value, currentFilters())
  if (disposed || version !== loadVersion || !fresh.length) return 0
  const recent = new Set(videos.value.slice(-60).flatMap((v) => [v.id, v.relpath]))
  let pool = fresh.filter((v) => !brokenIds.has(v.id) && !recent.has(v.id) && !recent.has(v.relpath))
  if (!pool.length) pool = fresh.filter((v) => !brokenIds.has(v.id))
  if (!pool.length) pool = fresh
  videos.value = [...videos.value, ...pool.map((video) => ({ ...video, queueKey: ++nextQueueKey }))]
  return pool.length
}

async function loadFolders(version = loadVersion) {
  try {
    const result = await api.folders()
    if (disposed || version !== loadVersion) return
    folders.value = result
    // Drop persisted selections for folders that no longer exist.
    const known = new Set(result.map((f) => f.name))
    const pruned = activeFolders.value.filter((name) => known.has(name))
    if (pruned.length !== activeFolders.value.length) {
      activeFolders.value = pruned
      persistFolders()
    }
  } catch {
    if (!disposed && version === loadVersion) folders.value = []
  }
}

async function load() {
  const version = ++loadVersion
  loading.value = true
  loadError.value = ''
  disconnectObserver()
  tracker.setPlaying(false)
  tracker.setActive(null)
  videos.value = []
  activeIndex.value = 0
  try {
    const result = await api.getConfig()
    if (disposed || version !== loadVersion) return
    config.value = result
    await loadFolders(version)
    if (disposed || version !== loadVersion) return
    await fetchBatch(version)
    if (disposed || version !== loadVersion) return
    tracker.setActive(videos.value[0]?.id ?? null)
    await nextTick()
    if (disposed || version !== loadVersion) return
    bindObserver()
    tracker.setPlaying(reelComps.value[0]?.isTracking() ?? false)
  } catch (e) {
    if (!disposed && version === loadVersion) loadError.value = e.message
  } finally {
    if (!disposed && version === loadVersion) loading.value = false
  }
}

function isFolderActive(name) {
  return activeFolders.value.includes(name)
}

async function toggleFolder(name) {
  const idx = activeFolders.value.indexOf(name)
  if (idx >= 0) activeFolders.value = activeFolders.value.filter((f) => f !== name)
  else activeFolders.value = [...activeFolders.value, name]
  persistFolders()
  await load()
}

async function showAllFolders() {
  folderMenuOpen.value = false
  if (!activeFolders.value.length) return
  activeFolders.value = []
  persistFolders()
  await load()
}

async function toggleFavorites() {
  favoritesOnly.value = !favoritesOnly.value
  await load()
}

async function clearFilters() {
  folderMenuOpen.value = false
  activeFolders.value = []
  persistFolders()
  favoritesOnly.value = false
  await load()
}

let appending = false
async function maybeAppend() {
  if (disposed || loading.value || appending || !videos.value.length || videos.value.length > 1900) return
  if (videos.value.length - activeIndex.value - 1 > AHEAD) return
  appending = true
  try {
    await fetchBatch()
    await nextTick()
    bindObserver()
  } catch {
    // non-fatal: user can keep scrolling existing videos
  } finally {
    appending = false
  }
}

watch(activeIndex, maybeAppend)

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
  tracker.setPlaying(false)
  videos.value = videos.value.filter((v) => v.id !== video.id)
  if (activeIndex.value > videos.value.length - 1) activeIndex.value = Math.max(0, videos.value.length - 1)
  tracker.setActive(videos.value[activeIndex.value]?.id ?? null)
  await nextTick()
  bindObserver()
  const feed = feedEl.value
  if (feed) feed.scrollTo({ top: activeIndex.value * feed.clientHeight })
  tracker.setPlaying(reelComps.value[activeIndex.value]?.isTracking() ?? false)
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

function toggleOrder() {
  order.value = order.value === 'weighted' ? 'random' : 'weighted'
  localStorage.setItem('lr.order', order.value)
  load() // rebuild the queue under the new strategy
}

function scrollByOne(delta) {
  scrollFeedBy(feedEl, delta)
}

function onKeydown(ev) {
  const action = keyboardAction(ev)
  if (!action || disposed || loading.value || !videos.value.length) return
  if (action === 'backward' || action === 'forward' || action === 'toggle') {
    transportAction(action)
    return
  }
  ev.preventDefault()
  if (action === 'next') scrollByOne(1)
  else if (action === 'previous') scrollByOne(-1)
  else if (action === 'mute') toggleMute()
  else if (action === 'rotate') rotateActive()
  else if (action === 'order') toggleOrder()
}

async function onConfigSaved() {
  await load()
}

function toggleFolderMenu() {
  folderMenuOpen.value = !folderMenuOpen.value
}

function toggleMoveMenu() {
  moveError.value = ''
  moveMenuOpen.value = !moveMenuOpen.value
  if (moveMenuOpen.value) loadFolders()
}

function onGlobalClick(ev) {
  if (folderMenuOpen.value && !ev.target.closest?.('.folder-menu')) folderMenuOpen.value = false
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
    <h1 class="brand">Local Reels</h1>

    <main v-if="videos.length" ref="feedEl" class="feed" aria-label="Media feed" :aria-busy="loading">
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

    <nav v-if="videos.length" class="side-rail side-rail--left" aria-label="Feed navigation and filters">
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
      <div class="folder-menu">
        <button
          type="button"
          ref="folderMenuBtn"
          class="icon-btn"
          :class="{ 'icon-btn--on': activeFolders.length > 0 }"
          :aria-pressed="activeFolders.length > 0"
          aria-haspopup="menu"
          :aria-expanded="folderMenuOpen"
          aria-label="Filter by folder"
          :disabled="loading"
          :title="activeFolders.length ? `Folders: ${activeFolders.join(', ')}` : 'Filter by folder'"
          @click.stop="toggleFolderMenu"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
            <path d="M3 7V5h6l2 2h10v12H3Z" />
          </svg>
        </button>
        <div v-if="folderMenuOpen" class="folder-popover" role="menu" aria-label="Folders">
          <button type="button" class="folder-item" :class="{ 'folder-item--on': !activeFolders.length }" @click="showAllFolders">
            All folders <span class="folder-count">{{ folders.reduce((n, f) => n + f.count, 0) }}</span>
          </button>
          <button
            v-for="f in folders"
            :key="f.name"
            type="button"
            class="folder-item"
            :class="{ 'folder-item--on': isFolderActive(f.name) }"
            :aria-pressed="isFolderActive(f.name)"
            @click="toggleFolder(f.name)"
          >
            <span aria-hidden="true">{{ isFolderActive(f.name) ? '☑' : '☐' }}</span>
            {{ f.name }} <span class="folder-count">{{ f.count }}</span>
          </button>
          <button v-if="filterActive" type="button" class="folder-item folder-item--clear" @click="clearFilters">
            Clear filters
          </button>
        </div>
      </div>
    </nav>

    <nav v-if="videos.length" class="side-rail side-rail--right" aria-label="Playback and media actions">
      <button
        type="button"
        class="icon-btn"
        :aria-pressed="order === 'weighted'"
        :disabled="loading"
        :title="order === 'weighted'
          ? 'Showing less-watched first (S). Switch to random order'
          : 'Random order (S). Switch to less-watched first'"
        :aria-label="`Feed order: ${order === 'weighted' ? 'less-watched first' : 'random'}. Change order`"
        @click="toggleOrder"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M4 6h10M4 12h7M4 18h4" />
          <path d="M17 4v9m0 0 3-3m-3 3-3-3" />
        </svg>
      </button>
      <RouterLink to="/batch" class="icon-btn" aria-label="Open daily batch" title="Daily batch (fixed set for today)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
          <path d="M8 6h12M8 12h12M8 18h12" /><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01" />
        </svg>
      </RouterLink>
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
        :class="{ 'icon-btn--on': favoritesOnly }"
        :aria-pressed="favoritesOnly"
        :disabled="loading"
        aria-label="Favorites only"
        :title="favoritesOnly ? 'Show all media' : 'Show favorites only'"
        @click="toggleFavorites"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" :fill="favoritesOnly ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false">
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

    <div v-else-if="loading" class="feed-state" role="status">
      <span class="spinner" aria-hidden="true" />
      <p>Loading media…</p>
    </div>

    <div v-else-if="loadError" class="feed-state" role="alert">
      <p class="state-title">Couldn’t reach the server</p>
      <p class="state-hint">{{ loadError }}</p>
      <button class="retry-btn" @click="load">Retry</button>
    </div>

    <div v-else-if="filterActive" class="feed-state">
      <p class="state-title">Nothing matches this filter</p>
      <p class="state-hint">
        {{ favoritesOnly && !activeFolders.length
          ? 'Use the Favorite button on a reel to save it here.'
          : 'Try another folder or clear the filter.' }}
      </p>
      <button class="retry-btn" @click="clearFilters">Show everything</button>
    </div>

    <div v-else class="feed-state">
      <p class="state-title">No media found</p>
      <p class="state-hint">
        Drop videos or photos (mp4, webm, mov, jpg, png, … — subfolders are scanned too) into
        <code>{{ config?.video_dir || 'the configured folder' }}</code>
        and reload — or point to a different folder:
      </p>
      <ConfigPanel @saved="onConfigSaved" />
    </div>
  </div>
</template>
