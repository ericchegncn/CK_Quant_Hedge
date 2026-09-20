"""回测层的「同一根 K 线双向开仓」契约测试（hedge_mode）。

上游回测器里有两道"一个币种一笔持仓"的硬规则，双向持仓必须绕过它们：

  1. `Backtesting.check_for_trade_entry` 把同一根 K 线上的 `enter_long` 与
     `enter_short` 当作**互斥**（两列都置 1 → 两个方向都不开）—— 策略于是只能
     "按 K 线槽位轮换方向"，两条腿永远差一根 K 线建仓，建仓价差就是后开那条腿的
     开仓浮亏。这正是要修的东西。
  2. `backtest_loop` 里 `(self._position_stacking or len(bt_trades_open_pp[pair]) == 0)`
     —— 一个币种只允许一笔在场。双向模式改为**按方向**计数。

本文件钉住：
  - `check_for_trade_entries`（双向）与 `check_for_trade_entry`（上游，互斥）的差异
  - 端到端：同一根 K 线上两条腿一起开，且**拿同一个开盘价**
  - `hedge_mode` 关闭时，同一根 K 线上的双向信号依然一笔都不开（上游行为不变）
"""
from copy import deepcopy
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from freqtrade.data.converter import ohlcv_fill_up_missing_data
from freqtrade.data.history import get_timerange
from freqtrade.enums import SignalDirection
from freqtrade.optimize.backtesting import Backtesting
from freqtrade.persistence import LocalTrade
from tests.conftest import EXMS, generate_test_data, patch_exchange


def _make_row(enter_long=0, exit_long=0, enter_short=0, exit_short=0):
    """按 HEADERS 顺序造一行（与 tests/optimize/test_backtesting.py 里的 row 一致）。"""
    return [
        pd.Timestamp(year=2020, month=1, day=1, hour=5, minute=0),
        0.1,  # Open
        0.12,  # High
        0.099,  # Low
        0.11,  # Close
        enter_long,
        exit_long,
        enter_short,
        exit_short,
        "",  # Long Signal Name
        "",  # Short Tag
        "",  # Exit Signal Name
    ]


def _prep_backtesting(mocker, default_conf_usdt, fee, hedge, pairs, max_open_trades=4):
    default_conf_usdt.update(
        {
            "runmode": "backtest",
            "timeframe": "5m",
            "max_open_trades": max_open_trades,
            "stoploss": -1.0,
            "minimal_roi": {"0": 100},
            "margin_mode": "isolated",
            "trading_mode": "futures",
            "position_stacking": True,
            "hedge_mode": hedge,
            "liquidation_buffer": 0.001,
            # 市价单：与真实网格策略一致（order_types 全是 market），
            # 也让两条腿在同一根 K 线上立刻成交、拿到同一个价格（限价单会挂单/超时重开）
            "order_types": {
                "entry": "market",
                "exit": "market",
                "stoploss": "market",
                "stoploss_on_exchange": False,
            },
            # 市价单的硬性要求（否则 Backtesting 构造时直接 ConfigurationError）
            "entry_pricing": {"price_side": "other", "use_order_book": False, "order_book_top": 1},
            "exit_pricing": {"price_side": "other", "use_order_book": False, "order_book_top": 1},
        }
    )
    default_conf_usdt["exchange"]["pair_whitelist"] = pairs
    mocker.patch(
        "freqtrade.optimize.backtesting.price_to_precision", lambda price, *args, **kwargs: price
    )
    mocker.patch(f"{EXMS}.get_min_pair_stake_amount", return_value=0.00001)
    mocker.patch(f"{EXMS}.get_max_pair_stake_amount", return_value=float("inf"))
    mocker.patch(f"{EXMS}.get_fee", fee)
    # 维持保证金压到极小 = 强平价远离建仓价（否则测试数据的大幅波动会把腿立刻扫掉）
    mocker.patch(f"{EXMS}.get_maintenance_ratio_and_amt", return_value=(0.0001, 0.0001))
    patch_exchange(mocker)

    raw_candles_1m = generate_test_data("1m", 2500, "2022-01-03 12:00:00+00:00")
    raw_candles = ohlcv_fill_up_missing_data(raw_candles_1m, "5m", "dummy")
    data = {pair: raw_candles for pair in pairs}
    # 只留最后 200 根主 K 线，跑得快
    data = {pair: candles[-200:].reset_index(drop=True) for pair, candles in data.items()}

    backtesting = Backtesting(default_conf_usdt)
    backtesting.funding_fee_timeframe_secs = 3600 * 8  # 8h（与上游 futures 回测用例一致）
    backtesting.futures_data = {pair: pd.DataFrame() for pair in pairs}
    backtesting.strategylist[0].can_short = True
    backtesting._set_strategy(backtesting.strategylist[0])
    # 杠杆固定 1x：让"止损/强平"彻底不可能触发，用例只考察双向建仓本身
    backtesting.strategy.leverage = MagicMock(return_value=1.0)
    return backtesting, data


