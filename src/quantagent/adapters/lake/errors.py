"""Parquet + DuckDB 适配器失败。"""

from __future__ import annotations


class LakeAdapterError(Exception):
    """湖读取失败的基类。"""


class EmptyDomainError(LakeAdapterError):
    """股票池、因子列表或结果域为空。fail-closed，不猜全市场。"""
