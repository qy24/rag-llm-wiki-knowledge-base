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
    </div>

    <!-- 消息区 -->
    <div ref="msgBox" class="chat-body">
      <el-empty v-if="messages.length === 0" description="输入问题开始测试" />
      <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
        <div class="avatar" :class="m.role">{{ m.role === 'user' ? '客户' : '客服' }}</div>
        <div class="msg-main">
          <div class="msg-name">
            {{ m.role === 'user' ? '客户' : '客服' }}
            <span v-if="m.role === 'assistant' && m.duration != null" class="msg-duration">⏱ {{ m.duration }}s</span>
          </div>
          <div class="msg-bubble" :class="{ error: m.error }">
            <div class="msg-content">{{ msgText(m.content) }}</div>
            <!-- 客户消息携带的图片 -->
            <div v-if="msgImages(m.content).length" class="msg-imgs">
              <img v-for="(u, j) in msgImages(m.content)" :key="j" :src="u" />
            </div>
            <!-- 检索依据（助手回复） -->
            <template v-if="m.role === 'assistant' && !m.error">
              <el-collapse v-if="m.sources?.length || m.graph?.entities?.length || m.internalImages?.length || m.prompt"
                           class="evidence">
                <el-collapse-item :title="`检索依据（文本 ${m.sources?.length || 0} · 图谱 ${m.graph?.entities?.length || 0} · 图片 ${m.internalImages?.length || 0}）`">
                  <div v-if="m.prompt" style="font-size:12px;margin-bottom:8px">
                    <span style="color:#909399">生效提示词：</span>
                    <el-tag size="small" :type="m.promptSource === 'key' ? 'warning' : 'info'">
                      {{ m.promptSource === 'key' ? '密钥自定义' : (m.promptSource === 'global' ? '全局默认' : '内置默认') }}
                    </el-tag>
                    <div class="evidence-block">{{ m.prompt }}</div>
                  </div>
                  <div v-if="m.searchQuery" class="evidence-hint">检索查询：{{ m.searchQuery }}</div>
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
                    <div class="evidence-hint">图谱命中实体：</div>
                    <div>
                      <el-tag v-for="e in m.graph.entities" :key="e.id" size="small"
                              :type="e.verified ? 'success' : 'info'" style="margin:2px">
                        {{ e.name }}<span style="opacity:.7">[{{ e.type }}]</span>
                      </el-tag>
                    </div>
                    <div v-if="m.graph.relations?.length" class="evidence-hint" style="margin-top:6px">关系：</div>
                    <div v-for="(r, k) in m.graph.relations" :key="k" class="evidence-rel">
                      {{ relLabel(r, m.graph.entities) }}
                    </div>
                  </div>
                  <div v-if="m.internalImages?.length" style="margin-top:6px">
                    <div class="evidence-hint">附带的知识库内部图片：</div>
                    <el-tag v-for="img in m.internalImages" :key="img.doc_id" size="small" style="margin:2px">
                      🖼 {{ img.filename }}
                    </el-tag>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </template>
            <div v-if="m.loading" class="typing"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div class="chat-footer">
      <div class="composer">
        <div v-if="pendingImages.length" class="composer-imgs">
          <div v-for="(u, i) in pendingImages" :key="i" class="img-thumb">
            <img :src="u" />
            <span class="img-del" @click="pendingImages.splice(i, 1)">×</span>
          </div>
        </div>
        <div class="composer-box">
          <el-input
            v-model="inputText"
            type="textarea"
            resize="none"
            class="composer-input"
            :autosize="{ minRows: 1, maxRows: 7 }"
            placeholder="输入问题开始测试…"
            @keydown.enter.exact.prevent="send"
          />
          <div class="composer-bar">
            <div class="composer-left">
              <el-upload
                :auto-upload="false"
                :show-file-list="false"
                accept="image/*"
                multiple
                :disabled="sending || pendingImages.length >= 4"
                :on-change="onPickImage"
              >
                <span class="icon-btn" :class="{ 'is-disabled': sending || pendingImages.length >= 4 }"
                      title="上传图片（最多 4 张）">
                  <svg viewBox="0 0 24 24" width="20" height="20">
                    <rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.6" />
                    <circle cx="8.5" cy="10" r="1.7" fill="currentColor" />
                    <path d="M3 17l5.5-5.5 4 4 3-3L21 17" fill="none" stroke="currentColor" stroke-width="1.6" />
                  </svg>
                </span>
              </el-upload>
              <span class="hint">Enter 发送 · Shift+Enter 换行</span>
            </div>
            <button class="send-btn"
                    :disabled="(!inputText.trim() && !pendingImages.length) || sending || !apiKeyId"
                    @click="send" :title="sending ? '生成中…' : '发送'">
              <svg v-if="!sending" viewBox="0 0 24 24" width="20" height="20">
                <path d="M3.4 20.4l17.4-8.4L3.4 3.6l2.1 7.2 8.2 1.2-8.2 1.2-2.1 7.2z" fill="currentColor" />
              </svg>
              <span v-else class="spin">···</span>
            </button>
          </div>
        </div>
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
// 待发送图片（dataURL），随消息一起发给视觉模型
const pendingImages = ref<string[]>([])
const MAX_IMAGES = 4

