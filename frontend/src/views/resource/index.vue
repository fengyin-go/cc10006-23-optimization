<template>
  <section class="page" data-module="resource">
    <header class="page-head">
      <div>
        <h2>资源计量管理</h2>
        <p class="page-desc">跨引擎计量视图按计算引擎、作业与计费周期汇总 CPU 核秒、内存 GB 秒与扫描数据量；同一记录只计一次，结算后金额冻结，视图筛选与导出保持同一口径。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="showCreate = !showCreate">登记计量记录</button>
        <button class="btn" type="button" @click="exportView">导出当前视图</button>
      </div>
    </header>

    <form v-if="showCreate" class="panel" @submit.prevent="createEntry">
      <h3 class="panel-title">登记计量记录</h3>
      <div class="form-grid">
        <label v-for="field in createFields" :key="field.key" class="filter-item">
          <span>{{ field.label }}</span>
          <select v-if="field.key === '计算引擎'" v-model="createForm[field.key]">
            <option value="">请选择引擎</option>
            <option v-for="engine in engines" :key="engine" :value="engine">{{ engine }}</option>
          </select>
          <input v-else-if="field.key === '计费周期'" v-model="createForm[field.key]" type="month" />
          <input v-else v-model="createForm[field.key]" :placeholder="`请输入${field.label}`" />
        </label>
      </div>
      <div class="form-actions">
        <button class="btn primary" type="submit">提交登记</button>
        <button class="btn ghost" type="button" @click="showCreate = false">取消</button>
      </div>
    </form>

    <section class="panel">
      <h3 class="panel-title">跨引擎计量视图</h3>
      <form class="filter-bar" @submit.prevent="loadView">
        <label class="filter-item">
          <span>计算引擎</span>
          <select v-model="viewFilters.engine">
            <option value="">全部引擎</option>
            <option v-for="engine in engines" :key="engine" :value="engine">{{ engine }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>作业名称</span>
          <input v-model="viewFilters.job" placeholder="按作业名称检索" />
        </label>
        <label class="filter-item">
          <span>计费周期起</span>
          <input v-model="viewFilters.periodStart" type="month" />
        </label>
        <label class="filter-item">
          <span>计费周期止</span>
          <input v-model="viewFilters.periodEnd" type="month" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetViewFilters">重置条件</button>
      </form>

      <div class="stat-row">
        <article v-for="item in viewStats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th>计算引擎</th>
            <th>计费周期</th>
            <th>作业名称</th>
            <th>CPU核秒</th>
            <th>内存GB秒</th>
            <th>存储占用GB</th>
            <th>扫描数据量GB</th>
            <th>记录数</th>
            <th>待汇总</th>
            <th>已结算</th>
            <th>异常</th>
            <th>金额(元)</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="group in view.groups" :key="`${group.计算引擎}-${group.计费周期}`">
            <tr class="group-row">
              <td>{{ group.计算引擎 }}</td>
              <td>{{ group.计费周期 }}</td>
              <td>全部作业</td>
              <td>{{ fmt(group.CPU核秒) }}</td>
              <td>{{ fmt(group.内存GB秒) }}</td>
              <td>{{ fmt(group.存储占用GB) }}</td>
              <td>{{ fmt(group.扫描数据量) }}</td>
              <td>{{ group.记录数 }}</td>
              <td><span class="badge warn">{{ group.待汇总数 }}</span></td>
              <td><span class="badge ok">{{ group.已结算数 }}</span></td>
              <td><span class="badge bad">{{ group.异常数 }}</span></td>
              <td>{{ fmt(group.金额合计) }}</td>
            </tr>
            <tr
              v-for="jobRow in group.jobs"
              :key="`${group.计算引擎}-${group.计费周期}-${jobRow.作业名称}`"
              class="sub-row"
            >
              <td></td>
              <td></td>
              <td>{{ jobRow.作业名称 }}</td>
              <td>{{ fmt(jobRow.CPU核秒) }}</td>
              <td>{{ fmt(jobRow.内存GB秒) }}</td>
              <td>{{ fmt(jobRow.存储占用GB) }}</td>
              <td>{{ fmt(jobRow.扫描数据量) }}</td>
              <td>{{ jobRow.记录数 }}</td>
              <td>{{ jobRow.待汇总数 }}</td>
              <td>{{ jobRow.已结算数 }}</td>
              <td>{{ jobRow.异常数 }}</td>
              <td>{{ fmt(jobRow.金额合计) }}</td>
            </tr>
          </template>
          <tr v-if="!view.groups.length">
            <td colspan="12" class="empty-state">当前筛选条件下暂无计量数据</td>
          </tr>
        </tbody>
      </table>
      <footer class="page-foot">
        <span>
          重复上报已剔除 {{ view.totals.重复剔除数 ?? 0 }} 条；金额口径：CPU核秒×{{ view.prices.CPU核秒 }} +
          内存GB秒×{{ view.prices.内存GB秒 }} + 扫描GB×{{ view.prices.扫描数据量 }} + 存储GB×{{ view.prices.存储占用GB }}（元）
        </span>
        <span v-if="viewError" class="error-text">{{ viewError }}</span>
      </footer>
    </section>

    <section class="panel">
      <h3 class="panel-title">计量明细</h3>
      <form class="filter-bar" @submit.prevent="reload">
        <label class="filter-item">
          <span>记录编号</span>
          <input v-model="listFilters.keyword" placeholder="按记录编号检索" />
        </label>
        <label class="filter-item">
          <span>状态</span>
          <select v-model="listFilters.status">
            <option value="">全部状态</option>
            <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>计算引擎</span>
          <select v-model="listFilters.engine">
            <option value="">全部引擎</option>
            <option v-for="engine in engines" :key="engine" :value="engine">{{ engine }}</option>
          </select>
        </label>
        <label class="filter-item">
          <span>计费周期</span>
          <input v-model="listFilters.period" type="month" />
        </label>
        <button class="btn" type="submit">查询</button>
        <button class="btn ghost" type="button" @click="resetListFilters">重置条件</button>
        <button class="btn ghost" type="button" @click="exportRows">导出明细清单</button>
      </form>

      <div class="batch-bar">
        <span>已选 {{ selectedIds.length }} 条</span>
        <button class="btn" type="button" :disabled="!selectedIds.length" @click="batchAction('提交汇总')">提交汇总</button>
        <button class="btn" type="button" :disabled="!selectedIds.length" @click="batchAction('结算确认')">结算确认</button>
        <label class="filter-item inline">
          <span>目标计费周期</span>
          <input v-model="batchPeriod" type="month" />
        </label>
        <button class="btn" type="button" :disabled="!selectedIds.length || !batchPeriod" @click="batchAction('归入计费周期')">归入计费周期</button>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th><input type="checkbox" :checked="allChecked" @change="toggleAll" /></th>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>状态</th>
            <th>结算金额(元)</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)">
            <td><input v-model="selectedIds" type="checkbox" :value="Number(row.id)" /></td>
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td><span class="badge" :class="statusClass(String(row.status ?? ''))">{{ row.status ?? '—' }}</span></td>
            <td>{{ row.结算金额 != null ? `${fmt(row.结算金额)}${row.金额冻结 ? '（已冻结）' : ''}` : '—' }}</td>
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
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 3" class="empty-state">暂无资源计量数据，可先登记计量记录</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ total }} 条资源计量记录</span>
        <span v-if="message" class="ok-text">{{ message }}</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type Bucket = Record<string, string | number> & { jobs?: Bucket[] }

