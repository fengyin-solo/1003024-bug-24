<template>
  <section class="page" data-module="fuel">
    <header class="page-head">
      <div>
        <h2>油料管理管理</h2>
        <p class="page-desc">维护油料记录，围绕记录编号、所属站点、油料类型、调入量做登记、筛选与状态流转。当前存量统一按「调入量 − 发电消耗」结算。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记油料记录</button>
        <button class="btn" type="button" @click="exportRows">导出油料管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="refill-panel">
      <h3 class="refill-title">需补油清单（与油料记录同一份存量）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in refillColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in refillRows" :key="`refill-${String(row.id)}`">
            <td v-for="column in refillColumns" :key="column">{{ row[column] ?? '—' }}</td>
          </tr>
          <tr v-if="!refillRows.length">
            <td :colspan="refillColumns.length" class="empty-state">暂无待补油记录</td>
          </tr>
        </tbody>
      </table>
    </section>

    <form class="filter-bar" @submit.prevent="reloadAll">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无油料管理数据，可先登记油料记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条油料管理记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="panel.visible" class="modal-mask" @click.self="closePanel">
      <div class="modal-card">
        <h3 class="modal-title">{{ panel.action }}（{{ panel.row?.['记录编号'] }}）</h3>
        <label class="modal-field">
          <span>{{ amountLabel }}</span>
          <input v-model="panel.amount" type="number" min="0" step="any" :placeholder="`请输入${amountLabel}`" />
        </label>
        <label v-if="needsTicket" class="modal-field">
          <span>{{ ticketLabel }}（同一单号重复提交只入账一次）</span>
          <input v-model="panel.ticket" :placeholder="`请输入${ticketLabel}`" />
        </label>
        <p v-if="panel.error" class="error-text">{{ panel.error }}</p>
        <div class="modal-actions">
          <button class="btn primary" type="button" :disabled="panel.submitting" @click="submitPanel">
            {{ panel.submitting ? '提交中…' : '确定' }}
          </button>
          <button class="btn ghost" type="button" @click="closePanel">取消</button>
        </div>
      </div>
    </div>

    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card wide">
        <h3 class="modal-title">油料记录详情（{{ detail['记录编号'] }}）</h3>
        <div class="detail-grid">
          <div v-for="column in columns" :key="`detail-${column}`" class="detail-item">
            <span class="stat-label">{{ column }}</span>
            <strong>{{ detail[column] ?? '—' }}</strong>
          </div>
          <div class="detail-item">
            <span class="stat-label">流转状态</span>
            <strong>{{ detail['status'] ?? '—' }}</strong>
          </div>
        </div>
        <h4 class="ledger-title">台账（历史记录保留当时的数，不随口径调整回改）</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in detailLedger" :key="`ledger-${record['序号']}`">
              <td v-for="column in ledgerColumns" :key="column">{{ record[column] ?? '—' }}</td>
            </tr>
            <tr v-if="!detailLedger.length">
              <td :colspan="ledgerColumns.length" class="empty-state">暂无台账记录</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/fuel'
const columns = ["记录编号", "所属站点", "油料类型", "调入量", "当前存量", "发电消耗", "油料日期", "油料状态"]
const refillColumns = ["记录编号", "所属站点", "油料类型", "调入量", "当前存量", "发电消耗"]
const ledgerColumns = ["序号", "类型", "单号", "数量", "调入量", "发电消耗", "当前存量", "时间", "说明"]
const actions = ["记录消耗", "申请补油", "完成补油", "调整调入量"]
const PANEL_ACTIONS = ["记录消耗", "完成补油", "调整调入量"]
const TICKET_PREFIX: Record<string, string> = { "记录消耗": "XF", "完成补油": "BY" }

const rows = ref<Row[]>([])
const refillRows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref([
  { label: '储备充足站点', value: 0 },
  { label: '油量偏低站点', value: 0 },
  { label: '需补油站点', value: 0 },
])

const panel = ref({
  visible: false,
  action: '',
  row: null as Row | null,
  amount: '',
  ticket: '',
  submitting: false,
  error: '',
})

const detail = ref<Row | null>(null)
const detailLedger = computed<Row[]>(() => (detail.value?.['台账'] as Row[]) ?? [])

