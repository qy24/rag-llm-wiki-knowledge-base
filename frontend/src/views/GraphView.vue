<template>
  <div class="page-card">
    <div class="toolbar">
      <el-select v-model="kbId" placeholder="选择知识库" style="width: 200px" @change="load">
        <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
      </el-select>
      <el-select v-model="docFilter" placeholder="全部文档" style="width: 220px" :disabled="!kbId" @change="renderGraph">
        <el-option label="全部文档（合并展示）" :value="0" />
        <el-option v-for="d in docs" :key="d.id" :label="d.filename" :value="d.id" />
      </el-select>
      <el-button type="primary" :disabled="!kbId" @click="load">加载图谱</el-button>
      <el-select v-model="layoutType" style="width: 170px" :disabled="!kbId" @change="onLayoutChange">
        <el-option label="布局：自动判断" value="auto" />
        <el-option label="布局：金字塔分层" value="layered" />
        <el-option label="布局：神经元力导向" value="force" />
      </el-select>
      <el-button type="success" :disabled="!kbId" @click="addEntityDialog = true">新增实体</el-button>
      <el-button type="warning" :disabled="!kbId" @click="addRelationDialog = true">新增关系</el-button>
      <el-button type="info" :disabled="!kbId" @click="autoLayout">🔄 重新布局</el-button>
      <span style="color:#909399;font-size:12px;margin-left:4px">
        规整层级数据用金字塔分层，网状数据用神经元力导向；选择自动判断更省心
      </span>
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
const docs = ref<{ id: number; filename: string }[]>([])
const docFilter = ref(0) // 0=全部文档；>0=按文档过滤展示
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

/**
 * 分层布局（有向）：入度 0 的节点（顶级，如店铺/大类）排最上，BFS 逐层向下；
 * 同层按名称（中文按拼音）排序 + Barycenter 迭代减交叉；节点宽度按最长标签自适应防遮挡。
 */
