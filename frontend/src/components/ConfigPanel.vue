<script setup>
import { onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['saved'])
const inputId = useId()
const videoDir = ref('')
const current = ref('')
const loaded = ref(false)
const loading = ref(true)
const busy = ref(false)
const message = ref('')
const isError = ref(false)
const loadError = ref('')
const invalid = ref(false)
let edited = false
let disposed = false
let requestId = 0

async function load() {
  if (disposed || busy.value) return
  const request = ++requestId
  loading.value = true
  loadError.value = ''
  try {
    const cfg = await api.getConfig()
    if (disposed || request !== requestId) return
    current.value = cfg.video_dir || ''
    loaded.value = true
    if (!edited) videoDir.value = current.value
  } catch (e) {
    if (disposed || request !== requestId) return
    loadError.value = `Could not load the current folder. ${e.message || 'Please try again.'}`
  } finally {
    if (!disposed && request === requestId) loading.value = false
  }
}

function onInput() {
  edited = true
  if (invalid.value && videoDir.value.trim()) invalid.value = false
  message.value = ''
  isError.value = false
}

async function save() {
  if (disposed || loading.value || busy.value) return
  const path = videoDir.value.trim()
  if (!path) {
    invalid.value = true
    message.value = ''
    return
  }
  const request = ++requestId
  busy.value = true
  invalid.value = false
  message.value = ''
  isError.value = false
  try {
    const cfg = await api.setConfig(path)
    if (disposed || request !== requestId) return
    current.value = cfg.video_dir || path
    videoDir.value = current.value
    loaded.value = true
    edited = false
    loadError.value = ''
    message.value = `Folder saved. ${cfg.video_count} video${cfg.video_count === 1 ? '' : 's'} found.`
    emit('saved', cfg)
  } catch (e) {
    if (disposed || request !== requestId) return
    message.value = e.message || 'Could not save this folder. Please try again.'
    isError.value = true
  } finally {
    if (!disposed && request === requestId) busy.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => {
  disposed = true
  requestId++
})
</script>

<template>
  <form class="config-panel" :aria-busy="loading || busy" @submit.prevent="save">
    <label class="config-label" :for="inputId">Video folder</label>
    <p :id="`${inputId}-help`" class="section-description">Enter a folder path on the machine running Local Reels, not a web address.</p>
    <div class="config-row">
      <input
        :id="inputId"
        v-model="videoDir"
        class="config-input"
        type="text"
        spellcheck="false"
        autocomplete="off"
        autocapitalize="off"
        :disabled="loading || busy"
        :aria-invalid="invalid"
        :aria-describedby="`${inputId}-help ${inputId}-validation ${inputId}-feedback`"
        placeholder="/path/to/videos"
        @input="onInput"
      />
      <button class="config-save" type="submit" :disabled="loading || busy">
        {{ busy ? 'Saving…' : loading ? 'Loading…' : 'Save folder' }}
      </button>
    </div>
    <p :id="`${inputId}-validation`" class="config-msg config-msg--error" aria-live="polite">{{ invalid ? 'Enter a folder path before saving.' : '' }}</p>
    <p class="config-current">
      <span class="config-label">Current folder</span>
      <span v-if="loading">Loading current folder…</span>
      <code v-else-if="loaded && current">{{ current }}</code>
      <span v-else>{{ loaded ? 'No folder configured yet.' : 'Current folder unavailable.' }}</span>
    </p>
    <div v-if="loadError" class="status-banner status-banner--error" role="alert">
      <p>{{ loadError }}</p>
      <button class="unhide-btn" type="button" :disabled="loading || busy" @click="load">Retry current folder</button>
    </div>
    <p :id="`${inputId}-feedback`" class="config-msg" :class="{ 'config-msg--error': isError, 'config-msg--pending': loading || busy }" role="status" aria-live="polite" aria-atomic="true">{{ loading ? 'Loading folder settings…' : busy ? 'Saving your folder and scanning for media…' : message }}</p>
  </form>
</template>
