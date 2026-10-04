"""Long-term memory: the part of Brainiac that keeps learning.

Every task ends with a reflection step that distils lessons into this store,
and `teach` ingests whole curricula. Nothing is ever capped or evicted, so
knowledge accumulates for as long as the database exists; retrieval (BM25
over SQLite FTS5) keeps the working context small no matter how large the
store grows. `consolidate` merges a topic's scattered notes into a single
dense entry when a topic gets noisy.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

KINDS = ("lesson", "fact", "skill", "episode", "curriculum")
STOPWORDS = set(
    "a an and are as at be by can do does for from how i in is it of on or should so that the this to "
    "was what when where which who why will with you your my me we our".split()
)


@dataclass
class Memory:
    id: int
    kind: str
    topic: str
    content: str
    uses: int
    created: float


class MemoryStore:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                digest TEXT UNIQUE NOT NULL,
                uses INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(topic, content, content='memories', content_rowid='id', tokenize='porter unicode61');
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, topic, content) VALUES (new.id, new.topic, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, topic, content)
                VALUES ('delete', old.id, old.topic, old.content);
            END;
            """
        )
        self.db.commit()

    # ------------------------------------------------------------------ write
    def remember(self, content: str, topic: str = "general", kind: str = "fact") -> int | None:
        """Store a memory. Returns its id, or None if it was already known."""
        if kind not in KINDS:
            kind = "fact"
        content = content.strip()
        if not content:
            return None
        digest = hashlib.sha256(f"{topic}\x00{content}".encode()).hexdigest()
        try:
            cur = self.db.execute(
                "INSERT INTO memories(kind, topic, content, digest, created) VALUES (?,?,?,?,?)",
                (kind, topic.strip().lower() or "general", content, digest, time.time()),
            )
            self.db.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def teach(self, text: str, topic: str, chunk_chars: int = 1800) -> int:
        """Ingest a document as curriculum, split on headings/paragraphs."""
        stored = 0
        for chunk in _chunk(text, chunk_chars):
            if self.remember(chunk, topic=topic, kind="curriculum") is not None:
                stored += 1
        return stored

    def teach_path(self, path: Path, topic: str | None = None) -> int:
        files: Iterable[Path] = sorted(path.rglob("*.md")) if path.is_dir() else [path]
        total = 0
        for f in files:
            t = topic or (f.parent.name if path.is_dir() else f.stem)
            total += self.teach(f.read_text(encoding="utf-8"), topic=t)
        return total

    # ------------------------------------------------------------------- read
    def recall(self, query: str, k: int = 6, topic: str | None = None) -> list[Memory]:
        terms = [t for t in re.findall(r"[a-z0-9]{2,}", query.lower()) if t not in STOPWORDS]
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms[:24])
        sql = (
            "SELECT m.id, m.kind, m.topic, m.content, m.uses, m.created FROM memories_fts f "
            "JOIN memories m ON m.id = f.rowid WHERE memories_fts MATCH ? AND m.archived = 0"
        )
        args: list = [match]
        if topic:
            sql += " AND m.topic = ?"
            args.append(topic.lower())
        # Lessons are distilled experience, so they get a small rank boost.
        sql += " ORDER BY bm25(memories_fts) - (CASE m.kind WHEN 'lesson' THEN 1.0 ELSE 0 END) LIMIT ?"
        args.append(k)
        rows = [Memory(*r) for r in self.db.execute(sql, args)]
        if rows:
            self.db.executemany("UPDATE memories SET uses = uses + 1 WHERE id = ?", [(m.id,) for m in rows])
            self.db.commit()
        return rows

    def topics(self) -> list[tuple[str, int]]:
        return list(
            self.db.execute(
                "SELECT topic, COUNT(*) FROM memories WHERE archived = 0 GROUP BY topic ORDER BY 2 DESC"
            )
        )

    def by_topic(self, topic: str) -> list[Memory]:
        return [
            Memory(*r)
            for r in self.db.execute(
                "SELECT id, kind, topic, content, uses, created FROM memories "
                "WHERE topic = ? AND archived = 0 ORDER BY id",
                (topic.lower(),),
            )
        ]

    def stats(self) -> dict:
        total = self.db.execute("SELECT COUNT(*) FROM memories WHERE archived = 0").fetchone()[0]
        kinds = dict(self.db.execute("SELECT kind, COUNT(*) FROM memories WHERE archived = 0 GROUP BY kind"))
        return {"total": total, "kinds": kinds, "topics": len(self.topics())}

    # ---------------------------------------------------------- maintenance
    def replace_topic(self, topic: str, summary: str) -> int | None:
        """Archive a topic's lessons/facts and store one consolidated entry.

        Curriculum is never archived: it is source material, not a summary.
        """
        self.db.execute(
            "UPDATE memories SET archived = 1 WHERE topic = ? AND kind IN ('lesson','fact','episode')",
            (topic.lower(),),
        )
        self.db.commit()
        return self.remember(summary, topic=topic, kind="skill")

    @staticmethod
    def format(memories: list[Memory]) -> str:
        return "\n\n".join(f"[{m.kind} #{m.id} · {m.topic}]\n{m.content}" for m in memories)


def _chunk(text: str, limit: int) -> list[str]:
    sections = re.split(r"\n(?=#{1,3} )", text)
    chunks: list[str] = []
    for section in sections:
        if len(section) <= limit:
            chunks.append(section)
            continue
        buf = ""
        for para in section.split("\n\n"):
            if buf and len(buf) + len(para) > limit:
                chunks.append(buf)
                buf = ""
            buf = f"{buf}\n\n{para}" if buf else para
        if buf:
            chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]
