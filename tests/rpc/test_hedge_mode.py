"""持久化/RPC 层（阶段 4）双向持仓契约测试 —— `/forceenter` 的方向归属。

钉住三条契约：
  1. **双向模式下反方向必须能开新腿**：已有空头腿时 `/forceenter <pair> long`
     要开出一条新的多头腿，而不是报「position already open」
  2. **同方向仍不得第二笔**：已有同向腿时 `/forceenter` 照旧拒绝
     （否则两笔记录指向同一个交易所仓位）
  3. **默认关闭时行为不变**：单向模式下反方向同样报「already open」——
     关掉开关就是上游行为，逐字节一致

背景：`_rpc_force_entry` 原本只按 `pair` 查开仓记录，双向模式下会抓到错的那条腿，
于是反方向请求被当成对该腿的加仓（甚至静默把方向改成该腿的方向）。
"""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from freqtrade.enums import SignalDirection
from freqtrade.persistence import Trade
from freqtrade.rpc import RPC, RPCException
from tests.conftest import EXMS, get_patched_freqtradebot, patch_get_signal


def _prep(
    mocker,
    default_conf_usdt,
    ticker,
    fee,
    limit_buy_order_usdt_open,
    limit_sell_order_usdt_open,
    hedge,
):
    default_conf_usdt["force_entry_enable"] = True
    default_conf_usdt["max_open_trades"] = 5
    default_conf_usdt["hedge_mode"] = hedge

    def _fake_order(*args, **kwargs):
        # execute_entry 用关键字调用 create_order；按 side 返回对应方向的挂单
        side = kwargs.get("side") or (args[2] if len(args) > 2 else "buy")
        base = limit_buy_order_usdt_open if side == "buy" else limit_sell_order_usdt_open
        return deepcopy(base)

    mocker.patch("freqtrade.rpc.telegram.Telegram", MagicMock())
    mocker.patch.multiple(
        EXMS,
        get_balances=MagicMock(return_value=ticker),
        fetch_ticker=ticker,
        get_fee=fee,
        _dry_is_price_crossed=MagicMock(return_value=False),
        create_order=MagicMock(side_effect=_fake_order),
    )
    freqtradebot = get_patched_freqtradebot(mocker, default_conf_usdt)
    patch_get_signal(freqtradebot)
    return freqtradebot, RPC(freqtradebot)


def _open_leg(freqtradebot, pair, is_short):
    assert freqtradebot.execute_entry(
        pair, freqtradebot.config["stake_amount"], is_short=is_short
    )
    return Trade.get_trades_proxy(pair=pair, is_open=True)[-1]


def test_hedge_on_force_entry_opens_opposite_leg(
    mocker,
    default_conf_usdt,
    ticker_usdt,
    fee,
    limit_buy_order_usdt_open,
    limit_sell_order_usdt_open,
):
    """打开后：已有空头腿时 force-entry 多头应开出一条新的多头腿。"""
    freqtradebot, rpc = _prep(
        mocker,
        default_conf_usdt,
        ticker_usdt,
        fee,
        limit_buy_order_usdt_open,
        limit_sell_order_usdt_open,
        hedge=True,
    )
    short_leg = _open_leg(freqtradebot, "ETH/USDT", is_short=True)
    assert len(Trade.get_open_trades()) == 1

    trade = rpc._rpc_force_entry("ETH/USDT", 2.0, order_side=SignalDirection.LONG)

    assert isinstance(trade, Trade)
    assert trade is not None
    assert trade.is_short is False
    assert trade.id != short_leg.id
    assert len(Trade.get_open_trades()) == 2
    # 原有空头腿不受影响（不是被"加仓"，也没被改写）
    assert short_leg.is_open is True
    assert short_leg.is_short is True


def test_hedge_on_force_entry_same_direction_refused(
    mocker,
    default_conf_usdt,
    ticker_usdt,
    fee,
    limit_buy_order_usdt_open,
    limit_sell_order_usdt_open,
):
    """同向绝不允许两笔：已有同向腿时 force-entry 照旧拒绝。"""
    freqtradebot, rpc = _prep(
        mocker,
        default_conf_usdt,
        ticker_usdt,
        fee,
        limit_buy_order_usdt_open,
        limit_sell_order_usdt_open,
        hedge=True,
    )
    long_leg = _open_leg(freqtradebot, "ETH/USDT", is_short=False)

    with pytest.raises(RPCException, match=rf"position for ETH/USDT already open - id: {long_leg.id}"):
        rpc._rpc_force_entry("ETH/USDT", 2.0, order_side=SignalDirection.LONG)
    assert len(Trade.get_open_trades()) == 1


def test_hedge_off_force_entry_opposite_still_refused(
    mocker,
    default_conf_usdt,
    ticker_usdt,
    fee,
    limit_buy_order_usdt_open,
    limit_sell_order_usdt_open,
):
    """关键回归防线：关闭开关时，反方向请求仍按上游语义报「already open」。"""
    freqtradebot, rpc = _prep(
        mocker,
        default_conf_usdt,
        ticker_usdt,
        fee,
        limit_buy_order_usdt_open,
        limit_sell_order_usdt_open,
        hedge=False,
    )
    short_leg = _open_leg(freqtradebot, "ETH/USDT", is_short=True)

    with pytest.raises(RPCException, match=rf"position for ETH/USDT already open - id: {short_leg.id}"):
        rpc._rpc_force_entry("ETH/USDT", 2.0, order_side=SignalDirection.LONG)
    assert len(Trade.get_open_trades()) == 1
