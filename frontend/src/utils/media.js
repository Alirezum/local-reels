/** Shared feed helpers: scrolling, folder names and stream URLs. */

export function scrollFeedBy(feedEl, delta) {
  const feed = feedEl.value
  if (feed) feed.scrollBy({ top: delta * feed.clientHeight, behavior: 'smooth' })
}

export function topFolderName(video) {
  if (!video) return ''
  const relpath = video.relpath || ''
  return relpath.includes('/') ? relpath.split('/')[0] : ''
}

export function buildMediaUrl(relpath) {
  return `/videos/${relpath.split('/').map(encodeURIComponent).join('/')}`
}
