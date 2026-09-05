<template>
  <div class="page-card">
    <div class="toolbar">
      <el-select v-model="kbId" placeholder="选择知识库" style="width: 240px" @change="load">
        <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
      </el-select>
      <el-upload
        v-if="auth.isAdmin"
        :show-file-list="false"
        :http-request="upload"
        accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm,.pptx,.xlsx"
        multiple
      >
        <el-button type="primary" :disabled="!kbId">上传文档</el-button>
      </el-upload>
      <span style="color: #909399; font-size: 12px">支持 PDF / DOCX / MD / TXT / HTML / PPTX / XLSX</span>
    </div>

    <el-table :data="docs" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
      <el-table-column prop="file_type" label="类型" width="80" />
      <el-table-column prop="page_count" label="块数" width="70" />
      <el-table-column label="状态" width="140">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="error_msg" label="错误信息" min-width="160" show-overflow-tooltip />
      <el-table-column label="操作" :width="auth.isAdmin ? 180 : 120">
        <template #default="{ row }">
          <el-button size="small" type="primary" link
                     @click="$router.push('/chunks?kb=' + kbId + '&doc=' + row.id)">切分块</el-button>
          <el-button v-if="auth.isAdmin" size="small" type="danger" link @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { DocumentItem, KB } from '../api/types'
import { getLastKb, setLastKb } from '../utils/kbStorage'

const auth = useAuthStore()

const route = useRoute()
const kbs = ref<KB[]>([])
const kbId = ref<number | undefined>(
  route.query.kb ? Number(route.query.kb) : getLastKb(),
)
watch(kbId, (v) => setLastKb(v))
const docs = ref<DocumentItem[]>([])
let timer: number | undefined

function statusType(s: string) {
  if (s === '完成') return 'success'
  if (s === '失败') return 'danger'
  return 'warning'
}

async function loadKbs() {
  const { data } = await client.get('/admin/kbs')
  kbs.value = data
}

async function load() {
  if (!kbId.value) return
  const { data } = await client.get('/admin/documents', { params: { kb_id: kbId.value } })
  docs.value = data
}

async function upload(opt: any) {
  if (!kbId.value) return
  const fd = new FormData()
  fd.append('file', opt.file)
  await client.post(`/admin/kbs/${kbId.value}/documents`, fd)
  ElMessage.success(`已上传：${opt.file.name}`)
  opt.onSuccess?.({})
  load()
}

async function remove(row: DocumentItem) {
  await ElMessageBox.confirm(`删除文档「${row.filename}」？将级联清理其切分块/向量/图谱。`, '警告', { type: 'warning' })
  await client.delete(`/admin/documents/${row.id}`)
  ElMessage.success('已删除')
  load()
}

onMounted(async () => {
  await loadKbs()
  if (kbs.value.length && !kbs.value.some((k) => k.id === kbId.value)) {
    kbId.value = kbs.value[0].id
  }
  await load()
  timer = window.setInterval(load, 4000)
})
</script>
