/**
 * Shared IntersectionObserver for the feed views.
 *
 * Observes `.reel` slides inside the scroll-snap feed and reports the most
 * visible slide index so the caller can switch the active reel.
 */
export function useReelObserver({ feedEl, isDisposed, isLoading, onActiveIndex }) {
  let observer = null

  function bindObserver() {
    if (!feedEl.value || isDisposed()) return
    observer?.disconnect()
    observer = new IntersectionObserver(
      (entries) => {
        if (isDisposed() || isLoading()) return
        let best = null
        for (const entry of entries) {
          if (entry.isIntersecting && (!best || entry.intersectionRatio > best.intersectionRatio)) {
            best = entry
          }
        }
        if (!best) return
        const idx = Number(best.target.dataset.index)
        if (!Number.isNaN(idx)) onActiveIndex(idx)
      },
      { root: feedEl.value, threshold: [0.6] },
    )
    for (const node of feedEl.value.querySelectorAll('.reel')) observer.observe(node)
  }

  function disconnectObserver() {
    observer?.disconnect()
    observer = null
  }

  return { bindObserver, disconnectObserver }
}
