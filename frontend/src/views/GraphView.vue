<template>
  <div class="page-card">
    <div class="toolbar">
      <el-select v-model="kbId" placeholder="选择知识库" style="width: 220px" @change="load">
        <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
      </el-select>
      <el-button type="primary" :disabled="!kbId" @click="load">加载图谱</el-button>
      <el-button type="success" :disabled="!kbId" @click="addEntityDialog = true">新增实体</el-button>
      <el-button type="warning" :disabled="!kbId" @click="addRelationDialog = true">新增关系</el-button>
    </div>

    <el-row :gutter="12">
      <el-col :span="17">
        <div ref="container" style="height: calc(100vh - 180px); border: 1px solid #eee"></div>
      </el-col>
      <el-col :span="7">
        <el-card shadow="never" header="选中节点 / 详情">
          <template v-if="selected">
            <el-form label-width="70px" size="small">
              <el-form-item label="名称"><el-input v-model="selected.name" /></el-form-item>
              <el-form-item label="类型"><el-input v-model="selected.type" /></el-form-item>
              <el-form-item label="已确认">
                <el-tooltip
                  content="人工核对无误后打开：已确认的实体/关系（绿色）在检索结果中权重更高，回答优先引用；未确认的为蓝色。不影响权限范围。"
                  placement="top"
                >
                  <el-switch v-model="selected.verified" />
                </el-tooltip>
              </el-form-item>
            </el-form>
            <div style="margin-top: 8px">
              <el-divider content-position="left">新增关系（可连续添加多个）</el-divider>
              <el-form label-width="70px" size="small">
                <el-form-item label="关系类型">
                  <el-input v-model="relType" placeholder="如：配图 / 属于 / 依赖" />
                </el-form-item>
                <el-form-item label="方向">
                  <el-select v-model="relDirection" style="width: 100%">
                    <el-option label="本实体 → 目标（出）" value="out" />
                    <el-option label="目标 → 本实体（入）" value="in" />
                  </el-select>
                </el-form-item>
                <el-form-item label="目标实体">
                  <el-select v-model="relTargetId" filterable style="width: 100%" placeholder="选择目标实体">
                    <el-option v-for="e in entities.filter((x) => x.id !== selected?.id)" :key="e.id"
                               :label="e.name + '（' + e.type + '）'" :value="e.id" />
                  </el-select>
                </el-form-item>
                <el-form-item>
                  <el-button type="success" size="small" :disabled="!relType || !relTargetId"
                             @click="addRelationFromSelected">添加关系</el-button>
                  <span style="color:#909399;font-size:12px;margin-left:6px">添加后自动刷新画布，可继续添加下一个</span>
                </el-form-item>
              </el-form>
              <el-divider content-position="left">已建立关系（{{ selectedRelations.length }}）</el-divider>
              <div v-if="selectedRelations.length === 0" style="color:#c0c4cc;font-size:12px">暂无关系</div>
              <div v-for="r in selectedRelations" :key="r.id"
                   style="display:flex;justify-content:space-between;align-items:center;font-size:12px;padding:2px 0">
                <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ relLabel(r) }}</span>
                <span style="flex-shrink:0">
                  <el-button size="small" type="primary" link @click="openEditRelation(r)">编辑</el-button>
                  <el-button size="small" type="danger" link @click="deleteRelation(r)">删除</el-button>
                </span>
              </div>
            </div>
            <div v-if="imageUrl" style="margin-top: 8px">
              <el-divider content-position="left">产品图片</el-divider>
              <img :src="imageUrl" style="max-width: 100%; border-radius: 4px" />
            </div>
            <div v-if="relatedChunk" style="margin-top: 8px">
              <el-divider content-position="left">关联原文</el-divider>
              <div style="font-size: 12px; color: #666; max-height: 200px; overflow: auto; white-space: pre-wrap">
                {{ relatedChunk.content }}
              </div>
            </div>
            <div style="margin-top: 12px">
              <el-button type="primary" size="small" @click="saveEntity">保存</el-button>
              <el-button type="warning" size="small" @click="mergeDialog = true">合并到…</el-button>
              <el-button type="danger" size="small" @click="deleteEntity">删除实体</el-button>
            </div>
          </template>
          <el-empty v-else description="点击图上的节点查看/编辑" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="editRelDialog" title="编辑关系类型" width="360px">
      <el-form label-width="80px" size="small">
        <el-form-item label="关系">
          <span v-if="editRelTarget" style="font-size: 12px; color: #606266">{{ relLabel(editRelTarget) }}</span>
        </el-form-item>
        <el-form-item label="关系类型">
          <el-input v-model="editRelType" placeholder="如：配图 / 属于 / 依赖" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editRelDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!editRelType" @click="saveRelationType">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mergeDialog" title="合并实体" width="420px">
      <p style="font-size: 13px; color: #666">
        将「{{ selected?.name }}」合并到目标实体（其关系将改指目标实体，属性合并）。
      </p>
      <el-select v-model="mergeTargetId" filterable placeholder="选择目标实体" style="width: 100%">
        <el-option v-for="e in entities.filter((x) => x.id !== selected?.id)" :key="e.id"
                   :label="e.name + '（' + e.type + '）'" :value="e.id" />
      </el-select>
      <template #footer>
        <el-button @click="mergeDialog = false">取消</el-button>
        <el-button type="warning" :disabled="!mergeTargetId" @click="doMerge">合并</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="addEntityDialog" title="新增实体" width="420px">
      <el-form label-width="70px">
        <el-form-item label="名称"><el-input v-model="newEntity.name" /></el-form-item>
        <el-form-item label="类型"><el-input v-model="newEntity.type" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addEntityDialog = false">取消</el-button>
        <el-button type="primary" @click="createEntity">添加</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="addRelationDialog" title="新增关系" width="480px">
      <el-form label-width="80px">
        <el-form-item label="起点实体">
          <el-select v-model="newRelation.source_entity_id" filterable style="width: 100%">
            <el-option v-for="e in entities" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="终点实体">
          <el-select v-model="newRelation.target_entity_id" filterable style="width: 100%">
            <el-option v-for="e in entities" :key="e.id" :label="e.name" :value="e.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关系类型"><el-input v-model="newRelation.relation_type" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addRelationDialog = false">取消</el-button>
        <el-button type="primary" @click="createRelation">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import client from '../api/client'
