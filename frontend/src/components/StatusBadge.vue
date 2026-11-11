<script setup>
import { computed } from 'vue'

const props = defineProps({
  status: { type: String, default: '' },
})

const MAP = {
  pending: ['待整理', 'badge-pending'],
  organizing: ['整理中', 'badge-organizing'],
  ready: ['已整理', 'badge-ready'],
  failed: ['失败', 'badge-failed'],
}

const view = computed(() => MAP[props.status] || [props.status || '未知', 'badge-soft'])
</script>

<template>
  <span class="badge" :class="view[1]">
    <i class="dot" :class="{ pulse: status === 'organizing' }" />
    {{ view[0] }}
  </span>
</template>
