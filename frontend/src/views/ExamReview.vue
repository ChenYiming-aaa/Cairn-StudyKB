<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { api, friendlyMessage, humanDetail } from '../api/client'
import { useToast } from '../composables/useToast'
import { useUi } from '../composables/useUi'
import { TYPE_LABELS, letterOf } from '../utils/quiz'

/**
 * 试卷复核页（T10.3）：左页图、右题目卡片。
 *
 * 三条不许改：
 * - **首屏就是复核界面**，不能是「正在解析…→ 导入成功」（需求 §9）：答案错一道，
 *   用户按错的答案复习，伤害比导不进来大得多。
 * - **草稿只在前端**（`exams/parse` 不落库）：改完点「确认导入」才写库，中途退出什么都不留。
 * - **答案缺失要说出来**，不能猜一个填上：卡片上标「没认到答案」，并把答案框标出来。
 *
 * 题号跳号（`stats.gaps`）单独提示：识别漏行是常态，不说就等于默认「这份就这么多题」。
 */
const route = useRoute()
const router = useRouter()
const toast = useToast()
const { openItem } = useUi()

const fileId = computed(() => Number(route.params.fileId || 0))
const phase = ref('loading')          // loading | ready | error
const error = ref('')
const saving = ref(false)
const drafts = ref([])
const stats = ref(null)
const item = ref(null)
const page = ref(1)
const imgBroken = ref(false)

const pageCount = computed(() => Number(item.value?.file?.page_count || 0))
const noAnswer = computed(() => drafts.value.filter((d) => d.answer === null || d.answer === '')
  .length)
const incomplete = computed(() => drafts.value.filter((d) => d.options_incomplete).length)
const gaps = computed(() => stats.value?.gaps || [])
const downgrades = computed(() => drafts.value.filter((d) => willDowngrade(d)).length)
const importLabel = computed(() => `确认导入 ${drafts.value.length} 题`)

/** 题号跳号的提示句：`第 22 题没认出来`；多个跳号就列出来，别只说「有缺号」 */
const gapText = computed(() => {
  const missing = gaps.value.flatMap((gap) => gap.missing)
  if (!missing.length) return ''
  const list = missing.slice(0, 6).join('、')
  const label = missing.length > 6 ? `${missing.length} 个题号（第 ${list} 等）` : `第 ${list} 题`
  return `${label}没认出来，多半是那一行没读到`
})

async function load() {
  phase.value = 'loading'
  error.value = ''
  try {
    const data = await api.examParse({ file_id: fileId.value, use_llm: true })
    drafts.value = (data.drafts || []).map((d) => ({ ...d, options: [...(d.options || [])] }))
    stats.value = data.stats || {}
    const detail = await api.getItem(data.stats.item_id)
    item.value = detail
    page.value = 1
  } catch (err) {
    error.value = `${friendlyMessage(err)}${humanDetail(err.detail) ? `（${humanDetail(err.detail)}）` : ''}`
    phase.value = 'error'
    return
  }
  phase.value = 'ready'
  // 初审跟在解析后面自己跑：用户不用先点一下才知道哪几题有问题。
  // 不 await —— 题目先给出来，提示后到，比转圈等十几秒好
  runAudit()
}

onMounted(load)

// 换一份文件（地址栏改了）就重来，别把上一份的草稿留在屏幕上
watch(fileId, (next) => {
  if (next) load()
})

function jumpTo(draft) {
  const target = Number(draft.page_no || 0)
  if (target) page.value = target
}

function go(delta) {
  const next = page.value + delta
  if (next < 1 || (pageCount.value && next > pageCount.value)) return
  page.value = next
  imgBroken.value = false
}

/** 补一道：识别漏行时唯一的补救办法，所以放在跳号提示旁边 */
function addDraft() {
  const numbers = drafts.value.map((d) => Number(d.number)).filter((n) => Number.isFinite(n))
  const next = numbers.length ? Math.max(...numbers) + 1 : 1
  drafts.value.push({
    number: String(next), type: 'short', question: '', options: [], options_incomplete: false,
    answer: null, explanation: '', score: null, material: null,
    group: drafts.value[drafts.value.length - 1]?.group || null, page_no: page.value,
  })
}

function removeDraft(index) {
  drafts.value.splice(index, 1)
}

