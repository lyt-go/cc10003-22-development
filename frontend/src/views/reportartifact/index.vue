<template>
  <section class="page" data-module="reportartifact">
    <header class="page-head">
      <div>
        <h2>报表产物登记</h2>
        <p class="page-desc">
          每次确认排期后自动登记不可变产物：数据日期偏移、实际数据日期、包含指标、返回字段与产物摘要。
          失败与中断排期同样留痕，但不可用于服务发布。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="exportRows">导出产物清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>产物/任务编号</span>
        <input v-model="keyword" placeholder="按产物编号或任务编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['产物编号'] ?? '—' }}</td>
          <td>{{ row['任务编号'] ?? '—' }}</td>
          <td>v{{ row['排期版本号'] ?? '—' }}</td>
          <td>{{ row['排期日期'] ?? '—' }}</td>
          <td>{{ row['数据日期偏移'] ?? '—' }}</td>
          <td>{{ row['数据日期'] ?? '—' }}</td>
          <td>
            <div class="field-tags">
              <span v-for="m in toList(row['包含指标'])" :key="m" class="field-tag">{{ m }}</span>
            </div>
          </td>
          <td>
            <div class="field-tags">
              <span v-for="f in toList(row['返回字段'])" :key="f" class="field-tag">{{ f }}</span>
            </div>
          </td>
          <td>{{ row['产物摘要'] ?? '—' }}</td>
          <td><span :class="statusClass(row['状态'])">{{ row['状态'] ?? '—' }}</span></td>
          <td>
            <button class="link" type="button" @click="showDetail(row)">查看</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">
            暂无报表产物，请先在「报表调度」对任务执行确认排期
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="selected" class="detail-panel">
      <h3>产物明细：{{ selected['产物编号'] }}（不可变）</h3>
      <dl class="bind-box" style="display: grid">
        <dt>失败/中断原因</dt>
        <dd>{{ selected['失败原因'] || '—' }}</dd>
        <dt>结果指纹</dt>
        <dd>{{ selected['结果指纹'] }}</dd>
        <dt>登记时间</dt>
        <dd>{{ selected['登记时间'] }}</dd>
        <dt>备注</dt>
        <dd>{{ selected['备注'] || '—' }}</dd>
      </dl>
      <p v-if="selected['状态'] !== '已登记'" class="notice warn">
        该产物为异常排期产物（{{ selected['状态'] }}），不能绑定发布为数据服务；重试排期只会补充缺失版本。
      </p>
      <button class="btn ghost" type="button" @click="selected = null">关闭明细</button>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条产物记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | string[] | null>

const ENDPOINT = '/api/report-artifacts'
const columns = ['产物编号', '任务编号', '排期版本号', '排期日期', '数据日期偏移', '数据日期', '包含指标', '返回字段', '产物摘要', '状态']
const statuses = ['已登记', '生成失败', '已中断']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const status = ref('')
const selected = ref<Row | null>(null)

const stats = computed(() => [
  { label: '产物总数', value: total.value },
  { label: '已登记可用', value: rows.value.filter((r) => r['状态'] === '已登记').length },
  { label: '失败/中断', value: rows.value.filter((r) => r['状态'] !== '已登记').length },
])

function toList(value: unknown): string[] {
  if (Array.isArray(value)) return value as string[]
  return value ? String(value).split(/[;,；]/).map((s) => s.trim()).filter(Boolean) : []
}

function statusClass(s: unknown): string {
  if (s === '已登记') return 'badge ok'
  if (s === '生成失败') return 'badge bad'
  return 'badge warn'
}

function resetFilters() {
  keyword.value = ''
  status.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function showDetail(row: Row) {
  selected.value = row
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (status.value) query.set('status', status.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('报表产物列表读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '报表产物列表读取失败'
  }
}

onMounted(reload)
</script>
