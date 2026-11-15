<template>
  <section class="page" data-module="market">
    <header class="page-head">
      <div>
        <h2>产品市场分发管理</h2>
        <p class="page-desc">维护市场商品的定价方案、试用配置与描述信息；上架前校验所属产品可分发状态，上架即固化试用配置快照。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记市场商品</button>
        <button class="btn" type="button" @click="exportRows">导出产品市场分发清单</button>
      </div>
    </header>

    <div v-if="readonly" class="readonly-banner">
      当前操作单位「{{ session.operatorUnit }}」与商品归属单位不一致，市场商品为只读：登记、编辑与上架/下架/删除都会被后端拒绝。
    </div>

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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '商品编号'" class="link" type="button" @click="openDetail(row)">{{ row[column] ?? '—' }}</button>
            <span v-else-if="column === '商品状态'">
              <span class="tag" :class="statusTagClass(row.status)">{{ row[column] ?? '—' }}</span>
            </span>
            <span v-else>{{ row[column] ?? '—' }}</span>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button v-if="!readonly" class="link" type="button" @click="openEdit(row)">编辑</button>
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
            <span v-if="readonly" class="page-desc">只读</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无产品市场分发数据，可先登记市场商品</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条产品市场分发记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>

    <!-- 登记 / 编辑表单 -->
    <div v-if="formVisible" class="modal-mask" @click.self="closeForm">
      <div class="modal-card">
        <h3 class="modal-title">{{ formMode === 'create' ? '登记市场商品' : `编辑市场商品 ${formModel.商品编号 ?? ''}` }}</h3>
        <form class="form-grid" @submit.prevent="submitForm">
          <label>
            商品编号
            <input v-model="formModel.商品编号" :disabled="formMode === 'edit'" placeholder="如 MKT-0010" required />
          </label>
          <label>
            商品名称
            <input v-model="formModel.商品名称" required />
          </label>
          <label>
            所属产品（产品编号）
            <input v-model="formModel.所属产品" placeholder="如 PROD-0002" required />
          </label>
          <label>
            定价方案
            <input v-model="formModel.定价方案" placeholder="如 99 元/月" :disabled="trialLocked" />
          </label>
          <label>
            试用天数
            <input v-model.number="formModel.试用天数" type="number" min="0" :disabled="trialLocked" />
          </label>
          <label>
            上线时间
            <input v-model="formModel.上线时间" type="date" :disabled="trialLocked" />
          </label>
          <label class="full">
            封面描述
            <textarea v-model="formModel.封面描述" rows="2"></textarea>
          </label>
          <label v-if="formMode === 'create'" class="full">
            商品归属
            <input :value="session.operatorUnit" disabled />
          </label>
          <p v-if="trialLocked" class="full page-desc">
            共享试用配置（定价方案、试用天数、上线时间）仅登记人「{{ formModel.登记人 }}」可修改，当前操作人无权改动。
          </p>
          <p v-if="formError" class="full error-text">{{ formError }}</p>
          <div class="modal-actions full">
            <button class="btn ghost" type="button" @click="closeForm">取消</button>
            <button class="btn primary" type="submit">保存</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 详情抽屉：完整回显 + 试用配置快照 -->
    <div v-if="detailVisible" class="modal-mask" @click.self="closeDetail">
      <div class="modal-card">
        <h3 class="modal-title">市场商品详情 · {{ detail?.商品编号 }}</h3>
        <dl v-if="detail" class="detail-list">
          <dt>商品名称</dt><dd>{{ detail.商品名称 ?? '—' }}</dd>
          <dt>所属产品</dt><dd>{{ detail.所属产品 ?? '—' }}</dd>
          <dt>定价方案</dt><dd>{{ detail.定价方案 ?? '—' }}</dd>
          <dt>试用天数</dt><dd>{{ detail.试用天数 ?? '—' }}</dd>
          <dt>上线时间</dt><dd>{{ detail.上线时间 ?? '—' }}</dd>
          <dt>封面描述</dt><dd>{{ detail.封面描述 ?? '—' }}</dd>
          <dt>商品归属</dt><dd>{{ detail.商品归属 ?? '—' }}</dd>
          <dt>登记人</dt><dd>{{ detail.登记人 ?? '—' }}</dd>
          <dt>商品状态</dt><dd><span class="tag" :class="statusTagClass(detail.status)">{{ detail.商品状态 ?? detail.status }}</span></dd>
        </dl>
        <div class="snapshot-box">
          <strong>试用配置快照</strong>
          <p v-if="!detail?.试用配置快照" class="page-desc">草稿商品尚未上架，暂无快照；上架成功时会固化当前完整试用配置。</p>
          <pre v-else>{{ JSON.stringify(detail.试用配置快照, null, 2) }}</pre>
        </div>
        <div v-if="detail?.状态变更记录?.length" class="snapshot-box">
          <strong>状态变更记录</strong>
          <pre>{{ JSON.stringify(detail.状态变更记录, null, 2) }}</pre>
        </div>
        <div class="modal-actions">
          <button class="btn" type="button" @click="closeDetail">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { postJson, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>

const ENDPOINT = '/api/market'
const columns = ['商品编号', '商品名称', '所属产品', '定价方案', '试用天数', '封面描述', '上线时间', '商品归属', '商品状态']
const filterFields = columns.slice(0, 3)
const ACTION_BY_STATUS: Record<string, string[]> = {
  草稿: ['上架商品'],
  已上架: ['下架商品'],
  已下架: ['删除商品'],
  已删除: [],
}

const session = useSessionStore()
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})