/** 合并到上一题：识别把一道题切成两半时用（后半截被当成了新题） */
function mergeUp(index) {
  if (index === 0) return
  const prev = drafts.value[index - 1]
  const cur = drafts.value[index]
  prev.question = `${prev.question} ${cur.question}`.trim()
  drafts.value.splice(index, 1)
}

function addOption(draft) {
  draft.options.push('')
}

function removeOption(draft, index) {
  draft.options.splice(index, 1)
  // 答案字母在新选项之后就不成立了：删完顺手清掉，别留一个指向不存在选项的答案
  const letters = draft.options.map((_, i) => letterOf(i))
  const picked = answerLetters(draft).filter((l) => letters.includes(l))
  setAnswer(draft, picked)
}

function answerLetters(draft) {
  if (Array.isArray(draft.answer)) return draft.answer.map((v) => String(v).toUpperCase())
  const text = String(draft.answer || '').toUpperCase()
  return [...new Set(text.split('').filter((ch) => /[A-H]/.test(ch)))]
}

function setAnswer(draft, letters) {
  if (draft.type === 'multiple') draft.answer = letters.length ? letters : null
  else if (draft.type === 'single') draft.answer = letters[0] || null
  else draft.answer = letters[0] || null
}

function toggleLetter(draft, letter) {
  if (draft.type === 'multiple') {
    const picked = answerLetters(draft)
    const at = picked.indexOf(letter)
    if (at >= 0) picked.splice(at, 1)
    else picked.push(letter)
    setAnswer(draft, picked.sort())
    return
  }
  setAnswer(draft, [letter])
}

/** 换题型就清答案：`B` 对判断题没有意义，留着会让「答案与题型自洽」那条校验白跑 */
function onTypeChange(draft) {
  draft.answer = null
}

function filledOptions(draft) {
  return draft.options.filter((o) => String(o || '').trim())
}

/**
 * 提交前的降级预警，判据与后端 `commit._settle` 同构。
 *
 * 必须在页面上说，不能等提交后的提示：第 7 题那种选项只认出字母、内容全丢的，
 * 用户在卡片上补两个选项就能保住选择题；点完「确认导入」再说「存成简答了」，
 * 用户得回卷子里重新找这一题。
 */
function willDowngrade(draft) {
  if (draft.type !== 'single' && draft.type !== 'multiple') return false
  return filledOptions(draft).length < 2
}

/** 答案指向不存在的选项：后端会把答案清空（不猜），这里先提醒一句 */
function answerLost(draft) {
  if (draft.type !== 'single') return false
  const letters = answerLetters(draft)
  if (letters.length !== 1) return false
  return filledOptions(draft).length < letters[0].charCodeAt(0) - 64
}

/* —— 初审（T10.9）：看这批题能不能用 —— */

const auditing = ref(false)
const auditData = ref(null)        // {issues: [{index, code, level, message, fix, applied}], stats}
const auditError = ref('')
// 校对改的是页文本，解析读的是它；不重读一次，页面上这些草稿还是改之前的
const staleAfterProofread = ref(false)

function isAnswerEmpty(draft) {
  const value = draft.answer
  if (Array.isArray(value)) return !value.length
  return value === null || value === undefined || !String(value).trim()
}

/** 只把草稿里复核要用的字段传过去：初审不看题号，也不该看到草稿上的临时字段 */
function auditPayload() {
  return drafts.value.map((d) => ({
    number: d.number,
    type: d.type,
    question: d.question,
    options: d.type === 'single' || d.type === 'multiple'
      ? d.options.filter((o) => String(o || '').trim())
      : [],
    answer: d.answer,
  }))
}

async function runAudit() {
  if (auditing.value || phase.value !== 'ready') return
  auditing.value = true
  auditError.value = ''
  try {
    const data = await api.examAudit({ drafts: auditPayload(), use_llm: true })
    auditData.value = {
      issues: (data.issues || []).map((it) => ({ ...it, applied: false })),
      stats: data.stats || {},
    }
  } catch (err) {
    // 初审挂了不影响复核：用户在页面上照样能改、能导入，只是少了这层提示
    auditError.value = friendlyMessage(err)
    auditData.value = null
  } finally {
    auditing.value = false
  }
}

