# CK Quant Hedge `hedge-2026.8.1`

## 这次发布带来了什么

**双向持仓（Hedge Mode）** —— 同一个币种可以**同时持有多头与空头两条腿**。

上游 freqtrade 明确不支持这个能力：它的持仓簿以 `pair` 为键，一个币种只能有一笔持仓在场，
且币安合约 Hedge Mode 要求的 `positionSide` 在上游代码里根本不存在。

本分支把持仓簿的键改成 `(pair, direction)`，并在四个层次收口：
钱包层（保证金/出场按腿）→ 交易所层（`positionSide` 全链路）→
主循环（入场候选按方向剔除、方向门禁、槽位按笔）→ 持久化/RPC/保护锁。

## 快速开始

| 资源 | 位置 |
|---|---|
| Docker 镜像 | `ericchenghz/ck-quant-hedge:latest` |
| Android APK | 本页下方的 `CK-Quant-Hedge-Android-*.apk`（附 SHA-256） |
| 安装部署与参数说明 | [`docs/hedge-mode.md`](https://github.com/ericchegncn/CK_Quant_Hedge/blob/main/docs/hedge-mode.md) |

最小配置（三个参数缺一不可）：

```json
{
    "trading_mode": "futures",
    "margin_mode": "cross",
    "hedge_mode": true,
    "max_open_trades": 20
}
```

**注意**：`max_open_trades` 按**腿数**算 —— 一个币最多两条腿，20 个币想全部在场就要给 40。

**逐仓 vs 全仓**是这个功能最关键的一次选择：逐仓损失封顶但走反的腿会被强平清场；
全仓不会单腿爆仓，但风险移到账户级，必须自己把单腿最大保证金框住。
详见 [`docs/hedge-mode.md` 第 4.3 节](https://github.com/ericchegncn/CK_Quant_Hedge/blob/main/docs/hedge-mode.md)。

## 兼容性契约

1. **`hedge_mode` 默认关闭**。关闭时请求参数里不出现 `positionSide`、保留 `reduceOnly`
   ⇒ 现有单向实盘/模拟盘路径**逐字节不变**。
2. **打开时不下发 `reduceOnly`** —— 币安在 Hedge Mode 下会直接拒单。
3. `positionSide` 由**这笔交易的方向**决定，与 buy/sell 无关（平多头仍是 `LONG`）。

回测时记得 `position_stacking: true`，否则回测器仍按"一个币一笔"处理，与实盘不一致。

## 本仓库的隐私边界

本仓库**只包含框架能力**，不含任何私人策略、实盘配置、凭据或服务器信息。
`.github/workflows/privacy-guard.yml` 会在每次推送时自动校验：

- 禁止被跟踪的路径：`user_data/strategies/**`、`scripts/ssh_*.py`、`tests/strategy/test_ck_*.py` 等
- 禁止出现的代码：`from user_data.strategies.CK_...`、`class CK_(Trend|EMA|...)`
- 禁止在文档里同时出现**凭据类字面值**与**公网 IP**

## 测试

```bash
pytest tests/exchange/test_hedge_mode.py tests/freqtradebot/test_hedge_mode.py \
       tests/rpc/test_hedge_mode.py tests/plugins/test_hedge_mode.py \
       tests/test_wallets.py -q
```

其中 `tests/freqtradebot/test_hedge_mode.py::test_hedge_mode_end_to_end_two_legs`
跑的是**真实主循环 `process()`**：多头腿开仓 → 空头腿开仓（同币两条腿同时在场）
→ 只给多头出场信号时只平多头腿 → 再平空头腿。

## 许可

与上游一致，**GPL-3.0**，见 `LICENSE`。