interface ViewData {
  filters: Record<string, string>
  prices: Record<string, number>
  groups: Bucket[]
  totals: Bucket
}

const ENDPOINT = '/api/resource'
const columns = ["记录编号", "计算引擎", "作业名称", "CPU核秒", "内存GB秒", "存储占用GB", "扫描数据量", "计费周期"]
const actions = ["提交汇总", "结算确认", "归档记录"]
const statuses = ["草稿", "待汇总", "已结算", "已归档"]
const engines = ["Spark", "Flink", "Hive"]
const createFields = [
  { key: '记录编号', label: '记录编号' },
  { key: '计算引擎', label: '计算引擎' },
  { key: '作业名称', label: '作业名称' },
  { key: 'CPU核秒', label: 'CPU核秒' },
  { key: '内存GB秒', label: '内存GB秒' },
  { key: '存储占用GB', label: '存储占用GB' },
  { key: '扫描数据量', label: '扫描数据量(GB)' },
  { key: '计费周期', label: '计费周期' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const message = ref('')
const errorMessage = ref('')
const viewError = ref('')
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const selectedIds = ref<number[]>([])
const batchPeriod = ref('')
const listFilters = ref({ keyword: '', status: '', engine: '', period: '' })
const viewFilters = ref({ engine: '', job: '', periodStart: '', periodEnd: '' })
const view = ref<ViewData>({ filters: {}, prices: {}, groups: [], totals: {} })

const viewStats = computed(() => {
  const totals = view.value.totals
  return [
    { label: 'CPU核秒合计', value: fmt(totals.CPU核秒) },
    { label: '内存GB秒合计', value: fmt(totals.内存GB秒) },
    { label: '扫描数据量GB', value: fmt(totals.扫描数据量) },
    { label: '存储占用GB', value: fmt(totals.存储占用GB) },
    { label: '待汇总记录', value: fmt(totals.待汇总数) },
    { label: '已结算记录', value: fmt(totals.已结算数) },
    { label: '异常记录', value: fmt(totals.异常数) },
    { label: '金额合计(元)', value: fmt(totals.金额合计) },
  ]
})

const allChecked = computed(() => {
  return rows.value.length > 0 && rows.value.every((row) => selectedIds.value.includes(Number(row.id)))
})

function fmt(value: unknown): string {
  const num = Number(value)
  if (!Number.isFinite(num)) return '0'
  return num.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function statusClass(status: string): string {
  if (status === '已结算') return 'ok'
  if (status === '待汇总') return 'warn'
  if (status === '已归档') return 'bad'
  return ''
}

function toggleAll() {
  selectedIds.value = allChecked.value ? [] : rows.value.map((row) => Number(row.id))
}

function viewQuery(): string {
  const params = new URLSearchParams()
  if (viewFilters.value.engine) params.set('engine', viewFilters.value.engine)
  if (viewFilters.value.job) params.set('job', viewFilters.value.job)
  if (viewFilters.value.periodStart) params.set('period_start', viewFilters.value.periodStart)
  if (viewFilters.value.periodEnd) params.set('period_end', viewFilters.value.periodEnd)
  return params.toString()
}

function listQuery(): string {
  const params = new URLSearchParams()
  if (listFilters.value.keyword) params.set('keyword', listFilters.value.keyword)
  if (listFilters.value.status) params.set('status', listFilters.value.status)
  if (listFilters.value.engine) params.set('engine', listFilters.value.engine)
  if (listFilters.value.period) params.set('period', listFilters.value.period)
  return params.toString()
}

function resetViewFilters() {
  viewFilters.value = { engine: '', job: '', periodStart: '', periodEnd: '' }
  void loadView()
}

function resetListFilters() {
  listFilters.value = { keyword: '', status: '', engine: '', period: '' }
  void reload()
}

function exportView() {
  window.open(`${ENDPOINT}/metering/export?${viewQuery()}`, '_blank')
}

function exportRows() {
  window.open(`${ENDPOINT}/export?${listQuery()}`, '_blank')
}

async function readPayload(response: Response): Promise<Record<string, unknown>> {
  try {
    return (await response.json()) as Record<string, unknown>
  } catch {
    return {}
  }
}

async function loadView() {
  viewError.value = ''
  try {
    const response = await request(`${ENDPOINT}/metering?${viewQuery()}`)
    if (!response.ok) {
      const body = await readPayload(response)
      throw new Error(String(body.detail ?? '计量视图读取失败'))
    }
    view.value = (await response.json()) as ViewData
  } catch (error) {
    viewError.value = error instanceof Error ? error.message : '计量视图读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}?${listQuery()}`)
    if (!response.ok) {
      throw new Error('计量记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资源计量列表读取失败'
  }
}

async function refreshAll() {
  await Promise.all([reload(), loadView()])
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await readPayload(response)
    if (!response.ok || payload.ok === false) {
      throw new Error(String(payload.message ?? payload.detail ?? '资源计量动作未生效'))
    }
    message.value = String(payload.message ?? '动作已完成')
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '资源计量操作失败'
  }
}

async function batchAction(action: string) {
  errorMessage.value = ''
  message.value = ''
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({
        values: { action, ids: selectedIds.value, 计费周期: batchPeriod.value || undefined },
      }),
    })
    const payload = await readPayload(response)
    if (!response.ok || payload.ok === false) {
      throw new Error(String(payload.message ?? payload.detail ?? '批量动作未生效'))
    }
    message.value = String(payload.message ?? '批量动作已完成')
    selectedIds.value = []
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量动作失败'
  }
}

async function createEntry() {
  errorMessage.value = ''
  message.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value } }),
    })
    const payload = await readPayload(response)
    if (!response.ok || payload.ok === false) {
      throw new Error(String(payload.message ?? payload.detail ?? '计量记录登记失败'))
    }
    message.value = String(payload.message ?? '计量记录已登记')
    showCreate.value = false
    createForm.value = {}
    await refreshAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '计量记录登记失败'
  }
}

onMounted(() => {
  void reload()
  void loadView()
})
</script>
