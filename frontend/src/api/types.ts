export interface UserInfo {
  id: number
  username: string
  role: string
}

export interface KB {
  id: number
  name: string
  description: string
  chunk_size: number
  chunk_overlap: number
  graph_extraction_enabled: boolean
  llm_base_url: string
  layout_type?: 'auto' | 'layered' | 'force'
  llm_model: string
  created_at: string
}

export interface DocumentItem {
  id: number
  kb_id: number
  filename: string
  file_size: number
  file_type: string
  status: string
  error_msg: string
  page_count: number
  created_at: string
}

export interface ChunkItem {
  id: number
  kb_id: number
  doc_id: number
  seq: number
  content: string
  metadata: Record<string, unknown>
  embedding_status: string
}

export interface EntityItem {
  id: string
  kb_id: number
  name: string
  type: string
  properties: Record<string, unknown>
  source_doc_id?: number | null
  source_chunk_id?: number | null
  verified: boolean
}

export interface RelationItem {
  id: string
  kb_id: number
  source_entity_id: string
  target_entity_id: string
  relation_type: string
  properties: Record<string, unknown>
  verified: boolean
  source_name?: string
  target_name?: string
}

export interface ApiKeyItem {
  id: number
  name: string
  key_type: string
  allowed_kb_ids: number[]
  expires_at: string | null
  revoked: boolean
  last_used_at: string | null
  created_at: string
  prompt_template?: string
  key?: string
}

export interface SearchResult {
  query: string
  chunks: Array<{
    chunk_id: number
    kb_id: number
    doc_id: number
    content: string
    metadata: Record<string, unknown>
    score: number
    source: string
  }>
  graph: { entities: EntityItem[]; relations: RelationItem[] }
  permission_scope: { kb_ids: number[] }
  kb_names?: Record<number, string>
}

export interface Dashboard {
  kb_count: number
  doc_count: number
  chunk_count: number
  vector_count: number
  entity_count: number
  relation_count: number
  doc_status: Record<string, number>
  pending_tasks: number
}

export interface AuditItem {
  id: number
  action: string
  query: string
  result_summary: Record<string, any>
  ip: string
  rating?: string
  note?: string
  created_at: string | null
}
