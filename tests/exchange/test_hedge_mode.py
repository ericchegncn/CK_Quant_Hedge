"""双向持仓（Hedge Mode）交易所层契约测试。

钉住三条契约：
  1. 默认关闭时，参数里**不得**出现 positionSide —— 单向路径行为不变
  2. 打开后，positionSide 由「交易方向」决定，与 buy/sell 无关
     （平多头仍是 LONG，平空头仍是 SHORT —— 错了就是平错仓）
  3. 开仓、止损两条下单路径都必须带上该字段
"""
from unittest.mock import MagicMock

from tests.conftest import EXMS, get_patched_exchange  # noqa: F401


def _futures_conf(default_conf, hedge):
    conf = default_conf.copy()
    conf.update(
        {
            # 必须关掉 dry_run：dry-run 下 create_order 会直接返回模拟单，
            # 不会走到 self._api.create_order，参数注入也就无从验证。
            "dry_run": False,
            "trading_mode": "futures",
            "margin_mode": "isolated",
            "hedge_mode": hedge,
            # 取价方向（默认 same：平多取 ask、平空取 bid）—— 测试配置未经 schema
            # 校验，这些键在 default_conf 里并不完整，需显式给出。
            "entry_pricing": {
                "price_side": "same",
                "use_order_book": False,
                "order_book_top": 1,
                "price_last_balance": 0.0,
            },
            "exit_pricing": {
                "price_side": "same",
                "use_order_book": False,
                "order_book_top": 1,
                "price_last_balance": 0.0,
            },
        }
    )
    return conf


def _prep_exchange(mocker, default_conf, hedge):
    exchange = get_patched_exchange(mocker, _futures_conf(default_conf, hedge))
    mocker.patch.object(exchange, "price_to_precision", return_value=100.0)
    mocker.patch.object(exchange, "amount_to_precision", return_value=1.0)
    mocker.patch.object(exchange, "_amount_to_contracts", return_value=1.0)
    mocker.patch.object(exchange, "_order_contracts_to_amount", side_effect=lambda o: o)
    mocker.patch.object(exchange, "_lev_prep")
    exchange._api = MagicMock()
    exchange._api.create_order = MagicMock(
        return_value={"id": "1", "status": "open", "filled": 1.0, "amount": 1.0}
    )
    return exchange


def _captured_params(exchange):
    """取出真正传给交易所的 params。

    普通下单路径用的是位置参数，止损路径用的是关键字参数 —— 两种都要覆盖，
    否则测试会因为取值方式不同而假失败（或更糟：假通过）。
    """
    call = exchange._api.create_order.call_args
    if call.kwargs.get("params") is not None:
        return call.kwargs["params"]
    return call[0][5]


def test_hedge_mode_disabled_by_default(default_conf, mocker):
    """默认关闭：不开开关时，任何方向都不产生 positionSide。"""
    exchange = _prep_exchange(mocker, default_conf, hedge=False)
    assert exchange._hedge_mode_enabled() is False
    assert exchange._get_position_side("long") is None
    assert exchange._get_position_side("short") is None


def test_hedge_mode_position_side_mapping(default_conf, mocker):
    """开关打开后的方向映射；未提供方向时仍返回 None（不猜）。"""
    exchange = _prep_exchange(mocker, default_conf, hedge=True)
    assert exchange._hedge_mode_enabled() is True
    assert exchange._get_position_side("long") == "LONG"
    assert exchange._get_position_side("short") == "SHORT"
    assert exchange._get_position_side(None) is None


def test_hedge_off_order_params_unchanged(default_conf, mocker):
    """关键回归防线：关闭时订单参数与单向实现一致 —— 不得出现 positionSide。"""
    exchange = _prep_exchange(mocker, default_conf, hedge=False)
    exchange.create_order(
        pair="ETH/USDT:USDT",
        ordertype="market",
        side="sell",
        amount=1.0,
        rate=100.0,
        leverage=5.0,
        position_side="short",
    )
    params = _captured_params(exchange)
    assert "positionSide" not in params


def test_hedge_on_entry_carries_position_side(default_conf, mocker):
    """打开后开仓带方向；注意 positionSide 取自传入的交易方向，而非 buy/sell。"""
    exchange = _prep_exchange(mocker, default_conf, hedge=True)

    # 开空：订单方向是 sell，交易方向是 short → SHORT
    exchange.create_order(
        pair="ETH/USDT:USDT",
        ordertype="market",
        side="sell",
        amount=1.0,
        rate=100.0,
        leverage=5.0,
        position_side="short",
    )
    assert exchange._api.create_order.call_args[0][5]["positionSide"] == "SHORT"

    # 平多头：订单方向是 sell、reduceOnly=True，但交易方向仍是 long → LONG
    exchange.create_order(
        pair="ETH/USDT:USDT",
        ordertype="market",
        side="sell",
        amount=1.0,
        rate=100.0,
        leverage=5.0,
        reduceOnly=True,
        position_side="long",
    )
    assert exchange._api.create_order.call_args[0][5]["positionSide"] == "LONG"