const stats = computed(() => [
  { label: '市场商品总数', value: total.value },
  { label: '已上架商品', value: rows.value.filter((r) => r.status === '已上架').length },
  { label: '已下架商品', value: rows.value.filter((r) => r.status === '已下架').length },
])
// 归属单位统一为华东渠道组（种子数据口径）；当前单位不一致即只读。
const readonly = computed(() => session.operatorUnit !== '华东渠道组')

const formVisible = ref(false)
const formMode = ref<'create' | 'edit'>('create')
const formModel = ref<Row>({})
const formError = ref('')
const editingId = ref<number | null>(null)

const detailVisible = ref(false)
const detail = ref<Row | null>(null)

const trialLocked = computed(() =>
  formMode.value === 'edit'
  && String(formModel.value.登记人 ?? '') !== ''
  && String(formModel.value.登记人) !== session.operator,
)

function statusTagClass(status: unknown): string {
  if (status === '草稿') return 'draft'
  if (status === '已上架') return 'on'
  if (status === '已下架') return 'off'
  return 'deleted'
}

function availableActions(row: Row): string[] {
  if (readonly.value) return []
  return ACTION_BY_STATUS[String(row.status)] ?? []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  if (readonly.value) {
    errorMessage.value = '当前操作单位为只读，不能登记市场商品'
    return
  }
  formMode.value = 'create'
  formModel.value = {
    商品编号: '', 商品名称: '', 所属产品: '', 定价方案: '', 试用天数: null,
    上线时间: '', 封面描述: '',
  }
  formError.value = ''
  formVisible.value = true
}

function openEdit(row: Row) {
  formMode.value = 'edit'
  editingId.value = Number(row.id)
  formModel.value = { ...row }
  formError.value = ''
  formVisible.value = true
}

function closeForm() {
  formVisible.value = false
  editingId.value = null
}

async function submitForm() {
  formError.value = ''
  try {
    const values = { ...formModel.value }
    const path = formMode.value === 'create' ? ENDPOINT : `${ENDPOINT}/${editingId.value}`
    const result = await postJson<Row>(path, { values }, formMode.value === 'create' ? 'POST' : 'PUT')
    if (!result.ok) {
      formError.value = result.message
      return
    }
    successMessage.value = result.message
    formVisible.value = false
    await reload()
  } catch (error) {
    formError.value = error instanceof Error ? error.message : '保存失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('商品详情读取失败')
    detail.value = (await response.json()) as Row
    detailVisible.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '商品详情读取失败'
  }
}

function closeDetail() {
  detailVisible.value = false
  detail.value = null
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''
  try {
    const result = await postJson<Row>(`${ENDPOINT}/${row.id}/actions`, { values: { action } })
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    successMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '产品市场分发操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('市场商品列表读取失败')
    }
    const payload = (await response.json()) as { items?: Row[]; total?: number }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '产品市场分发列表读取失败'
  }
}

onMounted(reload)
</script>
