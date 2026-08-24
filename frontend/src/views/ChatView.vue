<template>
  <div class="page-card chat-page">
    <!-- 顶栏：密钥选择 + 参数 -->
    <div class="chat-toolbar">
      <el-select v-model="apiKeyId" placeholder="选择测试密钥（检索范围=密钥绑定知识库）" style="width: 300px" filterable>
        <el-option v-for="k in activeKeys" :key="k.id" :label="keyLabel(k)" :value="k.id" />
      </el-select>
      <el-tag v-if="selectedKey" size="small" type="info" style="max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
        {{ scopeLabel }}
      </el-tag>
      <el-tooltip placement="top" :content="'图谱深度：0=仅文本命中；1=点名实体扩展1层关系（推荐）；2/3=扩展更多层，可能带出无关数据'">
        <el-select v-model="graphDepth" style="width: 150px" :disabled="sending">
          <el-option label="图谱深度 0（仅文本）" :value="0" />
          <el-option label="图谱深度 1（推荐）" :value="1" />
          <el-option label="图谱深度 2" :value="2" />
          <el-option label="图谱深度 3" :value="3" />
        </el-select>
      </el-tooltip>
      <el-button :disabled="!messages.length || sending" @click="clearChat">清空对话</el-button>
      <span style="color:#909399;font-size:12px;margin-left:6px">
        模拟客服场景输入问题，检索范围与提示词与真实密钥调用完全一致（不越权）
      </span>
    </div>

    <!-- 消息区 -->
    <div ref="msgBox" class="chat-body">
      <el-empty v-if="messages.length === 0" description="输入你的问题开始测试，例如：「客户说产品有异响，怎么回复？」" />
      <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
        <div class="msg-bubble">
          <div v-if="m.role === 'user'" class="msg-label">我（客服）</div>
          <div v-else class="msg-label">系统助手</div>
          <div class="msg-content" :class="{ error: m.error }">{{ m.content }}</div>
          <!-- 检索依据（助手回复） -->
          <template v-if="m.role === 'assistant' && !m.error">
            <el-collapse v-if="m.sources?.length || m.graph?.entities?.length || m.internalImages?.length || m.prompt"
                         style="margin-top:8px">
              <el-collapse-item :title="`检索依据（文本 ${m.sources?.length || 0} 条 · 图谱实体 ${m.graph?.entities?.length || 0} 个 · 内部图片 ${m.internalImages?.length || 0} 张）`">
                <div v-if="m.prompt" style="font-size:12px;margin-bottom:8px">
                  <span style="color:#909399">生效提示词：</span>
                  <el-tag size="small" :type="m.promptSource === 'key' ? 'warning' : 'info'">
                    {{ m.promptSource === 'key' ? '密钥自定义' : (m.promptSource === 'global' ? '全局默认' : '内置默认') }}
                  </el-tag>
                  <div style="margin-top:4px;color:#606266;background:#f7f8fa;border-radius:4px;padding:6px 8px;white-space:pre-wrap;max-height:120px;overflow:auto">
                    {{ m.prompt }}
                  </div>
                </div>
                <div v-if="m.searchQuery" style="font-size:12px;color:#909399;margin-bottom:6px">
                  检索查询：{{ m.searchQuery }}
                </div>
                <div v-if="m.sources?.length">
                  <div v-for="(c, j) in m.sources" :key="j" class="source-item">
                    <div class="source-head">
                      <el-tag size="small" :type="c.source === 'graph' ? 'success' : 'primary'">{{ c.source }}</el-tag>
                      <span class="source-ref">{{ c.doc_name }}{{ c.metadata?.page ? ' 第' + c.metadata.page + '页' : '' }}</span>
                      <span class="source-score">score {{ c.score }}</span>
                    </div>
                    <div class="source-content">{{ c.content }}</div>
                  </div>
                </div>
                <div v-if="m.graph?.entities?.length" style="margin-top:6px">
                  <div style="font-size:12px;color:#909399;margin-bottom:4px">图谱命中实体：</div>
                  <div>
                    <el-tag v-for="e in m.graph.entities" :key="e.id" size="small"
                            :type="e.verified ? 'success' : 'info'" style="margin:2px">
                      {{ e.name }}<span style="opacity:.7">[{{ e.type }}]</span>
                    </el-tag>
                  </div>
                  <div v-if="m.graph.relations?.length" style="font-size:12px;color:#909399;margin:6px 0 4px">关系：</div>
                  <div v-for="(r, k) in m.graph.relations" :key="k" style="font-size:12px;color:#606266;padding:1px 0">
                    {{ relLabel(r, m.graph.entities) }}
                  </div>
                </div>
                <div v-if="m.internalImages?.length" style="margin-top:6px">
                  <div style="font-size:12px;color:#909399;margin-bottom:4px">附带的知识库内部图片：</div>
                  <el-tag v-for="img in m.internalImages" :key="img.doc_id" size="small" style="margin:2px">
                    🖼 {{ img.filename }}
                  </el-tag>
                </div>
              </el-collapse-item>
            </el-collapse>
          </template>
          <div v-if="m.loading" style="margin-top:6px;font-size:12px;color:#909399">正在检索并生成回复…</div>
        </div>
      </div>
    </div>

    <!-- 输入区：输入框 + 右侧发送按钮 -->
    <div class="chat-input">
      <el-input
        v-model="inputText"
        type="textarea"
        :rows="2"
        resize="none"
        placeholder="模拟客服/客户诉说问题，Enter 发送，Shift+Enter 换行"
        @keydown.enter.exact.prevent="send"
      />
      <div class="chat-input-actions">
        <el-button type="primary" :disabled="!apiKeyId || sending" @click="send" style="width: 100%">
          {{ sending ? '生成中…' : '发送' }}
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import client from '../api/client'
import type { KB } from '../api/types'

