<template>
  <section class="page" data-module="fuel">
    <header class="page-head">
      <div>
        <h2>油料管理管理</h2>
        <p class="page-desc">围绕调入量、发电消耗与补油调运维护存量；当前存量由台账统一口径派生，列表与详情同数同源。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记油料记录</button>
        <button class="btn" type="button" @click="exportRows">导出油料管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article
        v-for="item in stats"
        :key="item.label"
        class="stat-card"
        :class="{ clickable: item.status }"
        role="button"
        tabindex="0"
        @click="filterByStatus(item.status)"
        @keydown.enter="filterByStatus(item.status)"
      >
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>记录编号</span>
        <input v-model="keyword" placeholder="按记录编号检索" />
      </label>
      <label class="filter-item">
        <span>油料状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
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
            <button class="link" type="button" :disabled="submitting" @click="openAmount('记录消耗', row)">
              记录消耗
            </button>
            <button
              class="link"
              type="button"
              :disabled="submitting || row.status === '已补充'"
              @click="runSimpleAction('申请补油', row)"
            >
              申请补油
            </button>
            <button
              class="link"
              type="button"
              :disabled="submitting || row.status === '已补充'"
              @click="openAmount('完成补油', row)"
            >
              完成补油
            </button>
            <button class="link" type="button" @click="openLedger(row)">历史台账</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无油料管理数据，可先登记油料记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条油料管理记录</span>
      <span v-if="notice" :class="noticeTone">{{ notice }}</span>
      <span v-else-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 发电消耗 / 完成补油 录入弹窗：token 在打开时生成，整笔表单重复提交只扣/加一次 -->
    <div v-if="amountDialog.open" class="modal-mask" @click.self="closeDialogs">
      <div class="modal">
        <h3>{{ amountDialog.action }}</h3>
        <p class="modal-tip">
          {{ amountDialog.action === '记录消耗'
            ? `记录编号 ${amountDialog.row?.['记录编号']}，当前存量 ${amountDialog.row?.['当前存量']}`
            : `记录编号 ${amountDialog.row?.['记录编号']}，补油完成后自动退出需补油清单` }}
        </p>
        <label class="modal-field">
          <span>{{ amountDialog.action === '记录消耗' ? '发电消耗量' : '补油调运量' }}</span>
          <input v-model="amountDialog.amount" type="number" min="0" step="0.01" placeholder="请输入数量（升）" />
        </label>
        <label class="modal-field">
          <span>发生日期</span>
          <input v-model="amountDialog.date" type="date" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" :disabled="submitting" @click="closeDialogs">取消</button>
          <button class="btn primary" type="button" :disabled="submitting" @click="submitAmount">
            {{ submitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 历史台账：每笔事件保留当时余额；补油调运量口径变了可在这里调整，当前存量按新口径重算 -->
    <div v-if="ledgerDialog.open" class="modal-mask" @click.self="closeDialogs">
      <div class="modal modal-wide">
        <h3>历史台账 · {{ ledgerDialog.row?.['记录编号'] }}</h3>
        <p class="modal-tip">
          当前存量 <strong>{{ ledgerDialog.row?.['当前存量'] }}</strong>
          ＝ 调入量 {{ ledgerDialog.row?.['调入量'] }} ＋ 累计调运 {{ ledgerDialog.row?.['累计调运'] }}
          − 发电消耗 {{ ledgerDialog.row?.['发电消耗'] }}；历史台账保留每笔发生后的余额快照。
        </p>
        <table class="data-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>类型</th>
              <th>数量</th>
              <th>日期</th>
              <th>事件后余额（历史快照）</th>
              <th>口径调整</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="event in ledgerEvents" :key="event.序号">
              <td>{{ event.序号 }}</td>
              <td>{{ event.类型 }}</td>
              <td>{{ event.数量 }}</td>
              <td>{{ event.日期 || '—' }}</td>
              <td>{{ event.事件后余额 }}</td>
              <td>
                <button
                  v-if="event.可调整"
                  class="link"
                  type="button"
                  :disabled="submitting"
                  @click="editResupply(event)"
                >
                  调整调运量
                </button>
                <span v-else class="muted-text">—</span>
              </td>
            </tr>
            <tr v-if="!ledgerEvents.length">
              <td colspan="6" class="empty-state">暂无台账记录</td>
            </tr>
          </tbody>
        </table>
        <div class="modal-actions">
          <button class="btn primary" type="button" @click="closeDialogs">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type LedgerEvent = {
  序号: number
  类型: string
  数量: number
  日期: string
  事件后余额: number
  可调整: boolean
}

const ENDPOINT = '/api/fuel'
const columns = ['记录编号', '所属站点', '油料类型', '调入量', '当前存量', '发电消耗', '累计调运', '油料日期', '油料状态']
const statuses = ['储备充足', '油量偏低', '需补油', '已补充']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const notice = ref('')
const noticeTone = ref('ok-text')
const submitting = ref(false)
const keyword = ref('')
const statusFilter = ref('')
const stats = ref([
  { label: '储备充足站点', value: 0, status: '储备充足' },
  { label: '油量偏低站点', value: 0, status: '油量偏低' },
  { label: '需补油站点', value: 0, status: '需补油' },
])

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function newToken(): string {
  return (globalThis.crypto?.randomUUID?.() ?? `t-${Date.now()}-${Math.random().toString(16).slice(2)}`)
}

const amountDialog = reactive<{
  open: boolean
  action: '记录消耗' | '完成补油'
  row: Row | null
  amount: string
  date: string
  token: string
}>({ open: false, action: '记录消耗', row: null, amount: '', date: today(), token: '' })

const ledgerDialog = reactive<{ open: boolean; row: Row | null }>({ open: false, row: null })
const ledgerEvents = ref<LedgerEvent[]>([])

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function filterByStatus(status: string) {
  statusFilter.value = statusFilter.value === status ? '' : status
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '油料记录登记入口尚未接入审批流'
}

function closeDialogs() {
  amountDialog.open = false
  ledgerDialog.open = false
}

function flash(message: string, tone: 'ok' | 'warn' | 'error' = 'ok') {
  notice.value = message
  noticeTone.value = tone === 'ok' ? 'ok-text' : tone === 'warn' ? 'warn-text' : 'error-text'
  if (tone !== 'error') {
    errorMessage.value = ''
  }
}

function openAmount(action: '记录消耗' | '完成补油', row: Row) {
  notice.value = ''
  errorMessage.value = ''
  amountDialog.open = true
  amountDialog.action = action
  amountDialog.row = row
  amountDialog.amount = ''
  amountDialog.date = today()
  // 凭证在弹窗打开时生成：同一张表单无论点几次确认，后端都只认一笔。
  amountDialog.token = newToken()
}

async function runSimpleAction(action: '申请补油', row: Row) {
  notice.value = ''
  errorMessage.value = ''
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '油料管理动作未生效，请稍后重试')
    }
    flash(payload.message as string)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '油料管理操作失败'
  } finally {
    submitting.value = false
  }
}

