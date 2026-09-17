"""
Protection manager class
"""

import logging
from datetime import UTC, datetime
from typing import Any

from freqtrade.constants import Config, LongShort
from freqtrade.exceptions import ConfigurationError
from freqtrade.persistence import PairLocks
from freqtrade.persistence.models import PairLock
from freqtrade.plugins.protections import IProtection
from freqtrade.resolvers import ProtectionResolver


logger = logging.getLogger(__name__)


class ProtectionManager:
    def __init__(self, config: Config, protections: list) -> None:
        self._config = config

        self._protection_handlers: list[IProtection] = []
        self.validate_protections(protections)
        for protection_handler_config in protections:
            protection_handler = ProtectionResolver.load_protection(
                protection_handler_config["method"],
                config=config,
                protection_config=protection_handler_config,
            )
            self._protection_handlers.append(protection_handler)

        if not self._protection_handlers:
            logger.info("No protection Handlers defined.")

    @property
    def name_list(self) -> list[str]:
        """
        Get list of loaded Protection Handler names
        """
        return [p.name for p in self._protection_handlers]

    def short_desc(self) -> list[dict]:
        """
        List of short_desc for each Pairlist Handler
        """
        return [{p.name: p.short_desc()} for p in self._protection_handlers]

    def global_stop(
        self, now: datetime | None = None, side: LongShort = "long", starting_balance: float = 0.0
    ) -> PairLock | None:
        if not now:
            now = datetime.now(UTC)
        result = None
        for protection_handler in self._protection_handlers:
            if protection_handler.has_global_stop:
                lock = protection_handler.global_stop(
                    date_now=now, side=side, starting_balance=starting_balance
                )
                if lock and lock.until:
                    if not PairLocks.is_global_lock(lock.until, side=lock.lock_side):
                        result = PairLocks.lock_pair(
                            "*", lock.until, lock.reason, now=now, side=lock.lock_side
                        )
        return result

    def _lock_side(self, lock_side: str, side: LongShort) -> str:
        """按币种保护锁的方向。

        上游默认锁整个币种（`lock_side="*"`）—— 单向模式下没问题，但双向持仓下
        一条腿止损会把**另一条腿的入场也一起冻结**，网格类策略直接瘫痪。
        `hedge_mode` 打开时把 `"*"` 收窄成触发它的那个方向；关闭时原样返回，
        单向行为逐字节不变。
        全局锁（最大回撤、StoplossGuard 的 global_stop）不走这里 —— 那是对整个
        账户/全部币种的风险闸，仍锁全方向。
        """
        if self._config.get("hedge_mode", False) and lock_side == "*":
            return side
        return lock_side

    def stop_per_pair(
        self,
        pair,
        now: datetime | None = None,
        side: LongShort = "long",
        starting_balance: float = 0.0,
    ) -> PairLock | None:
        if not now:
            now = datetime.now(UTC)
        result = None
        for protection_handler in self._protection_handlers:
            if protection_handler.has_local_stop:
                lock = protection_handler.stop_per_pair(
                    pair=pair, date_now=now, side=side, starting_balance=starting_balance
                )
                if lock and lock.until:
                    lock_side = self._lock_side(lock.lock_side, side)
                    if not PairLocks.is_pair_locked(pair, lock.until, lock_side):
                        result = PairLocks.lock_pair(
                            pair, lock.until, lock.reason, now=now, side=lock_side
                        )
        return result

    @staticmethod
    def validate_protections(protections: list[dict[str, Any]]) -> None:
        """
        Validate protection setup validity
        """

        for prot in protections:
            parsed_unlock_at = None
            if (config_unlock_at := prot.get("unlock_at")) is not None:
                try:
                    parsed_unlock_at = datetime.strptime(config_unlock_at, "%H:%M")
                except ValueError:
                    raise ConfigurationError(
                        f"Invalid date format for unlock_at: {config_unlock_at}."
                    )

            if "stop_duration" in prot and "stop_duration_candles" in prot:
                raise ConfigurationError(
                    "Protections must specify either `stop_duration` or `stop_duration_candles`.\n"
                    f"Please fix the protection {prot.get('method')}."
                )

            if "lookback_period" in prot and "lookback_period_candles" in prot:
                raise ConfigurationError(
                    "Protections must specify either `lookback_period` or "
                    f"`lookback_period_candles`.\n Please fix the protection {prot.get('method')}."
                )

            if parsed_unlock_at is not None and (
                "stop_duration" in prot or "stop_duration_candles" in prot
            ):
                raise ConfigurationError(
                    "Protections must specify either `unlock_at`, `stop_duration` or "
                    "`stop_duration_candles`.\n"
                    f"Please fix the protection {prot.get('method')}."
                )
