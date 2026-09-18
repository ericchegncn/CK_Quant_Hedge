"""HedgeModeDemo —— 只用来**验证双向持仓**的最小示例策略（不是交易策略）

这个文件的唯一用途：让你在几分钟内亲眼看到
「同一个币种同时持有多头与空头两条腿」这件事在本分支上真的成立。

它**没有任何盈利意图**：入场只用一条 RSI 规则，止盈止损都很粗糙，
参数也没有调过。请把它当成一个"能力演示 + 冒烟测试"，不要拿去实盘。

它怎么演示双向持仓：
  - `can_short = True`              —— 允许做空（双向持仓的前提）
  - 两条腿用**各自独立**的判据入场：RSI < 35 开多头腿、RSI > 65 开空头腿
  - **出场阈值刻意不对称**（多头等到 RSI > 70 才平、空头等到 RSI < 30 才平）：
    这样"多头还开着的时候 RSI 已经涨到 65 以上"就必然发生 → 空头腿进场 →
    **两条腿在同一币种上同时在场**。
    （如果出场阈值对称，多头在 RSI>55 就平掉了，永远等不到开空那一刻，
      这个示例就演示不出双向持仓了 —— 这点是踩过的坑，别改回去。）
  - 配合配置里的 `position_stacking: true`，同币的多空两条腿可以同时在场
    （回测器里同一根 K 线的 long/short 信号仍是互斥的，所以两条腿必然
      在不同 K 线上分别开出来，然后在场时间重叠）

怎么用（完整步骤见 docs/hedge-mode.md）：
    freqtrade backtesting \
      --config docs/examples/hedge-dryrun.example.json \
      --strategy HedgeModeDemo --strategy-path user_data/strategy \
      --datadir user_data/data/binance --timerange 20260601-20260801

期望看到的结果：出场统计里**同时**出现多头与空头两行；用
    freqtrade backtesting-analysis
可以逐笔确认同一币种的多空腿持有区间有重叠。
"""

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class HedgeModeDemo(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "15m"
    can_short = True
    process_only_new_candles = True
    startup_candle_count = 40

    minimal_roi = {"0": 0.02}
    stoploss = -0.05
    trailing_stop = False
    use_custom_stoploss = False

    # 演示用：不做仓位调整，保持逻辑一眼能看完
    position_adjustment_enable = False

    plot_config = {"main_plot": {}, "subplots": {"RSI": {"rsi": {}}}}

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 两条腿用**互相独立**的判据 —— 这是"双向"的关键：
        # 不是"要么做多要么做空"，而是两边各自判断、各自持仓。
        dataframe.loc[dataframe["rsi"] < 35, ["enter_long", "enter_tag"]] = (1, "rsi_oversold")
        dataframe.loc[dataframe["rsi"] > 65, ["enter_short", "enter_tag"]] = (1, "rsi_overbought")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 出场阈值**刻意不对称**（多头 70 / 空头 30）：
        # 多头还没平掉时 RSI 就可能已越过 65（开空条件）→ 两条腿同时在场。
        # 若改成对称阈值（例如都在 55/45 平），两条腿永远不会重叠，
        # 这个示例也就演示不出双向持仓了。
        dataframe.loc[dataframe["rsi"] > 70, ["exit_long", "exit_tag"]] = (1, "rsi_high")
        dataframe.loc[dataframe["rsi"] < 30, ["exit_short", "exit_tag"]] = (1, "rsi_low")
        return dataframe