// 消息内容兼容：字符串（纯文本）或 OpenAI 视觉片段数组（含图）
function msgText(content: any): string {
  if (typeof content === 'string') return content
  if (Array.isArray(content)) {
    return content.filter((p) => p?.type === 'text').map((p) => p.text).join('\n')
  }
  return String(content ?? '')
}
function msgImages(content: any): string[] {
  if (Array.isArray(content)) {
    return content.filter((p) => p?.type === 'image_url')
      .map((p) => p.image_url?.url).filter(Boolean)
  }
  return []
}

// 选择图片 → 读为 dataURL 缓存（≤8MB，最多 4 张；后端还会压缩）
function onPickImage(file: any) {
  const raw = file?.raw || file?.file
  if (!raw) return
  if (raw.size > 8 * 1024 * 1024) {
    ElMessage.warning('单张图片不能超过 8MB')
    return
  }
  if (!raw.type.startsWith('image/')) {
    ElMessage.warning('仅支持图片文件')
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    if (pendingImages.value.length >= MAX_IMAGES) {
      ElMessage.warning(`最多 ${MAX_IMAGES} 张图片`)
      return
    }
    pendingImages.value.push(String(reader.result))
  }
  reader.readAsDataURL(raw)
}

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

async function send() {
  const text = inputText.value.trim()
  const images = [...pendingImages.value]
  if ((!text && !images.length) || !apiKeyId.value || sending.value) return
  // 组装消息内容：纯文本直接字符串；带图用 OpenAI 视觉片段数组
  let content: string | any[]
  if (images.length) {
    content = []
    if (text) content.push({ type: 'text', text })
    for (const u of images) content.push({ type: 'image_url', image_url: { url: u } })
  } else {
    content = text
  }
  messages.value.push({ role: 'user', content })
  const ask = messages.value.filter((m) => !m.loading).map((m) => ({ role: m.role, content: m.content }))
  messages.value.push({ role: 'assistant', content: '', loading: true })
  sending.value = true
  inputText.value = ''
  pendingImages.value = []
  scrollBottom()
  const t0 = performance.now()
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
    last.duration = Math.round(((performance.now() - t0) / 1000) * 10) / 10
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
  pendingImages.value = []
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
/* ===== 整页：居中卡片式聊天 ===== */
.chat-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 96px);
  background: #f2f4f7;
  overflow: hidden;
}

/* ===== 顶部工具条 ===== */
.chat-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 22px;
  background: #fff;
  border-bottom: 1px solid #ececf0;
  flex-wrap: wrap;
  flex-shrink: 0;
}