const auditLine = computed(() => {
  if (auditing.value) return '正在看这批题能不能用…'
  if (auditError.value) return `没看成：${auditError.value}。照着页图自己过一遍更稳`
  const stats = auditData.value?.stats
  if (!stats) return ''
  const tail = stats.model === 'failed' ? '（模型没连上，这次只按规则看）'
    : stats.model === 'partial' ? '（有一批没看成）' : ''
  if (!liveFlagged.value) return `看了 ${stats.questions} 题，题目都是完整的${tail}`
  const bits = [`${liveFlagged.value} 题有疑问`]
  if (liveMissing.value) bits.push(`${liveMissing.value} 题没答案`)
  return `看了 ${stats.questions} 题，${bits.join('，')}${tail}`
})

/** 这一题要显示的问题。
 *
 * 两条在本地即时核对：「没答案」「选项不够」用户当场就会补上，补完还挂着提示
 * 等于骗人。其余（断句、串行）得重算整道题，留在「检查题目」里刷新 ——
 * 前端不复制后端的判据，否则两边迟早算出两个答案。
 */
function activeIssues(index) {
  const draft = drafts.value[index]
  if (!draft) return []
  return (auditData.value?.issues || []).filter((it) => {
    if (it.index !== index) return false
    if (it.code === 'NO_ANSWER' && !isAnswerEmpty(draft)) return false
    if (it.code === 'FEW_OPTIONS' && filledOptions(draft).length >= 2) return false
    if (it.code === 'ANSWER_OUT_OF_RANGE' && !answerLost(draft)) return false
    return true
  })
}

// 顶栏那行数字要跟着改：补完答案还说「2 题有疑问」，用户就不信它了
const liveFlagged = computed(() => {
  let count = 0
  for (let i = 0; i < drafts.value.length; i += 1) if (activeIssues(i).length) count += 1
  return count
})

const liveMissing = computed(() => drafts.value.filter((d) => isAnswerEmpty(d)).length)

/** 用模型给的题干：先留住原文，改错了能撤回（草稿只在前端，没有别的地方能找回来） */
function useFix(draft, issue) {
  if (!issue.fix) return
  draft.questionBefore = draft.question
  draft.question = issue.fix
  issue.applied = true
}

function undoFix(draft, issue) {
  if (draft.questionBefore !== undefined) draft.question = draft.questionBefore
  delete draft.questionBefore
  issue.applied = false
}

/** 校对采纳后重读：`parse` 读 `text_reviewed`，不重读页面上还是旧字 */
function reloadDrafts() {
  staleAfterProofread.value = false
  load()
}

const proof = ref(null)          // {total_lines, changed, pages:[{page_no, changes}]} 
const proofing = ref(false)
const applying = ref(false)
const picked = ref([])           // 接受的行，键是 `${page_no}:${line}`

/** 逐条展开成一行一条：界面上「第 3 页第 12 行」比嵌套结构好扫 */
const flatChanges = computed(() => (proof.value?.pages || [])
  .flatMap((p) => (p.changes || []).map((c) => ({ ...c, page_no: p.page_no, key: `${p.page_no}:${c.line}` }))))

function keyOf(pageNo, line) {
  return `${pageNo}:${line}`
}

async function openProofread() {
  if (proofing.value) return
  proofing.value = true
  try {
    const data = await api.examProofread({ file_id: fileId.value, use_llm: true })
    proof.value = data
    // 默认全接受（需求 §8.5），用户取消勾选的那几条才不改
    picked.value = (data.pages || []).flatMap((p) => (p.changes || []).map((c) => keyOf(p.page_no, c.line)))
    if (!data.changed) toast.info('这份文件没发现要改的字')
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    proofing.value = false
  }
}

function togglePick(key) {
  const at = picked.value.indexOf(key)
  if (at >= 0) picked.value.splice(at, 1)
  else picked.value.push(key)
}

function toggleAll() {
  picked.value = picked.value.length ? [] : flatChanges.value.map((c) => c.key)
}

async function applyProofread() {
  if (applying.value) return
  applying.value = true
  try {
    const accepted = flatChanges.value
      .filter((c) => picked.value.includes(c.key))
      .map((c) => ({ page_no: c.page_no, line: c.line, after: c.after }))
    const result = await api.examProofreadApply({ file_id: fileId.value, accepted })
    const dropped = (result.dropped || []).length
    toast.ok(`改了 ${result.applied} 处${dropped ? `，${dropped} 处没通过检查没改` : ''}`)
    proof.value = null
    // 页文本变了，屏幕上这些草稿还是旧的：不重读，用户以为改了字题目就会跟着变
    if (result.applied) staleAfterProofread.value = true
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    applying.value = false
  }
}

