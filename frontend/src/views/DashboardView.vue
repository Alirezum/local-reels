<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Chart } from 'chart.js/auto'
import { api } from '../api.js'
import { useStaleRequest } from '../composables/useStaleRequest.js'
import { formatDuration } from '../utils/format.js'
import StatCard from '../components/StatCard.vue'
import ConfigPanel from '../components/ConfigPanel.vue'

const summary = ref(null)
const topVideos = ref([])
const daily = ref([])
const folderStats = ref([])
const blockedList = ref([])
const rangeDays = ref(30)
const mode = ref('daily')
const sections = reactive(Object.fromEntries(
  ['summary', 'top', 'activity', 'folders', 'hidden'].map((key) => [key, { loading: true, error: '', chartError: '' }]),
))
const pendingUnhide = reactive(new Set())
const unhideErrors = reactive({})
const unhideMessage = ref('')
const guards = {
  summary: useStaleRequest(),
  top: useStaleRequest(),
  activity: useStaleRequest(),
  folders: useStaleRequest(),
  hidden: useStaleRequest(),
}
const modeGuard = useStaleRequest()
const restoredIds = new Set()
let disposed = false
const activityRows = computed(() => mode.value === 'weekly' ? weeklyBuckets(daily.value) : daily.value)
const rangeLoading = computed(() => sections.activity.loading || sections.folders.loading)

let lineChart = null
let barChart = null
let folderChart = null
const lineCanvas = ref(null)
const barCanvas = ref(null)
const folderCanvas = ref(null)

const avgPerView = computed(() => {
  if (!summary.value || !summary.value.total_views) return '—'
  return formatDuration(summary.value.total_watch_seconds / summary.value.total_views)
})

function truncate(name, max = 22) {
  return name.length > max ? name.slice(0, max - 1) + '…' : name
}

function weekStart(isoDate) {
  const d = new Date(isoDate + 'T00:00:00Z')
  const day = (d.getUTCDay() + 6) % 7
  d.setUTCDate(d.getUTCDate() - day)
  return d.toISOString().slice(0, 10)
}

function weeklyBuckets(rows) {
  const map = new Map()
  for (const r of rows) {
    const key = weekStart(r.date)
    const cur = map.get(key) || { date: key, watch_seconds: 0, views: 0 }
    cur.watch_seconds += r.watch_seconds
    cur.views += r.views
    map.set(key, cur)
  }
  return [...map.values()].sort((a, b) => a.date.localeCompare(b.date))
}

const axisOpts = {
  ticks: { color: '#9ca3af', maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
  grid: { color: 'rgba(255,255,255,0.06)' },
}

function renderLineChart() {
  if (disposed || !lineCanvas.value || !daily.value.length) return
  const rows = activityRows.value
  lineChart = new Chart(lineCanvas.value, {
    type: 'line',
    data: {
      labels: rows.map((r) => r.date),
      datasets: [
        {
          label: 'Watch time (min)',
          data: rows.map((r) => Math.round((r.watch_seconds / 60) * 100) / 100),
          borderColor: '#fc466b',
          backgroundColor: 'rgba(252,70,107,0.15)',
          fill: true,
          tension: 0.3,
          pointRadius: rows.length > 40 ? 0 : 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.parsed.y} min` } } },
      scales: { x: axisOpts, y: { ...axisOpts, beginAtZero: true } },
    },
  })
}

function renderBarChart() {
  if (disposed || !barCanvas.value || !topVideos.value.length) return
  barChart = new Chart(barCanvas.value, {
    type: 'bar',
    data: {
      labels: topVideos.value.map((v) => truncate(v.filename)),
      datasets: [
        {
          label: 'Watch time (min)',
          data: topVideos.value.map((v) => Math.round((v.watch_seconds / 60) * 100) / 100),
          backgroundColor: 'rgba(131,58,180,0.75)',
          borderRadius: 4,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.parsed.x} min` } } },
      scales: {
        x: { ...axisOpts, beginAtZero: true },
        y: { ticks: { color: '#9ca3af' }, grid: { display: false } },
      },
    },
  })
}

const FOLDER_COLORS = [
  '#833ab4', '#fc466b', '#f7b733', '#4cc9f0', '#9b5de5',
  '#f15bb5', '#00bbf9', '#00f5d4', '#fee440', '#e07a5f',
]

