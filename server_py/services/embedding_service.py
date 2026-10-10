"""Embedding service.

Default: deterministic local hashing n-gram embedding (no external service needed).
Optional: OpenAI-compatible embeddings API via EMBEDDING_* env vars.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import urllib.request
from typing import List

import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 512
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")


def embedding_mode() -> str:
    return "api" if (EMBEDDING_API_KEY and EMBEDDING_BASE_URL) else "local"


def _hash_feature(feature: str) -> tuple[int, float]:
    digest = hashlib.md5(feature.encode("utf-8")).digest()
    index = int.from_bytes(digest[:4], "little") % EMBEDDING_DIM
    sign = 1.0 if digest[4] & 1 else -1.0
    return index, sign


def _features(text: str) -> List[str]:
    lowered = text.lower()
    words = _WORD_RE.findall(lowered)

    features: List[str] = list(words)
    for word in words:
        parts = _CAMEL_RE.findall(word)
        if len(parts) > 1:
            features.extend(p.lower() for p in parts)
    features.extend(f"{words[i]}_{words[i + 1]}" for i in range(len(words) - 1))

    cjk = _CJK_RE.findall(lowered)
    features.extend(cjk)
    features.extend(f"{cjk[i]}{cjk[i + 1]}" for i in range(len(cjk) - 1))

    normalized = re.sub(r"\s+", " ", lowered)
    features.extend(normalized[i:i + 3] for i in range(max(0, len(normalized) - 2)))
    return features


def _local_embed(text: str) -> np.ndarray:
    vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    counts: dict[str, int] = {}
    for feature in _features(text):
        counts[feature] = counts.get(feature, 0) + 1
    for feature, count in counts.items():
        index, sign = _hash_feature(feature)
        vector[index] += sign * (1.0 + math.log(count))
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector


def _api_embed(texts: List[str]) -> np.ndarray:
    payload = json.dumps({"model": EMBEDDING_MODEL, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        f"{EMBEDDING_BASE_URL.rstrip('/')}/embeddings",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {EMBEDDING_API_KEY}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    vectors = [item["embedding"] for item in body["data"]]
    matrix = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def embed_texts(texts: List[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    if embedding_mode() == "api":
        try:
            return _api_embed(texts)
        except Exception as exc:
            # 显式记录降级，不再静默回退：API 向量与本地向量维度不同，
            # 静默回退会导致检索时维度不匹配（由检索层的维度校验兜底拦截）。
            logger.warning("Embedding API 调用失败，降级为本地哈希向量: %s", exc)
    return np.vstack([_local_embed(t) for t in texts])


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]