async function revertProofread() {
  try {
    const result = await api.examProofreadReset(fileId.value)
    toast.ok(result.reverted ? `退回原始文字（${result.reverted} 页）` : '本来就是原始文字')
    proof.value = null
  } catch (err) {
    toast.error(friendlyMessage(err))
  }
}

async function commit() {
  if (saving.value) return
  const usable = drafts.value.filter((d) => d.question.trim())
  if (!usable.length) {
    toast.error('一道题都没留，这次没导入。留一道再确认导入')
    return
  }
  saving.value = true
  try {
    const result = await api.examCommit({
      file_id: fileId.value,
      drafts: usable.map((d) => ({
        number: d.number, type: d.type, question: d.question,
        options: d.type === 'single' || d.type === 'multiple' ? d.options.filter((o) => o.trim()) : [],
        answer: d.answer, explanation: d.explanation, score: d.score,
        material: d.material, group: d.group,
      })),
    })
    const downgraded = (result.downgraded || []).length
    const kept = (result.kept_practiced || []).length
    const extra = [
      downgraded ? `${downgraded} 题选项没认全，存成了简答` : '',
      kept ? `${kept} 题练过，没能删掉（记录留着）` : '',
    ].filter(Boolean).join('；')
    toast.ok(`已导入 ${result.imported} 题${extra ? `，${extra}` : ''}`)
    router.push('/')
    openItem(result.item_id)
  } catch (err) {
    toast.error(friendlyMessage(err))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="exam-review">
    <header class="head">
      <div class="head-text">
        <h2>导入试卷</h2>
        <p v-if="item" class="sub">
          {{ item.title }}
          <template v-if="stats">· 认出 {{ stats.questions }} 题 · {{ stats.with_answer }} 题有答案</template>
        </p>
      </div>
      <div class="head-actions">
        <button
          class="btn btn-sm"
          type="button"
          aria-label="再检查一遍题目"
          :disabled="auditing || phase !== 'ready'"
          @click="runAudit"
        >{{ auditing ? '正在检查…' : '检查题目' }}</button>
        <button
          class="btn btn-sm"
          type="button"
          :disabled="proofing || phase !== 'ready'"
          @click="openProofread"
        >{{ proofing ? '正在校对…' : '校对文字' }}</button>
        <button class="btn btn-sm" type="button" :disabled="saving || phase !== 'ready'" @click="addDraft">
          补一道
        </button>
        <button
          class="btn btn-primary"
          type="button"
          :disabled="saving || phase !== 'ready' || !drafts.length"
          @click="commit"
        >{{ saving ? '正在导入…' : importLabel }}</button>
      </div>
    </header>

    <p v-if="phase === 'loading'" class="state">正在读这份试卷的题目…</p>

    <div v-else-if="phase === 'error'" class="state">
      <p>{{ error }}</p>
      <div class="state-actions">
        <button class="btn btn-sm" type="button" @click="load">再读一次</button>
        <button class="btn btn-sm btn-ghost" type="button" @click="router.push('/')">回到知识库</button>
      </div>
    </div>

    <template v-else>
      <p v-if="gapText" class="notice">
        {{ gapText }}
        <button class="btn btn-sm" type="button" @click="addDraft">补一道</button>
      </p>
      <p v-if="staleAfterProofread" class="notice">
        文字改完了，题目还是改之前的；重新读一次才会用上，这页手动改过的地方会被覆盖
        <button class="btn btn-sm" type="button" @click="reloadDrafts">重新读题</button>
        <button class="btn btn-sm btn-ghost" type="button" @click="staleAfterProofread = false">先不用</button>
      </p>
      <p
        v-if="auditLine"
        class="notice"
        :class="{ 'notice-quiet': !auditError && !liveFlagged }"
      >{{ auditLine }}</p>
      <p v-if="!drafts.length" class="notice">这份文件里没找到题目，可以照着页图手动录几道。</p>

      <div class="spread">
        <aside class="shots">
          <div class="shots-bar">
            <button class="btn btn-sm" type="button" :disabled="page <= 1" @click="go(-1)">上一页</button>
            <span class="pager">第 {{ page }} 页<template v-if="pageCount"> / 共 {{ pageCount }} 页</template></span>
            <button
              class="btn btn-sm"
              type="button"
              :disabled="!pageCount || page >= pageCount"
              @click="go(1)"
            >下一页</button>
          </div>
          <figure class="shot">
            <img
              v-if="item?.id && !imgBroken"
              :src="api.pageImageUrl(item.id, page)"
              :alt="`第 ${page} 页的页图`"
              @error="imgBroken = true"
            />
            <figcaption v-else class="shot-missing">这一页没有页图，看右边的题目就行。</figcaption>
          </figure>
        </aside>

        <section class="cards">
          <div class="cards-bar">
            <span v-if="noAnswer" class="badge badge-organizing">{{ noAnswer }} 题没认到答案</span>
            <span v-if="incomplete" class="badge badge-pending">{{ incomplete }} 题选项可能没认全</span>
            <span v-if="downgrades" class="badge badge-pending">{{ downgrades }} 题会存成简答</span>
            <span class="hint">答案对不上就改一下，错答案比没答案更糟</span>
          </div>

          <article v-for="(draft, index) in drafts" :key="index" class="card">
            <div class="card-head">
              <input
                v-model="draft.number"
                class="input num"
                type="text"
                :aria-label="`第 ${index + 1} 道题的题号`"
              />
              <select v-model="draft.type" class="input type" :aria-label="`第 ${index + 1} 道题的题型`" @change="onTypeChange(draft)">
                <option v-for="(label, key) in TYPE_LABELS" :key="key" :value="key">{{ label }}</option>
              </select>
              <button
                v-if="draft.page_no"
                class="btn btn-sm btn-ghost"
                type="button"
                :aria-label="`看第 ${draft.page_no} 页的原件`"
                @click="jumpTo(draft)"
              >第 {{ draft.page_no }} 页</button>
              <span class="spacer" />
              <button
                class="btn btn-sm btn-ghost"
                type="button"
                :disabled="index === 0"
                :aria-label="`把第 ${index + 1} 道题并到上一题`"
                @click="mergeUp(index)"
              >并到上一题</button>
              <button
                class="btn btn-sm btn-danger"
                type="button"
                :aria-label="`删掉第 ${index + 1} 道题`"
                @click="removeDraft(index)"
              >删掉</button>
            </div>

            <!-- 初审看到的问题：每条一句人话，能改的给一条改法（点了才改，改完能撤回） -->
            <ul v-if="activeIssues(index).length" class="issues">
              <li
                v-for="issue in activeIssues(index)"
                :key="issue.code"
                class="issue"
                :class="issue.level"
              >
                <span class="issue-text">{{ issue.message }}</span>
                <span v-if="issue.fix && !issue.applied" class="issue-fix">{{ issue.fix }}</span>
                <button
                  v-if="issue.fix && !issue.applied"
                  class="btn btn-sm"
                  type="button"
                  :aria-label="`第 ${index + 1} 题用这条改法`"
                  @click="useFix(draft, issue)"
                >用这条</button>
                <button
                  v-else-if="issue.applied"
                  class="btn btn-sm btn-ghost"
                  type="button"
                  :aria-label="`撤回第 ${index + 1} 题按建议做的改动`"
                  @click="undoFix(draft, issue)"
                >撤回</button>
              </li>
            </ul>

            <textarea v-model="draft.question" class="textarea stem" rows="3" :aria-label="`第 ${index + 1} 道题的题干`" />

            <div v-if="draft.type === 'single' || draft.type === 'multiple'" class="options">
              <div v-for="(_, oi) in draft.options" :key="oi" class="option">
                <span class="letter">{{ letterOf(oi) }}</span>
                <input
                  v-model="draft.options[oi]"
                  class="input"
                  type="text"
                  placeholder="选项内容"
                  :aria-label="`第 ${oi + 1} 个选项`"
                />
                <button
                  class="btn btn-sm btn-ghost"
                  type="button"
                  :aria-label="`删掉第 ${oi + 1} 个选项`"
                  @click="removeOption(draft, oi)"
                >×</button>
              </div>
              <button class="btn btn-sm" type="button" @click="addOption(draft)">加一个选项</button>
              <p v-if="draft.options_incomplete" class="warn">这题的选项没认全，对照页图补一下</p>
              <p v-if="willDowngrade(draft)" class="warn">
                选项不到两个，导入后会存成简答。补两个选项就能保住选择题
              </p>
              <p v-else-if="answerLost(draft)" class="warn">答案指向的选项不存在，导入后答案会留空</p>
            </div>

            <div class="answer">
              <span class="label">答案</span>
              <template v-if="draft.type === 'single' || draft.type === 'multiple'">
                <button
                  v-for="(_, oi) in draft.options"
                  :key="oi"
                  class="pick"
                  :class="{ on: answerLetters(draft).includes(letterOf(oi)) }"
                  type="button"
                  :aria-label="`把答案选成 ${letterOf(oi)}`"
                  @click="toggleLetter(draft, letterOf(oi))"
                >{{ letterOf(oi) }}</button>
              </template>
              <select v-else-if="draft.type === 'boolean'" v-model="draft.answer" class="input bool">
                <option :value="null">没认到答案</option>
                <option :value="true">正确</option>
                <option :value="false">错误</option>
              </select>
              <textarea v-else v-model="draft.answer" class="textarea" rows="2" placeholder="参考答案" />
              <span v-if="draft.type !== 'short' && !answerLetters(draft).length && draft.answer === null" class="badge badge-organizing">
                没认到答案
              </span>
            </div>

            <!-- 默认收起：20 道题都摊开讲解，一屏只能看到一道半 -->
            <details class="more">
              <summary>讲解与分值</summary>
              <textarea v-model="draft.explanation" class="textarea" rows="2" placeholder="讲解（可留空）" />
              <input v-model.number="draft.score" class="input score" type="number" step="0.5" min="0" placeholder="分值" />
            </details>
          </article>
        </section>
      </div>

      <footer class="foot">
        <span class="hint">导入后就在练习里按卷练，错题会进复习</span>
        <button class="btn btn-primary" type="button" :disabled="saving || !drafts.length" @click="commit">
          {{ saving ? '正在导入…' : importLabel }}
        </button>
      </footer>
    </template>

    <!-- 校对（T10.4）：浮层而不跳页 —— 跳走再回来会重新解析，刚改的草稿就没了 -->
    <section v-if="proof" class="sheet" role="dialog" aria-label="文字校对">
      <header class="sheet-head">
        <div>
          <h3>文字校对</h3>
          <p class="sheet-sub">
            识别 {{ proof.total_lines }} 行，模型改了 {{ proof.changed }} 处。
            只改错字、标点、题号，不改写内容；原文一直留着，随时能退回去
          </p>
        </div>
        <div class="sheet-actions">
          <button class="btn btn-sm" type="button" @click="toggleAll">
            {{ picked.length ? '全不采纳' : '全部采纳' }}
          </button>
          <button class="btn btn-sm btn-ghost" type="button" @click="proof = null">关掉</button>
        </div>
      </header>

      <ol v-if="flatChanges.length" class="diff-list">
        <li v-for="item in flatChanges" :key="item.key" class="diff">
          <label class="diff-pick">
            <input
              type="checkbox"
              :checked="picked.includes(item.key)"
              :aria-label="`采纳第 ${item.page_no} 页第 ${item.line} 行的改动`"
              @change="togglePick(item.key)"
            />
          </label>
          <div class="diff-body">
            <p class="diff-where">第 {{ item.page_no }} 页 · 第 {{ item.line }} 行 · {{ item.why }}</p>
            <p class="diff-before">{{ item.before }}</p>
            <p class="diff-after">{{ item.after }}</p>
          </div>
        </li>
      </ol>
      <p v-else class="state">这份文件没发现要改的字。</p>

      <footer v-if="flatChanges.length" class="sheet-foot">
        <span class="hint">不勾的那几条不改。这次改完还能再点一次「校对文字」</span>
        <button class="btn btn-sm btn-ghost" type="button" @click="revertProofread">退回原始文字</button>
        <button class="btn btn-primary" type="button" :disabled="applying" @click="applyProofread">
          {{ applying ? '正在写…' : `采纳选中的 ${picked.length} 处` }}
        </button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.exam-review {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  height: calc(100vh - var(--h-topbar));
  min-height: 0;
  padding: var(--space-4) var(--space-6);
  overflow: hidden;
}

.head {
  flex: none;
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
}

.head h2 {
  margin: 0;
  font-size: var(--fs-xl);
  line-height: var(--lh-title);
}

.sub {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.head-actions {
  margin-left: auto;
  display: flex;
  gap: var(--space-2);
}

.notice {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--c-warning-border);
  border-radius: var(--radius-sm);
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-sm);
}

/* 「看过了，都没问题」不必用告警色：一片橙色会让人以为出了事 */
.notice-quiet {
  border-color: var(--c-border);
  background: var(--c-bg-1);
  color: var(--c-text-2);
}

.spread {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr);
  gap: var(--space-4);
}