function renderFolderChart() {
  if (disposed || !folderCanvas.value || !folderStats.value.length) return
  folderChart = new Chart(folderCanvas.value, {
    type: 'doughnut',
    data: {
      labels: folderStats.value.map((f) => f.folder),
      datasets: [
        {
          data: folderStats.value.map((f) => Math.round(f.watch_seconds / 6) / 10),
          backgroundColor: folderStats.value.map((_, i) => FOLDER_COLORS[i % FOLDER_COLORS.length]),
          borderColor: '#121216',
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '58%',
      plugins: {
        legend: { position: 'right', labels: { color: '#e5e7eb', boxWidth: 14 } },
        tooltip: {
          callbacks: {
            label: (c) => {
              const f = folderStats.value[c.dataIndex]
              return ` ${f.folder}: ${formatDuration(f.watch_seconds)} (${f.views} views)`
            },
          },
        },
      },
    },
  })
}

function destroyChart(key) {
  if (key === 'activity') {
    lineChart?.destroy()
    lineChart = null
  } else if (key === 'top') {
    barChart?.destroy()
    barChart = null
  } else if (key === 'folders') {
    folderChart?.destroy()
    folderChart = null
  }
}

function renderChart(key) {
  if (disposed || sections[key].loading || sections[key].error) return
  destroyChart(key)
  sections[key].chartError = ''
  try {
    if (key === 'activity') renderLineChart()
    else if (key === 'top') renderBarChart()
    else if (key === 'folders') renderFolderChart()
  } catch {
    destroyChart(key)
    sections[key].chartError = 'Chart unavailable. The same data is available in the table below.'
  }
}

async function loadSection(key) {
  if (disposed) return
  const guard = guards[key].begin()
  const days = rangeDays.value
  const state = sections[key]
  destroyChart(key)
  state.loading = true
  state.error = ''
  state.chartError = ''
  const loaders = {
    summary: () => api.summary(),
    top: () => api.topVideos(10),
    activity: () => api.daily(days),
    folders: () => api.folderStats(days),
    hidden: () => api.blocked(),
  }
  const targets = { summary, top: topVideos, activity: daily, folders: folderStats, hidden: blockedList }
  const isCurrent = () => !disposed && guard.isCurrent()
  try {
    const result = await loaders[key]()
    if (!isCurrent()) return
    targets[key].value = key === 'hidden' ? result.filter((item) => !restoredIds.has(item.id)) : result
  } catch (e) {
    if (!isCurrent()) return
    state.error = e.message || 'Could not load this section. Please try again.'
  } finally {
    if (isCurrent()) state.loading = false
  }
  if (!isCurrent() || state.error) return
  await nextTick()
  if (!isCurrent()) return
  renderChart(key)
}

function setRange(days) {
  if (disposed || rangeDays.value === days) return
  rangeDays.value = days
  loadSection('activity')
  loadSection('folders')
}

const POLL_MS = 60000
let pollTimer = 0
const refreshing = ref(false)

function refreshAll() {
  if (disposed) return
  for (const key of Object.keys(sections)) loadSection(key)
}

async function manualRefresh() {
  if (disposed || refreshing.value) return
  refreshing.value = true
  try {
    refreshAll()
    await nextTick()
    while (Object.values(sections).some((s) => s.loading) && !disposed) {
      await new Promise((r) => setTimeout(r, 100))
    }
  } finally {
    if (!disposed) refreshing.value = false
  }
}

function startPolling() {
  stopPoll()
  pollTimer = window.setInterval(() => {
    if (!disposed && document.visibilityState === 'visible' && !Object.values(sections).some((s) => s.loading)) {
      refreshAll()
    }
  }, POLL_MS)
}

function stopPoll() {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = 0
  }
}

async function unhide(item) {
  if (disposed || pendingUnhide.has(item.id)) return
  pendingUnhide.add(item.id)
  delete unhideErrors[item.id]
  unhideMessage.value = ''
  try {
    await api.setFlags(item.id, { blocked: false })
    if (disposed) return
    restoredIds.add(item.id)
    blockedList.value = blockedList.value.filter((b) => b.id !== item.id)
    unhideMessage.value = `${item.relpath} is back in your feed.`
  } catch (e) {
    if (!disposed) unhideErrors[item.id] = e.message || 'Could not unhide this item. Please try again.'
  } finally {
    if (!disposed) pendingUnhide.delete(item.id)
  }
}

async function setMode(m) {
  if (disposed || mode.value === m) return
  mode.value = m
  const mode = modeGuard.begin()
  const activityId = guards.activity.peek()
  await nextTick()
  if (disposed || !mode.isCurrent() || activityId !== guards.activity.peek()) return
  renderChart('activity')
}

onMounted(() => {
  for (const key of Object.keys(sections)) loadSection(key)
  startPolling()
})
onBeforeUnmount(() => {
  disposed = true
  stopPoll()
  for (const guard of [...Object.values(guards), modeGuard]) guard.dispose()
  for (const key of ['activity', 'top', 'folders']) destroyChart(key)
})
</script>

<template>
  <main class="dashboard-page">
    <header class="dash-header">
      <RouterLink to="/" class="icon-btn" title="Back to Reels" aria-label="Back to Reels">←</RouterLink>
      <div class="dash-intro">
        <p class="eyebrow">Your library, in focus</p>
        <h1>Dashboard</h1>
        <p class="dash-subtitle">A closer look at what you watch. A little more control over your collection.</p>
      </div>
      <div class="dash-header-actions">
        <button type="button" class="range-btn" :disabled="refreshing" aria-label="Refresh dashboard data" @click="manualRefresh">{{ refreshing ? 'Refreshing…' : 'Refresh' }}</button>
        <a href="#dashboard-settings" class="range-btn">Settings</a>
      </div>
    </header>

    <section aria-labelledby="overview-heading" :aria-busy="sections.summary.loading">
      <div class="section-heading">
        <h2 id="overview-heading">Library overview</h2>
        <p class="section-description">All-time totals · independent of the selected range.</p>
      </div>
      <p v-if="sections.summary.loading" class="dash-loading" role="status">Loading your overview…</p>
      <div v-else-if="sections.summary.error" class="status-banner status-banner--error" role="alert">
        <p>Overview unavailable. {{ sections.summary.error }}</p>
        <button class="retry-btn" @click="loadSection('summary')">Retry overview</button>
      </div>
      <div class="stat-grid">
        <StatCard label="Total watch time" :value="sections.summary.loading || sections.summary.error ? '—' : formatDuration(summary?.total_watch_seconds || 0)" hint="All-time time spent watching" />
        <StatCard label="Total views" :value="sections.summary.loading || sections.summary.error ? '—' : String(summary?.total_views || 0)" hint="All-time plays, including replays" />
        <StatCard label="Videos watched" :value="sections.summary.loading || sections.summary.error ? '—' : String(summary?.videos_watched || 0)" hint="Distinct videos watched, all time" />
        <StatCard label="Avg. per view" :value="sections.summary.loading || sections.summary.error ? '—' : avgPerView" hint="All-time watch time per play" />
      </div>
    </section>

    <div class="section-heading">
      <div>
        <h2>Viewing insights</h2>
        <p id="range-description" class="section-description">The range applies to activity and folders only. Top videos remain all-time.</p>
      </div>
      <div class="range-toggle" role="group" aria-label="Activity and folder range" aria-describedby="range-description">
        <button
          v-for="d in [7, 30, 90]"
          :key="d"
          class="range-btn"
          :class="{ 'range-btn--active': rangeDays === d }"
          :aria-pressed="rangeDays === d"
          @click="setRange(d)"
        >{{ d }} days</button>
      </div>
    </div>
    <p class="section-description" role="status">{{ rangeLoading ? `Updating the last ${rangeDays} days…` : `Activity and folders · last ${rangeDays} days` }}</p>

    <div class="dashboard-grid">
      <section class="chart-panel dashboard-wide" aria-labelledby="activity-heading" :aria-busy="sections.activity.loading">
        <div class="chart-head">
          <div>
            <p class="eyebrow">Activity</p>
            <h2 id="activity-heading">{{ rangeDays }}-day watch time</h2>
          </div>
          <div class="range-toggle" role="group" aria-label="Activity grouping">
            <button
              v-for="m in ['daily', 'weekly']"
              :key="m"
              class="range-btn"
              :class="{ 'range-btn--active': mode === m }"
              :aria-pressed="mode === m"
              @click="setMode(m)"
            >{{ m === 'daily' ? 'Daily' : 'Weekly' }}</button>
          </div>
        </div>
        <p class="section-description">Watch time in minutes, {{ mode === 'daily' ? 'day by day' : 'grouped into weeks starting Monday; boundary weeks may be partial' }}.</p>
        <p v-if="sections.activity.loading" class="dash-loading" role="status">Loading activity…</p>
        <div v-else-if="sections.activity.error" class="status-banner status-banner--error" role="alert">
          <p>Activity unavailable. {{ sections.activity.error }}</p>
          <button class="retry-btn" @click="loadSection('activity')">Retry activity</button>
        </div>
        <p v-else-if="!daily.length" class="dash-empty">No watch activity in this range. Your next reel starts the story.</p>
        <template v-else>
          <p v-if="sections.activity.chartError" class="status-banner" role="status">{{ sections.activity.chartError }}</p>
          <div v-show="!sections.activity.chartError" class="chart-box"><canvas ref="lineCanvas" role="img" aria-label="Watch time over the selected range. Expand activity data below for exact values." /></div>
          <details class="chart-details">
            <summary>View activity data</summary>
            <div class="table-scroll" tabindex="0" role="region" aria-label="Activity data">
              <table class="top-table">
                <caption>{{ rangeDays }}-day watch activity · {{ mode }}</caption>
                <thead><tr><th scope="col">{{ mode === 'weekly' ? 'Week starting' : 'Date' }}</th><th scope="col">Watch time</th><th scope="col">Views</th></tr></thead>
                <tbody><tr v-for="row in activityRows" :key="row.date"><th scope="row">{{ row.date }}</th><td>{{ formatDuration(row.watch_seconds) }}</td><td>{{ row.views }}</td></tr></tbody>
              </table>
            </div>
          </details>
        </template>
      </section>

      <section class="chart-panel" aria-labelledby="top-heading" :aria-busy="sections.top.loading">
        <div class="chart-head"><div><p class="eyebrow">On repeat · all time</p><h2 id="top-heading">Most watched videos</h2></div></div>
        <p class="section-description">Your top 10 by total watch time, in minutes. Exact totals are in the detail table below.</p>
        <p v-if="sections.top.loading" class="dash-loading" role="status">Loading top videos…</p>
        <div v-else-if="sections.top.error" class="status-banner status-banner--error" role="alert">
          <p>Top videos unavailable. {{ sections.top.error }}</p>
          <button class="retry-btn" @click="loadSection('top')">Retry top videos</button>
        </div>
        <p v-else-if="!topVideos.length" class="dash-empty">No watch data yet. Head back to your reels to get started.</p>
        <template v-else>
          <p v-if="sections.top.chartError" class="status-banner" role="status">{{ sections.top.chartError }}</p>
          <div v-show="!sections.top.chartError" class="chart-box chart-box--tall"><canvas ref="barCanvas" role="img" aria-label="All-time top videos by watch time" aria-describedby="top-detail-heading" /></div>
        </template>
      </section>

      <section class="chart-panel" aria-labelledby="folders-heading" :aria-busy="sections.folders.loading">
        <div class="chart-head"><div><p class="eyebrow">Across your collection</p><h2 id="folders-heading">Watch time by folder</h2></div></div>
        <p class="section-description">How your watch time is shared across folders in the last {{ rangeDays }} days.</p>
        <p v-if="sections.folders.loading" class="dash-loading" role="status">Loading folder activity…</p>
        <div v-else-if="sections.folders.error" class="status-banner status-banner--error" role="alert">
          <p>Folders unavailable. {{ sections.folders.error }}</p>
          <button class="retry-btn" @click="loadSection('folders')">Retry folders</button>
        </div>
        <p v-else-if="!folderStats.length" class="dash-empty">No folder activity in this range. Try a longer window.</p>
        <template v-else>
          <p v-if="sections.folders.chartError" class="status-banner" role="status">{{ sections.folders.chartError }}</p>
          <div v-show="!sections.folders.chartError" class="chart-box"><canvas ref="folderCanvas" role="img" aria-label="Watch time by folder. Expand folder data below for exact values." /></div>
          <details class="chart-details">
            <summary>View folder data</summary>
            <div class="table-scroll" tabindex="0" role="region" aria-label="Folder data">
              <table class="top-table">
                <caption>Folder activity · last {{ rangeDays }} days</caption>
                <thead><tr><th scope="col">Folder</th><th scope="col">Watch time</th><th scope="col">Views</th></tr></thead>
                <tbody><tr v-for="folder in folderStats" :key="folder.folder"><th scope="row">{{ folder.folder }}</th><td>{{ formatDuration(folder.watch_seconds) }}</td><td>{{ folder.views }}</td></tr></tbody>
              </table>
            </div>
          </details>
        </template>
      </section>

      <section class="chart-panel dashboard-wide" aria-labelledby="top-detail-heading" :aria-busy="sections.top.loading">
        <div class="chart-head"><h2 id="top-detail-heading">Top videos detail</h2></div>
        <p class="section-description">All-time rankings, with full watch totals and replay counts.</p>
        <p v-if="sections.top.loading" class="dash-loading">Loading rankings…</p>
        <p v-else-if="sections.top.error" class="dash-empty">Rankings unavailable. Use “Retry top videos” above to try again.</p>
        <p v-else-if="!topVideos.length" class="dash-empty">Your most-watched videos will appear here.</p>
        <div v-else class="table-scroll" tabindex="0" role="region" aria-label="All-time top videos detail">
          <table class="top-table">
            <caption>Top 10 videos · all time</caption>
            <thead><tr><th scope="col">Rank</th><th scope="col">Video</th><th scope="col">Watch time</th><th scope="col">Views</th></tr></thead>
            <tbody>
              <tr v-for="(v, i) in topVideos" :key="v.video_id">
                <td>{{ i + 1 }}</td><th scope="row">{{ v.filename }}</th><td>{{ formatDuration(v.watch_seconds) }}</td><td>{{ v.views }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="chart-panel" aria-labelledby="hidden-heading" :aria-busy="sections.hidden.loading">
        <div class="chart-head"><div><p class="eyebrow">Feed controls</p><h2 id="hidden-heading">Hidden items<span v-if="!sections.hidden.loading && !sections.hidden.error"> ({{ blockedList.length }})</span></h2></div></div>
        <p class="section-description">Out of the feed, not out of your library. Unhide an item to bring it back.</p>
        <p v-if="sections.hidden.loading" class="dash-loading" role="status">Loading hidden items…</p>
        <div v-else-if="sections.hidden.error" class="status-banner status-banner--error" role="alert">
          <p>Hidden items unavailable. {{ sections.hidden.error }}</p>
          <button class="retry-btn" @click="loadSection('hidden')">Retry hidden items</button>
        </div>
        <p v-else-if="!blockedList.length" class="dash-empty">Nothing hidden. Your full collection is welcome in the feed.</p>
        <div v-else class="hidden-list">
          <div v-for="item in blockedList" :key="item.id" class="hidden-item">
            <div class="hidden-row" :aria-busy="pendingUnhide.has(item.id)">
              <span class="cell-name" :title="item.relpath">{{ item.relpath }}</span>
              <button class="unhide-btn" :disabled="pendingUnhide.has(item.id)" :aria-label="`Unhide ${item.relpath}`" @click="unhide(item)">{{ pendingUnhide.has(item.id) ? 'Unhiding…' : unhideErrors[item.id] ? 'Try again' : 'Unhide' }}</button>
            </div>
            <p v-if="unhideErrors[item.id]" class="dash-error" role="alert">{{ unhideErrors[item.id] }}</p>
          </div>
        </div>
        <p class="section-description" role="status">{{ unhideMessage }}</p>
      </section>

      <section id="dashboard-settings" class="chart-panel" aria-labelledby="settings-heading" tabindex="-1">
        <div class="chart-head"><div><p class="eyebrow">Make it yours</p><h2 id="settings-heading">Settings</h2></div></div>
        <p class="section-description">Choose the local folder that powers your feed. Subfolders are included.</p>
        <ConfigPanel />
      </section>
    </div>
  </main>
</template>
