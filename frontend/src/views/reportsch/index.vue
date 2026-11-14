<template>
  <section class="page" data-module="reportsch">
    <header class="page-head">
      <div>
        <h2>报表调度管理</h2>
        <p class="page-desc">
          管理周期性报表的生成和发送调度。确认排期后会在同一事务内登记不可变报表产物，
          记录数据日期偏移、指标、返回字段与产物摘要；失败/中断排期只留痕，不会变成已发布服务。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出报表调度清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
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
          <th>状态</th>
          <th>最新产物</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span :class="row.abnormal ? 'badge bad' : row.status === '已排期' ? 'badge ok' : 'badge'">
              {{ row.status }}
            </span>
          </td>
          <td>
            <button v-if="row['最新产物编号']" class="link" type="button" @click="openArtifacts(row)">
              {{ row['最新产物编号'] }}
            </button>
            <span v-else class="empty-state">暂无产物</span>
          </td>
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
          <td :colspan="columns.length + 3" class="empty-state">暂无报表调度数据</td>
        </tr>
      </tbody>
    </table>

    <div v-if="scheduleTarget" class="detail-panel">
      <h3>确认排期：{{ scheduleTarget['任务编号'] }}</h3>
      <form class="filter-bar" @submit.prevent="confirmSchedule">
        <label class="filter-item">
          <span>排期日期（默认今天）</span>
          <input v-model="scheduleForm.schedule_date" type="date" />
        </label>
        <label class="filter-item">
          <span>执行结果</span>
          <select v-model="scheduleForm.result">
            <option value="成功">成功</option>
            <option value="失败">失败</option>
            <option value="中断">中断</option>
          </select>
        </label>
        <label class="filter-item" v-if="scheduleForm.result !== '成功'">
          <span>失败/中断原因</span>
          <input v-model="scheduleForm.reason" placeholder="如：上游分区未就绪" />
        </label>
        <button class="btn primary" type="submit">提交排期</button>
        <button class="btn ghost" type="button" @click="scheduleTarget = null">取消</button>
      </form>
    </div>

    <div v-if="artifactRows.length" class="detail-panel">
      <h3>「{{ artifactTaskCode }}」的排期产物（不可变）</h3>
      <table class="data-table">
        <thead>
          <tr><th>产物编号</th><th>版本</th><th>数据日期</th><th>指标</th><th>产物摘要</th><th>状态</th><th>原因</th></tr>
        </thead>
        <tbody>
          <tr v-for="art in artifactRows" :key="String(art.id)">
            <td>{{ art['产物编号'] }}</td>
            <td>v{{ art['排期版本号'] }}</td>
            <td>{{ art['数据日期'] }}</td>
            <td>{{ toList(art['包含指标']).join('、') }}</td>
            <td>{{ art['产物摘要'] }}</td>
            <td><span :class="art['状态'] === '已登记' ? 'badge ok' : 'badge bad'">{{ art['状态'] }}</span></td>
            <td>{{ art['失败原因'] || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p style="margin-top:8px">
        <button class="btn ghost" type="button" @click="artifactRows = []">关闭产物列表</button>
      </p>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条报表调度记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="infoMessage" class="success-text">{{ infoMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | string[] | null>

const ENDPOINT = '/api/reportsch'
const columns = ['任务编号', '报表名称', '包含指标', '输出格式', '调度cron', '收件人列表', '数据日期偏移', '重试次数上限']
const actions = ['提交调度评审', '确认排期', '暂停调度']
const stats = ref([{ label: '报表任务总数', value: 0 }, { label: '已排期任务', value: 0 }, { label: '异常任务', value: 0 }])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const scheduleTarget = ref<Row | null>(null)
const scheduleForm = ref({ schedule_date: '', result: '成功', reason: '' })
const artifactRows = ref<Row[]>([])
const artifactTaskCode = ref('')

function toList(value: unknown): string[] {
  if (Array.isArray(value)) return value as string[]
  return value ? String(value).split(/[;,；]/).map((s) => s.trim()).filter(Boolean) : []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function openArtifacts(row: Row) {
  artifactTaskCode.value = String(row['任务编号'])
  const response = await request(`${ENDPOINT}/../report-artifacts/by-task/${row.id}`)
  if (response.ok) {
    const payload = await response.json()
    artifactRows.value = payload.items ?? []
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  infoMessage.value = ''
  if (action === '确认排期') {
    scheduleTarget.value = row
    scheduleForm.value = { schedule_date: '', result: '成功', reason: '' }
    return
  }
  await postAction(row, { action })
}

async function confirmSchedule() {
  if (!scheduleTarget.value) return
  if (scheduleForm.value.result !== '成功' && !scheduleForm.value.reason.trim()) {
    errorMessage.value = '失败或中断排期必须填写原因，保证异常产物可解释'
    return
  }
  const values: Record<string, string> = { action: '确认排期', result: scheduleForm.value.result }
  if (scheduleForm.value.schedule_date) values.schedule_date = scheduleForm.value.schedule_date
  if (scheduleForm.value.reason) values.reason = scheduleForm.value.reason
  const row = scheduleTarget.value
  scheduleTarget.value = null
  await postAction(row, values)
}

async function postAction(row: Row, values: Record<string, string>) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify(values),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '报表调度动作未生效，请稍后重试')
    }
    infoMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报表调度操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('报表任务列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = [
      { label: '报表任务总数', value: total.value },
      { label: '已排期任务', value: rows.value.filter((r) => r.status === '已排期').length },
      { label: '异常任务', value: rows.value.filter((r) => r.abnormal).length },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报表调度列表读取失败'
  }
}

onMounted(reload)
</script>