@media (max-width: 1100px) {
  .spread {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) minmax(0, 1.4fr);
  }
}

.shots {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  min-height: 0;
}

.shots-bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}

.pager {
  font-variant-numeric: tabular-nums;
}

.shot {
  margin: 0;
  flex: 1;
  min-height: 0;
  overflow: auto;
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
}

.shot img {
  display: block;
  width: 100%;
  height: auto;
}

.shot-missing {
  padding: var(--space-4);
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  text-align: center;
}

.cards {
  min-height: 0;
  overflow: auto;
  padding-right: var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.cards-bar {
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  background: var(--c-bg-0);
}

.hint {
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
}

.card-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.num {
  width: 64px;
  text-align: center;
}

.type {
  width: 88px;
}

.spacer {
  flex: 1;
}

.stem {
  font-family: var(--font-reading);
}

.options {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  align-items: flex-start;
}

.option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}

.letter {
  width: 18px;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  text-align: center;
}

.answer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.label {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.pick {
  min-width: 30px;
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-sm);
  background: var(--c-bg-1);
  font-size: var(--fs-sm);
}

.pick.on {
  border-color: var(--c-primary-border);
  background: var(--c-primary-soft);
  color: var(--c-primary-ink);
}

.bool {
  width: 140px;
}

.warn {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-warning-ink);
}

