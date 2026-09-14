<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Chart } from 'chart.js/auto'
import { api, formatDuration } from '../api.js'
import StatCard from '../components/StatCard.vue'
import ConfigPanel from '../components/ConfigPanel.vue'

const summary = ref(null)
const topVideos = ref([])
const daily = ref([])
const loading = ref(true)
const error = ref('')
const rangeDays = ref(30)
const mode = ref('daily')

let lineChart = null
let barChart = null
const lineCanvas = ref(null)
const barCanvas = ref(null)

const avgPerView = computed(() => {
  if (!summary.value || !summary.value.total_views) return '—'
  return formatDuration(summary.value.total_watch_seconds / summary.value.total_views)
})

function truncate(name, max = 22) {
  return name.length > max ? name.slice(0, max - 1) + '…' : name
}

function weekStart(isoDate) {
  const d = new Date(isoDate + 'T00:00:00Z')
  const day = (d.getUTCDay() + 6) % 7 // Monday = 0
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
  if (!lineCanvas.value) return
  lineChart?.destroy()
  const rows = mode.value === 'weekly' ? weeklyBuckets(daily.value) : daily.value
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
  if (!barCanvas.value) return
  barChart?.destroy()
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

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [s, t, d] = await Promise.all([api.summary(), api.topVideos(10), api.daily(rangeDays.value)])
    summary.value = s
    topVideos.value = t
    daily.value = d
    await nextTick()
    renderLineChart()
    renderBarChart()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

async function setRange(days) {
  rangeDays.value = days
  daily.value = await api.daily(days)
  renderLineChart()
}

async function setMode(m) {
  mode.value = m
  renderLineChart()
}

onMounted(load)
onBeforeUnmount(() => {
  lineChart?.destroy()
  barChart?.destroy()
})
</script>

<template>
  <div class="dashboard-page">
    <header class="dash-header">
      <RouterLink to="/" class="icon-btn" title="Back to Reels">←</RouterLink>
      <h1>Dashboard</h1>
      <div class="range-toggle">
        <button
          v-for="d in [7, 30, 90]"
          :key="d"
          class="range-btn"
          :class="{ 'range-btn--active': rangeDays === d }"
          @click="setRange(d)"
        >
          {{ d }}d
        </button>
      </div>
    </header>

    <p v-if="error" class="dash-error">{{ error }}</p>
    <p v-else-if="loading" class="dash-loading">Loading…</p>

    <template v-else>
      <section class="stat-grid">
        <StatCard label="Total watch time" :value="formatDuration(summary?.total_watch_seconds || 0)" />
        <StatCard label="Total views" :value="String(summary?.total_views || 0)" />
        <StatCard label="Videos watched" :value="String(summary?.videos_watched || 0)" />
        <StatCard label="Avg. per view" :value="avgPerView" />
      </section>

      <section class="chart-panel">
        <div class="chart-head">
          <h2>{{ rangeDays }}-day watch time</h2>
          <div class="range-toggle">
            <button
              v-for="m in ['daily', 'weekly']"
              :key="m"
              class="range-btn"
              :class="{ 'range-btn--active': mode === m }"
              @click="setMode(m)"
            >
              {{ m }}
            </button>
          </div>
        </div>
        <div class="chart-box"><canvas ref="lineCanvas" /></div>
      </section>

      <section class="chart-panel">
        <div class="chart-head"><h2>Most watched videos</h2></div>
        <p v-if="!topVideos.length" class="dash-empty">No watch data yet — go watch some reels.</p>
        <div v-else class="chart-box chart-box--tall"><canvas ref="barCanvas" /></div>
      </section>

      <section v-if="topVideos.length" class="chart-panel">
        <div class="chart-head"><h2>Top videos detail</h2></div>
        <table class="top-table">
          <thead>
            <tr><th>#</th><th>Video</th><th>Watch time</th><th>Views</th></tr>
          </thead>
          <tbody>
            <tr v-for="(v, i) in topVideos" :key="v.video_id">
              <td>{{ i + 1 }}</td>
              <td class="cell-name" :title="v.filename">{{ v.filename }}</td>
              <td>{{ formatDuration(v.watch_seconds) }}</td>
              <td>{{ v.views }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section class="chart-panel">
        <div class="chart-head"><h2>Settings</h2></div>
        <ConfigPanel />
      </section>
    </template>
  </div>
</template>
