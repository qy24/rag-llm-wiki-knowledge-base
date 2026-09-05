<template>
  <div class="page-card">
    <div class="toolbar">
      <el-button size="small" @click="load">刷新</el-button>
      <span style="color: #909399; font-size: 12px">共 {{ total }} 条记录</span>
    </div>
    <el-table :data="items" border size="small">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="action" label="动作" width="150" />
      <el-table-column prop="query" label="客户问题" min-width="220" show-overflow-tooltip />
      <el-table-column label="回复内容" min-width="260">
        <template #default="{ row }">
          <div v-if="row.result_summary?.answer">
            <!-- 固定两行高（行高一致），超长截断 -->
            <div style="max-height:42px;overflow:hidden;line-height:21px;white-space:pre-wrap">{{ row.result_summary.answer }}</div>
            <el-button size="small" link type="primary" @click="openDetail(row)">查看全文</el-button>
          </div>
          <span v-else style="color:#c0c4cc">—</span>
        </template>
      </el-table-column>
      <el-table-column label="结果摘要" width="150">
        <template #default="{ row }">
          <el-tooltip :content="JSON.stringify(row.result_summary)" placement="top" :show-after="300">
            <span style="cursor:default">hits={{ row.result_summary?.hits ?? '-' }} · len={{ row.result_summary?.answer_len ?? '-' }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="ip" label="IP" width="110" />
      <el-table-column v-if="auth.isAdmin" label="学习标记" width="250">
        <template #default="{ row }">
          <div v-if="row.result_summary?.answer">
            <div style="margin-bottom:4px">
              <el-tag v-if="row.rating === 'good'" type="success" size="small">好·可学习</el-tag>
              <el-tag v-else-if="row.rating === 'bad'" type="danger" size="small">差·需复盘</el-tag>
              <el-tag v-else type="info" size="small">未标记</el-tag>
              <el-button size="small" type="primary" link @click="setRating(row, 'good')">👍好</el-button>
              <el-button size="small" type="danger" link @click="setRating(row, 'bad')">👎差</el-button>
              <el-button v-if="row.rating" size="small" link @click="setRating(row, '')">清除</el-button>
            </div>
            <div style="display:flex;gap:4px">
              <el-input v-model="row.note" size="small" placeholder="备注：好在哪里/错在哪" style="flex:1" />
              <el-button size="small" @click="saveNote(row)">存</el-button>
            </div>
          </div>
          <span v-else style="color:#c0c4cc">—</span>
        </template>
      </el-table-column>
      <el-table-column label="时间（北京时间）" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
    </el-table>
    <div style="margin-top: 12px; display: flex; justify-content: flex-end">
      <el-pagination
        layout="prev, pager, next"
        :total="total"
        :page-size="pageSize"
        v-model:current-page="page"
        @current-change="load"
      />
    </div>

    <!-- 详情弹窗：内容多时可上下滚动查看 -->
    <el-dialog v-model="detailVisible" title="审计详情" width="760px" :close-on-click-modal="false">
      <div v-if="detail" style="max-height:65vh;overflow-y:auto;padding-right:8px">
        <p style="margin:4px 0"><b>ID：</b>{{ detail.id }}　<b>动作：</b>{{ detail.action }}　<b>IP：</b>{{ detail.ip }}</p>
        <p style="margin:4px 0"><b>时间：</b>{{ formatTime(detail.created_at) }}</p>
        <template v-if="detail.result_summary?.key_name || detail.result_summary?.api_key_id">
          <p style="margin:4px 0"><b>密钥：</b>{{ detail.result_summary.key_name || ('#' + detail.result_summary.api_key_id) }}</p>
        </template>
        <p style="margin:8px 0 2px"><b>查询内容：</b></p>
        <div style="background:#f5f7fa;border-radius:4px;padding:8px;white-space:pre-wrap">{{ detail.query || '—' }}</div>
        <p style="margin:8px 0 2px"><b>回复内容：</b></p>
        <div style="background:#f5f7fa;border-radius:4px;padding:8px;white-space:pre-wrap">{{ detail.result_summary?.answer || '—' }}</div>
        <p style="margin:8px 0 2px"><b>备注：</b></p>
        <div style="background:#f5f7fa;border-radius:4px;padding:8px;white-space:pre-wrap">{{ detail.note || '（未填写）' }}</div>
        <p style="margin:8px 0 2px"><b>学习标记：</b>
          <el-tag v-if="detail.rating === 'good'" type="success" size="small">好·可学习</el-tag>
          <el-tag v-else-if="detail.rating === 'bad'" type="danger" size="small">差·需复盘</el-tag>
          <el-tag v-else type="info" size="small">未标记</el-tag>
        </p>
        <p style="margin:8px 0 2px"><b>结果摘要：</b></p>
        <div style="background:#f5f7fa;border-radius:4px;padding:8px;white-space:pre-wrap">{{ JSON.stringify(detail.result_summary, null, 2) }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { AuditItem } from '../api/types'

const auth = useAuthStore()

const items = ref<AuditItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50
const detailVisible = ref(false)
const detail = ref<any>(null)

function openDetail(row: any) {
  detail.value = row
  detailVisible.value = true
}

async function load() {
  const { data } = await client.get('/admin/audit', { params: { limit: pageSize, offset: (page.value - 1) * pageSize } })
  items.value = data.items
  total.value = data.total
}

async function setRating(row: any, rating: string) {
  await client.patch(`/admin/audit/${row.id}`, { rating })
  row.rating = rating
}

async function saveNote(row: any) {
  await client.patch(`/admin/audit/${row.id}`, { note: row.note || '' })
  if (row.rating === 'good') {
    // 好案例 → 自动沉淀到「自我学习」库（后端提炼中文经验后入库）
    try {
      const r = await client.post('/admin/selflearn/case', { audit_id: row.id })
      if (r.data?.skipped) {
        ElMessage.success('备注已保存（案例已在此前存入「自我学习」库）')
      } else {
        ElMessage.success('已保存，并已存入「自我学习」库')
      }
    } catch (e: any) {
      ElMessage.warning(`备注已保存，但存入学习库失败：${e?.response?.data?.detail || ''}`)
    }
  } else {
    ElMessage.success('备注已保存（标记 👍好 再点存，才会存入「自我学习」库）')
  }
}

// 数据库存 UTC（naive），按 UTC 解析后强制显示中国北京时间
function formatTime(iso?: string): string {
  if (!iso) return '—'
  const d = new Date(iso.replace(' ', 'T') + 'Z')
  if (isNaN(d.getTime())) return iso
  return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

onMounted(load)
</script>
