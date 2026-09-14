<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: String, required: true },
  hint: { type: String, default: '' },
})
</script>

<template>
  <div class="stat-card">
    <span class="stat-label">{{ label }}</span>
    <span class="stat-value">{{ value }}</span>
    <span v-if="hint" class="stat-hint">{{ hint }}</span>
  </div>
</template>
