"""Embedding 服务测试：重点覆盖远程 Embedding 接口的返回处理。

切换 Embedding 模型（本地哈希 → API）时，向量与切片的对应关系完全依赖接口返回：
一旦返回乱序或丢条目，向量就会和内容静默错位——检索结果看起来"能用"但全是错的，
所以这里把顺序与条数两件事单独锁住。
"""
import json

import pytest

from services import embedding_service


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _patch_api(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(embedding_service, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(embedding_service, "EMBEDDING_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(
        embedding_service.urllib.request, "urlopen", lambda *args, **kwargs: _FakeResponse(payload)
    )


def test_api_embed_sorts_by_index(monkeypatch):
    # 故意把 index=1 放在前面，模拟服务端乱序返回
    _patch_api(monkeypatch, {"data": [
        {"index": 1, "embedding": [0.0, 1.0]},
        {"index": 0, "embedding": [1.0, 0.0]},
    ]})

    matrix = embedding_service._api_embed(["first", "second"])

    assert matrix.shape == (2, 2)
    assert matrix[0][0] == 1.0 and matrix[0][1] == 0.0  # index=0 的向量必须排在第一位
    assert matrix[1][1] == 1.0 and matrix[1][0] == 0.0


def test_api_embed_rejects_count_mismatch(monkeypatch):
    _patch_api(monkeypatch, {"data": [{"index": 0, "embedding": [1.0, 0.0]}]})

    with pytest.raises(ValueError):
        embedding_service._api_embed(["first", "second"])


def test_api_embed_rejects_empty_data(monkeypatch):
    _patch_api(monkeypatch, {})

    with pytest.raises(ValueError):
        embedding_service._api_embed(["first"])


def test_api_embed_normalizes_vectors(monkeypatch):
    _patch_api(monkeypatch, {"data": [
        {"index": 0, "embedding": [3.0, 4.0]},
    ]})

    matrix = embedding_service._api_embed(["only"])

    assert matrix.shape == (1, 2)
    assert abs(float((matrix[0] ** 2).sum()) - 1.0) < 1e-6
