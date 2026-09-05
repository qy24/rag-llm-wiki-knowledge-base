<template>
  <div class="page-card">
    <div class="toolbar">
      <el-button v-if="auth.isAdmin" type="primary" @click="dialog = true">新建知识库</el-button>
    </div>
    <el-table :data="kbs" border>
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
      <el-table-column prop="chunk_size" label="切分大小" width="100" />
      <el-table-column prop="chunk_overlap" label="重叠" width="80" />
      <el-table-column label="图谱抽取" width="110">
        <template #default="{ row }">
          <el-switch
            v-if="auth.isAdmin"
            :model-value="row.graph_extraction_enabled"
            :disabled="row._saving"
            @change="(v: boolean) => toggleGraphExtraction(row, v)"
          />
          <el-tag v-else :type="row.graph_extraction_enabled ? 'success' : 'info'" size="small">
            {{ row.graph_extraction_enabled ? '开启' : '关闭' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" :width="auth.isAdmin ? 300 : 220">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="$router.push('/documents?kb=' + row.id)">文档</el-button>
          <el-button size="small" type="success" link @click="$router.push('/graph?kb=' + row.id)">图谱</el-button>
          <el-button size="small" type="warning" link @click="$router.push('/chunks?kb=' + row.id)">切分块</el-button>
          <el-button v-if="auth.isAdmin" size="small" type="danger" link @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="新建知识库" width="480px">
      <el-form label-width="100px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" /></el-form-item>
        <el-form-item label="切分大小"><el-input-number v-model="form.chunk_size" :min="64" :max="4096" /></el-form-item>
        <el-form-item label="重叠"><el-input-number v-model="form.chunk_overlap" :min="0" :max="1024" /></el-form-item>
        <el-form-item label="图谱抽取"><el-switch v-model="form.graph_extraction_enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { KB } from '../api/types'

const auth = useAuthStore()
const kbs = ref<KB[]>([])
const dialog = ref(false)
const form = reactive({
  name: '', description: '', chunk_size: 512, chunk_overlap: 64, graph_extraction_enabled: true,
})

async function load() {
  const { data } = await client.get('/admin/kbs')
  kbs.value = data
}

async function create() {
  if (!form.name) return
  await client.post('/admin/kbs', form)
  dialog.value = false
  ElMessage.success('已创建')
  form.name = ''
  load()
}

async function remove(row: KB) {
  await ElMessageBox.confirm(`确定删除知识库「${row.name}」？其文档、切分块、向量与图谱将被级联删除。`, '警告', { type: 'warning' })
  await client.delete(`/admin/kbs/${row.id}`)
  ElMessage.success('已删除')
  load()
}

async function toggleGraphExtraction(row: any, v: boolean) {
  row._saving = true
  try {
    await client.patch(`/admin/kbs/${row.id}`, { graph_extraction_enabled: v })
    row.graph_extraction_enabled = v
    ElMessage.success(v ? '已开启图谱抽取（对之后处理的文档生效）' : '已关闭图谱抽取（文档只切分+向量）')
  } finally {
    row._saving = false
  }
}

onMounted(load)
</script>
