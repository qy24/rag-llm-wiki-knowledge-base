<template>
  <div class="page-card">
    <div class="toolbar">
      <el-button type="primary" @click="dialog = true">创建密钥</el-button>
      <span style="color: #909399; font-size: 12px">
        每个租户（电脑）持独立密钥，只能检索绑定知识库的数据
      </span>
    </div>

    <el-table :data="pagedKeys" border>
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="key_type" label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small">{{ row.key_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="绑定知识库" min-width="180">
        <template #default="{ row }">
          <el-tag
            v-for="kb in row.allowed_kb_ids"
            :key="kb"
            size="small"
            style="margin-right: 4px"
          >
            {{ kbName(kb) }}
          </el-tag>
          <span v-if="row.allowed_kb_ids.length === 0" style="color: #f56c6c; font-size: 12px">未绑定（无法检索）</span>
        </template>
      </el-table-column>
      <el-table-column label="提示词" min-width="140">
        <template #default="{ row }">
          <el-tooltip v-if="row.prompt_template" :content="row.prompt_template" placement="top" :show-after="300">
            <el-tag size="small" type="warning">自定义</el-tag>
          </el-tooltip>
          <span v-else style="color: #c0c4cc; font-size: 12px">使用默认</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.revoked ? 'danger' : 'success'" size="small">
            {{ row.revoked ? '无效' : '有效' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_used_at" label="最近使用" width="160">
        <template #default="{ row }">{{ row.last_used_at || '—' }}</template>
      </el-table-column>
      <el-table-column label="操作" width="170">
        <template #default="{ row }">
          <template v-if="!row.revoked">
            <el-button size="small" type="primary" link @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="warning" link @click="revoke(row)">吊销</el-button>
          </template>
          <el-button v-else size="small" type="success" link @click="restore(row)">恢复</el-button>
          <el-button size="small" type="danger" link @click="removeKey(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="margin-top: 12px; display: flex; justify-content: flex-end">
      <el-pagination
        layout="prev, pager, next, total"
        :total="keys.length"
        :page-size="pageSize"
        v-model:current-page="page"
        background
      />
    </div>

    <el-dialog v-model="dialog" title="创建密钥" width="560px">
      <el-form label-width="100px">
        <el-form-item label="名称" required><el-input v-model="form.name" placeholder="如：电脑1" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.key_type">
            <el-option label="search（只读检索）" value="search" />
            <el-option label="full（检索+管理）" value="full" />
          </el-select>
        </el-form-item>
        <el-form-item label="绑定知识库">
          <el-select v-model="form.allowed_kb_ids" multiple style="width: 100%">
            <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="提示词">
          <el-input v-model="form.prompt_template" type="textarea" :rows="4"
                    placeholder="（可选）分配给该密钥的回答提示词，如客服口吻/品牌风格；留空=用全局默认或内置" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialog" title="编辑密钥" width="560px">
      <el-form label-width="100px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.key_type" :disabled="true">
            <el-option label="search（只读检索）" value="search" />
            <el-option label="full（检索+管理）" value="full" />
          </el-select>
        </el-form-item>
        <el-form-item label="绑定知识库">
          <el-select v-model="form.allowed_kb_ids" multiple style="width: 100%">
            <el-option v-for="k in kbs" :key="k.id" :label="k.name" :value="k.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="提示词">
          <el-input v-model="form.prompt_template" type="textarea" :rows="5"
                    placeholder="（可选）分配给该密钥的回答提示词；留空=用全局默认或内置" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="plainDialog" title="密钥创建成功（仅显示一次，请立即保存）" width="560px">
      <el-input v-model="plainKey" readonly class="mono">
        <template #append><el-button @click="copyKey">复制</el-button></template>
      </el-input>
      <p style="color: #e6a23c; font-size: 12px">关闭后无法再次查看明文，遗失需重新创建。</p>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import client from '../api/client'
import type { ApiKeyItem, KB } from '../api/types'

const keys = ref<ApiKeyItem[]>([])
const kbs = ref<KB[]>([])
const dialog = ref(false)
const editDialog = ref(false)
const editId = ref<number | null>(null)
const plainDialog = ref(false)
const plainKey = ref('')
const form = reactive({ name: '', key_type: 'search', allowed_kb_ids: [] as number[], prompt_template: '' })

// 分页：每页 8 条，翻页查看，无需长页下滑
const page = ref(1)
const pageSize = 8
const pagedKeys = computed(() =>
  keys.value.slice((page.value - 1) * pageSize, page.value * pageSize),
)

// 知识库 ID -> 名称（按"知识库管理"中的名称展示；查不到时兜底显示 #ID）
function kbName(id: number): string {
  const k = kbs.value.find((x) => x.id === id)
  return k ? k.name : `#${id}`
}

async function load() {
  const { data } = await client.get('/admin/keys')
  keys.value = data
}

async function create() {
  if (!form.name) return
  const { data } = await client.post('/admin/keys', form)
  plainKey.value = data.key || ''
  plainDialog.value = true
  dialog.value = false
  form.name = ''
  form.allowed_kb_ids = []
  form.prompt_template = ''
  load()
}

function openEdit(row: ApiKeyItem) {
  editId.value = row.id
  form.name = row.name
  form.key_type = row.key_type
  form.allowed_kb_ids = [...(row.allowed_kb_ids || [])]
  form.prompt_template = row.prompt_template || ''
  editDialog.value = true
}

async function saveEdit() {
  if (!editId.value || !form.name) return
  await client.patch(`/admin/keys/${editId.value}`, form)
  ElMessage.success('已保存')
  editDialog.value = false
  load()
}

function copyKey() {
  navigator.clipboard?.writeText(plainKey.value)
  ElMessage.success('已复制')
}

async function revoke(row: ApiKeyItem) {
  await ElMessageBox.confirm(`吊销密钥「${row.name}」？吊销后立即失效（可随时恢复）。`, '确认吊销', { type: 'warning' })
  await client.post(`/admin/keys/${row.id}/revoke`)
  ElMessage.success('已吊销，状态为无效')
  load()
}

async function restore(row: ApiKeyItem) {
  await client.post(`/admin/keys/${row.id}/restore`)
  ElMessage.success('已恢复，状态为有效')
  load()
}

async function removeKey(row: ApiKeyItem) {
  await ElMessageBox.confirm(
    `删除密钥「${row.name}」？删除后不可恢复，其会话记忆将一并清除（审计记录保留）。`,
    '确认删除',
    { type: 'warning', confirmButtonText: '删除', confirmButtonClass: 'el-button--danger' },
  )
  await client.delete(`/admin/keys/${row.id}`)
  ElMessage.success('已删除')
  // 删除后修正页码，避免超出总页数
  if (page.value > 1 && keys.value.length <= (page.value - 1) * pageSize) {
    page.value = Math.max(1, page.value - 1)
  }
  load()
}

onMounted(async () => {
  const { data } = await client.get('/admin/kbs')
  kbs.value = data
  await load()
})
</script>