import type { ChunkItem, EntityItem, KB, RelationItem } from '../api/types'
import { getLastKb, setLastKb } from '../utils/kbStorage'

const route = useRoute()
const kbs = ref<KB[]>([])
const kbId = ref<number | undefined>(
  route.query.kb ? Number(route.query.kb) : getLastKb(),
)
watch(kbId, (v) => setLastKb(v))
const container = ref<HTMLElement>()
const entities = ref<EntityItem[]>([])
const relations = ref<RelationItem[]>([])
const selected = ref<EntityItem | null>(null)
const relatedChunk = ref<ChunkItem | null>(null)
const imageUrl = ref('')
const addEntityDialog = ref(false)
const addRelationDialog = ref(false)
const mergeDialog = ref(false)
const mergeTargetId = ref('')
const newEntity = reactive({ name: '', type: '术语' })
const newRelation = reactive({ source_entity_id: '', target_entity_id: '', relation_type: '' })
// 实体面板"新增关系"表单（可连续添加多个）
const relType = ref('')
const relTargetId = ref('')
const relDirection = ref('out')

let graph: any = null

// 选中实体已有的全部关系（出 + 入）
const selectedRelations = computed(() => {
  if (!selected.value) return []
  return relations.value.filter(
    (r) => r.source_entity_id === selected.value!.id || r.target_entity_id === selected.value!.id,
  )
})

function entityName(id: string): string {
  return entities.value.find((e) => e.id === id)?.name || id.slice(0, 8)
}

function relLabel(r: RelationItem): string {
  return `${entityName(r.source_entity_id)} -${r.relation_type}-> ${entityName(r.target_entity_id)}`
}

async function addRelationFromSelected() {
  if (!selected.value || !relType.value || !relTargetId.value) return
  const payload = relDirection.value === 'out'
    ? { source_entity_id: selected.value.id, target_entity_id: relTargetId.value, relation_type: relType.value }
    : { source_entity_id: relTargetId.value, target_entity_id: selected.value.id, relation_type: relType.value }
  await client.post(`/admin/kbs/${kbId.value}/relations`, payload)
  ElMessage.success('已添加关系')
  await load()
  relTargetId.value = ''   // 保留关系类型，可继续添加下一个
}

async function deleteRelation(r: RelationItem) {
  await ElMessageBox.confirm('删除这条关系？', '确认', { type: 'warning' })
  await client.delete(`/admin/relations/${r.id}`)
  ElMessage.success('已删除')
  await load()
}

// 编辑关系类型
const editRelDialog = ref(false)
const editRelType = ref('')
const editRelTarget = ref<RelationItem | null>(null)

function openEditRelation(r: RelationItem) {
  editRelTarget.value = r
  editRelType.value = r.relation_type
  editRelDialog.value = true
}

async function saveRelationType() {
  if (!editRelTarget.value || !editRelType.value) return
  await client.patch(`/admin/relations/${editRelTarget.value.id}`, { relation_type: editRelType.value })
  ElMessage.success('已更新关系类型')
  editRelDialog.value = false
  await load()
}

async function load() {
  if (!kbId.value) return
  const [eRes, rRes] = await Promise.all([
    client.get(`/admin/kbs/${kbId.value}/entities`, { params: { limit: 500 } }),
    client.get(`/admin/kbs/${kbId.value}/relations`, { params: { limit: 500 } }),
  ])
  entities.value = eRes.data.items
  relations.value = rRes.data.items
  renderGraph()
}

