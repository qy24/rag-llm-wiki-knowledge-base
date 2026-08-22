// 知识库选择记忆：进入图谱/文档/切分块/检索调试台时记住上次选择，不用每次重选
const KEY = 'kb_last_selected'

export function getLastKb(): number | undefined {
  const v = localStorage.getItem(KEY)
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : undefined
}

export function setLastKb(id: number | undefined) {
  if (id) localStorage.setItem(KEY, String(id))
  else localStorage.removeItem(KEY)
}