interface ChatSource {
  chunk_id?: number
  doc_name?: string
  content: string
  score?: number
  source?: string
  metadata?: { page?: string | number; [k: string]: any }
}
interface GraphEntity { id: string; name: string; type: string; verified?: boolean }
interface GraphRelation { id?: string; source_entity_id: string; target_entity_id: string; relation_type: string }
interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  loading?: boolean
  error?: boolean
  sources?: ChatSource[]
  graph?: { entities: GraphEntity[]; relations: GraphRelation[] }
  internalImages?: { doc_id: number; filename: string }[]
  searchQuery?: string
  prompt?: string
  promptSource?: 'key' | 'global' | 'builtin'
}
interface ApiKeyItem {
  id: number
  name: string
  key_type: string
  revoked: boolean
  allowed_kb_ids: number[]
  prompt_template?: string
}

const kbs = ref<KB[]>([])
const keys = ref<ApiKeyItem[]>([])
const apiKeyId = ref<number>()
const graphDepth = ref(1)
const messages = ref<ChatMsg[]>([])
const inputText = ref('')
const sending = ref(false)
const msgBox = ref<HTMLElement>()

const activeKeys = computed(() => keys.value.filter((k) => !k.revoked))
const selectedKey = computed(() => keys.value.find((k) => k.id === apiKeyId.value))

function keyLabel(k: ApiKeyItem): string {
  const scopes = (k.allowed_kb_ids || []).map((id) => kbName(id)).join('、') || '未绑定'
  return `${k.name}（${scopes}）${k.prompt_template ? ' · 自定义提示词' : ''}`
}
const scopeLabel = computed(() => {
  const k = selectedKey.value
  if (!k) return ''
  const names = (k.allowed_kb_ids || []).map((id) => kbName(id)).join('、')
  return `检索范围：${names || '无'}${k.prompt_template ? ' · 自定义提示词' : ''}`
})
function kbName(id: number): string {
  return kbs.value.find((x) => x.id === id)?.name || `#${id}`
}

function relLabel(r: GraphRelation, entities: GraphEntity[]): string {
  const name = (id: string) => entities.find((e) => e.id === id)?.name || id.slice(0, 8)
  return `${name(r.source_entity_id)} -${r.relation_type}-> ${name(r.target_entity_id)}`
}

function scrollBottom() {
  nextTick(() => {
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
  })
}

