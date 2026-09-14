const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function handle(res) {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* ignore */ }
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  listVideos: () => fetch('/api/videos').then(handle),
  randomVideos: (limit) =>
    fetch(`/api/videos/random${limit ? `?limit=${limit}` : ''}`).then(handle),
  recordWatch: (payload, keepalive = false) =>
    fetch('/api/watch', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify(payload),
      keepalive,
    }).then(handle),
  summary: () => fetch('/api/stats/summary').then(handle),
  topVideos: (limit = 10) => fetch(`/api/stats/top-videos?limit=${limit}`).then(handle),
  daily: (days = 30) => fetch(`/api/stats/daily?days=${days}`).then(handle),
  getConfig: () => fetch('/api/config').then(handle),
  setConfig: (videoDir) =>
    fetch('/api/config', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ video_dir: videoDir }),
    }).then(handle),
}

export function formatDuration(seconds) {
  const s = Math.max(0, Math.round(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  if (h > 0) return `${h}h ${m}m ${sec}s`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}