def _both_sides_same_candle(dataframe=None, metadata=None):
    """每 20 根 K 线上，enter_long 与 enter_short **同时**为 1（不设出场信号）。"""
    dataframe["enter_long"] = np.where(dataframe.index % 20 == 0, 1, 0)
    dataframe["enter_short"] = dataframe["enter_long"]
    dataframe["exit_long"] = 0
    dataframe["exit_short"] = 0
    return dataframe


def _always_both_sides(dataframe=None, metadata=None):
    """每根 K 线都给双向信号（最极端：一平就立刻重开）。"""
    dataframe["enter_long"] = np.where(dataframe["volume"] > 0, 1, 0)
    dataframe["enter_short"] = dataframe["enter_long"]
    dataframe["exit_long"] = 0
    dataframe["exit_short"] = 0
    return dataframe


def test_check_for_trade_entries_double_sided(mocker, default_conf_usdt, fee):
    """双向：两列都置 1 → ['long', 'short']；上游版本同一行 → None（两个方向都不开）。"""
    backtesting, _ = _prep_backtesting(
        mocker, default_conf_usdt, fee, hedge=True, pairs=["ETH/USDT:USDT"]
    )
    assert backtesting._hedge_mode is True
    assert backtesting._position_stacking is True

    # 上游行为（互斥）—— 这一条是"为什么必须改"的证据
    assert backtesting.check_for_trade_entry(_make_row(1, 0, 1, 0)) is None
    # 双向行为
    assert backtesting.check_for_trade_entries(_make_row(1, 0, 1, 0)) == ["long", "short"]
    # 同一方向内部的互斥两者一致
    assert backtesting.check_for_trade_entries(_make_row(1, 1, 0, 0)) == []
    assert backtesting.check_for_trade_entries(_make_row(0, 0, 1, 0)) == ["short"]
    assert backtesting.check_for_trade_entries(_make_row(0, 0, 0, 0)) == []


def test_check_for_trade_entries_one_way_mode(mocker, default_conf_usdt, fee):
    """hedge_mode 关闭：`_hedge_mode` 为假，回测仍走上游的单方向 + 互斥路径。"""
    backtesting, _ = _prep_backtesting(
        mocker, default_conf_usdt, fee, hedge=False, pairs=["ETH/USDT:USDT"]
    )
    assert backtesting._hedge_mode is False
    assert backtesting.check_for_trade_entry(_make_row(1, 0, 1, 0)) is None