async function submitAmount() {
  if (!amountDialog.row) {
    return
  }
  const amount = Number(amountDialog.amount)
  if (!Number.isFinite(amount) || amount <= 0) {
    errorMessage.value = '数量必须是大于 0 的数字'
    return
  }
  submitting.value = true
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${amountDialog.row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          action: amountDialog.action,
          amount,
          date: amountDialog.date,
          token: amountDialog.token,
        },
      }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '油料管理动作未生效，请稍后重试')
    }
    flash(payload.message as string)
    amountDialog.open = false
    await reload()
  } catch (error) {
    // 业务失败（如超存量）不关闭弹窗，修正数量后可用同一笔表单重提
    errorMessage.value = error instanceof Error ? error.message : '油料管理操作失败'
  } finally {
    submitting.value = false
  }
}

async function openLedger(row: Row) {
  notice.value = ''
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('油料记录明细读取失败')
    }
    const detail = (await response.json()) as Row & { 台账?: LedgerEvent[] }
    ledgerDialog.row = detail
    ledgerEvents.value = detail.台账 ?? []
    ledgerDialog.open = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '油料记录明细读取失败'
  }
}

async function editResupply(event: LedgerEvent) {
  if (!ledgerDialog.row) {
    return
  }
  const input = window.prompt(`将第 ${event.序号} 笔补油调运量由 ${event.数量} 调整为：`, String(event.数量))
  if (input === null) {
    return
  }
  const amount = Number(input)
  if (!Number.isFinite(amount) || amount <= 0) {
    errorMessage.value = '补油调运量必须是大于 0 的数字'
    return
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/${ledgerDialog.row.id}/ledger/${event.序号}`, {
      method: 'PUT',
      body: JSON.stringify({ values: { amount } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message ?? '补油口径调整未生效')
    }
    flash(payload.message as string)
    ledgerDialog.row = payload.entry as Row
    ledgerEvents.value = (payload.entry as { 台账?: LedgerEvent[] }).台账 ?? []
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补油口径调整失败'
  } finally {
    submitting.value = false
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) {
    query.set('keyword', keyword.value.trim())
  }
  if (statusFilter.value) {
    query.set('status', statusFilter.value)
  }
  try {
    const [listResponse, statsResponse] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/stats`),
    ])
    if (!listResponse.ok) {
      throw new Error('油料记录列表读取失败')
    }
    const payload = await listResponse.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (statsResponse.ok) {
      const statPayload = (await statsResponse.json()) as Record<string, number>
      stats.value.forEach((card) => {
        card.value = statPayload[card.status] ?? 0
      })
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '油料管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.ok-text {
  color: #067647;
}
.warn-text {
  color: #b54708;
}
.muted-text {
  color: var(--muted);
}
.stat-card.clickable {
  cursor: pointer;
}
.link:disabled {
  color: var(--muted);
  cursor: not-allowed;
}
.filter-item select {
  padding: 4px 6px;
  border: 1px solid var(--border);
  border-radius: 6px;
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
.modal {
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  width: 380px;
  max-width: calc(100vw - 32px);
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.18);
}
.modal-wide {
  width: 760px;
  max-height: 80vh;
  overflow: auto;
}
.modal h3 {
  margin: 0 0 6px;
  font-size: 16px;
}
.modal-tip {
  margin: 0 0 12px;
  font-size: 12px;
  color: var(--muted);
}
.modal-field {
  display: block;
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--muted);
}
.modal-field input {
  display: block;
  width: 100%;
  margin-top: 4px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
</style>
