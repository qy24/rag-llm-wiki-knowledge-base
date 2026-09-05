"""文本切分：递归分隔符切分，按块处理并保留跨块重叠。

输入 parsing.extract_blocks 的输出，输出 list[(content, meta)]。
"""
from __future__ import annotations

_SEPARATORS = ["\n\n", "\n", "。", "；", "，", " ", ""]


def split_blocks(blocks: list[dict], chunk_size: int, overlap: int) -> list[tuple[str, dict]]:
    results: list[tuple[str, dict]] = []
    seq = 0
    carry = ""  # 上一块的尾巴，实现跨块重叠

    for block in blocks:
        content = block["content"]
        meta = block.get("meta", {})
        if carry:
            content = carry + "\n" + content
            carry = ""
        pieces = _split_text(content, chunk_size, overlap)
        for piece in pieces:
            seq += 1
            results.append((piece, {**meta, "seq": seq}))
        if pieces and len(pieces) > 1:
            carry = pieces[-1][-overlap:] if overlap else ""
        elif pieces and len(content) > chunk_size:
            carry = content[-overlap:] if overlap else ""

    return results


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            cut = _find_cut(text, start, end)
            if cut:
                end = cut
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        # 仅当本块长度 > overlap 时才重叠（否则 overlap 会回看已切区域，
        # 导致 start 每次只前进 1 字符、产生大量近重复碎片块——英文长段落常见）
        start = end - overlap if (end - start) > overlap else end
    return chunks


def _find_cut(text: str, start: int, end: int) -> int | None:
    """在 [start,end] 内找最靠后的分隔符位置。"""
    window = text[start:end]
    for sep in _SEPARATORS[:-1]:
        idx = window.rfind(sep)
        if idx > 0:
            return start + idx + len(sep)
    return None