function renderGraph() {
  if (!container.value) return
  // 记录当前画布各节点坐标（重绘后保持位置不乱动）
  const posMap = new Map<string, { x: number; y: number }>()
  if (graph) {
    graph.getNodes().forEach((n: any) => {
      const m = n.getModel()
      posMap.set(m.id, { x: m.x, y: m.y })
    })
    graph.destroy()
    graph = null
  }
  const w = container.value.clientWidth
  const h = container.value.clientHeight
  const nodes = entities.value.map((e, i) => {
    const saved = (e.properties as any) || {}
    const pos = posMap.get(e.id) || saved
    const x = typeof pos.x === 'number' ? pos.x : 80 + ((i * 97) % Math.max(w - 160, 100))
    const y = typeof pos.y === 'number' ? pos.y : 80 + ((i * 53) % Math.max(h - 160, 100))
    return {
      id: e.id,
      label: e.name,
      type: e.type,
      x,
      y,
      style: { fill: e.verified ? '#67c23a' : '#409eff', stroke: '#333' },
      size: 26,
    }
  })
  const edges = relations.value.map((r) => ({
    source: r.source_entity_id,
    target: r.target_entity_id,
    label: r.relation_type,
    style: { endArrow: true },
  }))
  import('@antv/g6').then(({ default: G6 }: any) => {
    graph = new G6.Graph({
      container: container.value!,
      width: container.value!.clientWidth,
      height: container.value!.clientHeight,
      fitView: true,
      modes: { default: ['drag-canvas', 'zoom-canvas', 'drag-node'] },
      layout: { type: 'none' },  // 不自动重排，保持节点位置
      defaultNode: { type: 'circle', labelCfg: { style: { fontSize: 11 } } },
      defaultEdge: { labelCfg: { autoRotate: true, style: { fontSize: 9 } } },
      data: { nodes, edges },
    })
    graph.on('node:click', (evt: any) => {
      const model = evt.item.getModel()
      selected.value = entities.value.find((e) => e.id === model.id) || null
      relTargetId.value = ''
      loadRelatedChunk()
    })
    // 拖拽结束后把坐标写入实体属性（自动持久化，刷新/保存后位置不变）
    graph.on('node:dragend', (evt: any) => {
      const model = evt.item.getModel()
      const ent = entities.value.find((e) => e.id === model.id)
      if (!ent) return
      const props = { ...(ent.properties || {}), x: Math.round(model.x), y: Math.round(model.y) }
      ent.properties = props
      client.patch(`/admin/entities/${ent.id}`, { properties: props }).catch(() => {})
    })
    graph.render()
  })
}

async function loadRelatedChunk() {
  relatedChunk.value = null
  if (imageUrl.value) {
    URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = ''
  }
  if (!selected.value) return
  // 图片实体：显示原图
  const imgDocId = selected.value.properties?.image_doc_id
  if (imgDocId) {
    try {
      const resp = await client.get(`/admin/documents/${imgDocId}/file`, { responseType: 'blob' })
      imageUrl.value = URL.createObjectURL(resp.data)
    } catch {
      /* 图片加载失败不阻塞 */
    }
  }
  if (!selected.value.source_chunk_id) return
  const { data } = await client.get(`/admin/chunks/${selected.value.source_chunk_id}`)
  relatedChunk.value = data
}

async function saveEntity() {
  if (!selected.value) return
  await client.patch(`/admin/entities/${selected.value.id}`, {
    name: selected.value.name,
    type: selected.value.type,
    verified: selected.value.verified,
  })
  ElMessage.success('已保存')
  load()
}

async function deleteEntity() {
  if (!selected.value) return
  await ElMessageBox.confirm(`删除实体「${selected.value.name}」？关联关系将一并删除。`, '警告', { type: 'warning' })
  await client.delete(`/admin/entities/${selected.value.id}`)
  selected.value = null
  ElMessage.success('已删除')
  load()
}

async function doMerge() {
  if (!selected.value || !mergeTargetId.value) return
  await ElMessageBox.confirm(
    `将「${selected.value.name}」合并到目标实体？此操作不可撤销。`, '确认合并', { type: 'warning' },
  )
  await client.post('/admin/entities/merge', {
    source_id: selected.value.id, target_id: mergeTargetId.value,
  })
  ElMessage.success('已合并')
  mergeDialog.value = false
  mergeTargetId.value = ''
  selected.value = null
  load()
}

async function createEntity() {
  if (!newEntity.name) return
  await client.post(`/admin/kbs/${kbId.value}/entities`, { ...newEntity })
  ElMessage.success('已添加')
  addEntityDialog.value = false
  newEntity.name = ''
  load()
}

async function createRelation() {
  if (!newRelation.source_entity_id || !newRelation.target_entity_id || !newRelation.relation_type) return
  await client.post(`/admin/kbs/${kbId.value}/relations`, { ...newRelation })
  ElMessage.success('已添加')
  addRelationDialog.value = false
  newRelation.source_entity_id = ''
  newRelation.target_entity_id = ''
  newRelation.relation_type = ''
  load()
}

onMounted(async () => {
  const { data } = await client.get('/admin/kbs')
  kbs.value = data
  if (kbs.value.length && !kbs.value.some((k) => k.id === kbId.value)) {
    kbId.value = kbs.value[0].id
  }
  await load()
})

onBeforeUnmount(() => {
  if (graph) {
    graph.destroy()
    graph = null
  }
})
</script>
