// 版本比较（T8.5）。**刻意不 require electron**：这样它能在纯 node 下被验收脚本直接跑，
// 而不是为了测三个 if 分支去起一个 Electron 进程。
//
// 只处理"发布用的三段式版本 + 可选预发布后缀"，不实现完整 semver：
// 更新器要回答的只有"GitHub 上的 vX 比本机这个 Y 新吗"，`+build` 元数据与
// `-rc.1` 的内部排序都不影响这个判断。规则写死两条：
//   1. 逐段比数字（缺的段补 0，所以 `1.0` 等于 `1.0.0`）
//   2. 带预发布后缀的**低于**同号正式版（`0.2.0-rc1` < `0.2.0`），后缀之间按字符串比
'use strict'

/** `v0.2.0` → { nums: [0,2,0], pre: '' }；解析不出来返回 null */
function parseVersion(text) {
  const raw = String(text || '').trim().replace(/^v/i, '')
  const [core, ...rest] = raw.split('-')
  const nums = core.split('.').map((n) => Number.parseInt(n, 10))
  if (!nums.length || nums.some((n) => !Number.isFinite(n))) return null
  while (nums.length < 3) nums.push(0)
  return { nums: nums.slice(0, 3), pre: rest.join('-') }
}

/** a > b 返回 1，相等 0，a < b 返回 -1；任一方解析不出来按"相等"处理（不误报新版本） */
function compareVersions(a, b) {
  const pa = parseVersion(a)
  const pb = parseVersion(b)
  if (!pa || !pb) return 0
  for (let i = 0; i < 3; i += 1) {
    if (pa.nums[i] !== pb.nums[i]) return pa.nums[i] > pb.nums[i] ? 1 : -1
  }
  if (pa.pre && !pb.pre) return -1
  if (!pa.pre && pb.pre) return 1
  if (pa.pre === pb.pre) return 0
  return pa.pre > pb.pre ? 1 : -1
}

module.exports = { parseVersion, compareVersions }
