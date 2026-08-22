<template>
  <div class="page-card">
    <div class="toolbar">
      <el-select v-model="kbId" placeholder="选择知识库" style="width: 220px" @change="loadDocs">
        <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
      </el-select>
      <el-select v-model="docId" placeholder="选择文档" style="width: 260px" @change="loadChunks">
        <el-option v-for="d in docs" :key="d.id" :label="d.filename" :value="d.id" />
      </el-select>
      <el-button size="small" type="primary" :disabled="!docId" @click="saveAll">保存修改并重新向量化</el-button>
    </div>

    <el-table :data="chunks" border size="small" max-height="calc(100vh - 200px)">
      <el-table-column prop="seq" label="#" width="50" />
      <el-table-column label="来源" width="100">
        <template #default="{ row }">{{ row.metadata?.page || '' }}</template>
      </el-table-column>
      <el-table-column label="内容（可编辑）" min-width="500">
        <template #default="{ row }">
          <el-input v-model="row.content" type="textarea" :autosize="{ minRows: 2, maxRows: 8 }" />
        </template>
      </el-table-column>
      <el-table-column label="向量状态" width="110">
        <template #default="{ row }">
          <el-tag :type="row.embedding_status === 'done' ? 'success' : 'warning'" size="small">
            {{ row.embedding_status }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import client from '../api/client'
import type { ChunkItem, DocumentItem, KB } from '../api/types'
import { getLastKb, setLastKb } from '../utils/kbStorage'

const route = useRoute()
const kbs = ref<KB[]>([])
const docs = ref<DocumentItem[]>([])
const kbId = ref<number | undefined>(
  route.query.kb ? Number(route.query.kb) : getLastKb(),
)
watch(kbId, (v) => setLastKb(v))
const docId = ref<number | undefined>(route.query.doc ? Number(route.query.doc) : undefined)
const chunks = ref<ChunkItem[]>([])

async function loadDocs() {
  docs.value = []
  chunks.value = []
  if (!kbId.value) return
  const { data } = await client.get('/admin/documents', { params: { kb_id: kbId.value } })
  docs.value = data
  if (docId.value && !data.some((d: DocumentItem) => d.id === docId.value)) docId.value = undefined
  if (docId.value) loadChunks()
}

async function loadChunks() {
  if (!kbId.value || !docId.value) return
  const { data } = await client.get(`/admin/kbs/${kbId.value}/chunks`, { params: { doc_id: docId.value } })
  chunks.value = data
}

async function saveAll() {
  let n = 0
  for (const c of chunks.value) {
    await client.patch(`/admin/chunks/${c.id}`, { content: c.content })
    n++
  }
  ElMessage.success(`已保存 ${n} 个切分块，重新向量化任务已入队`)
}

onMounted(async () => {
  const { data } = await client.get('/admin/kbs')
  kbs.value = data
  if (kbs.value.length && !kbs.value.some((k) => k.id === kbId.value)) {
    kbId.value = kbs.value[0].id
  }
  await loadDocs()
})
</script>
