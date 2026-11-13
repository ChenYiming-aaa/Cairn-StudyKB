<script setup>
/**
 * 工作区一行（T9.9 从 WorkspaceBar 拆出来）。
 *
 * 一行只有三种形态：**普通**（点它筛选）、**改名中**（输入框 + 保存）、**固定项**
 * （「全部」「未归类」没有 `row.ws`，所以不显示改名/删除）。
 *
 * 改名输入框由本组件自己持有草稿：草稿是「正在编辑的东西」，留在父组件会让父组件
 * 同时管两个草稿（新建的与改名的），很容易串。
 */
import { nextTick, ref, watch } from 'vue'

const props = defineProps({
  // { key, name, count, ws? }：`ws` 存在才是用户建的工作区
  row: { type: Object, required: true },
  active: { type: Boolean, default: false },
  editing: { type: Boolean, default: false },
})
const emit = defineEmits(['select', 'rename', 'remove', 'save', 'cancel'])

const draft = ref(props.row.name)
const inputRef = ref(null)

watch(
  () => props.editing,
  async (on) => {
    if (!on) return
    draft.value = props.row.name
    await nextTick()
    inputRef.value?.focus?.()
    inputRef.value?.select?.()
  },
  { immediate: true }
)

function save() {
  const name = draft.value.trim()
  if (name) emit('save', name)
}
</script>

<template>
  <li class="ws-row">
    <div v-if="editing" class="editor">
      <input
        ref="inputRef"
        v-model="draft"
        class="input input-sm"
        maxlength="20"
        aria-label="工作区名字"
        @keydown.enter="save"
        @keydown.esc="emit('cancel')"
      />
      <button class="btn btn-sm" type="button" @click="save">保存</button>
    </div>

    <template v-else>
      <button
        type="button"
        class="node"
        :class="{ on: active }"
        :aria-label="`工作区 ${row.name}`"
        @click="emit('select', row.key)"
      >
        <span class="label">{{ row.name }}</span>
        <span class="count">{{ row.count }}</span>
      </button>
      <div v-if="row.ws" class="acts">
        <button
          class="act"
          type="button"
          :aria-label="`重命名 ${row.ws.name}`"
          title="重命名"
          @click="emit('rename', row.ws)"
        >
          ✎
        </button>
        <button
          class="act act-del"
          type="button"
          :aria-label="`删除 ${row.ws.name}`"
          title="删除工作区"
          @click="emit('remove', row.ws)"
        >
          ×
        </button>
      </div>
    </template>
  </li>
</template>

<style scoped>
.ws-row {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.node {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  text-align: left;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.node:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.node.on {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
  font-weight: 600;
}

.label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.count {
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  color: var(--c-text-3);
}

.node.on .count {
  color: var(--c-primary-ink);
}

/* 改名 / 删除只在悬停或键盘落到这一行时露出：常驻两个小图标会让左栏像工具栏 */
.acts {
  display: flex;
  gap: 1px;
  opacity: 0;
}

.ws-row:hover .acts,
.ws-row:focus-within .acts {
  opacity: 1;
}

.act {
  width: 20px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--c-text-3);
  font-size: var(--fs-xs);
  line-height: 1;
}

.act:hover {
  background: var(--c-bg-2);
  color: var(--c-text-1);
}

.act-del:hover {
  color: var(--c-danger, #c0392b);
}

.editor {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1) var(--space-2);
  width: 100%;
}

.input-sm {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-sm);
  padding: var(--space-1) var(--space-2);
}
</style>
