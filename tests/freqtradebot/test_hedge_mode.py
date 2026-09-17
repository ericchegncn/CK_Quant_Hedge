"""主循环层（阶段 3）双向持仓契约测试。

钉住四条契约（每一条对应一个真实会亏钱的错误）：
  1. **默认关闭**：同一币种开了多头后，空头信号不得再开一笔 —— 单向路径行为不变
  2. **打开后第二条腿能开出来**：只占一个方向的币种必须留在候选里，
     且反方向信号可以真正开仓（这是 fork 存在的理由）
  3. **同向绝不能两笔**：同一 (币种, 方向) 已有持仓时 create_trade 直接拒绝
     （whitelist 在双向模式下会保留只占一边的币种，所以门禁必须在 create_trade）
  4. **槽位按笔计数**：两条腿 = 两个槽位，max_open_trades 是「最多几条腿」

注意：`create_trade` 方向门禁只在 hedge_mode 打开时生效 —— 上游
`test_create_trades_preopen` 明确断言「已持仓的币种仍能直接 create_trade」，
单向路径必须保持这个行为。
"""
from unittest.mock import MagicMock

from freqtrade.freqtradebot import FreqtradeBot
from freqtrade.persistence import Trade
from tests.conftest import EXMS, get_patched_freqtradebot, patch_exchange, patch_get_signal


def _prep(mocker, default_conf_usdt, ticker, fee, hedge, whitelist, max_open_trades=4):
    mocker.patch("freqtrade.freqtradebot.RPCManager", MagicMock())
    patch_exchange(mocker)
    mocker.patch.multiple(
        EXMS,
        fetch_ticker=ticker,
        get_fee=fee,
        # 成交价不越界 → 入场单挂着未成交，但交易记录已建立且 is_open
        _dry_is_price_crossed=MagicMock(return_value=False),
    )
    default_conf_usdt["hedge_mode"] = hedge
    default_conf_usdt["max_open_trades"] = max_open_trades
    default_conf_usdt["exchange"]["pair_whitelist"] = whitelist
    return FreqtradeBot(default_conf_usdt)


def _open_leg(freqtrade, pair, is_short):
    """直接建一条腿（绕开信号），用于构造「已经占了一个方向」的局面。"""
    assert freqtrade.execute_entry(
        pair, freqtrade.config["stake_amount"], is_short=is_short
    )
    return Trade.get_trades_proxy(pair=pair, is_open=True)[-1]


def test_hedge_off_blocks_second_leg(default_conf_usdt, ticker_usdt, fee, mocker):
    """默认关闭：一个币种只允许一笔，反方向信号也不得再开。"""
    freqtrade = _prep(
        mocker, default_conf_usdt, ticker_usdt, fee, hedge=False, whitelist=["ETH/USDT"]
    )
    patch_get_signal(freqtrade, enter_long=True)
    _open_leg(freqtrade, "ETH/USDT", is_short=False)
    assert len(Trade.get_open_trades()) == 1

    # 切成空头信号：币种已被 whitelist 剔除 → 开不出来
    patch_get_signal(freqtrade, enter_long=False, enter_short=True)
    assert freqtrade.enter_positions(1) == 0
    assert len(Trade.get_open_trades()) == 1


def test_hedge_on_opens_opposite_leg(default_conf_usdt, ticker_usdt, fee, mocker):
    """打开后：只占多头的币种保持候选，空头信号应开出第二条腿。

    这是 fork 的核心目的 —— 上游在这里永远开不出第二笔（whitelist 无差别剔除）。
    """
    freqtrade = _prep(
        mocker, default_conf_usdt, ticker_usdt, fee, hedge=True, whitelist=["ETH/USDT"]
    )
    patch_get_signal(freqtrade, enter_long=True)
    _open_leg(freqtrade, "ETH/USDT", is_short=False)

    patch_get_signal(freqtrade, enter_long=False, enter_short=True)
    assert freqtrade.enter_positions(1) == 1

    trades = Trade.get_trades_proxy(pair="ETH/USDT", is_open=True)
    assert len(trades) == 2
    assert {t.trade_direction for t in trades} == {"long", "short"}


def test_hedge_on_blocks_same_direction_leg(default_conf_usdt, ticker_usdt, fee, mocker):
    """同向绝不允许两笔：即使直接调 create_trade 也必须被挡下。"""
    freqtrade = _prep(
        mocker, default_conf_usdt, ticker_usdt, fee, hedge=True, whitelist=["ETH/USDT"]
    )
    patch_get_signal(freqtrade, enter_long=True)
    _open_leg(freqtrade, "ETH/USDT", is_short=False)

    # 同一个多头信号：方向门禁必须拦下（不能只靠 whitelist）
    assert freqtrade.create_trade("ETH/USDT") is False
    assert freqtrade.enter_positions(1) == 0
    assert len(Trade.get_trades_proxy(pair="ETH/USDT", is_open=True)) == 1


