"""Milvus 向量库工具类：封装 pymilvus 的高层 MilvusClient，提供集合管理与向量存取。

只负责与 Milvus 交互的技术细节，不含业务规则——存什么向量、如何切分/embedding、
检索后如何拼 prompt，都由调用方决定。连接配置全部来自环境变量（见 Settings.milvus_*），
代码中不硬编码 uri / token。

设计取舍：本类只处理「向量」，不计算 embedding（embedding 依赖具体模型/API，是另一层
关注点）。每个实例绑定一个集合（collection），与 OssClient 绑定一个 bucket 的风格一致。
"""
from functools import lru_cache

from pymilvus import MilvusClient as _SdkClient

from app.core.config import Settings, get_settings


class MilvusError(Exception):
    """Milvus 操作失败的统一异常，避免把 pymilvus 的底层异常直接抛给调用方。"""


class MilvusStore:
    """Milvus 向量集合封装：建集合、插入向量、相似度检索。

    用法：
        store = get_milvus_client()
        store.ensure_collection(dim=1024)
        store.insert([{"id": 1, "vector": [...], "text": "..."}])
        hits = store.search([0.1, 0.2, ...], limit=5, output_fields=["text"])

    依赖：pymilvus。底层 client 可通过 _client 注入，便于测试时替换。
    """

    def __init__(
        self,
        uri: str,
        token: str,
        collection: str,
        *,
        _client: _SdkClient | None = None,
    ) -> None:
        self._collection = collection
        self._client = _client if _client is not None else _SdkClient(uri=uri, token=token)

    @classmethod
    def from_settings(cls, settings: Settings) -> "MilvusStore":
        if not settings.milvus_configured:
            raise MilvusError("Milvus 未配置：请设置 MILVUS_URI 与 MILVUS_COLLECTION")
        return cls(
            uri=settings.milvus_uri,
            token=settings.effective_milvus_token,
            collection=settings.milvus_collection,
        )

    def ensure_collection(self, dim: int) -> None:
        """确保集合存在且已加载（幂等）。

        注意：高层 create_collection 会按实例默认副本数自动 load，若实例可用 streaming 节点
        不足（如单节点实例默认 2 副本）会 load 失败但集合已建。故统一在创建后以**单副本**
        显式加载，兼容单节点实例。"""
        try:
            if not self._client.has_collection(self._collection):
                try:
                    self._client.create_collection(collection_name=self._collection, dimension=dim)
                except Exception:  # noqa: BLE001 多为自动 load 副本不足；集合通常已建
                    if not self._client.has_collection(self._collection):
                        raise  # 确实未建成才上抛
            self._load_single_replica()
        except Exception as exc:  # noqa: BLE001 统一包装 pymilvus 异常
            raise MilvusError(f"创建集合失败: {self._collection}: {exc}") from exc

    def _load_single_replica(self) -> None:
        """以单副本加载集合（已按单副本加载时为幂等 no-op）；兼容仅 1 个 streaming 节点的实例。"""
        try:
            self._client.load_collection(self._collection, replica_number=1)
        except Exception:  # noqa: BLE001 残留的多副本 load 状态 → 先释放再单副本加载
            self._client.release_collection(self._collection)
            self._client.load_collection(self._collection, replica_number=1)

    def insert(self, data: list[dict]) -> dict:
        """插入若干条记录（每条含 id / vector 及可选字段），返回 Milvus 的插入结果。"""
        try:
            return self._client.insert(collection_name=self._collection, data=data)
        except Exception as exc:  # noqa: BLE001 统一包装 pymilvus 异常
            raise MilvusError(f"插入向量失败: {self._collection}: {exc}") from exc

    def upsert(self, data: list[dict]) -> dict:
        """按主键 upsert（存在则覆盖、不存在则插入），适合可重复导入的场景（如知识库）。"""
        try:
            return self._client.upsert(collection_name=self._collection, data=data)
        except Exception as exc:  # noqa: BLE001 统一包装 pymilvus 异常
            raise MilvusError(f"upsert 向量失败: {self._collection}: {exc}") from exc

    def collection_exists(self) -> bool:
        """集合是否已存在（供 list/delete 在无数据时优雅返回）。"""
        try:
            return self._client.has_collection(self._collection)
        except Exception as exc:  # noqa: BLE001 统一包装 pymilvus 异常
            raise MilvusError(f"查询集合是否存在失败: {self._collection}: {exc}") from exc

    def query(self, expr: str, output_fields: list[str], limit: int = 1000) -> list[dict]:
        """按标量条件（非向量）过滤查询，返回命中的字段记录。expr 为 Milvus 过滤表达式。"""
        try:
            return list(
                self._client.query(
                    collection_name=self._collection,
                    filter=expr,
                    output_fields=output_fields,
                    limit=limit,
                )
            )
        except Exception as exc:  # noqa: BLE001 统一包装 pymilvus 异常
            raise MilvusError(f"查询失败: {self._collection}: {exc}") from exc

    def delete(self, expr: str) -> dict:
        """按标量条件删除记录。expr 为 Milvus 过滤表达式（如 'doc_id == "abc"'）。"""
        try:
            return self._client.delete(collection_name=self._collection, filter=expr)
        except Exception as exc:  # noqa: BLE001 统一包装 pymilvus 异常
            raise MilvusError(f"删除失败: {self._collection}: {exc}") from exc

    def search(
        self,
        vector: list[float],
        limit: int = 5,
        output_fields: list[str] | None = None,
        expr: str | None = None,
    ) -> list[dict]:
        """按查询向量做相似度检索，返回 top-limit 命中（已展开为单个查询的结果列表）。

        expr 为可选的标量过滤表达式（如按 scope/owner_id 限定检索范围）。
        """
        try:
            results = self._client.search(
                collection_name=self._collection,
                data=[vector],
                limit=limit,
                output_fields=output_fields,
                filter=expr or "",
            )
        except Exception as exc:  # noqa: BLE001 统一包装 pymilvus 异常
            raise MilvusError(f"检索失败: {self._collection}: {exc}") from exc
        # pymilvus 按「每个查询向量」返回一组命中；此处只传了一个向量，取第一组。
        return list(results[0]) if results else []


@lru_cache
def get_milvus_client() -> MilvusStore:
    """返回进程级单例 Milvus 客户端（对话索引集合）；未配置 Milvus 时抛出 MilvusError。"""
    return MilvusStore.from_settings(get_settings())


@lru_cache
def get_kb_milvus_client() -> MilvusStore:
    """返回绑定到知识库集合的 Milvus 客户端；未配置时抛出 MilvusError。"""
    settings = get_settings()
    if not (settings.milvus_uri and settings.milvus_kb_collection):
        raise MilvusError("Milvus 知识库未配置：请设置 MILVUS_URI 与 MILVUS_KB_COLLECTION")
    return MilvusStore(
        uri=settings.milvus_uri,
        token=settings.effective_milvus_token,
        collection=settings.milvus_kb_collection,
    )


@lru_cache
def get_trajectory_milvus_client() -> MilvusStore:
    """返回绑定到研究任务轨迹集合的 Milvus 客户端；未配置时抛出 MilvusError。"""
    settings = get_settings()
    if not (settings.milvus_uri and settings.milvus_trajectory_collection):
        raise MilvusError("Milvus 轨迹库未配置：请设置 MILVUS_URI 与 MILVUS_TRAJECTORY_COLLECTION")
    return MilvusStore(
        uri=settings.milvus_uri,
        token=settings.effective_milvus_token,
        collection=settings.milvus_trajectory_collection,
    )