const amountLabel = computed(() => {
  if (panel.value.action === '调整调入量') return '新调入量'
  return panel.value.action === '记录消耗' ? '消耗量' : '补油量'
})
const ticketLabel = computed(() => (panel.value.action === '记录消耗' ? '消耗单号' : '补油单号'))
const needsTicket = computed(() => panel.value.action !== '调整调入量')

function resetFilters() {
  filters.value = {}
  void reloadAll()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '油料记录登记入口尚未接入审批流'
}

function runAction(action: string, row: Row) {
  if (PANEL_ACTIONS.includes(action)) {
    openPanel(action, row)
    return
  }
  void submitAction(row, { action })
}

function openPanel(action: string, row: Row) {
  const prefix = TICKET_PREFIX[action] ?? 'TZ'
  // 单号在打开面板时生成一次，重复点击确定沿用同一单号，后端据此只入账一次
  panel.value = {
    visible: true,
    action,
    row,
    amount: '',
    ticket: `${prefix}-${row['记录编号'] ?? row.id}-${Date.now()}`,
    submitting: false,
    error: '',
  }
}

function closePanel() {
  panel.value.visible = false
}

async function submitPanel() {
  const { action, row, amount, ticket } = panel.value
  if (!row) return
  if (!String(amount).trim()) {
    panel.value.error = `请填写${amountLabel.value}`
    return
  }
  if (needsTicket.value && !ticket.trim()) {
    panel.value.error = `请填写${ticketLabel.value}`
    return
  }
  const values: Record<string, any> = { action }
  if (action === '调整调入量') {
    values['调入量'] = amount
  } else {
    values[amountLabel.value] = amount
    values[ticketLabel.value] = ticket.trim()
  }
  panel.value.submitting = true
  panel.value.error = ''
  try {
    const ok = await submitAction(row, values)
    if (ok) {
      closePanel()
    } else {
      panel.value.error = errorMessage.value || '油料管理动作未生效，请稍后重试'
    }
  } finally {
    panel.value.submitting = false
  }
}

async function submitAction(row: Row, values: Record<string, any>): Promise<boolean> {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      errorMessage.value = payload?.message ?? '油料管理动作未生效，请稍后重试'
      return false
    }
    // 成功与重复提交忽略都会给出提示，页面不再静默
    noticeMessage.value = payload.message ?? '油料管理动作已生效'
    await reloadAll()
    return true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '油料管理操作失败'
    return false
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('油料记录详情读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '油料记录详情读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function reload() {
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  const response = await request(`${ENDPOINT}?${query}`)
  if (!response.ok) {
    throw new Error('油料记录列表读取失败')
  }
  const payload = await response.json()
  rows.value = payload.items ?? []
  total.value = payload.total ?? rows.value.length
}

async function loadRefill() {
  const response = await request(`${ENDPOINT}/refill`)
  if (!response.ok) {
    throw new Error('需补油清单读取失败')
  }
  const payload = await response.json()
  refillRows.value = payload.items ?? []
}

async function loadStats() {
  const response = await request(`${ENDPOINT}?page=1&size=200`)
  if (!response.ok) {
    throw new Error('油料统计读取失败')
  }
  const payload = await response.json()
  const all: Row[] = payload.items ?? []
  const count = (status: string) => all.filter((row) => row.status === status).length
  stats.value = [
    { label: '储备充足站点', value: count('储备充足') },
    { label: '油量偏低站点', value: count('油量偏低') },
    { label: '需补油站点', value: count('需补油') },
  ]
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    await Promise.all([reload(), loadRefill(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '油料管理列表读取失败'
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.refill-panel {
  margin-bottom: 12px;
}
.refill-title {
  font-size: 13px;
  color: var(--muted);
  margin: 0 0 6px;
}
.notice-text {
  color: #067647;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal-card {
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px;
  width: 380px;
  max-width: 92vw;
  max-height: 85vh;
  overflow: auto;
}
.modal-card.wide {
  width: 720px;
}
.modal-title {
  margin: 0 0 12px;
  font-size: 15px;
}
.modal-field {
  display: block;
  margin-bottom: 10px;
}
.modal-field span {
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 4px;
}
.modal-field input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.modal-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-bottom: 12px;
}
.detail-item {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
}
.ledger-title {
  font-size: 13px;
  color: var(--muted);
  margin: 0 0 6px;
}
</style>
