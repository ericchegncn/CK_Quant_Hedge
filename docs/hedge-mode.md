# 双向持仓（Hedge Mode）

> 同一币种**同时持有多头与空头两条腿**。这是本分支相对上游 freqtrade 的**唯一能力差异**，
> 也是它存在的理由 —— 上游明确不支持，且短期内不打算支持。

---

## 1. 为什么上游做不到

上游 freqtrade 的持仓簿以 `pair` 为键：**一个币种只能有一笔持仓在场**。
`enter_long` / `enter_short` 在回测器里还互斥（同一根 K 线两列都置 1 时，两个方向都不开）。
币安合约的 Hedge Mode 要求逐笔订单带 `positionSide`，而上游代码里没有这个概念。

## 2. 本分支改了什么（四个层次，逐层收口）

| 层次 | 改动 | 位置 |
|---|---|---|
| **钱包层** | 持仓簿键从 `pair` 改为 `(pair, direction)`；保证金占用、出场金额校验按腿计算 | `freqtrade/wallets.py` |
| **交易所层** | 逐笔订单按方向下发 `positionSide`；**hedge 打开时不下发 `reduceOnly`**；行情缓存键带方向 | `freqtrade/exchange/exchange.py`、`binance.py`、`kucoin.py` |
| **主循环层** | 入场候选按方向剔除（只有多空都占满才跳过该币）；`create_trade` 加方向门禁；槽位按笔计 | `freqtrade/freqtradebot.py` |
| **持久化/RPC** | `/forceenter` 按方向找腿；按币保护锁按方向收敛；逐仓强平价计入同币反向腿 | `rpc/rpc.py`、`plugins/protectionmanager.py`、`exchange/binance.py` |

## 3. 设计契约（改代码前必读）

1. **`positionSide` 由「这笔交易的方向」决定，与 buy/sell 无关。**
   平多头仍是 `LONG`、平空头仍是 `SHORT`。
2. **`hedge_mode` 默认关闭。** 关闭时请求参数里**不出现** `positionSide`、
   **保留** `reduceOnly` ⇒ 现有单向实盘/模拟盘路径**逐字节不变**。
   这是每次改动的第一验收项。
3. **`hedge_mode` 打开时不得出现 `reduceOnly`** —— 币安会直接拒单
   （官方：*Cannot be sent in Hedge Mode*）。平仓意图完全由 `side + positionSide` 表达。
   注意 `reduceOnly` 这个**函数入参**语义不变（仍表示"这是平仓单"），
   只是"是否落到交易所参数里"被开关控制。
4. **主循环里凡"按 pair 决策"的地方都要问一句：方向呢？**
   已处理：入场候选剔除、`create_trade` 门禁、行情缓存键、RPC 查询、按币保护锁、跨保证金强平价。

## 4. 怎么开启

### 4.1 最小配置

```json
{
    "trading_mode": "futures",
    "margin_mode": "cross",
    "hedge_mode": true,
    "max_open_trades": 20
}
```

### 4.2 每个参数为什么必须这么给

| 参数 | 取值 | 说明 |
|---|---|---|
| `trading_mode` | `futures` | 双向持仓是**合约**能力。现货没有 `positionSide` 概念，开启无效。 |
| `margin_mode` | `isolated` / `cross` | **最容易踩错的一个**，见 4.3。 |
| `hedge_mode` | `true` | 总开关。默认 `false`。 |
| `max_open_trades` | 按**腿数**算 | 一个币最多有 2 条腿（多 + 空）。20 个币最多 40 条腿 → 想全部在场就得给 40。给少了不会报错，只是排不进去。 |
| `position_stacking` | 回测时需要 | **仅回测**：回测器没有 hedge 概念，默认一个币只允许一笔在场，不开这个就永远只有一条腿。实盘不需要它（方向门禁已经允许反向腿共存）。 |

### 4.3 逐仓 vs 全仓：这是双向持仓最关键的一次选择

| | 逐仓 `isolated` | 全仓 `cross` |
|---|---|---|
| 强平层级 | **单腿**：每条腿只用自己的保证金兜底 | **账户级**：整个钱包兜底 |
| 强平距离 | 约 `1/杠杆`（价格口径） | 直到账户权益耗尽 |
| 表现 | 走反的腿会被**强平清场**，损失被单腿保证金封顶 | 走反的腿**不爆也不停**，长期占用保证金与槽位（"僵尸腿"，需要靠策略侧的结构控制） |
| 风险 | 单腿爆仓（可预期、可封顶） | 账户级回撤（不可封顶，必须靠仓位上限约束） |

**选择原则**：想"损失封顶、可预期"用逐仓；想"单腿不被强平、能等回来"用全仓 —— 但用全仓必须
自己把每条腿的最大占用框住（`max_open_trades` × 单腿最大保证金必须远小于钱包）。

### 4.4 杠杆

本分支不改变杠杆逻辑：`leverage()` 返回多少就用多少（受交易所上限约束）。
注意一个**只在合约下成立的换算**：

```
保证金波动 = 价格距离 × 杠杆
```

