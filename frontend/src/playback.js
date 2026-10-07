export function canSeek(state) {
  return Boolean(state.active && state.mounted && !state.isImage && !state.failed
    && state.readyState >= 1 && Number.isFinite(state.duration) && state.duration > 0
    && Number.isFinite(state.currentTime))
}

export function seekTarget(state, delta) {
  if (!canSeek(state) || !Number.isFinite(delta)) return null
  return Math.min(state.duration, Math.max(0, state.currentTime + delta))
}

export function canTrackPlayback(state) {
  return Boolean(state.active && state.mounted && !state.failed && !state.isImage
    && !state.paused && !state.ended && !state.seeking && !state.waiting && state.readyState >= 3)
}

export function keyboardAction(event) {
  if (event.defaultPrevented || event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return null
  const targets = event.composedPath?.() || [event.target]
  if (targets.some((target) => target?.isContentEditable || target?.closest?.(
    'input, textarea, select, button, a, summary, audio, video, [contenteditable]:not([contenteditable="false"]), [role="button"], [role="link"], [role="slider"], [role="textbox"], [role="combobox"], [role="spinbutton"], [role="menu"], [role="listbox"], [role="checkbox"], [role="switch"], [role="radio"], [role="tab"]',
  ))) return null
  const actions = {
    ArrowDown: 'next',
    ArrowUp: 'previous',
    ArrowLeft: 'backward',
    ArrowRight: 'forward',
    ' ': 'toggle',
    m: 'mute',
    r: 'rotate',
    s: 'order',
  }
  const action = actions[event.key?.length === 1 ? event.key.toLowerCase() : event.key]
  if (event.repeat && ['toggle', 'mute', 'rotate', 'order'].includes(action)) return null
  return action || null
}