def test_hedge_on_never_sends_reduce_only(default_conf, mocker):
    """双向模式下**任何**订单都不得出现 reduceOnly。

    币安官方：reduceOnly「Cannot be sent in Hedge Mode」，带上就是拒单 ——
    平仓意图必须完全由 side + positionSide 表达（平多 = SELL+LONG，
    平空 = BUY+SHORT）。这里同时覆盖开仓、平仓、止损三条路径。
    """
    exchange = _prep_exchange(mocker, default_conf, hedge=True)
    mocker.patch.object(exchange, "_get_stop_order_type", return_value=("market", "market"))
    mocker.patch.object(exchange, "_get_stop_limit_rate", return_value=None)
    mocker.patch.object(exchange, "_get_stop_params", return_value={})

    # 开仓
    exchange.create_order(
        pair="ETH/USDT:USDT",
        ordertype="market",
        side="buy",
        amount=1.0,
        rate=100.0,
        leverage=5.0,
        position_side="long",
    )
    assert "reduceOnly" not in _captured_params(exchange)

    # 平仓（reduceOnly 入参为 True，但不得落到参数里）
    exchange.create_order(
        pair="ETH/USDT:USDT",
        ordertype="market",
        side="sell",
        amount=1.0,
        rate=100.0,
        leverage=5.0,
        reduceOnly=True,
        position_side="long",
    )
    params = _captured_params(exchange)
    assert "reduceOnly" not in params
    assert params["positionSide"] == "LONG"

    # 止损单
    exchange.create_stoploss(
        pair="ETH/USDT:USDT",
        amount=1.0,
        stop_price=90.0,
        order_types={"stoploss": "market"},
        side="buy",
        leverage=5.0,
        position_side="short",
    )
    params = _captured_params(exchange)
    assert "reduceOnly" not in params
    assert params["positionSide"] == "SHORT"


def test_hedge_off_still_sends_reduce_only(default_conf, mocker):
    """关键回归防线：关闭开关时 reduceOnly 照旧发送，参数与单向实现一致。"""
    exchange = _prep_exchange(mocker, default_conf, hedge=False)
    mocker.patch.object(exchange, "_get_stop_order_type", return_value=("market", "market"))
    mocker.patch.object(exchange, "_get_stop_limit_rate", return_value=None)
    mocker.patch.object(exchange, "_get_stop_params", return_value={})

    exchange.create_order(
        pair="ETH/USDT:USDT",
        ordertype="market",
        side="sell",
        amount=1.0,
        rate=100.0,
        leverage=5.0,
        reduceOnly=True,
        position_side="long",
    )
    params = _captured_params(exchange)
    assert params["reduceOnly"] is True
    assert "positionSide" not in params

    exchange.create_stoploss(
        pair="ETH/USDT:USDT",
        amount=1.0,
        stop_price=90.0,
        order_types={"stoploss": "market"},
        side="sell",
        leverage=5.0,
        position_side="long",
    )
    params = _captured_params(exchange)
    assert params["reduceOnly"] is True
    assert "positionSide" not in params


def test_hedge_on_stoploss_carries_position_side(default_conf, mocker):
    """止损单必须带方向，否则双向模式下会被交易所拒单。"""
    exchange = _prep_exchange(mocker, default_conf, hedge=True)
    mocker.patch.object(exchange, "_get_stop_order_type", return_value=("market", "market"))
    mocker.patch.object(exchange, "_get_stop_limit_rate", return_value=None)
    mocker.patch.object(exchange, "_get_stop_params", return_value={})
    exchange._api.create_order = MagicMock(
        return_value={"id": "sl1", "status": "open", "filled": 1.0, "amount": 1.0}
    )

    exchange.create_stoploss(
        pair="ETH/USDT:USDT",
        amount=1.0,
        stop_price=90.0,
        order_types={"stoploss": "market"},
        side="sell",
        leverage=5.0,
        position_side="short",
    )
    params = _captured_params(exchange)
    assert params["positionSide"] == "SHORT"
    # 双向模式不得发 reduceOnly（币安拒单），意图由 side + positionSide 表达
    assert "reduceOnly" not in params


def test_hedge_on_rate_cache_is_direction_scoped(default_conf, mocker):
    """同币多空两笔的取价必须各用各的一侧。

    默认 exit_pricing.price_side="same" 下：平多卖出取 ask、平空买回取 bid。
    缓存键若只按币种，后写入的一条腿会覆盖另一条 —— 两条腿用同一个（错的）价平仓。
    """
    exchange = _prep_exchange(mocker, default_conf, hedge=True)
    ticker = {"symbol": "ETH/USDT:USDT", "bid": 99.0, "ask": 101.0, "last": 100.0}

    long_exit = exchange.get_rate(
        "ETH/USDT:USDT", refresh=True, side="exit", is_short=False, ticker=ticker
    )
    short_exit = exchange.get_rate(
        "ETH/USDT:USDT", refresh=True, side="exit", is_short=True, ticker=ticker
    )
    assert long_exit == 101.0  # 平多 = 卖出 → ask
    assert short_exit == 99.0  # 平空 = 买回 → bid

    # 回读缓存时也要各归各位（这正是逐笔预取 _prefetch_exit_rates 的路径）
    assert (
        exchange.get_rate("ETH/USDT:USDT", refresh=False, side="exit", is_short=False)
        == 101.0
    )
    assert (
        exchange.get_rate("ETH/USDT:USDT", refresh=False, side="exit", is_short=True)
        == 99.0
    )


def test_hedge_off_rate_cache_keeps_pair_key(default_conf, mocker):
    """回归防线：关闭开关时缓存键仍是币种本身，单向路径逐字节不变。"""
    exchange = _prep_exchange(mocker, default_conf, hedge=False)
    ticker = {"symbol": "ETH/USDT:USDT", "bid": 99.0, "ask": 101.0, "last": 100.0}
    exchange.get_rate(
        "ETH/USDT:USDT", refresh=True, side="exit", is_short=False, ticker=ticker
    )
    exchange.get_rate("ETH/USDT:USDT", refresh=True, side="exit", is_short=True, ticker=ticker)
    # 同一个键：后写的值覆盖前一个 —— 单向模式下同币不可能同时存在两笔，故无影响
    assert exchange._exit_rate_cache["ETH/USDT:USDT"] == 99.0
    assert len(exchange._exit_rate_cache) == 1