即 2% 的价格波动在 25x 下是 50% 的保证金波动。**凡是以"价格百分比"设定的阈值
（止损、网格间距、止盈），都要乘一遍杠杆再来判断它是不是合理。**

## 5. 双向持仓的六个坑（都已在代码里处理，但你得知道它们存在）

1. **`reduceOnly` 必须去掉** —— 否则币安在 Hedge Mode 下拒单，表现为"平仓单全部失败"。
2. **行情缓存键必须带方向** —— 同币多空取价方向不同（默认平多取 `ask`、平空取 `bid`），
   共用键会让两条腿用同一个错的价格平仓。
3. **按币种的保护锁会误伤另一条腿** —— 上游 `lock_side="*"` 锁整个币种。双向模式下
   一条腿止损会把另一条腿的入场一起冻结。本分支把 `"*"` 收敛成触发它的方向；
   **全局锁不动**（MaxDrawdown / StoplossGuard 这类账户级闸门仍锁全方向）。
4. **逐仓强平价要计入同币反向腿** —— 反方向腿是另一个独立仓位，它的维持保证金与
   未实现盈亏会影响本腿的强平价（跨保证金）。本分支已计入。
5. **RPC `/forceenter` 必须按方向找腿** —— 否则已有空头腿时请求做多，会抓到那条空头腿
   然后报"position already open"，或在开启仓位调整时**静默把方向改成空头去加仓**。
6. **槽位按笔计** —— `max_open_trades: N` 表示最多 N 条**腿**，不是 N 个币。

## 6. 安装与部署

### 6.1 Docker（推荐）

```bash
docker pull ericchenghz/ck-quant-hedge:latest

docker run -d --name ck-quant-hedge \
  -v "$(pwd)/user_data:/freqtrade/user_data" \
  -p 127.0.0.1:8080:8080 \
  ericchenghz/ck-quant-hedge:latest \
  trade --config /freqtrade/user_data/config.json
```

`docker-compose` 示例见仓库根目录的 `docker-compose.ck-quant.example.yml`：
把 `image:` 换成上面的镜像名，并确认 `config.json` 里 `hedge_mode: true`。

**注意**：容器只监听 `127.0.0.1`；要对外提供访问请自行加反向代理与认证，
不要把 API 端口直接暴露到公网（`api_server` 没有内置的用户体系）。

### 6.2 从源码

```bash
git clone https://github.com/ericchegncn/CK_Quant_Hedge.git
cd CK_Quant_Hedge

python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .

freqtrade create-userdir --userdir user_data
# 把 config.json 放进来，确认 trading_mode/margin_mode/hedge_mode 三项
freqtrade trade --config user_data/config.json
```

### 6.3 上实盘前的自检清单

- [ ] `trading_mode: futures`、`hedge_mode: true`（漏了就是单向，不会报错）
- [ ] `margin_mode` 是你想要的（逐仓=损失封顶 / 全仓=不会单腿爆但账户风险敞口更大）
- [ ] `max_open_trades` ≥ 你要同时持有的**腿数**（币数 × 2）
- [ ] 交易所账户本身已切到 **Hedge Mode**（币安 App/网页端设置）—— 交易所没开、
      程序开了，`positionSide` 会被拒
- [ ] 单腿最大保证金 × 最大腿数 ≪ 钱包余额
- [ ] 先用 `dry_run: true` 跑通：确认同一币种能同时出现多空两条腿、
      平仓单不报错（这是 `reduceOnly` 是否被正确抑制的直接证据）
- [ ] 回测时记得 `position_stacking: true`，否则回测只有一条腿（与实盘不一致）

## 7. 测试

```bash
pytest tests/exchange/test_hedge_mode.py tests/freqtradebot/test_hedge_mode.py \
       tests/rpc/test_hedge_mode.py tests/plugins/test_hedge_mode.py \
       tests/test_wallets.py -q
```

契约测试覆盖：`positionSide` 的注入与关闭时的缺省、`reduceOnly` 的抑制、
按方向的入场门禁与 whitelist 剔除、`/forceenter` 的方向过滤、
按币保护锁的方向收敛、跨保证金强平价计入反向腿，
以及**跑真实主循环 `process()` 的端到端用例**（同币两条腿同时在场、只平其中一条）。

## 8. 已知限制

- **回测器没有 hedge 概念**：入场信号必须写在 `enter_long` / `enter_short` **列**上
  （只实现 `get_entry_signal` 的策略在回测里一笔都不开），且同一根 K 线两列**互斥**。
  想要"双向同时在场"，要么按 K 线轮换方向写列，要么在 `confirm_trade_entry` 里做同向去重。
- **同一币种的多空两条腿不共享保证金计算**（全仓下由交易所账户统一处理，
  但本地风控仍按腿算）。
- **UI 是预编译包**：本仓库不含 WebUI 源码，界面能力与上游一致（API 契约本身是逐笔/逐仓位，
  两条腿自然显示为两行）。

---

## 许可

本分支与上游 freqtrade 一样按 **GPL-3.0** 发布，见 `LICENSE`。
