<script setup>
/**
 * 骨架屏。
 *
 * 超过 300ms 的等待必须有骨架或进度，不能只留空白或一个转圈。
 * 骨架的形状要与真实内容同构——列表三条就是三行，不要用一个通栏矩形糊过去，
 * 否则内容到达时整块跳动，比等待本身更难受。
 */
defineProps({
  variant: { type: String, default: 'text' }, // text | block | circle
  width: { type: String, default: '' },
  height: { type: String, default: '' },
  // 列表里依次入场时用，单位是 --stagger 的倍数
  index: { type: Number, default: 0 },
})
</script>

<template>
  <span
    class="u-skel"
    :class="`u-skel-${variant}`"
    :style="{
      width: width || undefined,
      height: height || undefined,
      animationDelay: `calc(var(--stagger) * ${index})`,
    }"
    aria-hidden="true"
  />
</template>

<style scoped>
.u-skel {
  display: block;
  border-radius: var(--radius-sm);
  background: var(--c-bg-2);
  background-image: linear-gradient(
    90deg,
    var(--c-bg-2) 0%,
    var(--c-skeleton) 50%,
    var(--c-bg-2) 100%
  );
  background-size: 220% 100%;
  animation: u-skel-shimmer 1.2s var(--ease-linear) infinite;
}

.u-skel-text {
  height: 12px;
  border-radius: 3px;
}

.u-skel-block {
  height: 64px;
}

.u-skel-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
}

@keyframes u-skel-shimmer {
  from {
    background-position: 120% 0;
  }

  to {
    background-position: -120% 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .u-skel {
    animation: none;
    background: var(--c-bg-2);
  }
}
</style>
