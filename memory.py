import json
import math
import os
import random as _random
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ── numpy 为可选依赖 ──
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False
    np = None  # type: ignore

MEMORY_DIR = Path(__file__).parent / "memory_data"


# ── 纯 Python 向量运算（numpy 不可用时的回退） ──
def _py_zeros(n: int) -> List[float]:
    return [0.0] * n


def _py_norm(vec: List[float]) -> float:
    return math.sqrt(sum(v * v for v in vec))


def _py_dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _py_cosine(vec1: List[float], vec2: List[float]) -> float:
    n1, n2 = _py_norm(vec1), _py_norm(vec2)
    return 0.0 if n1 == 0 or n2 == 0 else _py_dot(vec1, vec2) / (n1 * n2)


def _atomic_write(filepath: Path, data: Any) -> None:
    """原子写入 JSON 文件，避免写入过程中断导致数据损坏。"""
    dirpath = filepath.parent
    dirpath.mkdir(parents=True, exist_ok=True)
    fd, tmppath = tempfile.mkstemp(dir=str(dirpath), suffix=".tmp", prefix=".mem_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmppath, str(filepath))
    except Exception:
        try:
            os.unlink(tmppath)
        except OSError:
            pass
        raise


# ============================================================================
# WorkingMemory - 工作记忆
# ============================================================================

class WorkingMemory:
    """工作记忆，存储当前会话的最近消息。

    Attributes:
        messages: 消息列表，每条消息包含 role, content, time。
        max_messages: 最大消息数量。
    """

    def __init__(self, max_messages: int = 50):
        """初始化工作记忆。

        Args:
            max_messages: 最大保留消息数，超过则丢弃最旧的消息。
        """
        self.messages: List[Dict[str, Any]] = []
        self.max_messages = max_messages

    def add(self, role: str, content: str) -> None:
        """添加一条消息。

        Args:
            role: 消息角色（如 'user', 'assistant'）。
            content: 消息内容。
        """
        self.messages.append({
            "role": role,
            "content": content,
            "time": datetime.now().isoformat(),
        })
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def get_context(self) -> List[Dict[str, Any]]:
        """获取全部消息上下文。

        Returns:
            消息列表。
        """
        return self.messages

    def clear(self) -> None:
        """清空所有消息。"""
        self.messages = []

    def summarize(self) -> str:
        """生成消息的简要文本摘要。

        Returns:
            多行文本，每行一条消息的摘要（截断至 80 字符）。
        """
        if not self.messages:
            return ""
        lines: List[str] = []
        for m in self.messages:
            text = str(m["content"])[:80]
            lines.append(f"{m['role']}: {text}")
        return "\n".join(lines)

    def export(self) -> str:
        """导出消息为可读文本。

        Returns:
            格式化的消息文本，包含时间和角色标记。
        """
        lines: List[str] = []
        for m in self.messages:
            role = "\u4f60" if m["role"] == "user" else "AI"
            lines.append(f"[{m['time']}] {role}: {m['content']}")
        return "\n\n".join(lines)

    def generate_summary(self) -> Dict[str, Any]:
        """基于规则的关键信息提取，生成结构化的会话摘要。

        从当前消息列表中提取以下信息：
        - 决定 (decisions): 用户或 AI 做出的决策
        - 行动项 (action_items): 需要执行的任务或待办事项
        - 关键事实 (key_facts): 重要的陈述或信息
        - 情感标记 (emotional_markers): 积极/消极的情感表达

        Returns:
            结构化摘要字典，包含 decisions, action_items, key_facts, emotional_markers。
        """
        # 决策识别模式
        decision_patterns = [
            r"(?:我|我们|你|AI)\s*(?:决定|确认|确定|选择|选定|拍板|定下来)\s*(.+)",
            r"(?:方案|计划|策略)\s*(?:是|为|确定[为]?)\s*(.+)",
            r"(?:最终|最后)\s*(?:采用|使用|选择)\s*(.+)",
            r"(?:同意|批准|认可)\s*(.+)",
            r"(?:就这么|定了|敲定|定稿)\s*(.+)",
        ]

        # 行动项识别模式
        action_patterns = [
            r"(?:需要|必须|要|得|应该|应当|马上|立刻|尽快)\s*(?:做|完成|处理|实现|开发|修复|提交|部署|测试|检查|准备|写|改|优化|更新)\s*(.+)",
            r"(?:TODO|FIXME|HACK|XXX)[:：]?\s*(.+)",
            r"(?:下一步|接下来|然后|接着)\s*(.+)",
            r"(?:任务|待办|行动项)[:：]?\s*(.+)",
            r"(?:我会|我去|我来|让我|由我)\s*(.+)",
        ]

        # 关键事实识别模式
        fact_patterns = [
            r"(?:根据|按照|依据|基于|参考)\s*(.+)",
            r"(?:重要|关键|核心|根本|主要)\s*(?:的是|在于|是|为)\s*(.+)",
            r"(?:注意|记住|别忘了|请留意)\s*(.+)",
            r"(?:事实[上]?|实际上|本质上|归根结底)\s*(.+)",
            r"(?:结论|结果|总结|归纳)[:：]?\s*(.+)",
        ]

        # 情感标记识别模式
        positive_patterns = [
            r"(?:很好|不错|太棒了|非常好|完美|很满意|满意|高效|优秀|出色|厉害|赞)",
            r"(?:开心|高兴|愉快|欣喜|欣慰|放心|轻松)",
            r"(?:感谢|谢谢|感激|感恩|多谢)",
            r"(?:成功|顺利|进展|突破|达成)",
        ]
        negative_patterns = [
            r"(?:不好|糟糕|很差|有问题|缺陷|错误|失败|不行|无法|不能|困难|麻烦)",
            r"(?:担心|焦虑|不安|紧张|害怕|失望|沮丧|生气|愤怒)",
            r"(?:抱歉|对不起|遗憾|可惜|遗憾)",
            r"(?:卡住|阻塞|阻碍|瓶颈|延迟)",
        ]

        all_text = " ".join([str(m["content"]) for m in self.messages])

        decisions: List[str] = []
        action_items: List[str] = []
        key_facts: List[str] = []
        emotional_markers: List[Dict[str, str]] = []

        for pattern in decision_patterns:
            for m in re.finditer(pattern, all_text):
                item = m.group(1).strip().rstrip("。，.!！,?？")
                if item and len(item) > 1 and item not in decisions:
                    decisions.append(item)

        for pattern in action_patterns:
            for m in re.finditer(pattern, all_text):
                item = m.group(1).strip().rstrip("。，.!！,?？")
                if item and len(item) > 1 and item not in action_items:
                    action_items.append(item)

        for pattern in fact_patterns:
            for m in re.finditer(pattern, all_text):
                item = m.group(1).strip().rstrip("。，.!！,?？")
                if item and len(item) > 1 and item not in key_facts:
                    key_facts.append(item)

        for pattern in positive_patterns:
            for m in re.finditer(pattern, all_text):
                emotional_markers.append({
                    "sentiment": "positive",
                    "expression": m.group(0).strip(),
                    "source": "user" if "user" in str(m.string).lower() else "unknown",
                })

        for pattern in negative_patterns:
            for m in re.finditer(pattern, all_text):
                emotional_markers.append({
                    "sentiment": "negative",
                    "expression": m.group(0).strip(),
                    "source": "user" if "user" in str(m.string).lower() else "unknown",
                })

        return {
            "decisions": decisions[:10],
            "action_items": action_items[:10],
            "key_facts": key_facts[:10],
            "emotional_markers": emotional_markers[:10],
            "message_count": len(self.messages),
            "generated_at": datetime.now().isoformat(),
        }


# ============================================================================
# EpisodicMemory - 情景记忆
# ============================================================================

class EpisodicMemory:
    """情景记忆，存储过去的会话摘要（情景）。

    Attributes:
        episodes: 情景列表，每条包含 title, summary, tags, time, importance。
        file: 持久化文件路径。
    """

    def __init__(self):
        """初始化情景记忆，从磁盘加载已有数据。"""
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.file: Path = MEMORY_DIR / "episodes.json"
        self.episodes: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        """从磁盘加载情景数据。"""
        if self.file.exists():
            with open(self.file, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self) -> None:
        """原子写入情景数据到磁盘。"""
        _atomic_write(self.file, self.episodes)

    def add(
        self,
        title: str,
        summary: str,
        tags: Optional[List[str]] = None,
        importance: int = 5,
    ) -> Dict[str, Any]:
        """添加一条情景记忆。

        Args:
            title: 情景标题。
            summary: 情景摘要。
            tags: 标签列表。
            importance: 重要性评分（1-10），1 为最低，10 为最高，默认 5。

        Returns:
            添加的情景字典。
        """
        episode = {
            "title": title,
            "summary": summary,
            "tags": tags or [],
            "time": datetime.now().isoformat(),
            "importance": max(1, min(10, importance)),
        }
        self.episodes.append(episode)
        if len(self.episodes) > 100:
            self.episodes = self.episodes[-100:]
        self._save()
        return episode

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """关键词搜索情景记忆。

        Args:
            query: 搜索查询字符串。
            limit: 最大返回数量。

        Returns:
            匹配的情景列表（按时间倒序）。
        """
        results: List[Dict[str, Any]] = []
        q = query.lower()
        for ep in reversed(self.episodes):
            if q in ep["title"].lower() or q in ep["summary"].lower():
                results.append(ep)
            if len(results) >= limit:
                break
        return results

    def recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        """获取最近的情景记忆。

        Args:
            limit: 最大返回数量。

        Returns:
            最近的情景列表。
        """
        return self.episodes[-limit:]

    def all(self) -> List[Dict[str, Any]]:
        """获取全部情景记忆。

        Returns:
            所有情景的列表。
        """
        return self.episodes

    def get_important(self, threshold: int = 5) -> List[Dict[str, Any]]:
        """获取重要性达到阈值的情景记忆。

        Args:
            threshold: 重要性阈值（1-10），默认 5。

        Returns:
            重要性 >= threshold 的情景列表（按时间倒序）。
        """
        return sorted(
            [ep for ep in self.episodes if ep.get("importance", 5) >= threshold],
            key=lambda x: x.get("time", ""),
            reverse=True,
        )

    def consolidate(self, importance_threshold: int = 5) -> Dict[str, Any]:
        """记忆巩固：低重要性记忆压缩为摘要，高重要性记忆保留详情。

        将重要性低于阈值的多条情景合并为一条摘要，减少存储占用。
        高重要性情景保持原样。

        Args:
            importance_threshold: 重要性阈值，低于此值的记忆将被压缩。

        Returns:
            包含 compressed_count, kept_count, summary 的字典。
        """
        high_imp = [ep for ep in self.episodes if ep.get("importance", 5) >= importance_threshold]
        low_imp = [ep for ep in self.episodes if ep.get("importance", 5) < importance_threshold]

        compressed_count = len(low_imp)
        if compressed_count == 0:
            self.episodes = high_imp
            self._save()
            return {"compressed_count": 0, "kept_count": len(high_imp), "summary": ""}

        # 生成低重要性记忆的压缩摘要
        titles = [ep.get("title", "") for ep in low_imp]
        combined = "；".join([f"{ep.get('title', '')}: {ep.get('summary', '')[:100]}" for ep in low_imp])
        consolidated_summary = (
            f"[已压缩 {compressed_count} 条低重要性记忆] "
            f"涵盖主题: {', '.join(titles[:5])}"
            f"{'...' if len(titles) > 5 else ''}"
        )

        consolidated_episode = {
            "title": f"记忆巩固 {datetime.now().strftime('%m-%d %H:%M')}",
            "summary": consolidated_summary,
            "tags": [],
            "time": datetime.now().isoformat(),
            "importance": 3,
            "consolidated": True,
            "original_count": compressed_count,
            "original_content": combined,
        }

        self.episodes = high_imp + [consolidated_episode]
        self._save()

        return {
            "compressed_count": compressed_count,
            "kept_count": len(high_imp),
            "summary": consolidated_summary,
        }


# ============================================================================
# TFIDFSearch - 基础 TF-IDF 搜索（保持兼容）
# ============================================================================

class TFIDFSearch:
    """基于 TF-IDF 的关键词搜索（原有实现，保持兼容）。

    Attributes:
        documents: 文档文本列表。
        idf: 逆文档频率字典。
        doc_freq: 文档频率字典。
    """

    def __init__(self):
        self.documents: List[str] = []
        self.idf: Dict[str, float] = {}
        self.doc_freq: Dict[str, int] = {}

    def add_document(self, text: str) -> None:
        """添加文档并更新 TF-IDF 索引。

        Args:
            text: 文档文本。
        """
        terms = self._tokenize(text.lower())
        self.documents.append(text)
        for term in set(terms):
            self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
        self._update_idf()

    def _tokenize(self, text: str) -> List[str]:
        """分词：去除标点、小写化、按空白分割。

        Args:
            text: 输入文本。

        Returns:
            词语列表。
        """
        text = re.sub(r"[^\w\s]", "", text.lower())
        return text.split()

    def _update_idf(self) -> None:
        """根据当前文档集合更新 IDF 值。"""
        n = len(self.documents)
        for term, freq in self.doc_freq.items():
            self.idf[term] = math.log(1 + n / (1 + freq))

    def _tfidf(self, terms: List[str]) -> Dict[str, float]:
        """计算词语列表的 TF-IDF 分数。

        Args:
            terms: 词语列表。

        Returns:
            词语到 TF-IDF 分数的映射。
        """
        scores: Dict[str, float] = {}
        term_counts: Dict[str, int] = {}
        for term in terms:
            term_counts[term] = term_counts.get(term, 0) + 1
        for term, count in term_counts.items():
            scores[term] = (count / len(terms)) * self.idf.get(term, 0)
        return scores

    def search(self, query: str) -> List[Tuple[int, float]]:
        """搜索与查询最相关的文档。

        Args:
            query: 查询字符串。

        Returns:
            (文档索引, 相关度分数) 列表，按分数降序排列。
        """
        query_terms = self._tokenize(query.lower())
        query_tfidf = self._tfidf(query_terms)

        scores: List[Tuple[int, float]] = []
        for idx, doc in enumerate(self.documents):
            doc_terms = self._tokenize(doc.lower())
            doc_tfidf = self._tfidf(doc_terms)
            dot = sum(query_tfidf.get(t, 0) * doc_tfidf.get(t, 0) for t in query_terms)
            scores.append((idx, dot))

        return sorted(scores, key=lambda x: x[1], reverse=True)


# ============================================================================
# VectorMemory - 向量化语义检索
# ============================================================================

class VectorMemory:
    """向量化语义记忆，使用 TF-IDF 向量 + 余弦相似度做语义检索。

    优先使用 numpy，未安装时自动回退为纯 Python 列表实现。

    Attributes:
        vocabulary: 词汇表，词 -> 索引。
        idf: 逆文档频率字典。
        doc_freq: 文档频率字典。
        doc_texts: 文档文本列表。
        doc_metadata: 文档元数据列表。
        doc_vectors: 文档 TF-IDF 向量列表。
    """

    def __init__(self):
        """初始化向量记忆。"""
        self.vocabulary: Dict[str, int] = {}
        self.idf: Dict[str, float] = {}
        self.doc_freq: Dict[str, int] = {}
        self.doc_texts: List[str] = []
        self.doc_metadata: List[Dict[str, Any]] = []
        self.doc_vectors: List[Any] = []  # np.ndarray or List[float]

    def _tokenize(self, text: str) -> List[str]:
        """分词：去除标点、小写化、按空白分割。

        Args:
            text: 输入文本。

        Returns:
            词语列表。
        """
        text = re.sub(r"[^\w\s]", "", text.lower())
        return text.split()

    def _update_vocabulary(self, terms: List[str]) -> None:
        """增量更新词汇表和文档频率。

        Args:
            terms: 新文档中出现的词语列表。
        """
        for term in set(terms):
            if term not in self.vocabulary:
                self.vocabulary[term] = len(self.vocabulary)
            self.doc_freq[term] = self.doc_freq.get(term, 0) + 1

    def _recompute_idf(self) -> None:
        """重新计算所有词的 IDF 值。"""
        n = len(self.doc_texts)
        if n == 0:
            return
        for term in self.vocabulary:
            freq = self.doc_freq.get(term, 0)
            self.idf[term] = math.log((n + 1) / (1 + freq)) + 1

    def _text_to_vector(self, text: str) -> Any:
        """将文本转换为 TF-IDF 向量。

        Args:
            text: 输入文本。

        Returns:
            numpy 数组或列表，维度为词汇表大小。
        """
        terms = self._tokenize(text)
        vocab_size = len(self.vocabulary)
        if vocab_size == 0 or not terms:
            return np.zeros(max(vocab_size, 1)) if _NUMPY_AVAILABLE else _py_zeros(max(vocab_size, 1))

        if _NUMPY_AVAILABLE:
            vector = np.zeros(vocab_size)
        else:
            vector = _py_zeros(vocab_size)

        term_counts: Dict[str, int] = {}
        for term in terms:
            if term in self.vocabulary:
                term_counts[term] = term_counts.get(term, 0) + 1

        for term, count in term_counts.items():
            tf = count / len(terms)
            idx = self.vocabulary[term]
            vector[idx] = tf * self.idf.get(term, 0)

        return vector

    def _rebuild_all_vectors(self) -> None:
        """重建所有文档的向量表示。"""
        self.doc_vectors = []
        for text in self.doc_texts:
            self.doc_vectors.append(self._text_to_vector(text))

    def _cosine_similarity(self, vec1: Any, vec2: Any) -> float:
        """计算两个向量的余弦相似度。

        Args:
            vec1: 第一个向量（numpy 数组或列表）。
            vec2: 第二个向量（numpy 数组或列表）。

        Returns:
            余弦相似度值，范围 [-1, 1]。
        """
        if _NUMPY_AVAILABLE:
            norm1 = float(np.linalg.norm(vec1))
            norm2 = float(np.linalg.norm(vec2))
            if norm1 == 0 or norm2 == 0:
                return 0.0
            return float(np.dot(vec1, vec2) / (norm1 * norm2))
        else:
            # 纯 Python 回退
            v1: List[float] = vec1 if isinstance(vec1, list) else list(vec1)
            v2: List[float] = vec2 if isinstance(vec2, list) else list(vec2)
            return _py_cosine(v1, v2)

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """将长文档分割为重叠的文本块。

        使用滑动窗口方式，每个块的大小为 chunk_size，相邻块之间有 overlap 的重叠。

        Args:
            text: 要分割的原始文本。
            chunk_size: 每个块的最大字符数，默认 500。
            overlap: 相邻块之间的重叠字符数，默认 50。

        Returns:
            文本块列表。
        """
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]

        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunk = text[start:end]
            chunks.append(chunk)
            if end >= len(text):
                break
            start += chunk_size - overlap
        return chunks

    def add_document(
        self, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """添加文档并计算其 TF-IDF 向量。

        Args:
            text: 文档文本。
            metadata: 可选的元数据字典。

        Returns:
            文档在内部列表中的索引。
        """
        terms = self._tokenize(text)
        self.doc_texts.append(text)
        self.doc_metadata.append(metadata or {})

        self._update_vocabulary(terms)
        self._recompute_idf()
        self._rebuild_all_vectors()

        return len(self.doc_texts) - 1

    def add_documents(
        self, docs: List[Union[str, Tuple[str, Dict[str, Any]]]]
    ) -> List[int]:
        """批量添加文档。

        支持两种输入格式：
        - 纯文本字符串
        - (text, metadata) 元组

        Args:
            docs: 文档列表，每个元素为字符串或 (text, metadata) 元组。

        Returns:
            添加的文档索引列表。
        """
        indices: List[int] = []
        for doc in docs:
            if isinstance(doc, tuple):
                text, metadata = doc
            else:
                text, metadata = doc, None
            idx = self.add_document(text, metadata)
            indices.append(idx)
        return indices

    def search(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[int, float, str, Dict[str, Any]]]:
        """语义搜索，返回与查询最相关的 top_k 个文档。

        使用余弦相似度计算查询向量与每个文档向量之间的相似度。

        Args:
            query: 查询字符串。
            top_k: 返回的最大结果数，默认 5。

        Returns:
            (文档索引, 相似度分数, 文档文本, 元数据) 列表，按相似度降序。
        """
        if not self.doc_texts:
            return []

        query_vector = self._text_to_vector(query)
        if _NUMPY_AVAILABLE:
            query_norm = float(np.linalg.norm(query_vector))
        else:
            query_norm = _py_norm(query_vector)
        if query_norm == 0:
            return []

        scores: List[Tuple[int, float, str, Dict[str, Any]]] = []
        for idx, doc_vector in enumerate(self.doc_vectors):
            sim = self._cosine_similarity(query_vector, doc_vector)
            if sim > 0:
                scores.append((idx, sim, self.doc_texts[idx], self.doc_metadata[idx]))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def save_vectors(self, path: str) -> None:
        """将向量索引持久化保存到磁盘。

        保存内容包括：词汇表、IDF、文档频率、文档文本、文档元数据、向量数据。

        Args:
            path: 保存路径（JSON 文件）。
        """
        save_data = {
            "vocabulary": self.vocabulary,
            "idf": self.idf,
            "doc_freq": self.doc_freq,
            "doc_texts": self.doc_texts,
            "doc_metadata": self.doc_metadata,
            "doc_vectors": [
                v.tolist() if _NUMPY_AVAILABLE and hasattr(v, 'tolist') else v
                for v in self.doc_vectors
            ],
            "saved_at": datetime.now().isoformat(),
        }
        _atomic_write(Path(path), save_data)

    def load_vectors(self, path: str) -> bool:
        """从磁盘加载向量索引。

        Args:
            path: 加载路径（JSON 文件）。

        Returns:
            加载成功返回 True，文件不存在或格式错误返回 False。
        """
        filepath = Path(path)
        if not filepath.exists():
            return False

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            self.vocabulary = loaded.get("vocabulary", {})
            self.idf = loaded.get("idf", {})
            self.doc_freq = loaded.get("doc_freq", {})
            self.doc_texts = loaded.get("doc_texts", [])
            self.doc_metadata = loaded.get("doc_metadata", [])
            self.doc_vectors = [
                np.array(v) if _NUMPY_AVAILABLE else list(v)
                for v in loaded.get("doc_vectors", [])
            ]
            return True
        except (json.JSONDecodeError, KeyError, ValueError):
            return False

    def get_stats(self) -> Dict[str, Any]:
        """获取向量记忆的统计信息。

        Returns:
            包含文档数、词汇表大小等统计信息的字典。
        """
        return {
            "document_count": len(self.doc_texts),
            "vocabulary_size": len(self.vocabulary),
            "total_terms": sum(self.doc_freq.values()),
            "unique_terms": len(self.doc_freq),
        }


# ============================================================================
# RAGStore - 检索增强生成存储
# ============================================================================

class RAGStore:
    """RAG（检索增强生成）存储系统。

    自动对文档进行分块、向量化，支持语义检索和上下文构建。
    检索结果可直接注入到 LLM prompt 中。

    Attributes:
        vector_memory: 底层 VectorMemory 实例。
        documents: 文档注册表，doc_id -> 文档信息。
        chunk_map: 块索引到文档 ID 的映射。
    """

    _DEFAULT_CHUNK_SIZE = 500
    _DEFAULT_OVERLAP = 50
    _CHARS_PER_TOKEN = 4  # 粗略估计：1 token ≈ 4 字符

    def __init__(self):
        """初始化 RAG 存储。"""
        self.vector_memory = VectorMemory()
        self.documents: Dict[str, Dict[str, Any]] = {}  # doc_id -> doc info
        self.chunk_map: Dict[int, str] = {}  # chunk_idx -> doc_id
        self._doc_counter = 0

    def _generate_doc_id(self) -> str:
        """生成唯一文档 ID。"""
        self._doc_counter += 1
        return f"doc_{self._doc_counter}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def add_document(self, title: str, content: str, source: str = "") -> str:
        """添加文档到 RAG 存储。

        自动对文档内容进行分块，每个块独立向量化。

        Args:
            title: 文档标题。
            content: 文档内容。
            source: 文档来源（如 URL、文件名等）。

        Returns:
            文档 ID。
        """
        doc_id = self._generate_doc_id()
        chunks = VectorMemory.chunk_text(
            content,
            chunk_size=self._DEFAULT_CHUNK_SIZE,
            overlap=self._DEFAULT_OVERLAP,
        )

        self.documents[doc_id] = {
            "title": title,
            "content": content,
            "source": source,
            "chunk_count": len(chunks),
            "added_at": datetime.now().isoformat(),
        }

        for i, chunk in enumerate(chunks):
            chunk_idx = self.vector_memory.add_document(
                chunk,
                metadata={
                    "doc_id": doc_id,
                    "title": title,
                    "source": source,
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                },
            )
            self.chunk_map[chunk_idx] = doc_id

        return doc_id

    def retrieve(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """检索与查询最相关的文档片段。

        Args:
            query: 查询字符串。
            top_k: 返回的最大结果数。

        Returns:
            检索结果列表，每个结果为包含 chunk_text, score, metadata 的字典。
        """
        results = self.vector_memory.search(query, top_k=top_k)
        return [
            {
                "chunk_text": text,
                "score": score,
                "metadata": metadata,
                "doc_id": metadata.get("doc_id", ""),
            }
            for _, score, text, metadata in results
        ]

    def retrieve_with_context(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """检索相关片段并附带上下文（前后各一个块）。

        Args:
            query: 查询字符串。
            top_k: 返回的最大结果数。

        Returns:
            带上下文的检索结果列表。
        """
        results = self.retrieve(query, top_k=top_k)
        enriched: List[Dict[str, Any]] = []

        for result in results:
            chunk_idx_atom = result["metadata"].get("chunk_index", -1)
            doc_id = result["doc_id"]
            total_chunks = result["metadata"].get("total_chunks", 1)

            context_before = ""
            context_after = ""

            if chunk_idx_atom > 0:
                # 查找前一个块
                prev_idx = chunk_idx_atom - 1
                for ci, di in self.chunk_map.items():
                    meta = self.vector_memory.doc_metadata[ci]
                    if meta.get("doc_id") == doc_id and meta.get("chunk_index") == prev_idx:
                        context_before = self.vector_memory.doc_texts[ci][:200]
                        break

            if chunk_idx_atom < total_chunks - 1:
                # 查找后一个块
                next_idx = chunk_idx_atom + 1
                for ci, di in self.chunk_map.items():
                    meta = self.vector_memory.doc_metadata[ci]
                    if meta.get("doc_id") == doc_id and meta.get("chunk_index") == next_idx:
                        context_after = self.vector_memory.doc_texts[ci][:200]
                        break

            enriched.append({
                **result,
                "context_before": context_before,
                "context_after": context_after,
            })

        return enriched

    def build_context(self, query: str, max_tokens: int = 2000) -> str:
        """构建 RAG 上下文字符串，用于注入到 LLM prompt。

        检索相关文档片段并格式化为可直接注入 prompt 的文本。

        Args:
            query: 查询字符串。
            max_tokens: 最大 token 数限制（粗略估计），默认 2000。

        Returns:
            格式化的上下文字符串。
        """
        max_chars = max_tokens * self._CHARS_PER_TOKEN
        results = self.retrieve_with_context(query, top_k=5)

        if not results:
            return ""

        lines: List[str] = ["[相关文档上下文]"]
        total_chars = len(lines[0])

        seen_docs: set = set()
        for result in results:
            doc_id = result.get("doc_id", "")
            title = result["metadata"].get("title", "未知文档")
            source = result["metadata"].get("source", "")

            doc_header = ""
            if doc_id not in seen_docs:
                doc_header = f"\n[文档: {title}]"
                if source:
                    doc_header += f"\n来源: {source}"
                seen_docs.add(doc_id)

            chunk_text = result["chunk_text"]
            context_before = result.get("context_before", "")
            context_after = result.get("context_after", "")

            entry = ""
            if doc_header:
                entry += doc_header + "\n"
            if context_before:
                entry += f"...{context_before}...\n"
            entry += f"{chunk_text}\n"
            if context_after:
                entry += f"...{context_after}...\n"
            entry += "---"

            if total_chars + len(entry) > max_chars:
                remaining = max_chars - total_chars
                if remaining > 100:
                    entry = entry[:remaining] + "..."
                else:
                    break

            lines.append(entry)
            total_chars += len(entry)

        return "\n".join(lines)

    def remove_document(self, doc_id: str) -> bool:
        """删除指定文档及其所有分块。

        Args:
            doc_id: 要删除的文档 ID。

        Returns:
            删除成功返回 True，文档不存在返回 False。
        """
        if doc_id not in self.documents:
            return False

        # 收集需要删除的块索引
        indices_to_remove = sorted(
            [ci for ci, di in self.chunk_map.items() if di == doc_id],
            reverse=True,
        )

        # 反向删除以保持索引有效
        for ci in indices_to_remove:
            if ci < len(self.vector_memory.doc_texts):
                del self.vector_memory.doc_texts[ci]
            if ci < len(self.vector_memory.doc_metadata):
                del self.vector_memory.doc_metadata[ci]
            if ci < len(self.vector_memory.doc_vectors):
                del self.vector_memory.doc_vectors[ci]
            if ci in self.chunk_map:
                del self.chunk_map[ci]

        # 重新映射 chunk_map 索引（因为删除后索引会偏移）
        new_chunk_map: Dict[int, str] = {}
        for ci, di in self.chunk_map.items():
            offset = sum(1 for r in indices_to_remove if r < ci)
            new_chunk_map[ci - offset] = di
        self.chunk_map = new_chunk_map

        # 删除文档注册
        del self.documents[doc_id]

        return True

    def list_documents(self) -> List[Dict[str, Any]]:
        """列出所有已索引的文档。

        Returns:
            文档信息列表，包含 id, title, source, chunk_count, added_at。
        """
        return [
            {
                "id": doc_id,
                "title": info["title"],
                "source": info["source"],
                "chunk_count": info["chunk_count"],
                "added_at": info["added_at"],
            }
            for doc_id, info in self.documents.items()
        ]

    def get_stats(self) -> Dict[str, Any]:
        """获取 RAG 存储的统计信息。

        Returns:
            包含文档数、总块数、词汇表大小等统计信息的字典。
        """
        vec_stats = self.vector_memory.get_stats()
        return {
            "document_count": len(self.documents),
            "total_chunks": vec_stats["document_count"],
            "vocabulary_size": vec_stats["vocabulary_size"],
            "unique_terms": vec_stats["unique_terms"],
            "documents": [
                {"id": did, "title": info["title"], "chunks": info["chunk_count"]}
                for did, info in self.documents.items()
            ],
        }


# ============================================================================
# SemanticMemory - 语义记忆
# ============================================================================

class SemanticMemory:
    """语义记忆，存储用户偏好和事实。

    支持 TF-IDF 关键词搜索和向量语义搜索两种模式。

    Attributes:
        data: 内存数据，包含 preferences 和 facts。
        file: 持久化文件路径。
        use_embedding: 是否启用向量语义搜索。
        _tfidf: 底层 TF-IDF 搜索实例。
        _vector_memory: 底层 VectorMemory 实例（embedding 模式使用）。
    """

    def __init__(self, use_embedding: bool = False):
        """初始化语义记忆。

        Args:
            use_embedding: 是否启用向量化语义搜索，默认 False。
        """
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.file: Path = MEMORY_DIR / "semantic.json"
        self.data: Dict[str, Any] = self._load()
        self.use_embedding = use_embedding
        self._tfidf = TFIDFSearch()
        self._vector_memory = VectorMemory()
        self._rebuild_index()

    def _load(self) -> Dict[str, Any]:
        """从磁盘加载语义记忆数据。"""
        if self.file.exists():
            with open(self.file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"preferences": {}, "facts": []}

    def _save(self) -> None:
        """原子写入语义记忆数据到磁盘。"""
        _atomic_write(self.file, self.data)
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        """重建 TF-IDF 索引和向量索引。"""
        self._tfidf = TFIDFSearch()
        self._vector_memory = VectorMemory()
        self._fact_indices: List[int] = []

        for i, fact in enumerate(self.data.get("facts", [])):
            doc = f"{fact.get('key', '')} {fact.get('value', '')}"
            self._tfidf.add_document(doc)
            self._fact_indices.append(i)
            if self.use_embedding:
                self._vector_memory.add_document(doc, metadata={"fact_index": i})

        for pref_key, pref_val in self.data.get("preferences", {}).items():
            doc = f"{pref_key} {pref_val}"
            self._tfidf.add_document(doc)
            if self.use_embedding:
                self._vector_memory.add_document(
                    doc, metadata={"preference_key": pref_key}
                )

    def set_preference(self, key: str, value: Any) -> None:
        """设置用户偏好。

        Args:
            key: 偏好键名。
            value: 偏好值。
        """
        self.data["preferences"][key] = value
        self._save()

    def get_preference(self, key: str) -> Optional[Any]:
        """获取指定偏好。

        Args:
            key: 偏好键名。

        Returns:
            偏好值，不存在则返回 None。
        """
        return self.data["preferences"].get(key)

    def get_all_preferences(self) -> Dict[str, Any]:
        """获取所有偏好。

        Returns:
            偏好字典的副本。
        """
        return dict(self.data.get("preferences", {}))

    def add_fact(self, key: str, value: str) -> None:
        """添加事实。

        Args:
            key: 事实键名。
            value: 事实值。
        """
        self.data["facts"].append({
            "key": key,
            "value": value,
            "time": datetime.now().isoformat(),
            "weight": 1.0,
        })
        if len(self.data["facts"]) > 100:
            self.data["facts"] = self.data["facts"][-100:]
        self._save()

    def search_facts(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """使用 TF-IDF 关键词搜索事实。

        Args:
            query: 查询字符串。
            limit: 最大返回数量。

        Returns:
            匹配的事实列表。
        """
        results = self._tfidf.search(query)
        facts = self.data.get("facts", [])
        matched: List[Dict[str, Any]] = []
        for idx, score in results:
            if score > 0 and idx < len(self._fact_indices):
                matched.append(facts[self._fact_indices[idx]])
            if len(matched) >= limit:
                break
        return matched

    def search_semantic(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """使用向量语义搜索事实。

        当 use_embedding=True 时使用余弦相似度搜索，否则回退到 TF-IDF 关键词搜索。

        Args:
            query: 查询字符串。
            top_k: 最大返回数量。

        Returns:
            匹配的事实列表，每个包含 fact, score 字段。
        """
        if self.use_embedding and self._vector_memory.doc_texts:
            vec_results = self._vector_memory.search(query, top_k=top_k)
            facts = self.data.get("facts", [])
            matched: List[Dict[str, Any]] = []
            for idx, score, text, metadata in vec_results:
                fact_idx = metadata.get("fact_index", -1)
                if 0 <= fact_idx < len(facts):
                    matched.append({
                        "fact": facts[fact_idx],
                        "score": round(score, 4),
                    })
                if len(matched) >= top_k:
                    break
            return matched
        else:
            # 回退到 TF-IDF 搜索
            raw_results = self.search_facts(query, limit=top_k)
            return [{"fact": f, "score": 1.0} for f in raw_results]

    def cluster_facts(self, n_clusters: int = 3) -> Dict[int, List[Dict[str, Any]]]:
        """将事实按主题聚类（K-means）。

        使用 TF-IDF 向量表示每条事实，通过 K-means 算法进行聚类。
        如果 numpy 不可用，回退为基于关键词的简单分组。

        Args:
            n_clusters: 聚类数量，默认 3。

        Returns:
            聚类结果字典，键为聚类编号，值为该聚类中的事实列表。
        """
        facts = self.data.get("facts", [])
        if not facts:
            return {}

        if len(facts) < n_clusters:
            return {i: [facts[i]] for i in range(len(facts))}

        if not _NUMPY_AVAILABLE:
            return self._cluster_facts_simple(facts, n_clusters)

        # ── numpy 路径：K-means ──
        vectors: List[Any] = []
        for fact in facts:
            text = f"{fact.get('key', '')} {fact.get('value', '')}"
            vec = self._vector_memory._text_to_vector(text) if self.use_embedding else None
            if vec is None or np.linalg.norm(vec) == 0:
                terms = re.sub(r"[^\w\s]", "", text.lower()).split()
                vec = np.zeros(max(len(terms), 1))
                for i, t in enumerate(terms[:len(vec)]):
                    vec[i] = 1.0
            vectors.append(vec)

        max_dim = max(v.shape[0] for v in vectors)
        aligned = []
        for v in vectors:
            if v.shape[0] < max_dim:
                padded = np.zeros(max_dim)
                padded[:v.shape[0]] = v
                aligned.append(padded)
            else:
                aligned.append(v)
        X = np.array(aligned)

        rng = np.random.default_rng(42)
        n_samples = len(X)
        initial_indices = rng.choice(n_samples, n_clusters, replace=False)
        centroids = X[initial_indices].copy()

        labels = np.zeros(n_samples, dtype=int)
        for _ in range(100):
            distances = np.linalg.norm(X[:, np.newaxis] - centroids, axis=2)
            new_labels = np.argmin(distances, axis=1)
            new_centroids = np.array([
                X[new_labels == i].mean(axis=0) if np.any(new_labels == i) else centroids[i]
                for i in range(n_clusters)
            ])
            if np.allclose(centroids, new_centroids) or np.array_equal(labels, new_labels):
                labels = new_labels
                break
            centroids = new_centroids
            labels = new_labels

        clusters: Dict[int, List[Dict[str, Any]]] = {}
        for i in range(n_clusters):
            clusters[i] = [facts[j] for j in range(len(facts)) if labels[j] == i]
        return clusters

    def _cluster_facts_simple(
        self, facts: List[Dict[str, Any]], n_clusters: int
    ) -> Dict[int, List[Dict[str, Any]]]:
        """纯 Python 简单聚类：基于关键词分组（numpy 不可用时的回退）。"""
        # 按 key 的首字符哈希分组
        clusters: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(n_clusters)}
        for i, fact in enumerate(facts):
            bucket = hash(fact.get("key", str(i))) % n_clusters
            clusters[bucket].append(fact)
        # 过滤空簇
        return {k: v for k, v in clusters.items() if v}

    def decay_score(self, lambda_param: float = 0.01) -> None:
        """根据时间衰减记忆权重（遗忘曲线）。

        使用指数衰减公式: weight = exp(-lambda * days_since_added)
        对每条事实的 weight 字段进行衰减。

        Args:
            lambda_param: 衰减率参数，默认 0.01（越高衰减越快）。
        """
        now = datetime.now()
        for fact in self.data.get("facts", []):
            time_str = fact.get("time", "")
            if not time_str:
                fact["weight"] = 1.0
                continue
            try:
                added_time = datetime.fromisoformat(time_str)
                days = max(0, (now - added_time).total_seconds() / 86400.0)
                fact["weight"] = round(math.exp(-lambda_param * days), 6)
            except (ValueError, TypeError):
                fact["weight"] = 1.0

        self._save()

    def get_context_string(self) -> str:
        """获取语义记忆的文本上下文。

        Returns:
            格式化的偏好和事实字符串。
        """
        prefs = self.data.get("preferences", {})
        if not prefs:
            return ""
        lines = [f"- {k}: {v}" for k, v in prefs.items()]
        return "\u7528\u6237\u504f\u597d:\n" + "\n".join(lines)


# ============================================================================
# MemorySystem - 记忆系统总控
# ============================================================================

class MemorySystem:
    """记忆系统总控，集成工作记忆、情景记忆、语义记忆和 RAG 存储。

    提供统一的记忆管理接口，支持自动学习、知识检索和增强上下文构建。

    Attributes:
        working: WorkingMemory 工作记忆实例。
        episodic: EpisodicMemory 情景记忆实例。
        semantic: SemanticMemory 语义记忆实例。
        rag_store: RAGStore 检索增强生成存储实例。
    """

    _LEARN_PATTERNS: List[Tuple[str, str]] = [
        (r"\u6211\u53eb\s*(\S+)", "name"),
        (r"\u6211\u662f\s*(\S+)", "name"),
        (r"\u6211\u7684\u540d\u5b57[\u662f\u53eb]?\s*(\S+)", "name"),
        (r"\u6211[\u5728\u5c31\u4e8e]\s*(\S+)", "location"),
        (r"\u6211[\u4f4f\u5728]\s*(\S+[\u7701\u5e02])", "location"),
        (r"\u6211\u7684\u90ae\u7bb1[\u662f]?\s*(\S+@\S+)", "email"),
        (r"\u6211[\u7528\u4f7f]\u7684[\u662f]?\s*([Pp]ython|Java|Go|Rust|C\+\+|JS|Node)", "language"),
        (r"\u6211[\u7684]?\u6280\u672f\u6808[\u662f]?\s*(.+)", "tech_stack"),
        (r"\u6211[\u7684]?\u804c\u4e1a[\u662f]?\s*(.+)", "profession"),
        (r"\u6211\u559c\u6b22\s*(.+)", "like"),
        (r"\u6211\u504f\u597d\s*(.+)", "preference"),
        (r"\u6211\u4e0d\u559c\u6b22\s*(.+)", "dislike"),
    ]

    def __init__(self):
        """初始化记忆系统。"""
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.rag_store = RAGStore()

    def learn_patterns(self, user_message: str) -> None:
        """从用户消息中自动学习模式（偏好、事实等）。

        Args:
            user_message: 用户消息文本。
        """
        for pattern, key in self._LEARN_PATTERNS:
            m = re.search(pattern, user_message)
            if m:
                value = m.group(1).strip()
                if value and len(value) < 200:
                    self.semantic.set_preference(key, value)
                    if key == "name":
                        break

    def record_interaction(self, user_msg: str, ai_reply: str) -> None:
        """记录一次交互（用户消息 + AI 回复）。

        Args:
            user_msg: 用户消息。
            ai_reply: AI 回复。
        """
        self.working.add("user", user_msg)
        self.working.add("assistant", ai_reply)

    def save_session(self, title: Optional[str] = None) -> None:
        """保存当前会话为情景记忆。

        Args:
            title: 会话标题，默认使用时间戳。
        """
        summary = self.working.summarize()
        if summary:
            self.episodic.add(
                title=title or f"\u4f1a\u8bdd {datetime.now().strftime('%m-%d %H:%M')}",
                summary=summary,
            )

    def learn_preference(self, key: str, value: Any) -> None:
        """手动设置偏好。

        Args:
            key: 偏好键名。
            value: 偏好值。
        """
        self.semantic.set_preference(key, value)

    def get_memory_context(self) -> str:
        """获取当前记忆上下文，用于注入到 LLM prompt。

        整合语义记忆、最近情景记忆和 RAG 检索结果。

        Returns:
            格式化的记忆上下文字符串。
        """
        parts: List[str] = []

        # 语义记忆上下文
        semantic = self.semantic.get_context_string()
        if semantic:
            parts.append(semantic)

        # 最近情景记忆
        recent = self.episodic.recent(3)
        if recent:
            parts.append("\u6700\u8fd1\u4f1a\u8bdd\u6458\u8981:")
            for ep in recent:
                parts.append(f"- {ep['title']}: {ep['summary'][:200]}")

        # 重要情景记忆
        important = self.episodic.get_important(threshold=7)
        if important:
            parts.append("\u91cd\u8981\u8bb0\u5fc6:")
            for ep in important[:3]:
                parts.append(f"- [{ep.get('importance', 5)}/10] {ep['title']}: {ep['summary'][:150]}")

        return "\n".join(parts)

    def enhanced_memory_context(self) -> Dict[str, Any]:
        """返回增强版记忆上下文（语义 + 情景 + RAG + 工作记忆摘要）。

        整合所有记忆模块的信息，提供全面的上下文视图。

        Returns:
            包含 semantic, episodic, working_summary, rag_stats 的字典。
        """
        working_summary = self.working.generate_summary()

        return {
            "semantic": {
                "preferences": self.semantic.get_all_preferences(),
                "facts": self.semantic.data.get("facts", [])[-20:],
            },
            "episodic": {
                "recent": self.episodic.recent(5),
                "important": self.episodic.get_important(threshold=5),
                "total": len(self.episodic.episodes),
            },
            "working_summary": working_summary,
            "rag_stats": self.rag_store.get_stats(),
            "generated_at": datetime.now().isoformat(),
        }

    def add_knowledge(self, title: str, content: str, source: str = "") -> str:
        """向 RAG 存储添加知识文档。

        Args:
            title: 文档标题。
            content: 文档内容。
            source: 文档来源。

        Returns:
            文档 ID。
        """
        return self.rag_store.add_document(title, content, source)

    def query_knowledge(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """从 RAG 存储检索知识。

        Args:
            query: 查询字符串。
            top_k: 返回的最大结果数。

        Returns:
            检索结果列表。
        """
        return self.rag_store.retrieve(query, top_k=top_k)

    def get_rag_context(self, query: str, max_tokens: int = 2000) -> str:
        """获取 RAG 上下文，用于注入到 LLM prompt。

        Args:
            query: 查询字符串。
            max_tokens: 最大 token 数限制。

        Returns:
            格式化的 RAG 上下文字符串。
        """
        return self.rag_store.build_context(query, max_tokens=max_tokens)

    def search_all(self, query: str) -> Dict[str, Any]:
        """跨所有记忆模块搜索。

        Args:
            query: 查询字符串。

        Returns:
            包含 episodes, facts, rag_results 的字典。
        """
        rag_results = self.rag_store.retrieve(query, top_k=3)
        return {
            "episodes": self.episodic.search(query),
            "facts": self.semantic.search_facts(query),
            "rag_results": rag_results,
        }

    def clear_working(self) -> None:
        """清空工作记忆。"""
        self.working.clear()

    def get_stats(self) -> Dict[str, int]:
        """获取记忆系统的统计信息。

        Returns:
            包含各模块计数的字典。
        """
        return {
            "working_messages": len(self.working.messages),
            "episodes": len(self.episodic.episodes),
            "facts": len(self.semantic.data.get("facts", [])),
            "preferences": len(self.semantic.data.get("preferences", {})),
            "rag_documents": len(self.rag_store.documents),
        }

    def export_memory(self) -> Dict[str, Any]:
        """导出全部记忆数据。

        Returns:
            包含 working, episodes, semantic 的字典。
        """
        return {
            "working": self.working.get_context(),
            "episodes": self.episodic.all(),
            "semantic": {
                "preferences": self.semantic.get_all_preferences(),
                "facts": self.semantic.data.get("facts", []),
            },
        }

    def import_memory(self, data: Dict[str, Any]) -> None:
        """从字典导入记忆数据。

        Args:
            data: 包含 semantic, episodes 的字典。
        """
        if "semantic" in data:
            for k, v in data["semantic"].get("preferences", {}).items():
                self.semantic.set_preference(k, v)
            for fact in data["semantic"].get("facts", []):
                self.semantic.add_fact(fact["key"], fact["value"])
        if "episodes" in data:
            for ep in data["episodes"]:
                self.episodic.add(
                    ep["title"],
                    ep["summary"],
                    ep.get("tags", []),
                    importance=ep.get("importance", 5),
                )

    def reset(self) -> None:
        """重置所有记忆模块。"""
        self.working.clear()
        self.episodic.episodes = []
        self.episodic._save()
        self.semantic.data = {"preferences": {}, "facts": []}
        self.semantic._save()
        self.rag_store = RAGStore()