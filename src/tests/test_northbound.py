"""
北向资金采集层测试

覆盖场景：
  1. 正常数据 — 沪深均有，合计正确
  2. 正常数据 — 净买入为负（外资净卖出）
  3. 目标日期在数据集中不存在（非交易日）
  4. 沪股通数据缺失（NaN），深股通正常
  5. 两个分项均缺失 — total 不应瞎合计
  6. AKShare 返回空 DataFrame
  7. 接口字段变更 — 缺少必需列时应抛出明确异常
  8. 网络异常时重试逻辑是否按配置次数执行
  9. 网络异常重试耗尽后返回 None
  10. 存储：正常数据写入文件格式正确
  11. 存储：无数据时写入缺失标记，不写空表格
  12. 存储：净买入为负时格式带负号，为正时带加号
"""

import os
import sys
from datetime import date
from unittest.mock import call, patch

import pandas as pd
import pytest

# 将 src/ 加入路径，确保可以 import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collector.northbound import (
    BOARD_SHANGHAI,
    BOARD_SHENZHEN,
    RETRY_DELAY,
    _parse_northbound,
    _validate_columns,
    fetch_northbound,
    save_northbound,
)

# ── 测试数据工厂 ──────────────────────────────────────────────────────────────

def make_df(target_date: date,
            sh_net: float = 32.40,
            sz_net: float = 18.60,
            sh_left: float = 487.60,
            sz_left: float = 381.40) -> pd.DataFrame:
    """构造与 AKShare 结构一致的 DataFrame（含沪深两行）"""
    return pd.DataFrame([
        {
            "交易日":      target_date,
            "类型":        "北向资金",
            "板块":        BOARD_SHANGHAI,
            "资金方向":    "流入",
            "交易状态":    "交易中",
            "成交净买额":  sh_net,
            "资金净流入":  sh_net * 0.98,
            "当日资金余额": sh_left,
            "上涨数":      1234,
            "持平数":      56,
            "下跌数":      789,
            "相关指数":    "000001",
            "指数涨跌幅":  0.85,
        },
        {
            "交易日":      target_date,
            "类型":        "北向资金",
            "板块":        BOARD_SHENZHEN,
            "资金方向":    "流入",
            "交易状态":    "交易中",
            "成交净买额":  sz_net,
            "资金净流入":  sz_net * 0.97,
            "当日资金余额": sz_left,
            "上涨数":      876,
            "持平数":      43,
            "下跌数":      321,
            "相关指数":    "399001",
            "指数涨跌幅":  1.12,
        },
    ])


# ── 1. 正常数据，沪深均有 ─────────────────────────────────────────────────────

def test_parse_normal_data():
    d = date(2026, 3, 19)
    df = make_df(d, sh_net=32.40, sz_net=18.60)
    result = _parse_northbound(df, d)

    assert result["data_available"] is True
    assert result["sh_net_buy"]    == 32.40
    assert result["sz_net_buy"]    == 18.60
    assert result["total_net_buy"] == round(32.40 + 18.60, 2)
    assert result["date"]          == d


# ── 2. 净买入为负（外资净卖出）────────────────────────────────────────────────

def test_parse_net_sell():
    d = date(2026, 3, 19)
    df = make_df(d, sh_net=-45.20, sz_net=-12.80)
    result = _parse_northbound(df, d)

    assert result["data_available"] is True
    assert result["sh_net_buy"]    == -45.20
    assert result["sz_net_buy"]    == -12.80
    assert result["total_net_buy"] == round(-45.20 + (-12.80), 2)


# ── 3. 目标日期不在数据集中（非交易日）────────────────────────────────────────

def test_parse_date_not_in_data():
    trading_day  = date(2026, 3, 19)
    weekend_day  = date(2026, 3, 21)   # 周六
    df = make_df(trading_day)
    result = _parse_northbound(df, weekend_day)

    assert result["data_available"] is False
    assert result["sh_net_buy"]     is None
    assert result["total_net_buy"]  is None


# ── 4. 沪股通当日数据 NaN（部分缺失）─────────────────────────────────────────

def test_parse_sh_nan():
    d = date(2026, 3, 19)
    df = make_df(d, sh_net=float("nan"), sz_net=18.60)
    result = _parse_northbound(df, d)

    assert result["data_available"] is True
    assert result["sh_net_buy"]    is None   # NaN → None
    assert result["sz_net_buy"]    == 18.60
    # 有一项缺失时不应合计
    assert result["total_net_buy"] is None


# ── 5. 沪深均缺失时 total 不合计 ─────────────────────────────────────────────

def test_parse_both_nan_no_total():
    d = date(2026, 3, 19)
    df = make_df(d, sh_net=float("nan"), sz_net=float("nan"))
    result = _parse_northbound(df, d)

    assert result["sh_net_buy"]    is None
    assert result["sz_net_buy"]    is None
    assert result["total_net_buy"] is None


