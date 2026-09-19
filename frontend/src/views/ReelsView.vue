<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import ConfigPanel from '../components/ConfigPanel.vue'
import ReelItem from '../components/ReelItem.vue'
import { api } from '../api.js'
import { useWatchTracker } from '../composables/useWatchTracker.js'
import { keyboardAction } from '../playback.js'

const BATCH = 25 // slides fetched per request
const AHEAD = 8 // append the next batch when this few slides remain
const MOUNT_WINDOW = 2 // only active ± this render a real <video>/<img>

const feedEl = ref(null)
const reelComps = ref([])
const videos = ref([])
const activeIndex = ref(0)
const muted = ref(localStorage.getItem('lr.muted') !== '0')
const order = ref(localStorage.getItem('lr.order') === 'random' ? 'random' : 'weighted')
const loading = ref(true)
const loadError = ref('')
const config = ref(null)
const brokenIds = new Set()
const rotations = ref({}) // video id -> degrees, kept for this browser session only
const folders = ref([])
const activeFolder = ref('') // '' = all
const favoritesOnly = ref(false)

const tracker = useWatchTracker()
let observer = null
let loadVersion = 0
let disposed = false

const filterActive = computed(() => activeFolder.value !== '' || favoritesOnly.value)

function currentFilters() {
  return { folder: activeFolder.value || undefined, favorites: favoritesOnly.value }
}

function bindObserver() {
  if (!feedEl.value || disposed) return
  observer?.disconnect()
  observer = new IntersectionObserver(
    (entries) => {
      if (disposed || loading.value) return
      let best = null
      for (const entry of entries) {
        if (entry.isIntersecting && (!best || entry.intersectionRatio > best.intersectionRatio)) {
          best = entry
        }
      }
      if (!best) return
      const idx = Number(best.target.dataset.index)
      if (!Number.isNaN(idx) && idx !== activeIndex.value) {
        tracker.setPlaying(false)
        tracker.setActive(videos.value[idx]?.id ?? null)
        activeIndex.value = idx
      }
    },
    { root: feedEl.value, threshold: [0.6] },
  )
  for (const node of feedEl.value.querySelectorAll('.reel')) observer.observe(node)
}

async function fetchBatch(version = loadVersion) {
  const fresh = await api.randomVideos(BATCH, order.value, currentFilters())
  if (disposed || version !== loadVersion || !fresh.length) return 0
  const recent = new Set(videos.value.slice(-60).map((v) => v.id))
  let pool = fresh.filter((v) => !brokenIds.has(v.id) && !recent.has(v.id))
  if (!pool.length) pool = fresh.filter((v) => !brokenIds.has(v.id))
  if (!pool.length) pool = fresh
  videos.value = [...videos.value, ...pool]
  return pool.length
}

async function loadFolders(version = loadVersion) {
  try {
    const result = await api.folders()
    if (!disposed && version === loadVersion) folders.value = result
  } catch {
    if (!disposed && version === loadVersion) folders.value = []
  }
}

async function load() {
  const version = ++loadVersion
  loading.value = true
  loadError.value = ''
  observer?.disconnect()
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

async function setFolder(name) {
  activeFolder.value = name
  await load()
}

async function toggleFavorites() {
  favoritesOnly.value = !favoritesOnly.value
  await load()
}

async function clearFilters() {
  activeFolder.value = ''
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

async function onFavorite(video) {
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

function toggleOrder() {
  order.value = order.value === 'weighted' ? 'random' : 'weighted'
  localStorage.setItem('lr.order', order.value)
  load() // rebuild the queue under the new strategy
}

function scrollByOne(delta) {
  const feed = feedEl.value
  if (feed) feed.scrollBy({ top: delta * feed.clientHeight, behavior: 'smooth' })
}

function onKeydown(ev) {
  const action = keyboardAction(ev)
  if (!action || disposed || loading.value || !videos.value.length) return
  ev.preventDefault()
  const active = reelComps.value[activeIndex.value]
  if (action === 'next') scrollByOne(1)
  else if (action === 'previous') scrollByOne(-1)
  else if (action === 'backward') active?.seekBy(-5)
  else if (action === 'forward') active?.seekBy(5)
  else if (action === 'toggle') active?.toggle()
  else if (action === 'mute') toggleMute()
  else if (action === 'rotate') rotateActive()
  else if (action === 'order') toggleOrder()
}

async function onConfigSaved() {
  await load()
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  disposed = true
  ++loadVersion
  observer?.disconnect()
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div class="reels-page">
    <header class="reels-header">
      <h1 class="brand">Local Reels</h1>
      <nav class="header-actions" aria-label="Feed controls">
        <button
          type="button"
          class="fav-filter-btn"
          :disabled="loading"
          :title="order === 'weighted'
            ? 'Showing less-watched first (S). Switch to random order'
            : 'Random order (S). Switch to less-watched first'"
          :aria-label="`Feed order: ${order === 'weighted' ? 'less-watched first' : 'random'}. Change order`"
          @click="toggleOrder"
        >{{ order === 'weighted' ? 'Less-watched' : 'Random' }}</button>
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
      </nav>
      <div class="filter-bar">
        <select class="folder-select" aria-label="Filter by folder" :disabled="loading" :value="activeFolder" @change="setFolder($event.target.value)">
          <option value="">All folders</option>
          <option v-for="f in folders" :key="f.name" :value="f.name">
            {{ f.name }} ({{ f.count }})
          </option>
        </select>
        <button
          type="button"
          class="fav-filter-btn"
          :class="{ 'fav-filter-btn--on': favoritesOnly }"
          :aria-pressed="favoritesOnly"
          :disabled="loading"
          title="Show favorites only"
          @click="toggleFavorites"
        >Favorites</button>
        <button v-if="filterActive" type="button" class="fav-filter-btn" :disabled="loading" title="Clear filters" @click="clearFilters">
          Clear filters
        </button>
      </div>
    </header>

    <main v-if="videos.length" ref="feedEl" class="feed" aria-label="Media feed" :aria-busy="loading">
      <ReelItem
        v-for="(video, i) in videos"
        :key="`${video.id}-${i}`"
        :ref="(c) => (reelComps[i] = c)"
        :video="video"
        :index="i"
        :active="i === activeIndex"
        :mount="Math.abs(i - activeIndex) <= MOUNT_WINDOW"
        :rotation="rotationFor(video)"
        :muted="muted"
        @state="onReelState"
        @error="onReelError"
        @favorite="onFavorite"
        @block="onBlock"
      />
    </main>

    <div v-if="videos.length" class="nav-arrows" role="group" aria-label="Feed navigation">
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
      <button type="button" class="icon-btn" aria-label="Next media" title="Next (Down arrow)" :disabled="activeIndex >= videos.length - 1" @click="scrollByOne(1)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true" focusable="false"><path d="m6 9 6 6 6-6" /></svg>
      </button>
    </div>

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
        {{ favoritesOnly && !activeFolder
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
