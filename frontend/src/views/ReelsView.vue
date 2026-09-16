<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import ConfigPanel from '../components/ConfigPanel.vue'
import ReelItem from '../components/ReelItem.vue'
import { api } from '../api.js'
import { useWatchTracker } from '../composables/useWatchTracker.js'

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

const isEmpty = computed(() => !loading.value && !loadError.value && videos.value.length === 0)
const filterActive = computed(() => activeFolder.value !== '' || favoritesOnly.value)

function currentFilters() {
  return { folder: activeFolder.value || undefined, favorites: favoritesOnly.value }
}

function bindObserver() {
  if (!feedEl.value) return
  observer?.disconnect()
  observer = new IntersectionObserver(
    (entries) => {
      let best = null
      for (const entry of entries) {
        if (entry.isIntersecting && (!best || entry.intersectionRatio > best.intersectionRatio)) {
          best = entry
        }
      }
      if (!best) return
      const idx = Number(best.target.dataset.index)
      if (!Number.isNaN(idx) && idx !== activeIndex.value) {
        activeIndex.value = idx
        tracker.setActive(videos.value[idx]?.id ?? null)
        // Videos count time only while actually playing; an active image
        // (no <video> element inside) counts as "playing" until swiped.
        const vid = best.target.querySelector('video')
        tracker.setPlaying(vid ? !vid.paused : true)
      }
    },
    { root: feedEl.value, threshold: [0.6] },
  )
  for (const node of feedEl.value.querySelectorAll('.reel')) observer.observe(node)
}

async function fetchBatch() {
  const fresh = await api.randomVideos(BATCH, order.value, currentFilters())
  if (!fresh.length) return 0
  const recent = new Set(videos.value.slice(-60).map((v) => v.id))
  let pool = fresh.filter((v) => !brokenIds.has(v.id) && !recent.has(v.id))
  if (!pool.length) pool = fresh.filter((v) => !brokenIds.has(v.id))
  if (!pool.length) pool = fresh
  videos.value = [...videos.value, ...pool]
  return pool.length
}

async function loadFolders() {
  try {
    folders.value = await api.folders()
  } catch {
    folders.value = []
  }
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    config.value = await api.getConfig()
    videos.value = []
    await loadFolders()
    if (!(await fetchBatch())) {
      config.value = await api.getConfig() // refresh count/error state
    }
    await nextTick()
    bindObserver()
    tracker.setActive(videos.value[0]?.id ?? null)
  } catch (e) {
    loadError.value = e.message
  } finally {
    loading.value = false
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
  if (appending || !videos.value.length || videos.value.length > 1900) return
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
  if (index === activeIndex.value) tracker.setPlaying(playing)
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
  // Remove every slide for this id, then snap the feed onto the next item.
  videos.value = videos.value.filter((v) => v.id !== video.id)
  if (activeIndex.value > videos.value.length - 1) activeIndex.value = Math.max(0, videos.value.length - 1)
  await nextTick()
  bindObserver()
  const feed = feedEl.value
  if (feed) feed.scrollTo({ top: activeIndex.value * feed.clientHeight })
  tracker.setActive(videos.value[activeIndex.value]?.id ?? null)
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
  if (ev.target instanceof HTMLInputElement) return
  if (ev.key === 'ArrowDown') { ev.preventDefault(); scrollByOne(1) }
  else if (ev.key === 'ArrowUp') { ev.preventDefault(); scrollByOne(-1) }
  else if (ev.key === ' ') { ev.preventDefault(); reelComps.value[activeIndex.value]?.toggle() }
  else if (ev.key.toLowerCase() === 'm') toggleMute()
  else if (ev.key.toLowerCase() === 'r') rotateActive()
  else if (ev.key.toLowerCase() === 's') toggleOrder()
}

async function onConfigSaved() {
  await load()
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <div class="reels-page">
    <header class="reels-header">
      <h1 class="brand">Local Reels</h1>
      <nav class="header-actions">
        <button
          class="icon-btn"
          :title="order === 'weighted'
            ? 'Shuffle: showing less-watched first (s) — click for pure random'
            : 'Shuffle: pure random (s) — click to show less-watched first'"
          @click="toggleOrder"
        >{{ order === 'weighted' ? '🌱' : '🎲' }}</button>
        <button class="icon-btn" title="Rotate active (r)" @click="rotateActive">⟳</button>
        <button class="icon-btn" :title="muted ? 'Unmute (m)' : 'Mute (m)'" @click="toggleMute">
          {{ muted ? '🔇' : '🔊' }}
        </button>
        <RouterLink to="/dashboard" class="icon-btn" title="Dashboard">📊</RouterLink>
      </nav>
      <div v-if="folders.length > 1 || favoritesOnly" class="filter-bar">
        <select class="folder-select" :value="activeFolder" @change="setFolder($event.target.value)">
          <option value="">📂 All folders</option>
          <option v-for="f in folders" :key="f.name" :value="f.name">
            {{ f.name }} ({{ f.count }})
          </option>
        </select>
        <button
          class="fav-filter-btn"
          :class="{ 'fav-filter-btn--on': favoritesOnly }"
          title="Show favorites only"
          @click="toggleFavorites"
        >♥ Favorites</button>
        <button v-if="filterActive" class="fav-filter-btn" title="Clear filters" @click="clearFilters">
          ✕
        </button>
      </div>
    </header>

    <main v-if="videos.length" ref="feedEl" class="feed">
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

    <div v-if="videos.length" class="nav-arrows">
      <button
        class="icon-btn"
        title="Previous (↑)"
        :disabled="activeIndex === 0"
        @click="scrollByOne(-1)"
      >▲</button>
      <button class="icon-btn" title="Next (↓)" @click="scrollByOne(1)">▼</button>
    </div>

    <div v-else-if="loading" class="feed-state">
      <span class="spinner" />
      <p>Loading videos…</p>
    </div>

    <div v-else-if="loadError" class="feed-state">
      <p class="state-title">Couldn’t reach the server</p>
      <p class="state-hint">{{ loadError }}</p>
      <button class="retry-btn" @click="load">Retry</button>
    </div>

    <div v-else-if="filterActive" class="feed-state">
      <p class="state-title">Nothing matches this filter</p>
      <p class="state-hint">
        {{ favoritesOnly && !activeFolder
          ? 'Tap ♡ on a reel to add it to your favorites.'
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
