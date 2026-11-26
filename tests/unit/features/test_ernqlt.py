"""barra_cne6_ernqlt 逐股票 descriptor 纯函数测试。对照旧仓 QUALITY.ERNQLT 的手工核算。"""
from __future__ import annotations

from decimal import Decimal

import pytest

from quantagent.features.library.fundamental.ernqlt import (
    abs_descriptor,
    acf_descriptor,
    net_operating_assets,
)

D = Decimal


@pytest.mark.unit
def test_noa_basic() -> None:
    # (1000-100)-(500-50)=450
    assert net_operating_assets(total_assets=D(1000), cash_end=D(100), total_liab=D(500), interest_debt=D(50)) == D(450)


@pytest.mark.unit
def test_noa_interest_debt_none_fills_zero() -> None:
    # 带息债务缺失补0: (1000-100)-(500-0)=400。仅 debt 补 0。
    assert net_operating_assets(total_assets=D(1000), cash_end=D(100), total_liab=D(500), interest_debt=None) == D(400)


@pytest.mark.unit
def test_noa_other_fields_none_returns_none() -> None:
    # 其余三项任一缺失 → None（不补0）。
    assert net_operating_assets(total_assets=None, cash_end=D(100), total_liab=D(500), interest_debt=D(50)) is None
    assert net_operating_assets(total_assets=D(1000), cash_end=None, total_liab=D(500), interest_debt=D(50)) is None
    assert net_operating_assets(total_assets=D(1000), cash_end=D(100), total_liab=None, interest_debt=D(50)) is None


@pytest.mark.unit
def test_abs_descriptor_value() -> None:
    # 5期NOA [400,420,430,440,450], delta=50, da=30, assets=10000 → -(50-30)/10000=-0.002
    out = abs_descriptor(noa_series=[D(400), D(420), D(430), D(440), D(450)], da_ttm=D(30), total_assets_latest=D(10000))
    assert out == pytest.approx(D("-0.002"))


@pytest.mark.unit
def test_abs_requires_exactly_5_periods() -> None:
    # 不足5期 → None（严格性差异，见模块docstring）。
    assert abs_descriptor(noa_series=[D(400), D(420), D(430), D(440)], da_ttm=D(30), total_assets_latest=D(10000)) is None
    # 6期也不行（必须恰好5期，对齐旧仓tail(5)）
    assert abs_descriptor(noa_series=[D(1), D(400), D(420), D(430), D(440), D(450)], da_ttm=D(30), total_assets_latest=D(10000)) is None


@pytest.mark.unit
def test_abs_missing_endpoint_or_da_or_denominator() -> None:
    base = [D(400), D(420), D(430), D(440), D(450)]
    # 首尾缺失 → None
    assert abs_descriptor(noa_series=[None, D(420), D(430), D(440), D(450)], da_ttm=D(30), total_assets_latest=D(10000)) is None
    assert abs_descriptor(noa_series=[D(400), D(420), D(430), D(440), None], da_ttm=D(30), total_assets_latest=D(10000)) is None
    # da缺失 → None
    assert abs_descriptor(noa_series=base, da_ttm=None, total_assets_latest=D(10000)) is None
    # 分母缺失/为0 → None
    assert abs_descriptor(noa_series=base, da_ttm=D(30), total_assets_latest=None) is None
    assert abs_descriptor(noa_series=base, da_ttm=D(30), total_assets_latest=D(0)) is None


@pytest.mark.unit
def test_acf_descriptor_value() -> None:
    # ni=100, cfo sum=90, cfi sum=20, da=30, assets=10000 → accr=100-110+30=20, accf=-20/10000=-0.002
    out = acf_descriptor(
        ni_ttm=D(100),
        cfo_single=[D(20), D(25), D(22), D(23)],
        cfi_single=[D(5), D(5), D(5), D(5)],
        da_ttm=D(30),
        total_assets_latest=D(10000),
    )
    assert out == pytest.approx(D("-0.002"))


@pytest.mark.unit
def test_acf_cfo_skipna() -> None:
    # cfo [20,None,22,23] sum=65(skipna): accr=100-(65+20)+30=45, accf=-0.0045
    out = acf_descriptor(
        ni_ttm=D(100),
        cfo_single=[D(20), None, D(22), D(23)],
        cfi_single=[D(5), D(5), D(5), D(5)],
        da_ttm=D(30),
        total_assets_latest=D(10000),
    )
    assert out == pytest.approx(D("-0.0045"))


@pytest.mark.unit
def test_acf_missing_ni_or_da_or_denominator() -> None:
    kw = {"cfo_single": [D(20)], "cfi_single": [D(5)], "total_assets_latest": D(10000)}
    assert acf_descriptor(ni_ttm=None, da_ttm=D(30), **kw) is None
    assert acf_descriptor(ni_ttm=D(100), da_ttm=None, **kw) is None
    assert acf_descriptor(ni_ttm=D(100), da_ttm=D(30), cfo_single=[D(20)], cfi_single=[D(5)], total_assets_latest=None) is None
    assert acf_descriptor(ni_ttm=D(100), da_ttm=D(30), cfo_single=[D(20)], cfi_single=[D(5)], total_assets_latest=D(0)) is None
