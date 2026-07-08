import json
import math
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

MEMORY_DIR = Path(__file__).parent / "memory_data"


def _atomic_write(filepath: Path, data: Any) -> None:
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


class WorkingMemory:
    def __init__(self, max_messages: int = 50):
        self.messages: List[Dict[str, Any]] = []
        self.max_messages = max_messages

    def add(self, role: str, content: str) -> None:
        self.messages.append({
            "role": role,
            "content": content,
            "time": datetime.now().isoformat(),
        })
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def get_context(self) -> List[Dict[str, Any]]:
        return self.messages

    def clear(self) -> None:
        self.messages = []

    def summarize(self) -> str:
        if not self.messages:
            return ""
        lines: List[str] = []
        for m in self.messages:
            text = str(m["content"])[:80]
            lines.append(f"{m['role']}: {text}")
        return "\n".join(lines)

    def export(self) -> str:
        lines: List[str] = []
        for m in self.messages:
            role = "你" if m["role"] == "user" else "AI"
            lines.append(f"[{m['time']}] {role}: {m['content']}")
        return "\n\n".join(lines)


class EpisodicMemory:
    def __init__(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.file: Path = MEMORY_DIR / "episodes.json"
        self.episodes: List[Dict[str, Any]] = self._load()

    def _load(self) -> List[Dict[str, Any]]:
        if self.file.exists():
            with open(self.file, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save(self) -> None:
        _atomic_write(self.file, self.episodes)

    def add(
        self, title: str, summary: str, tags: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        episode = {
            "title": title,
            "summary": summary,
            "tags": tags or [],
            "time": datetime.now().isoformat(),
        }
        self.episodes.append(episode)
        if len(self.episodes) > 100:
            self.episodes = self.episodes[-100:]
        self._save()
        return episode

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        q = query.lower()
        for ep in reversed(self.episodes):
            if q in ep["title"].lower() or q in ep["summary"].lower():
                results.append(ep)
            if len(results) >= limit:
                break
        return results

    def recent(self, limit: int = 5) -> List[Dict[str, Any]]:
        return self.episodes[-limit:]

    def all(self) -> List[Dict[str, Any]]:
        return self.episodes


class TFIDFSearch:
    def __init__(self):
        self.documents: List[str] = []
        self.idf: Dict[str, float] = {}
        self.doc_freq: Dict[str, int] = {}

    def add_document(self, text: str) -> None:
        terms = self._tokenize(text.lower())
        self.documents.append(text)
        for term in set(terms):
            self.doc_freq[term] = self.doc_freq.get(term, 0) + 1
        self._update_idf()

    def _tokenize(self, text: str) -> List[str]:
        text = re.sub(r"[^\w\s]", "", text.lower())
        return text.split()

    def _update_idf(self) -> None:
        n = len(self.documents)
        for term, freq in self.doc_freq.items():
            self.idf[term] = math.log(n / (1 + freq))

    def _tfidf(self, terms: List[str]) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        term_counts: Dict[str, int] = {}
        for term in terms:
            term_counts[term] = term_counts.get(term, 0) + 1
        for term, count in term_counts.items():
            scores[term] = (count / len(terms)) * self.idf.get(term, 0)
        return scores

    def search(self, query: str) -> List[Tuple[int, float]]:
        query_terms = self._tokenize(query.lower())
        query_tfidf = self._tfidf(query_terms)

        scores: List[Tuple[int, float]] = []
        for idx, doc in enumerate(self.documents):
            doc_terms = self._tokenize(doc.lower())
            doc_tfidf = self._tfidf(doc_terms)
            dot = sum(query_tfidf.get(t, 0) * doc_tfidf.get(t, 0) for t in query_terms)
            scores.append((idx, dot))

        return sorted(scores, key=lambda x: x[1], reverse=True)


class SemanticMemory:
    def __init__(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self.file: Path = MEMORY_DIR / "semantic.json"
        self.data: Dict[str, Any] = self._load()
        self._tfidf = TFIDFSearch()
        self._rebuild_index()

    def _load(self) -> Dict[str, Any]:
        if self.file.exists():
            with open(self.file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"preferences": {}, "facts": []}

    def _save(self) -> None:
        _atomic_write(self.file, self.data)
        self._rebuild_index()

    def _rebuild_index(self) -> None:
        self._tfidf = TFIDFSearch()
        for fact in self.data.get("facts", []):
            doc = f"{fact.get('key', '')} {fact.get('value', '')}"
            self._tfidf.add_document(doc)
        for pref_key, pref_val in self.data.get("preferences", {}).items():
            doc = f"{pref_key} {pref_val}"
            self._tfidf.add_document(doc)

    def set_preference(self, key: str, value: Any) -> None:
        self.data["preferences"][key] = value
        self._save()

    def get_preference(self, key: str) -> Optional[Any]:
        return self.data["preferences"].get(key)

    def get_all_preferences(self) -> Dict[str, Any]:
        return dict(self.data.get("preferences", {}))

    def add_fact(self, key: str, value: str) -> None:
        self.data["facts"].append({
            "key": key,
            "value": value,
            "time": datetime.now().isoformat(),
        })
        if len(self.data["facts"]) > 100:
            self.data["facts"] = self.data["facts"][-100:]
        self._save()

    def search_facts(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        results = self._tfidf.search(query)
        selected = results[:limit]
        facts = self.data.get("facts", [])
        return [facts[idx] for idx, score in selected if score > 0]

    def get_context_string(self) -> str:
        prefs = self.data.get("preferences", {})
        if not prefs:
            return ""
        lines = [f"- {k}: {v}" for k, v in prefs.items()]
        return "用户偏好:\n" + "\n".join(lines)


class MemorySystem:
    def __init__(self):
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()

    def record_interaction(self, user_msg: str, ai_reply: str) -> None:
        self.working.add("user", user_msg)
        self.working.add("assistant", ai_reply)

    def save_session(self, title: Optional[str] = None) -> None:
        summary = self.working.summarize()
        if summary:
            self.episodic.add(
                title=title or f"会话 {datetime.now().strftime('%m-%d %H:%M')}",
                summary=summary,
            )

    def learn_preference(self, key: str, value: Any) -> None:
        self.semantic.set_preference(key, value)

    def get_memory_context(self) -> str:
        parts: List[str] = []
        semantic = self.semantic.get_context_string()
        if semantic:
            parts.append(semantic)
        recent = self.episodic.recent(3)
        if recent:
            parts.append("最近会话摘要:")
            for ep in recent:
                parts.append(f"- {ep['title']}: {ep['summary'][:200]}")
        return "\n".join(parts)

    def search_all(self, query: str) -> Dict[str, Any]:
        return {
            "episodes": self.episodic.search(query),
            "facts": self.semantic.search_facts(query),
        }

    def clear_working(self) -> None:
        self.working.clear()

    def get_stats(self) -> Dict[str, int]:
        return {
            "working_messages": len(self.working.messages),
            "episodes": len(self.episodic.episodes),
            "facts": len(self.semantic.data.get("facts", [])),
            "preferences": len(self.semantic.data.get("preferences", {})),
        }

    def export_memory(self) -> Dict[str, Any]:
        return {
            "working": self.working.get_context(),
            "episodes": self.episodic.all(),
            "semantic": {
                "preferences": self.semantic.get_all_preferences(),
                "facts": self.semantic.data.get("facts", []),
            },
        }

    def import_memory(self, data: Dict[str, Any]) -> None:
        if "semantic" in data:
            for k, v in data["semantic"].get("preferences", {}).items():
                self.semantic.set_preference(k, v)
            for fact in data["semantic"].get("facts", []):
                self.semantic.add_fact(fact["key"], fact["value"])
        if "episodes" in data:
            for ep in data["episodes"]:
                self.episodic.add(ep["title"], ep["summary"], ep.get("tags", []))

    def reset(self) -> None:
        self.working.clear()
        self.episodic.episodes = []
        self.episodic._save()
        self.semantic.data = {"preferences": {}, "facts": []}
        self.semantic._save()