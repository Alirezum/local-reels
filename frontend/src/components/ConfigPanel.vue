<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const emit = defineEmits(['saved'])

const videoDir = ref('')
const current = ref('')
const busy = ref(false)
const message = ref('')
const isError = ref(false)

async function load() {
  try {
    const cfg = await api.getConfig()
    current.value = cfg.video_dir
    if (!videoDir.value) videoDir.value = cfg.video_dir
  } catch (e) {
    message.value = `Failed to load config: ${e.message}`
    isError.value = true
  }
}

async function save() {
  if (!videoDir.value.trim() || busy.value) return
  busy.value = true
  message.value = ''
  isError.value = false
  try {
    const cfg = await api.setConfig(videoDir.value.trim())
    current.value = cfg.video_dir
    message.value = `Saved — ${cfg.video_count} video${cfg.video_count === 1 ? '' : 's'} found.`
    emit('saved', cfg)
  } catch (e) {
    message.value = e.message
    isError.value = true
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="config-panel">
    <label class="config-label" for="video-dir">Video folder</label>
    <div class="config-row">
      <input
        id="video-dir"
        v-model="videoDir"
        class="config-input"
        type="text"
        spellcheck="false"
        :placeholder="current || '/path/to/videos'"
        @keyup.enter="save"
      />
      <button class="config-save" :disabled="busy" @click="save">
        {{ busy ? 'Saving…' : 'Save' }}
      </button>
    </div>
    <p v-if="message" class="config-msg" :class="{ 'config-msg--error': isError }">{{ message }}</p>
  </div>
</template>
