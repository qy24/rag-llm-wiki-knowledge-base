<template>
  <div class="page-card">
    <div class="toolbar">
      <el-select v-model="kbId" placeholder="选择知识库" style="width: 200px">
        <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
      </el-select>
      <el-input v-model="query" placeholder="输入查询，验证向量+图谱混合检索" style="width: 360px" @keyup.enter="run" />
      <el-input-number v-model="topK" :min="1" :max="50" />
      <el-switch v-model="enableGraph" active-text="图谱检索" />
      <el-button type="primary" :disabled="!kbId || !query" @click="run">检 索</el-button>
    </div>

    <template v-if="result">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px"
                :title="`实际生效范围: 知识库 #${result.permission_scope.kb_ids.join(', ')}；图谱命中实体 ${result.graph.entities.length} 个 / 关系 ${result.graph.relations.length} 条`" />

      <!-- 文本命中 -->
      <template v-if="result.chunks.length > 0">
        <el-table :data="result.chunks" border size="small" style="margin-bottom: 12px">
          <el-table-column prop="source" label="来源" width="90">
            <template #default="{ row }">
              <el-tag :type="row.source === 'graph' ? 'success' : 'primary'" size="small">{{ row.source }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="score" label="分数" width="80" />
          <el-table-column label="来源文档" width="140">
            <template #default="{ row }">{{ result.kb_names?.[row.kb_id] }} / {{ row.metadata?.page ?? '' }}</template>
          </el-table-column>
          <el-table-column prop="content" label="内容" min-width="400" show-overflow-tooltip />
        </el-table>
      </template>
      <el-alert v-else type="warning" :closable="false" style="margin-bottom: 12px"
                title="文本命中 0 条（该知识库暂无相关文档内容，以下为图谱命中）" />

      <!-- 图谱命中的实体 -->
      <el-card v-if="result.graph.entities.length > 0" shadow="never" style="margin-bottom: 12px"
               :header="`图谱命中实体（${result.graph.entities.length}）`">
        <el-table :data="result.graph.entities" border size="small">
          <el-table-column prop="name" label="实体" min-width="140" />
          <el-table-column prop="type" label="类型" width="120" />
          <el-table-column label="已确认" width="90">
            <template #default="{ row }">
              <el-tag :type="row.verified ? 'success' : 'info'" size="small">{{ row.verified ? '是' : '否' }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 图谱命中的关系 -->
      <el-card v-if="result.graph.relations.length > 0" shadow="never" :header="`图谱命中关系（${result.graph.relations.length}）`">
        <el-table :data="relRows" border size="small">
          <el-table-column prop="label" label="关系" min-width="300" />
        </el-table>
      </el-card>

      <el-empty v-if="result.chunks.length === 0 && result.graph.entities.length === 0 && result.graph.relations.length === 0"
                description="未命中任何内容（可到知识库管理上传文档，或到图谱页添加实体）" />
    </template>
    <el-empty v-else description="输入问题开始检索调试" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import client from '../api/client'
import type { KB, SearchResult } from '../api/types'
import { getLastKb, setLastKb } from '../utils/kbStorage'

const kbs = ref<KB[]>([])
const kbId = ref<number | undefined>(getLastKb())
watch(kbId, (v) => setLastKb(v))
const query = ref('')
const topK = ref(8)
const enableGraph = ref(true)
const result = ref<SearchResult | null>(null)

function entityName(id: string): string {
  return result.value?.graph.entities.find((e) => e.id === id)?.name || id.slice(0, 8)
}

// 关系行：实体A -类型-> 实体B
const relRows = computed(() =>
  (result.value?.graph.relations || []).map((r) => ({
    label: `${entityName(r.source_entity_id)} -${r.relation_type}-> ${entityName(r.target_entity_id)}`,
  })),
)

async function run() {
  if (!kbId.value || !query.value) return
  const { data } = await client.post(`/admin/kbs/${kbId.value}/debug-search`, {
    query: query.value, top_k: topK.value, graph_depth: 1, enable_graph: enableGraph.value,
  })
  result.value = data
}

onMounted(async () => {
  const { data } = await client.get('/admin/kbs')
  kbs.value = data
  // 优先使用记忆的知识库；不存在或未记忆时用第一个
  if (kbs.value.length && !kbs.value.some((k) => k.id === kbId.value)) {
    kbId.value = kbs.value[0].id
  }
})
</script>