function layeredPositions(
  nodeList: { id: string; label: string }[],
  edgeList: { source: string; target: string }[],
  w: number, h: number,
): Map<string, { x: number; y: number }> {
  const idSet = new Set(nodeList.map((n) => n.id))
  const labelOf = new Map(nodeList.map((n) => [n.id, n.label] as const))
  const out: Record<string, string[]> = {}
  const inDeg: Record<string, number> = {}
  nodeList.forEach((n) => { out[n.id] = []; inDeg[n.id] = 0 })
  edgeList.forEach((e) => {
    if (!idSet.has(e.source) || !idSet.has(e.target)) return
    out[e.source].push(e.target)
    inDeg[e.target]++
  })

  // 根 = 入度 0 的节点集合（无入边者如"斑笔科技"在最上层）
  let roots = nodeList.filter((n) => inDeg[n.id] === 0).map((n) => n.id)
  if (roots.length === 0) {
    // 全部有入边（存在环）：退化为度最大的节点为根
    const deg: Record<string, number> = {}
    edgeList.forEach((e) => {
      if (idSet.has(e.source) && idSet.has(e.target)) {
        deg[e.source] = (deg[e.source] || 0) + 1
        deg[e.target] = (deg[e.target] || 0) + 1
      }
    })
    let mx = -1
    nodeList.forEach((n) => { if ((deg[n.id] || 0) > mx) { mx = deg[n.id]; roots = [n.id] } })
  }

  // BFS 分层：level = 到最近根的最短距离
  const level = new Map<string, number>()
  let frontier = [...roots]
  frontier.forEach((id) => level.set(id, 0))
  let lv = 0
  while (frontier.length) {
    lv++
    const next: string[] = []
    frontier.forEach((id) => {
      out[id].forEach((t) => { if (!level.has(t)) { level.set(t, lv); next.push(t) } })
    })
    frontier = next
  }
  nodeList.forEach((n) => { if (!level.has(n.id)) level.set(n.id, Math.max(lv, 1)) })

  // 同层分组，先按名称（中文拼音）排序
  const byLevel = new Map<number, string[]>()
  nodeList.forEach((n) => {
    const l = level.get(n.id)!
    if (!byLevel.has(l)) byLevel.set(l, [])
    byLevel.get(l)!.push(n.id)
  })
  const levels = [...byLevel.keys()].sort((a, b) => a - b)

  // Barycenter 减交叉：先按"父节点位置优先"排序（同一父节点的子节点相邻，父子连线不交叉），
  // 再迭代 5 次按邻居平均位置微调
  const indexIn = new Map<number, Map<string, number>>()
  levels.forEach((l) => {
    const m = new Map<string, number>()
    byLevel.get(l)!.forEach((id, i) => m.set(id, i))
    indexIn.set(l, m)
  })
  // 父节点排名：节点在上一层邻居（父）中的最小序号；无父 → 按名称
  const parentRank = (id: string, l: number): number => {
    let best = Infinity
    edgeList.forEach((e) => {
      let other = ''
      if (e.source === id && idSet.has(e.target)) other = e.target
      if (e.target === id && idSet.has(e.source)) other = e.source
      if (!other) return
      const nl = level.get(other)!
      if (nl < l) {
        const idx = indexIn.get(nl)?.get(other)
        if (idx !== undefined && idx < best) best = idx
      }
    })
    return best
  }
  levels.forEach((l) => {
    byLevel.get(l)!.sort((a, b) => {
      const pa = parentRank(a, l)
      const pb = parentRank(b, l)
      if (pa !== pb) return pa - pb
      return (labelOf.get(a) || '').localeCompare(labelOf.get(b) || '', 'zh')
    })
    const m = new Map<string, number>()
    byLevel.get(l)!.forEach((id, i) => m.set(id, i))
    indexIn.set(l, m)
  })
  for (let iter = 0; iter < 5; iter++) {
    levels.forEach((l) => {
      const ids = byLevel.get(l)!
      const center = (id: string) => {
        const neigh = new Set<string>()
        edgeList.forEach((e) => {
          if (e.source === id && idSet.has(e.target)) neigh.add(e.target)
          if (e.target === id && idSet.has(e.source)) neigh.add(e.source)
        })
        let sum = 0
        let cnt = 0
        neigh.forEach((nid) => {
          const nl = level.get(nid)!
          const idx = indexIn.get(nl)?.get(nid)
          if (nl !== l && idx !== undefined) { sum += idx; cnt++ }
        })
        return cnt ? sum / cnt : ids.indexOf(id)
      }
      ids.sort((a, b) => center(a) - center(b))
      const m = new Map<string, number>()
      ids.forEach((id, i) => m.set(id, i))
      indexIn.set(l, m)
    })
  }

  // 坐标分配：统一间距（下限 110px 防重叠）；宽层折行放宽到每行 10 个（父子尽量同排不拆散，
  // 减少行间连线交叉）；层级间距 170px（跨层），子行间距 80px
  const MAX_PER_ROW = 10
  const ROW_GAP = 80
  const maxLabel = Math.max(...nodeList.map((n) => (labelOf.get(n.id) || '').length), 2)
  const nodeW = Math.min(Math.max(maxLabel * 13 + 40, 110), 190)
  const layerH = 170
  const pos = new Map<string, { x: number; y: number }>()
  levels.forEach((l) => {
    const ids = byLevel.get(l)!
    // 拆行：ceil(n/MAX) 行，每行尽量均衡（8 一行，14 → 7+7，15 → 5+5+5）
    const rowCount = Math.max(1, Math.ceil(ids.length / MAX_PER_ROW))
    const perRow = Math.ceil(ids.length / rowCount)
    const rows: string[][] = []
    for (let r = 0; r < rowCount; r++) rows.push(ids.slice(r * perRow, (r + 1) * perRow))
    const maxRowW = Math.max(...rows.map((r) => r.length * nodeW))
    const x0 = maxRowW > w - 20 ? 10 : (w - maxRowW) / 2
    rows.forEach((row, ri) => {
      const rowW = row.length * nodeW
      const rowX0 = x0 + (maxRowW - rowW) / 2 // 子行相对整层居中
      row.forEach((id, i) => {
        pos.set(id, { x: rowX0 + nodeW / 2 + i * nodeW, y: 60 + l * layerH + ri * ROW_GAP })
      })
    })
  })
  return pos
}

async function autoLayout() {
  if (!container.value || !graph) return
  if (effectiveLayout() === 'force') {
    // force：先重置节点位置到画布中心附近，再重新力导向——
    // 否则每次都在上次位置基础上继续施力，孤立节点（无边）会被越推越远
    const w = container.value.clientWidth
    const h = container.value.clientHeight
    const cx = w / 2
    const cy = h / 2
    graph.getNodes().forEach((n: any) => {
      graph.updateItem(n, {
        x: cx + (Math.random() - 0.5) * w * 0.4,
        y: cy + (Math.random() - 0.5) * h * 0.4,
      })
    })
    graph.updateLayout({ ...FORCE_LAYOUT })
    ElMessage.success('已按神经元力导向重新布局')
  } else {
    // 金字塔分层：重新计算分层坐标并应用
    const pos = layeredPositions(
      entities.value.map((e) => ({ id: e.id, label: e.name })),
      relations.value.map((r) => ({ source: r.source_entity_id, target: r.target_entity_id })),
      container.value.clientWidth, container.value.clientHeight,
    )
    graph.getNodes().forEach((n: any) => {
      const m = n.getModel()
      const p = pos.get(m.id)
      if (p) graph.updateItem(n, { x: p.x, y: p.y })
    })
    ElMessage.success('已按金字塔分层重新布局')
  }
}

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
  // 同步当前知识库的布局偏好
  const kb = kbs.value.find((k) => k.id === kbId.value)
  layoutType.value = (kb?.layout_type as any) || 'auto'
  // 拉取当前库文档列表（图谱按文档过滤展示用）
  const { data: allDocs } = await client.get('/admin/documents')
  docs.value = allDocs.filter((d: any) => d.kb_id === kbId.value)
  if (docFilter.value !== 0 && !docs.value.some((d) => d.id === docFilter.value)) {
    docFilter.value = 0
  }
  const [eRes, rRes] = await Promise.all([
    client.get(`/admin/kbs/${kbId.value}/entities`, { params: { limit: 500 } }),
    client.get(`/admin/kbs/${kbId.value}/relations`, { params: { limit: 500 } }),
  ])
  entities.value = eRes.data.items
  relations.value = rRes.data.items
  renderGraph()
}