def test_backtest_hedge_on_both_legs_same_candle(mocker, default_conf_usdt, fee):
    """端到端：同一根 K 线上两条腿一起建仓，且**建仓价完全相同**。

    上游在同一个场景下一笔都不开（两个方向互相取消）。
    """
    pairs = ["ETH/USDT:USDT"]
    backtesting, data = _prep_backtesting(
        mocker, default_conf_usdt, fee, hedge=True, pairs=pairs, max_open_trades=4
    )
    backtesting.strategy.advise_entry = _both_sides_same_candle
    backtesting.strategy.advise_exit = _both_sides_same_candle

    processed = backtesting.strategy.advise_all_indicators(data)
    min_date, max_date = get_timerange(processed)
    results = backtesting.backtest(
        processed=deepcopy(processed), start_date=min_date, end_date=max_date
    )

    trades = results["results"]
    # 两根腿都在场，方向各一
    assert len(trades) == 2
    assert set(trades["is_short"]) == {True, False}

    # 同一根 K 线、同一个价格建仓 —— 这就是"同时开仓"的全部意义
    assert trades["open_date"].nunique() == 1
    assert trades["open_rate"].nunique() == 1

    # 出场（清仓）时两条腿各自独立
    assert trades["close_date"].nunique() == 1


def test_backtest_hedge_off_same_candle_signal_opens_nothing(mocker, default_conf_usdt, fee):
    """hedge_mode 关闭：同一根 K 线上两列都置 1 → 一个方向都不开（上游行为不变）。"""
    backtesting, data = _prep_backtesting(
        mocker, default_conf_usdt, fee, hedge=False, pairs=["ETH/USDT:USDT"]
    )
    backtesting.strategy.advise_entry = _both_sides_same_candle
    backtesting.strategy.advise_exit = _both_sides_same_candle

    processed = backtesting.strategy.advise_all_indicators(data)
    min_date, max_date = get_timerange(processed)
    results = backtesting.backtest(
        processed=deepcopy(processed), start_date=min_date, end_date=max_date
    )

    assert len(results["results"]) == 0
    assert LocalTrade.bt_trades_open_pp["ETH/USDT:USDT"] == []


def test_backtest_hedge_on_requires_per_direction_slot(mocker, default_conf_usdt, fee):
    """同一方向不允许两笔：K 线上每根都给双向信号，最终也只有两条腿。"""
    pairs = ["ETH/USDT:USDT", "LTC/USDT:USDT"]
    backtesting, data = _prep_backtesting(
        mocker, default_conf_usdt, fee, hedge=True, pairs=pairs, max_open_trades=8
    )
    # 每根 K 线都给双向信号（比每 20 根更极端）
    backtesting.strategy.advise_entry = _always_both_sides
    backtesting.strategy.advise_exit = _always_both_sides

    processed = backtesting.strategy.advise_all_indicators(data)
    min_date, max_date = get_timerange(processed)
    results = backtesting.backtest(
        processed=deepcopy(processed), start_date=min_date, end_date=max_date
    )

    trades = results["results"]
    # 每个币种最多 2 条腿（同方向叠加被按方向的名额挡下）
    assert len(trades) == 4
    counts = trades.groupby("pair")["is_short"].apply(lambda s: sorted(s.tolist()))
    assert all(v == [False, True] for v in counts), counts


def _always_both_sides(dataframe=None, metadata=None):
    dataframe["enter_long"] = np.where(dataframe["volume"] > 0, 1, 0)
    dataframe["enter_short"] = dataframe["enter_long"]
    dataframe["exit_long"] = 0
    dataframe["exit_short"] = 0
    return dataframe


def test_hedge_mode_backtest_signal_direction_is_long_short_typed(mocker, default_conf_usdt, fee):
    """`check_for_trade_entries` 返回的顺序与类型（LongShort）稳定：先多后空。"""
    backtesting, _ = _prep_backtesting(
        mocker, default_conf_usdt, fee, hedge=True, pairs=["ETH/USDT:USDT"]
    )
    dirs = backtesting.check_for_trade_entries(_make_row(1, 0, 1, 0))
    assert dirs == ["long", "short"]
    assert all(isinstance(d, str) for d in dirs)
    assert SignalDirection.LONG.value == dirs[0]