/* ===== 消息区：居中对齐 + 纵向滚动 ===== */
.chat-body {
  flex: 1;
  overflow-y: auto;
  padding: 22px 16px;
  scroll-behavior: smooth;
}
.chat-body::-webkit-scrollbar { width: 6px; }
.chat-body::-webkit-scrollbar-thumb { background: #cfd6de; border-radius: 3px; }
.chat-body > * { max-width: 880px; margin-left: auto; margin-right: auto; }
.chat-body .el-empty { padding: 80px 0 0; }

/* ===== 消息行：头像 + 主体 ===== */
.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}
.msg-row.user { flex-direction: row-reverse; }
.avatar {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: #fff;
  user-select: none;
}
.avatar.assistant { background: linear-gradient(135deg, #4facfe, #00c9b7); }
.avatar.user { background: linear-gradient(135deg, #667eea, #764ba2); }

.msg-main { max-width: min(78%, 720px); display: flex; flex-direction: column; }
.msg-row.user .msg-main { align-items: flex-end; }

.msg-name {
  font-size: 12px;
  color: #9aa3af;
  margin: 0 4px 5px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.msg-duration { color: #b3a14a; font-size: 11px; }

/* ===== 气泡 ===== */
.msg-bubble {
  padding: 10px 14px 11px;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
  border: 1px solid #f0f0f3;
  min-width: 60px;
}
.msg-row.user .msg-bubble {
  background: linear-gradient(135deg, #5b8def, #4f7fe8);
  color: #fff;
  border: none;
  border-top-right-radius: 4px;
}
.msg-row.assistant .msg-bubble {
  border-top-left-radius: 4px;
}
.msg-content {
  font-size: 14.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-row.assistant .msg-content { color: #2b303b; }
.msg-row.user .msg-content { color: #fff; }
.msg-bubble.error .msg-content { color: #f56c6c; }

/* 消息内图片 */
.msg-imgs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.msg-imgs img {
  max-width: 160px;
  max-height: 160px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.6);
}

/* 思考中动画 */
.typing {
  display: flex;
  gap: 4px;
  padding: 6px 0 2px;
}
.typing span {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #b6c2d1;
  animation: blink 1.2s infinite;
}
.typing span:nth-child(2) { animation-delay: .2s; }
.typing span:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%, 80%, 100% { opacity: .25 } 40% { opacity: 1 } }

/* ===== 检索依据 ===== */
.evidence { margin-top: 8px; background: transparent; border: none; }
.evidence :deep(.el-collapse-item__header) {
  font-size: 12px; color: #98a2b3; background: transparent;
  height: 28px; border: none;
}
.evidence :deep(.el-collapse-item__wrap) { background: transparent; border: none; }
.evidence-block {
  margin-top: 4px; color: #606266; background: #f7f8fa;
  border-radius: 6px; padding: 6px 8px; white-space: pre-wrap;
  max-height: 120px; overflow: auto; font-size: 12px;
}
.evidence-hint { font-size: 12px; color: #98a2b3; margin: 6px 0 4px; }
.evidence-rel { font-size: 12px; color: #606266; padding: 1px 0; }
.source-item {
  border: 1px solid #eef1f5; border-radius: 8px; padding: 6px 10px;
  margin-bottom: 6px; background: #fff;
}
.source-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.source-ref { font-size: 12px; color: #606266; }
.source-score { font-size: 11px; color: #c0c4cc; }
.source-content { font-size: 12px; color: #666; max-height: 90px; overflow: auto; white-space: pre-wrap; }

/* ===== 底部输入区（居中卡片） ===== */
.chat-footer {
  flex-shrink: 0;
  padding: 12px 16px 16px;
  background: #f2f4f7;
}
.composer {
  max-width: 880px;
  margin: 0 auto;
  background: #fff;
  border-radius: 16px;
  border: 1px solid #e4e7ec;
  box-shadow: 0 4px 16px rgba(16, 24, 40, 0.06);
  padding: 6px 6px 4px;
  transition: border-color .2s, box-shadow .2s;
}
.composer:focus-within {
  border-color: #4f7fe8;
  box-shadow: 0 4px 16px rgba(79, 127, 232, 0.14);
}
.composer-imgs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 8px 2px;
}
.img-thumb { position: relative; display: inline-block; }
.img-thumb img { width: 62px; height: 62px; object-fit: cover; border-radius: 10px; }
.img-del {
  position: absolute; top: -7px; right: -7px;
  width: 18px; height: 18px; line-height: 16px; text-align: center;
  border-radius: 50%; background: rgba(0, 0, 0, 0.55); color: #fff;
  font-size: 13px; cursor: pointer;
}

/* 输入框：随内容 1→7 行自动增高，再多内部滚动 */
.composer-input :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none;
  padding: 10px 12px 6px;
  font-size: 14.5px;
  line-height: 1.7;
  resize: none;
  max-height: calc(1.7em * 7 + 16px);   /* 最多 7 行，超出滚动 */
  overflow-y: auto;
}
.composer-input :deep(.el-textarea__inner:focus) { box-shadow: none; }
.composer-input :deep(.el-textarea__inner::-webkit-scrollbar) { width: 5px; }
.composer-input :deep(.el-textarea__inner::-webkit-scrollbar-thumb) { background: #d2d8e0; border-radius: 3px; }

/* 底部操作行：左图标区 + 右发送 */
.composer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 6px 4px 4px;
}
.composer-left { display: flex; align-items: center; gap: 10px; }
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px; height: 32px;
  border-radius: 8px;
  color: #7a8494;
  cursor: pointer;
  transition: background .15s, color .15s;
}
.icon-btn:hover { background: #eef2f8; color: #4f7fe8; }
.icon-btn.is-disabled { color: #c3cad4; cursor: not-allowed; }
.hint { font-size: 12px; color: #b0b8c4; }
.send-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px; height: 38px;
  border: none;
  border-radius: 11px;
  background: linear-gradient(135deg, #4f7fe8, #6a5ae0);
  color: #fff;
  cursor: pointer;
  transition: transform .12s, box-shadow .15s, opacity .2s;
  box-shadow: 0 3px 10px rgba(79, 127, 232, 0.3);
}
.send-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 5px 14px rgba(79, 127, 232, 0.38); }
.send-btn:active:not(:disabled) { transform: translateY(0); }
.send-btn:disabled { background: #c8d0da; box-shadow: none; cursor: not-allowed; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
