<template>
  <section class="page" data-module="auditlog">
    <header class="page-head">
      <div>
        <h2>发布审计</h2>
        <p class="page-desc">
          只追加的审计日志：同步记录报表排期产物登记、数据服务发布与联动回滚，
          可按任务编号或服务编号回放完整交付轨迹。
        </p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>关联编号/动作/对象</span>
        <input v-model="keyword" placeholder="如 DELI-0003、REPO-0003、发布服务" />
      </label>
      <label class="filter-item">
        <span>结果</span>
        <select v-model="result">
          <option value="">全部</option>
          <option v-for="r in resultOptions" :key="r" :value="r">{{ r }}</option>
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
          <td>{{ row['记录时间'] ?? '—' }}</td>
          <td>{{ row['动作类型'] ?? '—' }}</td>
          <td>{{ row['操作对象'] ?? '—' }}</td>
          <td>{{ row['关联编号'] ?? '—' }}</td>
          <td>{{ row['产物编号'] || '—' }}</td>
          <td>{{ row['服务版本号'] || '—' }}</td>
          <td><span :class="resultClass(row['结果'])">{{ row['结果'] ?? '—' }}</span></td>
          <td>{{ row['说明'] ?? '—' }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length" class="empty-state">暂无审计记录，完成排期或发布后将自动留痕</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条审计记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/audit-logs'
const columns = ['记录时间', '动作类型', '操作对象', '关联编号', '产物编号', '服务版本号', '结果', '说明']
const resultOptions = ['成功', '已回滚', '生成失败', '已中断']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const keyword = ref('')
const result = ref('')

function resultClass(r: unknown): string {
  if (r === '成功') return 'badge ok'
  if (r === '已回滚' || r === '生成失败') return 'badge bad'
  return 'badge warn'
}

function resetFilters() {
  keyword.value = ''
  result.value = ''
  void reload()
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value) query.set('keyword', keyword.value)
  if (result.value) query.set('result', result.value)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) throw new Error('审计日志读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '审计日志读取失败'
  }
}

onMounted(reload)
</script>