def test_hedge_on_both_legs_removes_pair_from_whitelist(
    default_conf_usdt, ticker_usdt, fee, mocker, caplog
):
    """两个方向都占满后，该币种才被剔除（此时才应该报「没有候选币种」）。"""
    freqtrade = _prep(
        mocker, default_conf_usdt, ticker_usdt, fee, hedge=True, whitelist=["ETH/USDT"]
    )
    patch_get_signal(freqtrade, enter_long=True)
    _open_leg(freqtrade, "ETH/USDT", is_short=False)
    patch_get_signal(freqtrade, enter_long=False, enter_short=True)
    assert freqtrade.enter_positions(1) == 1
    assert len(Trade.get_open_trades()) == 2

    # 两边都占了 → 候选被清空
    assert freqtrade.enter_positions(1) == 0
    assert any(
        "No currency pair in active pair whitelist" in r.message for r in caplog.records
    )


def test_hedge_on_slots_count_legs(default_conf_usdt, ticker_usdt, fee, mocker):
    """槽位口径按笔：两条腿吃掉两个槽位（各自占保证金、各自有止损风险）。"""
    freqtrade = _prep(
        mocker,
        default_conf_usdt,
        ticker_usdt,
        fee,
        hedge=True,
        whitelist=["ETH/USDT"],
        max_open_trades=2,
    )
    patch_get_signal(freqtrade, enter_long=True)
    _open_leg(freqtrade, "ETH/USDT", is_short=False)
    assert freqtrade.get_free_open_trades() == 1

    patch_get_signal(freqtrade, enter_long=False, enter_short=True)
    assert freqtrade.enter_positions(1) == 1
    # 两笔腿 = 两个槽位，双双占满
    assert freqtrade.get_free_open_trades() == 0
    assert Trade.get_open_trade_count() == 2
    # 槽位耗尽后连信号都不再评估：无空闲槽位 → create_trade 对任何币种直接拒绝
    assert freqtrade.create_trade("LTC/USDT") is False


def test_hedge_mode_end_to_end_two_legs(default_conf_usdt, ticker_usdt, fee, mocker):
    """端到端（真实主循环 `process()`）：同币多空两条腿各自开仓、各自平仓。

    上面几条测的是单点契约，这条把整条链路串起来跑：
      process → enter_positions → create_trade → execute_entry（多头腿）
      process → enter_positions → create_trade（方向门禁放行反方向）→ 空头腿
      process → exit_positions → handle_trade（只平收到出场信号的那条腿）
    关键断言：第二轮能开出第二条腿（上游此处永远 0 笔），
    且出场时**只动对应方向**，另一条腿不受影响。
    """
    default_conf_usdt["hedge_mode"] = True
    default_conf_usdt["max_open_trades"] = 4
    default_conf_usdt["exchange"]["pair_whitelist"] = ["ETH/USDT"]

    freqtrade = get_patched_freqtradebot(mocker, default_conf_usdt)
    mocker.patch.multiple(
        EXMS,
        fetch_ticker=ticker_usdt,
        get_fee=fee,
        amount_to_precision=lambda s, x, y: round(y, 4),
        price_to_precision=lambda s, x, y: y,
    )

    def _legs():
        return Trade.get_trades_proxy(pair="ETH/USDT", is_open=True)

    # 第一轮：多头信号 → 第一条腿
    patch_get_signal(freqtrade, enter_long=True)
    freqtrade.process()
    assert len(_legs()) == 1
    long_leg = _legs()[0]
    assert long_leg.is_short is False

    # 第二轮：空头信号 → 同一币种的第二条腿（上游在这里永远开不出来）
    patch_get_signal(freqtrade, enter_long=False, enter_short=True)
    freqtrade.process()
    legs = _legs()
    assert len(legs) == 2
    assert {t.trade_direction for t in legs} == {"long", "short"}
    short_leg = next(t for t in legs if t.is_short is True)

    # 第三轮：只给多头出场信号 → 只平多头腿，空头腿仍在
    patch_get_signal(freqtrade, enter_long=False, exit_long=True)
    freqtrade.process()
    assert long_leg.is_open is False
    remaining = _legs()
    assert [t.id for t in remaining] == [short_leg.id]
    # 平多头 = 卖出、平空头 = 买回 —— 各自取对边
    assert long_leg.orders[-1].side == "sell"

    # 第四轮：只给空头出场信号 → 空头腿也独立平掉
    patch_get_signal(freqtrade, enter_long=False, enter_short=False, exit_short=True)
    freqtrade.process()
    assert short_leg.is_open is False
    assert short_leg.orders[-1].side == "buy"
    assert _legs() == []
