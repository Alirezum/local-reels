/**
 * Stale-request guard for async loads.
 *
 * Each load calls begin() and only commits its result while isCurrent()
 * still holds, so a slow earlier request can never overwrite a newer one.
 * Call dispose() on unmount to invalidate everything outstanding.
 */
export function useStaleRequest() {
  let current = 0
  let disposed = false

  function begin() {
    const id = ++current
    return { id, isCurrent: () => !disposed && id === current }
  }

  function peek() {
    return current
  }

  function dispose() {
    disposed = true
    ++current
  }

  return { begin, peek, dispose }
}
