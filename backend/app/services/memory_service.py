from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Iterable

from app.models.schemas import (
    KnowledgeEdge,
    KnowledgeGraphQueryRequest,
    KnowledgeNode,
    MemoryEmbedResponse,
    MemoryEntry,
    MemoryShardStats,
)
from app.services.storage import store


class MemoryService:
    _EMBED_DIM = 384

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [token for token in re.findall(r"[a-z0-9_'-]+", text.lower()) if token]

    @staticmethod
    def _deterministic_embedding(text: str, dim: int = 384) -> list[float]:
        # Local deterministic embedding approximation to keep offline behavior stable.
        vector = [0.0] * dim
        tokens = re.findall(r"[a-z0-9_'-]+", text.lower())
        if not tokens:
            return vector
        for idx, token in enumerate(tokens):
            digest = hashlib.sha256(f'{token}:{idx}'.encode('utf-8')).digest()
            for offset in range(0, min(len(digest), 32), 4):
                bucket = int.from_bytes(digest[offset : offset + 4], byteorder='big', signed=False) % dim
                sign = 1.0 if digest[offset] % 2 == 0 else -1.0
                vector[bucket] += sign * (1.0 / (1 + idx))
        norm = sum(value * value for value in vector) ** 0.5
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector

    def upsert(self, key: str, content: str, tags: Iterable[str] | None = None) -> MemoryEntry:
        now = datetime.now(timezone.utc)
        normalized_tags = sorted({tag.strip().lower() for tag in (tags or []) if tag.strip()})

        with store.conn() as conn:
            existing = conn.execute(
                'SELECT payload FROM memory_entries WHERE memory_key = ?',
                (key,),
            ).fetchone()

        if existing:
            item = MemoryEntry.model_validate(store.load(existing[0]))
            item.content = content
            item.tags = normalized_tags
            item.updated_at = now
        else:
            item = MemoryEntry(
                key=key,
                content=content,
                tags=normalized_tags,
                created_at=now,
                updated_at=now,
            )

        payload = item.model_dump(mode='json')
        with store.conn() as conn:
            conn.execute(
                '''
                INSERT INTO memory_entries (id, memory_key, created_at, updated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(memory_key) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                ''',
                (
                    item.id,
                    item.key,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                    store.dump(payload),
                ),
            )
        return item

    def recent(self, limit: int = 20) -> list[MemoryEntry]:
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT payload FROM memory_entries ORDER BY updated_at DESC LIMIT ?',
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [MemoryEntry.model_validate(store.load(row[0])) for row in rows]

    def search(self, query: str, limit: int = 8) -> list[MemoryEntry]:
        q = query.strip().lower()
        if not q:
            return self.recent(limit=limit)

        now = datetime.now(timezone.utc)
        tokens = self._tokenize(q)
        unique_tokens = list(dict.fromkeys(tokens))
        with store.conn() as conn:
            rows = conn.execute(
                'SELECT payload FROM memory_entries ORDER BY updated_at DESC LIMIT 500'
            ).fetchall()

        scored: list[MemoryEntry] = []
        for row in rows:
            item = MemoryEntry.model_validate(store.load(row[0]))
            key_text = item.key.lower()
            content_text = item.content.lower()
            tags_text = ' '.join(item.tags).lower()
            haystack = f'{key_text} {content_text} {tags_text}'.strip()
            score = 0.0

            if q in haystack:
                score += 3.0

            for token in unique_tokens:
                if token in key_text:
                    score += 1.6
                elif token in tags_text:
                    score += 1.2
                elif token in content_text:
                    score += 1.0

            if unique_tokens:
                token_hits = sum(1 for token in unique_tokens if token in haystack)
                score += (token_hits / len(unique_tokens)) * 1.8

            age_hours = max((now - item.updated_at).total_seconds() / 3600.0, 0.0)
            recency_boost = max(0.0, 1.6 - min(age_hours / 72.0, 1.6))
            score += recency_boost

            if score > 0:
                item.score = score
                scored.append(item)

        scored.sort(key=lambda x: (x.score, x.updated_at), reverse=True)
        return scored[: max(1, min(limit, 100))]

    def embed(self, text: str) -> MemoryEmbedResponse:
        vector = self._deterministic_embedding(text, dim=self._EMBED_DIM)
        return MemoryEmbedResponse(vector=vector, dimensions=len(vector), strategy='deterministic-hash-v1')

    def reindex(self, limit: int = 1000) -> list[MemoryShardStats]:
        entries = self.recent(limit=max(1, min(limit, 100000)))
        with store.conn() as conn:
            conn.execute('DELETE FROM knowledge_nodes')
            conn.execute('DELETE FROM knowledge_edges')

            for item in entries:
                node = KnowledgeNode(
                    key=item.key,
                    label=item.key,
                    node_type='memory_entry',
                    score=float(item.score),
                    metadata={'tags': item.tags, 'updated_at': item.updated_at.isoformat()},
                )
                conn.execute(
                    '''
                    INSERT INTO knowledge_nodes (id, node_key, label, node_type, score, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        node.id,
                        node.key,
                        node.label,
                        node.node_type,
                        node.score,
                        store.dump(node.model_dump(mode='json')),
                    ),
                )

                for tag in item.tags[:12]:
                    tag_key = f'tag:{tag}'
                    tag_node = KnowledgeNode(
                        key=tag_key,
                        label=tag,
                        node_type='tag',
                        score=1.0,
                        metadata={},
                    )
                    conn.execute(
                        '''
                        INSERT INTO knowledge_nodes (id, node_key, label, node_type, score, payload)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(node_key) DO UPDATE SET
                            label=excluded.label,
                            node_type=excluded.node_type,
                            score=excluded.score,
                            payload=excluded.payload
                        ''',
                        (
                            tag_node.id,
                            tag_node.key,
                            tag_node.label,
                            tag_node.node_type,
                            tag_node.score,
                            store.dump(tag_node.model_dump(mode='json')),
                        ),
                    )
                    edge = KnowledgeEdge(
                        source_key=item.key,
                        target_key=tag_key,
                        relation='tagged_with',
                        score=1.0,
                    )
                    conn.execute(
                        '''
                        INSERT INTO knowledge_edges (id, source_key, target_key, relation, score, payload)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            edge.id,
                            edge.source_key,
                            edge.target_key,
                            edge.relation,
                            edge.score,
                            store.dump(edge.model_dump(mode='json')),
                        ),
                    )

        shards: dict[str, list[float]] = {}
        for item in entries:
            shard = (item.key[:2] or 'na').lower()
            shards.setdefault(shard, []).append(item.score)
        return [
            MemoryShardStats(shard=shard, entries=len(scores), avg_score=(sum(scores) / len(scores)) if scores else 0.0)
            for shard, scores in sorted(shards.items())
        ]

    def graph(self, request: KnowledgeGraphQueryRequest) -> dict[str, list[dict]]:
        nodes: list[dict] = []
        edges: list[dict] = []
        query = request.query.strip().lower()
        with store.conn() as conn:
            node_rows = conn.execute(
                'SELECT payload FROM knowledge_nodes ORDER BY score DESC LIMIT ?',
                (max(1, min(request.limit, 500)),),
            ).fetchall()
            for row in node_rows:
                payload = store.load(row[0])
                key = str(payload.get('key', '')).lower()
                label = str(payload.get('label', '')).lower()
                if request.node_key and payload.get('key') != request.node_key:
                    continue
                if query and query not in key and query not in label:
                    continue
                nodes.append(payload)

            edge_rows = conn.execute(
                'SELECT payload FROM knowledge_edges ORDER BY score DESC LIMIT ?',
                (max(1, min(request.limit * 2, 1000)),),
            ).fetchall()
            valid_keys = {str(node.get('key')) for node in nodes}
            for row in edge_rows:
                payload = store.load(row[0])
                if request.relation and payload.get('relation') != request.relation:
                    continue
                source = str(payload.get('source_key'))
                target = str(payload.get('target_key'))
                if valid_keys and source not in valid_keys and target not in valid_keys:
                    continue
                edges.append(payload)
                if len(edges) >= request.limit:
                    break

        return {'nodes': nodes[: request.limit], 'edges': edges[: request.limit]}


memory_service = MemoryService()