.issues {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.issue {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-1) var(--space-2);
  border-left: 2px solid var(--c-warning-border);
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  background: var(--c-warning-soft);
  color: var(--c-warning-ink);
  font-size: var(--fs-xs);
}

.issue.error {
  border-left-color: var(--c-danger-border);
  background: var(--c-danger-soft);
  color: var(--c-danger-ink);
}

/* 改法单独占一行：题干可能很长，挤在按钮旁边会被压成一列竖排的字。
   用 order 排成「问题 + 按钮 / 改法」，DOM 里仍然是「问题、改法、按钮」，读屏顺序不受影响 */
.issue-fix {
  order: 3;
  flex: 1 1 100%;
  min-width: 0;
  font-family: var(--font-reading);
  line-height: var(--lh-body);
  color: var(--c-primary-ink);
  overflow-wrap: anywhere;
}

.issue-text {
  order: 1;
}

.issue > .btn {
  order: 2;
  margin-left: auto;
}

.more summary {
  cursor: pointer;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}

.more .textarea,
.more .score {
  margin-top: var(--space-2);
}

.score {
  width: 100px;
}

.foot {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-top: var(--space-2);
  border-top: 1px solid var(--c-border);
}

.foot .btn {
  margin-left: auto;
}

.state {
  margin: var(--space-4) 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.state-actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

/* —— 校对浮层（T10.4） —— */
.sheet {
  position: fixed;
  inset: var(--h-topbar) 0 0 0;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-6);
  background: var(--c-bg-0);
  overflow: hidden;
}

.sheet-head {
  flex: none;
  display: flex;
  align-items: flex-start;
  gap: var(--space-4);
}

.sheet-head h3 {
  margin: 0;
  font-size: var(--fs-lg);
  line-height: var(--lh-title);
}

.sheet-sub {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

.sheet-actions {
  margin-left: auto;
  display: flex;
  gap: var(--space-2);
}

.diff-list {
  flex: 1;
  min-height: 0;
  overflow: auto;
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.diff {
  display: flex;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--c-border);
  border-radius: var(--radius-md);
  background: var(--c-bg-1);
}

.diff-pick {
  padding-top: 2px;
}

.diff-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.diff-where {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  font-variant-numeric: tabular-nums;
}

.diff-before,
.diff-after {
  margin: 0;
  font-size: var(--fs-sm);
  font-family: var(--font-reading);
  line-height: var(--lh-body);
  overflow-wrap: anywhere;
}

.diff-before {
  color: var(--c-text-3);
  text-decoration: line-through;
}

.diff-after {
  color: var(--c-primary-ink);
}

.sheet-foot {
  flex: none;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--c-border);
}

.sheet-foot .btn:last-child {
  margin-left: auto;
}
</style>