// 力导向布局配置（神经元式：节点按关系自然聚拢、边清晰）
const FORCE_LAYOUT = {
  type: 'force',
  preventOverlap: true,
  linkDistance: 300,    // 边长度拉大（有关系的节点靠得近但边间隙大，减少线重叠）
  nodeStrength: -220,   // 节点间排斥力加大（节点更分散，边更分开）
  edgeStrength: 0.25,   // 边拉力适中（配合更长距离）
  damping: 0.9,
  maxIteration: 700,
}

// 布局选择（当前知识库）：auto 时按图谱结构自动判断
const layoutType = ref<'auto' | 'layered' | 'force'>('auto')

function effectiveLayout(): 'layered' | 'force' {
  if (layoutType.value === 'layered' || layoutType.value === 'force') return layoutType.value
  // 自动判断：入度 0 的顶级节点很少（≤3，层级分明）→ 金字塔分层；否则网状 → 神经元
  const ids = new Set(entities.value.map((e) => e.id))
  const inDeg = new Map<string, number>()
  entities.value.forEach((e) => inDeg.set(e.id, 0))
  relations.value.forEach((r) => {
    if (ids.has(r.source_entity_id) && ids.has(r.target_entity_id)) {
      inDeg.set(r.target_entity_id, (inDeg.get(r.target_entity_id) || 0) + 1)
    }
  })
  const roots = [...inDeg.values()].filter((d) => d === 0).length
  return roots <= 3 ? 'layered' : 'force'
}

async function onLayoutChange() {
  // 持久化到知识库（下次打开同样布局）
  if (!kbId.value) return
  try {
    await client.patch(`/admin/kbs/${kbId.value}`, { layout_type: layoutType.value })
    ElMessage.success('布局偏好已保存')
  } catch {
    /* 保存失败不影响本次渲染 */
  }
  load()
}

function renderGraph() {
  if (!container.value) return
  if (graph) {
    graph.destroy()
    graph = null
  }
  container.value.querySelectorAll('.graph-empty-tip').forEach((el) => el.remove())
  // 按文档过滤展示（0=全部；>0=只展示该文档抽取的实体及其关联关系）
  let showEntities = entities.value
  let showRelations = relations.value
  if (docFilter.value !== 0) {
    showEntities = entities.value.filter((e) => e.source_doc_id === docFilter.value)
    const entIds = new Set(showEntities.map((e) => e.id))
    showRelations = relations.value.filter(
      (r) => entIds.has(r.source_entity_id) && entIds.has(r.target_entity_id),
    )
  }
  if (!showEntities.length) {
    // 空画布提示
    const empty = document.createElement('div')
    empty.className = 'graph-empty-tip'
    empty.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);color:#909399;font-size:13px'
    empty.textContent = docFilter.value !== 0 ? '该文档暂无可展示的图谱实体（图谱抽取可能未完成）' : '暂无图谱数据'
    container.value.appendChild(empty)
    return
  }
  const useForce = effectiveLayout() === 'force'
  let layeredPos: Map<string, { x: number; y: number }> | null = null
  if (!useForce) {
    const w = container.value.clientWidth
    const h = container.value.clientHeight
    layeredPos = layeredPositions(
      showEntities.map((e) => ({ id: e.id, label: e.name })),
      showRelations.map((r) => ({ source: r.source_entity_id, target: r.target_entity_id })),
      w, h,
    )
  }
  const nodes = showEntities.map((e) => {
    const lp = layeredPos?.get(e.id)
    return {
      id: e.id,
      label: e.name,
      type: e.type,
      ...(lp ? { x: lp.x, y: lp.y } : {}),
      size: 34, // 节点统一大小，名称显示在节点下方（不溢出、整齐）
      labelCfg: { position: 'bottom', offset: 10, style: { fontSize: 12 } },
      style: { fill: e.verified ? '#67c23a' : '#409eff', stroke: '#333' },
    }
  })
  const edges = showRelations.map((r) => ({
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
      layout: useForce ? FORCE_LAYOUT : { type: 'none' },  // 神经元力导向 / 金字塔分层（坐标已算好）
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