# ── 6. AKShare 返回空 DataFrame ───────────────────────────────────────────────

def test_parse_empty_dataframe():
    d = date(2026, 3, 19)
    result = _parse_northbound(pd.DataFrame(), d)

    assert result["data_available"] is False
    assert result["sh_net_buy"]     is None


# ── 7. 接口字段变更 — 缺少必需列应抛出明确异常 ────────────────────────────────

def test_validate_columns_missing_raises():
    bad_df = pd.DataFrame({"日期": [], "净买入": []})  # 字段名与预期不符
    with pytest.raises(ValueError, match="AKShare 返回字段缺失"):
        _validate_columns(bad_df)


def test_validate_columns_ok():
    good_df = pd.DataFrame(columns=["交易日", "板块", "成交净买额", "当日资金余额", "其他列"])
    _validate_columns(good_df)  # 不应抛出


# ── 8. 网络异常时重试次数正确 ─────────────────────────────────────────────────

def test_retry_count_on_network_error():
    with patch("akshare.stock_hsgt_fund_flow_summary_em",
               side_effect=ConnectionError("网络超时")) as mock_ak, \
         patch("collector.northbound.time.sleep") as mock_sleep:

        result = fetch_northbound(target_date=date(2026, 3, 19), retries=3)

    assert result is None
    assert mock_ak.call_count == 3               # 重试了 3 次
    assert mock_sleep.call_count == 2            # 前两次失败后各 sleep 一次


# ── 9. 重试间隔时间符合配置 ───────────────────────────────────────────────────

def test_retry_delay_value():
    with patch("akshare.stock_hsgt_fund_flow_summary_em",
               side_effect=ConnectionError("超时")), \
         patch("collector.northbound.time.sleep") as mock_sleep:

        fetch_northbound(target_date=date(2026, 3, 19), retries=2)

    for c in mock_sleep.call_args_list:
        assert c == call(RETRY_DELAY)


# ── 10. 第二次重试成功时返回正确数据 ─────────────────────────────────────────

def test_retry_succeeds_on_second_attempt():
    d = date(2026, 3, 19)
    good_df = make_df(d)

    with patch("akshare.stock_hsgt_fund_flow_summary_em",
               side_effect=[ConnectionError("第一次失败"), good_df]) as mock_ak, \
         patch("collector.northbound.time.sleep"):

        result = fetch_northbound(target_date=d, retries=3)

    assert result is not None
    assert result["data_available"] is True
    assert mock_ak.call_count == 2


# ── 11. 存储：正常数据写入文件格式正确 ────────────────────────────────────────

def test_save_writes_correct_content(tmp_path):
    d = date(2026, 3, 19)
    data = {
        "date":           d,
        "sh_net_buy":     32.40,
        "sz_net_buy":     18.60,
        "total_net_buy":  51.00,
        "sh_quota_left":  487.60,
        "sz_quota_left":  381.40,
        "data_available": True,
    }

    with patch("config.settings.NORTHBOUND_DIR", str(tmp_path)):
        save_northbound(data)

    out_file = tmp_path / "20260319.md"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")

    assert "北向资金 2026-03-19" in content
    assert "沪股通成交净买额(亿)" in content
    assert "+32.40" in content      # 正数带加号
    assert "+18.60" in content
    assert "+51.00" in content
    assert "487.60" in content


# ── 12. 存储：无数据时写入缺失标记，不写空表格 ────────────────────────────────

def test_save_unavailable_writes_marker(tmp_path):
    d = date(2026, 3, 21)
    data = {
        "date":           d,
        "sh_net_buy":     None,
        "sz_net_buy":     None,
        "total_net_buy":  None,
        "sh_quota_left":  None,
        "sz_quota_left":  None,
        "data_available": False,
    }

    with patch("config.settings.NORTHBOUND_DIR", str(tmp_path)):
        save_northbound(data)

    content = (tmp_path / "20260321.md").read_text(encoding="utf-8")
    assert "非交易日或接口暂未更新" in content
    assert "|" not in content       # 不应出现表格


# ── 13. 存储：净买入为负时格式带负号 ─────────────────────────────────────────

def test_save_negative_net_buy_format(tmp_path):
    d = date(2026, 3, 19)
    data = {
        "date":           d,
        "sh_net_buy":     -45.20,
        "sz_net_buy":     -12.80,
        "total_net_buy":  -58.00,
        "sh_quota_left":  250.00,
        "sz_quota_left":  180.00,
        "data_available": True,
    }

    with patch("config.settings.NORTHBOUND_DIR", str(tmp_path)):
        save_northbound(data)

    content = (tmp_path / "20260319.md").read_text(encoding="utf-8")
    assert "-45.20" in content
    assert "-58.00" in content
    assert "+" not in content.split("合计")[1].split("\n")[0]   # 合计行不带加号