// ---- 对话持久化（localStorage）：刷新/重进页面自动恢复，清空时删除 ----
const STORE_KEY = 'kb-chat-history'

function saveHistory() {
  try {
    const saveable = messages.value
      .filter((m) => !m.loading)
      .slice(-50) // 只保留最近 50 条，避免撑爆 localStorage
    localStorage.setItem(STORE_KEY, JSON.stringify(saveable))
  } catch {
    /* 存储失败（超限等）静默忽略，不影响对话 */
  }
}

function loadHistory() {
  try {
    const raw = localStorage.getItem(STORE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw)
    if (Array.isArray(saved)) messages.value = saved
  } catch {
    /* 损坏的历史数据直接丢弃 */
  }
}

watch(messages, saveHistory, { deep: true })

async function send() {  const text = inputText.value.trim()
  if (!text || !apiKeyId.value || sending.value) return
  messages.value.push({ role: 'user', content: text })
  const ask = messages.value.filter((m) => !m.loading).map((m) => ({ role: m.role, content: m.content }))
  messages.value.push({ role: 'assistant', content: '', loading: true })
  sending.value = true
  inputText.value = ''
  scrollBottom()
  try {
    const { data } = await client.post('/admin/chat', {
      api_key_id: apiKeyId.value,
      messages: ask,
      graph_depth: graphDepth.value,
    })
    const last = messages.value[messages.value.length - 1]
    last.loading = false
    last.content = data.answer
    last.sources = data.sources || []
    last.graph = data.graph || { entities: [], relations: [] }
    last.internalImages = data.internal_images || []
    last.searchQuery = data.search_query
    last.prompt = data.prompt || ''
    last.promptSource = data.prompt_source || 'builtin'
  } catch (e: any) {
    const last = messages.value[messages.value.length - 1]
    last.loading = false
    last.error = true
    last.content = e?.response?.data?.detail || `调用失败：${e?.message || e}`
  } finally {
    sending.value = false
    scrollBottom()
  }
}

function clearChat() {
  messages.value = []
  inputText.value = ''
  localStorage.removeItem(STORE_KEY)
}

onMounted(async () => {
  loadHistory()
  scrollBottom()
  const [{ data: kbsData }, { data: keysData }] = await Promise.all([
    client.get('/admin/kbs'),
    client.get('/admin/keys'),
  ])
  kbs.value = kbsData
  keys.value = keysData
  const valid = keysData.filter((k: ApiKeyItem) => !k.revoked)
  if (apiKeyId.value && valid.some((k: ApiKeyItem) => k.id === apiKeyId.value)) {
    // 保留已恢复的密钥选择
  } else if (valid.length) {
    apiKeyId.value = valid[0].id
  }
})
</script>

<style scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 100px);
}
.chat-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid #eee;
  flex-wrap: wrap;
}
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  background: #f7f8fa;
}
.msg-row {
  display: flex;
  margin-bottom: 14px;
}
.msg-row.user {
  justify-content: flex-end;
}
.msg-row.assistant {
  justify-content: flex-start;
}
.msg-bubble {
  max-width: 76%;
  background: #fff;
  border-radius: 8px;
  padding: 10px 14px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}
.msg-row.user .msg-bubble {
  background: #e8f3ff;
}
.msg-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}
.msg-content {
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-content.error {
  color: #f56c6c;
}
.source-item {
  border: 1px solid #eee;
  border-radius: 6px;
  padding: 6px 8px;
  margin-bottom: 6px;
}
.source-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.source-ref {
  font-size: 12px;
  color: #606266;
}
.source-score {
  font-size: 11px;
  color: #c0c4cc;
}
.source-content {
  font-size: 12px;
  color: #666;
  max-height: 90px;
  overflow: auto;
  white-space: pre-wrap;
}
.chat-input {
  display: flex;
  align-items: stretch;
  gap: 10px;
  padding: 10px 12px;
  border-top: 1px solid #eee;
  background: #fff;
}
.chat-input :deep(.el-textarea) {
  flex: 1;
}
.chat-input-actions {
  display: flex;
  align-items: center;
  width: 90px;
  flex-shrink: 0;
}
</style>
