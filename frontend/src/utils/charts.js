/** Shared dashboard chart helpers (pure functions and constants). */

export const AXIS_OPTS = {
  ticks: { color: '#9ca3af', maxRotation: 0, autoSkip: true, maxTicksLimit: 8 },
  grid: { color: 'rgba(255,255,255,0.06)' },
}

export const FOLDER_COLORS = [
  '#833ab4', '#fc466b', '#f7b733', '#4cc9f0', '#9b5de5',
  '#f15bb5', '#00bbf9', '#00f5d4', '#fee440', '#e07a5f',
]

export function truncateName(name, max = 22) {
  return name.length > max ? name.slice(0, max - 1) + '…' : name
}

/** Monday (UTC) starting the week that contains the given YYYY-MM-DD date. */
export function weekStartMonday(isoDate) {
  const d = new Date(isoDate + 'T00:00:00Z')
  const day = (d.getUTCDay() + 6) % 7
  d.setUTCDate(d.getUTCDate() - day)
  return d.toISOString().slice(0, 10)
}

export function groupWeekly(rows) {
  const map = new Map()
  for (const r of rows) {
    const key = weekStartMonday(r.date)
    const cur = map.get(key) || { date: key, watch_seconds: 0, views: 0 }
    cur.watch_seconds += r.watch_seconds
    cur.views += r.views
    map.set(key, cur)
  }
  return [...map.values()].sort((a, b) => a.date.localeCompare(b.date))
}

/** Seconds converted to minutes, rounded to the given decimals, for chart datasets. */
export function toMinutes(seconds, decimals = 2) {
  const factor = 10 ** decimals
  return Math.round((seconds / 60) * factor) / factor
}
