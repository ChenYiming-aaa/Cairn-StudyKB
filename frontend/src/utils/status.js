/**
 * 状态 → 徽标（文案 + 语气）的唯一映射。
 *
 * 列表行与详情页头都要给同一条内容挂状态徽标：两处各写一份，早晚会漂成
 * 「列表说已整理、详情说完成」。所以文案与语气只在这里定义。
 *
 * 语气名与 `ui/Badge.vue` 的 tone 一一对应；文字必须与状态语义对得上，
 * 不能只靠颜色区分（色盲用户与黑白打印都读不出差异）。
 * 后端枚举只有四个值，见 `docs/dev/文案规范.md` §2.2。
 */
export const STATUS = {
  pending: ['待整理', 'warning'],
  organizing: ['整理中', 'info'],
  ready: ['已整理', 'success'],
  failed: ['失败', 'danger'],
}

/** 后端给了没见过的状态时：原样显示，别藏起来，也别猜语气 */
export function statusOf(status) {
  return STATUS[status] || [status || '未知', 'neutral']
}
