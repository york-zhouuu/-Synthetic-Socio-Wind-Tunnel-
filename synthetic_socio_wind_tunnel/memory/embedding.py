"""
EmbeddingProvider 协议 + NullEmbedding stub。

真实 embedding（OpenAI / Anthropic / 本地 sentence-transformer）由用户
显式注入到 MemoryService；默认 NullEmbedding 提供 hash-based 伪向量，
确定性但"语义"无意义，让其它 3 路检索继续工作。
"""

from __future__ import annotations

import hashlib
import struct
from typing import Protocol, runtime_checkable


_EMBEDDING_DIM = 32


@runtime_checkable
class EmbeddingProvider(Protocol):
    """任何实现 embed() 的对象都可作为 EmbeddingProvider。"""

    def embed(self, text: str) -> tuple[float, ...]:
        """Return a fixed-dim vector for the text. Deterministic if possible."""
        ...


class NullEmbedding:
    """
    Hash-based 伪 embedding，维度固定 32。

    用于测试与无 LLM 环境。同一 text 产出同一向量；但向量本身不含语义
    相似性（"dog" 与 "cat" 的 cosine 与 "dog" 与 "xyzzy" 无异）。
    """

    __slots__ = ()

    def embed(self, text: str) -> tuple[float, ...]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # 把 sha256 的 32 字节拆为 32 个 float (转 [-1, 1))
        floats: list[float] = []
        for byte in h[:_EMBEDDING_DIM]:
            # byte 0..255 → [-1, 1)
            floats.append((byte / 128.0) - 1.0)
        return tuple(floats)


def cosine_similarity(
    a: tuple[float, ...] | None,
    b: tuple[float, ...] | None,
) -> float:
    """
    返回 [0, 1] 的余弦相似度；零向量或长度不匹配时返回 0。
    """
    if a is None or b is None:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(y * y for y in b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    # cosine ∈ [-1, 1]，映射到 [0, 1]
    cos = dot / (mag_a * mag_b)
    return max(0.0, min(1.0, (cos + 1.0) / 2.0))
