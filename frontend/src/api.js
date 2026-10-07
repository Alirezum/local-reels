const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function handle(res) {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      if (body.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* ignore */ }
    const error = new Error(detail)
    error.status = res.status
    throw error
  }
  return res.json()
}

export const api = {
  listVideos: () => fetch('/api/videos').then(handle),
  randomVideos: (limit, order, filters = {}) => {
    const params = new URLSearchParams()
    if (limit) params.set('limit', String(limit))
    params.set('order', order ?? 'weighted')
    const folders = Array.isArray(filters.folders)
      ? filters.folders
      : filters.folder
        ? [filters.folder]
        : []
    for (const folder of folders) {
      if (folder) params.append('folder', folder)
    }
    if (filters.favorites) params.set('favorites', 'true')
    return fetch(`/api/videos/random?${params}`).then(handle)
  },
  folders: () => fetch('/api/videos/folders').then(handle),
  batchGet: (date) => fetch(`/api/batch?date=${encodeURIComponent(date)}`).then(handle),
  batchPrevious: (before) => fetch(`/api/batch/previous?before=${encodeURIComponent(before)}`).then(handle),
  batchNew: (date, size, folder) =>
    fetch('/api/batch/new', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ date, size, ...(folder ? { folder } : {}) }),
    }).then(handle),
  batchContinue: (date, fromDate) =>
    fetch('/api/batch/continue', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ date, from_date: fromDate }),
    }).then(handle),
  batchAddRandom: (date) =>
    fetch('/api/batch/add-random', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ date }),
    }).then(handle),
  batchRemove: (date, videoId) =>
    fetch(`/api/batch/${encodeURIComponent(date)}/${encodeURIComponent(videoId)}`, {
      method: 'DELETE',
    }).then(handle),
  batchReplace: (date, oldId, newId) =>
    fetch('/api/batch/replace', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ date, old_id: oldId, new_id: newId }),
    }).then(handle),
  setFlags: (videoId, flags) =>
    fetch('/api/flags', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ video_id: videoId, ...flags }),
    }).then(handle),
  blocked: () => fetch('/api/blocked').then(handle),
  moveVideo: (videoId, folder) =>
    fetch('/api/videos/move', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ video_id: videoId, folder }),
    }).then(handle),
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
  folderStats: (days = 30) => fetch(`/api/stats/folders?days=${days}`).then(handle),
  getConfig: () => fetch('/api/config').then(handle),
  setConfig: (videoDir) =>
    fetch('/api/config', {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ video_dir: videoDir }),
    }).then(handle),
}
