"""保护锁方向（阶段 4）双向持仓契约测试。

上游的按币种保护锁（CooldownPeriod 等）默认 `lock_side="*"` —— 锁整个币种。
单向模式下没问题，但双向持仓下一条腿止损会把**另一条腿的入场也一起冻结**，
网格类策略直接瘫痪。

契约：
  1. `hedge_mode` 打开时，按币种的保护锁只锁触发它的那个方向
  2. 关闭时仍是 `"*"`（单向行为逐字节不变）
"""
from datetime import timedelta

from freqtrade.persistence import PairLocks
from freqtrade.plugins.protectionmanager import ProtectionManager
from freqtrade.plugins.protections import ProtectionReturn
from freqtrade.util.datetime_helpers import dt_now


def _manager(default_conf, mocker):
    man = ProtectionManager(
        default_conf, [{"method": "CooldownPeriod", "stop_duration": 60}]
    )
    assert len(man._protection_handlers) == 1
    handler = man._protection_handlers[0]
    # 让保护必然触发；这里只关心锁的方向，不关心触发阈值
    mocker.patch.object(
        handler,
        "_cooldown_period",
        return_value=ProtectionReturn(
            lock=True, until=dt_now() + timedelta(minutes=60), reason="test lock"
        ),
    )
    return man


def test_hedge_on_protection_lock_is_direction_scoped(default_conf, mocker, init_persistence):
    """打开后：按币种保护锁只锁住触发它的方向，另一条腿仍可入场。"""
    default_conf["hedge_mode"] = True
    man = _manager(default_conf, mocker)

    lock = man.stop_per_pair("ETH/USDT", side="long")
    assert lock is not None
    assert lock.side == "long"

    # 只锁住 long —— 该方向被锁，反方向不受影响
    assert PairLocks.is_pair_locked("ETH/USDT", side="long") is True
    assert PairLocks.is_pair_locked("ETH/USDT", side="short") is False


def test_hedge_off_protection_lock_unchanged(default_conf, mocker, init_persistence):
    """关键回归防线：关闭开关时保护锁仍然是整币种锁（上游行为不变）。"""
    default_conf["hedge_mode"] = False
    man = _manager(default_conf, mocker)

    lock = man.stop_per_pair("ETH/USDT", side="long")
    assert lock is not None
    assert lock.side == "*"

    assert PairLocks.is_pair_locked("ETH/USDT", side="long") is True
    assert PairLocks.is_pair_locked("ETH/USDT", side="short") is True
