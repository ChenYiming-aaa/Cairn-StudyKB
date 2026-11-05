<script setup>
defineProps({
  text: { type: String, default: '' },
})
</script>

<template>
  <div class="pane">
    <pre class="raw">{{ text }}</pre>
  </div>
</template>

<style scoped>
.raw {
  margin: 0;
  max-width: 74ch;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-reading);
  font-size: 14px;
  line-height: 1.9;
  color: var(--c-text-2);
}
</style>
