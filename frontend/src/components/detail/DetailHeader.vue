<script setup>
/**
 * 详情页页头。
 *
 * 改造前：标题、状态、七个同权重的小按钮、一排 chip 全挤在首屏，读不出「现在最该做什么」。
 * 改造后：
 *   - 左：面包屑 → 可编辑标题 → 状态与归属（只读信息归到一处）
 *   - 右：一个主操作 + 一个次操作 + 一个「更多」（删除收进确认框，不再与整理按钮相邻）
 *
 * 原有逻辑一个没删：试卷导入、原件没读完时的「重读 / 去装识别组件」、笔记手改提示、
 * 工作区下拉都还在，只是按重要性重新排了位置。
 */
import { ref } from 'vue'

import Badge from '../../ui/Badge.vue'
import Button from '../../ui/Button.vue'
import Dialog from '../../ui/Dialog.vue'
import Icon from '../../ui/Icon.vue'
import Select from '../../ui/Select.vue'
import TitleEditor from '../TitleEditor.vue'
import { statusOf } from '../../utils/status'

const props = defineProps({
  item: { type: Object, required: true },
  busy: { type: Boolean, default: false },
  organizing: { type: Boolean, default: false },
  reocrBusy: { type: Boolean, default: false },
  fileState: { type: Object, default: null },
  needsRead: { type: Boolean, default: false },
  ocrReady: { type: Boolean, default: null },
  canImportExam: { type: Boolean, default: false },
  examBlockedByRead: { type: Boolean, default: false },
  workspaces: { type: Array, default: () => [] },
})

const emit = defineEmits([
  'organize', 'remove', 'practice', 'reocr', 'install-ocr', 'import-exam', 'move', 'title-saved',
])

const confirmOpen = ref(false)

function onWorkspaceChange(value) {
  emit('move', { id: props.item.id, workspaceId: value === '' ? null : Number(value) })
}

const workspaceOptions = () => [
  { value: '', label: '未归类' },
  ...props.workspaces.map((ws) => ({ value: String(ws.id), label: ws.name })),
]

function doRemove() {
  confirmOpen.value = false
  emit('remove')
}
</script>

<template>
  <header class="dhead">
    <div class="dhead-main">
      <nav class="dhead-crumb" aria-label="位置">
        <span>知识库</span>
        <Icon name="chevron-right" :size="12" />
        <span>{{ item.category || '未分类' }}</span>
      </nav>

      <TitleEditor
        :item-id="item.id"
        :title="item.title"
        :disabled="busy"
        @saved="emit('title-saved')"
      />

      <div class="dhead-meta">
        <Badge
          :tone="statusOf(item.status)[1]"
          :dot="item.status !== 'organizing'"
          :pulse="item.status === 'organizing'"
        >
          {{ statusOf(item.status)[0] }}
        </Badge>

        <!-- 原件读字状态（6-3）：关掉采集面板后，这份 PDF 在界面上曾经「失踪」 -->
        <span
          v-if="fileState"
          class="chip"
          :class="`chip-${fileState.tone}`"
        >
          <Icon name="doc" :size="12" />
          {{ fileState.text }}
        </span>

        <span v-if="item.note_edited" class="chip chip-edit" title="重新整理会覆盖手改内容">
          <Icon name="edit" :size="12" />
          笔记已手改
        </span>

        <span v-for="tag in item.tags || []" :key="tag" class="chip chip-tag">#{{ tag }}</span>

        <span class="chip-sep" aria-hidden="true" />

        <!-- 归属：一个能改的下拉，前面加「归到」，免得被当成又一个只读标签 -->
        <label class="ws-pick">
          <Icon name="folder" :size="12" />
          <span class="ws-pick-label">归到</span>
          <Select
            class="ws-select"
            :options="workspaceOptions()"
            :model-value="item.workspace_id ? String(item.workspace_id) : ''"
            :placeholder="''"
            :aria-label="'把这条移到哪个工作区'"
            @update:model-value="onWorkspaceChange"
          />
        </label>
      </div>
    </div>

    <div class="dhead-actions">
      <!-- 主操作随状态切换：没整理完时「整理」最重要，整理完「练这条」最重要 -->
      <Button
        v-if="item.status !== 'ready' && item.kind !== 'exam'"
        variant="primary"
        icon="refresh"
        :loading="busy"
        @click="emit('organize')"
      >
        {{ organizing ? '整理中…' : '开始整理' }}
      </Button>

      <Button
        v-else-if="item.status === 'ready'"
        variant="primary"
        icon="practice"
        @click="emit('practice')"
      >
        练这条
      </Button>

      <!-- 次操作 -->
      <Button
        v-if="item.status === 'ready' && item.kind !== 'exam'"
        icon="refresh"
        :loading="busy"
        @click="emit('organize')"
      >
        重新整理
      </Button>

      <Button
        v-if="canImportExam"
        icon="upload"
        @click="emit('import-exam')"
      >
        {{ item.kind === 'exam' ? '重新导入' : '导入试卷' }}
      </Button>

      <!-- 5-3：是 PDF/图片但没读完时，按钮出现但禁用并说明差在哪 -->
      <template v-else-if="examBlockedByRead">
        <Button icon="upload" disabled>导入试卷</Button>
        <span class="dhead-hint">还没读完，读完才能导入</span>
      </template>

      <!-- 原件没读完时的出口（6-3）：缺组件给「去装」，装了给「重读」 -->
      <Button
        v-if="needsRead && item.status !== 'ready' && ocrReady === false"
        icon="download"
        @click="emit('install-ocr')"
      >
        去装识别组件
      </Button>
      <Button
        v-else-if="needsRead && item.status !== 'ready'"
        icon="refresh"
        :disabled="reocrBusy"
        @click="emit('reocr')"
      >
        {{ reocrBusy ? '正在排队…' : '重读' }}
      </Button>

      <!-- 删除：单独一颗，隔开摆放，点整理时手抖不会点到它 -->
      <Button variant="ghost" icon="trash" label="删除这条" @click="confirmOpen = true" />
    </div>

    <!-- 删除确认：写清后果与不可恢复，比 window.confirm 更容易读 -->
    <Dialog
      :open="confirmOpen"
      title="删除这条内容？"
      size="sm"
      @close="confirmOpen = false"
    >
      <p class="dlg-text">
        「{{ item.title }}」的笔记片段、题目和作答记录会一起删掉，<b>不能恢复</b>。
      </p>
      <template #footer>
        <Button @click="confirmOpen = false">取消</Button>
        <Button variant="danger" icon="trash" data-autofocus @click="doRemove">删除</Button>
      </template>
    </Dialog>
  </header>
