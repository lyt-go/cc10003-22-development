<template>
  <section class="page" data-module="delivery">
    <header class="page-head">
      <div>
        <h2>数据服务管理</h2>
        <p class="page-desc">
          发布服务必须绑定一份「已登记」的报表产物，发布时冻结返回字段、数据日期与产物摘要快照；
          指标或数据日期变化只能发布新版本，旧版本可追溯但不会被自动改写。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出数据服务清单</button>
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
          <th>绑定产物 / 数据日期</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <div v-if="column === '返回字段'" class="field-tags">
              <span v-for="f in toList(row[column])" :key="f" class="field-tag">{{ f }}</span>
              <span v-if="!toList(row[column]).length">—</span>
            </div>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td>
            <span :class="row.abnormal ? 'badge bad' : row.status === '已发布' ? 'badge ok' : 'badge'">
              {{ row.status }}
            </span>
          </td>
          <td>
            <template v-if="row['绑定产物编号']">
              <div><strong>{{ row['绑定产物编号'] }}</strong>（{{ row['绑定排期版本号'] }}）</div>
              <div class="page-desc">数据日期：{{ row['绑定数据日期'] }}</div>
            </template>
            <span v-else class="empty-state">未绑定产物，不可发布</span>
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
            <button class="link" type="button" @click="openTrace(row)">追溯链路</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无数据服务数据</td>
        </tr>
      </tbody>
    </table>

    <div v-if="publishTarget" class="detail-panel">
      <h3>发布服务：{{ publishTarget['服务编号'] }}</h3>
      <p class="notice info">
        发布将与产物绑定在同一事务内提交，失败时服务状态与产物绑定两侧同时退回。
        异常（失败/中断）产物不可选。
      </p>
      <form class="filter-bar" @submit.prevent="confirmPublish">
        <label class="filter-item">
          <span>选择报表产物</span>
          <select v-model="artifactCode">
            <option value="">请选择已登记产物</option>
            <option v-for="art in availableArtifacts" :key="String(art.id)" :value="art['产物编号']">
              {{ art['产物编号'] }}｜{{ art['任务编号'] }}｜{{ art['数据日期'] }}｜{{ art['产物摘要'] }}
            </option>
          </select>
        </label>
        <button class="btn primary" type="submit" :disabled="!artifactCode">确认发布</button>
        <button class="btn ghost" type="button" @click="publishTarget = null">取消</button>
      </form>
      <p v-if="!availableArtifacts.length" class="notice warn">暂无「已登记」产物，请先到报表调度完成一次成功排期。</p>
    </div>

    <div v-if="trace" class="detail-panel">
      <h3>交付链路追溯：{{ trace['服务版本']['服务编号'] }}</h3>
      <p :class="trace['可追溯'] ? 'notice info' : 'notice warn'">{{ trace['说明'] }}</p>
      <template v-if="trace['可追溯']">
        <dl class="bind-box">
          <dt>服务版本号</dt><dd>{{ trace['服务版本']['版本号'] || '—' }}（状态：{{ trace['服务版本']['状态'] }}）</dd>
          <dt>返回字段</dt>
          <dd>
            <div class="field-tags">
              <span v-for="f in toList(trace['服务版本']['返回字段'])" :key="f" class="field-tag">{{ f }}</span>
            </div>
          </dd>
          <dt>报表任务</dt><dd>{{ trace['报表任务']!['任务编号'] }}｜{{ trace['报表任务']!['报表名称'] }}（{{ trace['报表任务']!['status'] }}）</dd>
          <dt>产物编号</dt><dd>{{ trace['绑定产物']!['产物编号'] }}（排期 v{{ trace['绑定产物']!['排期版本号'] }}）</dd>
          <dt>数据日期</dt><dd>{{ trace['绑定产物']!['数据日期'] }}（偏移 {{ trace['绑定产物']!['数据日期偏移'] || '—' }}）</dd>
          <dt>产物摘要</dt><dd>{{ trace['绑定产物']!['产物摘要'] }}</dd>
        </dl>
      </template>
      <h3 v-if="trace['审计记录'].length">审计记录</h3>
      <table v-if="trace['审计记录'].length" class="data-table">
        <thead><tr><th>时间</th><th>动作</th><th>结果</th><th>说明</th></tr></thead>
        <tbody>
          <tr v-for="log in trace['审计记录']" :key="String(log.id)">
            <td>{{ log['记录时间'] }}</td>
            <td>{{ log['动作类型'] }}</td>
            <td><span :class="log['结果'] === '成功' ? 'badge ok' : log['结果'] === '已回滚' ? 'badge bad' : 'badge warn'">{{ log['结果'] }}</span></td>
            <td>{{ log['说明'] }}</td>
          </tr>
        </tbody>
      </table>
      <p v-if="!trace['审计记录'].length" class="empty-state">该服务暂无审计记录</p>
      <p style="margin-top:8px"><button class="btn ghost" type="button" @click="trace = null">关闭追溯</button></p>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条数据服务记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="infoMessage" class="success-text">{{ infoMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | string[] | null>

interface TraceData {
  服务版本: Row
  绑定产物: Row | null
  报表任务: Row | null
  审计记录: Row[]
  可追溯: boolean
  说明: string
}

const ENDPOINT = '/api/delivery'
const columns = ['服务编号', '数据集名称', '查询参数定义', '返回字段', '速率限制', '分页最大条数', '版本号', '消费方应用']
const actions = ['提交服务评审', '发布服务', '下线服务']
const stats = ref([{ label: '服务版本总数', value: 0 }, { label: '已发布服务', value: 0 }, { label: '未绑定产物', value: 0 }])

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const publishTarget = ref<Row | null>(null)
const artifactCode = ref('')
const availableArtifacts = ref<Row[]>([])
const trace = ref<TraceData | null>(null)

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

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  infoMessage.value = ''
  if (action === '发布服务') {
    publishTarget.value = row
    artifactCode.value = String(row['绑定产物编号'] ?? '')
    const response = await request('/api/report-artifacts?status=已登记&size=200')
    if (response.ok) {
      const payload = await response.json()
      availableArtifacts.value = payload.items ?? []
    }
    return
  }
  await postAction(row, { action })
}

async function confirmPublish() {
  if (!publishTarget.value || !artifactCode.value) return
  const row = publishTarget.value
  publishTarget.value = null
  await postAction(row, { action: '发布服务', artifact_code: artifactCode.value })
}

async function openTrace(row: Row) {
  errorMessage.value = ''
  const response = await request(`${ENDPOINT}/${row.id}/trace`)
  if (!response.ok) {
    errorMessage.value = '追溯链路读取失败'
    return
  }
  trace.value = await response.json()
}

async function postAction(row: Row, values: Record<string, string>) {
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify(values),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || '数据服务动作未生效，请稍后重试')
    }
    infoMessage.value = payload.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据服务操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('服务版本列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = [
      { label: '服务版本总数', value: total.value },
      { label: '已发布服务', value: rows.value.filter((r) => r.status === '已发布').length },
      { label: '未绑定产物', value: rows.value.filter((r) => !r['绑定产物编号']).length },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据服务列表读取失败'
  }
}

onMounted(reload)
</script>