</template>

<style scoped>
.dhead {
  display: flex;
  align-items: flex-start;
  gap: var(--space-5);
  flex: none;
}

.dhead-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.dhead-crumb {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.dhead-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px var(--space-2);
  border-radius: 999px;
  background: var(--c-bg-2);
  color: var(--c-text-2);
  white-space: nowrap;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chip-tag {
  background: transparent;
  border: 1px solid var(--c-border);
  color: var(--c-text-3);
}

.chip-edit {
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
}

/* 原件读字状态三种语气：正常、进行中/部分、失败 */
.chip-ok {
  background: var(--c-success-soft);
  color: var(--c-success-ink);
}

.chip-warn {
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
}

.chip-busy {
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.chip-bad {
  background: var(--c-danger-soft);
  color: var(--c-danger-ink);
}

.chip-sep {
  width: 1px;
  height: 12px;
  background: var(--c-border);
  margin: 0 2px;
}

/* 归属下拉：包在标签样式里，但控件本身用原生 select，保证键盘与读屏行为 */
.ws-pick {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px var(--space-1) 1px var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: 999px;
  background: var(--c-bg-2);
  color: var(--c-text-2);
}

.ws-pick-label {
  white-space: nowrap;
}

.ws-select {
  width: auto;
  min-height: 0;
  height: 20px;
  padding: 0 18px 0 2px;
  border: none;
  background-color: transparent;
  background-position:
    right 8px center,
    right 3px center;
  font-size: var(--fs-xs);
  color: var(--c-text-2);
}

.ws-select:focus-visible {
  box-shadow: var(--focus-ring-inset);
}

.dhead-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: none;
  flex-wrap: wrap;
  justify-content: flex-end;
  max-width: 46%;
}

.dhead-hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  white-space: nowrap;
}

.dlg-text {
  margin: 0;
  font-size: var(--fs-md);
  line-height: var(--lh-body);
  color: var(--c-text-2);
}

.dlg-text b {
  color: var(--c-danger-ink);
}

/* 窄窗：操作行掉到标题下方并左对齐 */
@media (max-width: 1024px) {
  .dhead {
    flex-direction: column;
    gap: var(--space-3);
  }

  .dhead-actions {
    max-width: none;
    justify-content: flex-start;
  }
}
</style>
