# 双向持仓（Hedge Mode）完整指南

> 同一币种**同时持有多头与空头两条腿**。这是本分支相对上游 freqtrade 的**唯一能力差异**，
> 也是它存在的理由 —— 上游明确不支持，且短期内不打算支持。
>
> 本文覆盖：**安装 → 配置 → 回测 → 模拟盘 → 实盘**，以及所有已知的坑。

---

## 0. 五分钟验证「双向持仓到底成不成立」

不需要 API key，不需要实盘，只需要历史数据。

```bash
# 1) 拿到本分支（或用 Docker，见第 4 节）
git clone https://github.com/ericchegncn/CK_Quant_Hedge.git
cd CK_Quant_Hedge
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .

# 2) 下一点历史数据（4 个币、15m）
freqtrade download-data --config docs/examples/hedge-dryrun.example.json \
  --timeframes 15m --days 90

# 3) 跑示例策略（它存在的唯一目的就是演示双向持仓，不是交易策略）
freqtrade backtesting --config docs/examples/hedge-dryrun.example.json \
  --strategy HedgeModeDemo --strategy-path user_data/strategy \
  --timerange 20260601-20260801 --export trades
```

看到**多空两行**的出场统计就说明能力生效了。要确认"同币两条腿真的同时在场"，
用第 6.2 节的逐笔检查。

- 示例策略：`user_data/strategy/hedge_mode_demo.py`（RSI 双判据，无盈利意图）
- 示例配置：`docs/examples/hedge-dryrun.example.json`（带中文注释）

> 示例配置里的 `stake_amount` 特意给了 150 —— **BTC 期货的最小名义价值约 100 USDT**，
> 给少了（例如 20）这个币会被**静默跳过**（日志无报错、只是一笔都不开），
> 很容易让人误以为策略坏了。需要的 stake ≈ 最小名义 ÷ 杠杆。

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

---

## 4. 安装

### 4.1 Docker（推荐）

```bash
docker pull ericchenghz/ck-quant-hedge:latest

docker run -d --name ck-quant-hedge \
  -v "$(pwd)/user_data:/freqtrade/user_data" \
  -p 127.0.0.1:8080:8080 \
  ericchenghz/ck-quant-hedge:latest \
  trade --config /freqtrade/user_data/config.json
```

镜像里 `freqtrade` 命令已就绪；把配置与策略放进挂载的 `user_data/` 即可。
**镜像标签**：`latest` / `stable` / `hedge-2026.8.1`（同一个镜像的多个别名）。

**注意**：容器只监听 `127.0.0.1`；要对外提供访问请自行加反向代理与认证，
不要把 API 端口直接暴露到公网（`api_server` 没有内置的用户体系）。

### 4.2 docker-compose

仓库根目录已经配好，**直接用**（镜像名与容器内路径都已指向本分支）：

```bash
cp .env.example .env        # 首次；.env 已被 .gitignore 挡住
docker compose up -d
```

`.env` 里的变量名是 `CK_HEDGE_*`（主项目的 `CK_QUANT_*` 本仓库**不读**，
所以从主项目复制来的 `.env` 不会静默把镜像指回 `ck-quant`）。
默认会挂载 `./user_data` 到容器内的 `/freqtrade/user_data`，并把 WebUI 绑在 `127.0.0.1:8080`。

**两个最容易踩的点**：
1. 配置里必须有 `"strategy"` 字段，否则报 `No strategy specified`；
2. 配置里三个开关要齐：`trading_mode="futures"`、`margin_mode`、`hedge_mode=true`。
   可直接拿 `docs/examples/hedge-dryrun.example.json` 当模板。

> 换配置文件：在 `.env` 里改 `CK_HEDGE_CONFIG=<配置文件名>` 即可（相对 `./user_data`）。
> 默认值是 `config.json` —— **故意不指向任何具体策略的配置**，别人照抄不会报"文件找不到"。

**策略由配置文件里的 `"strategy"` 字段决定**，compose 里**不写死策略名**：
写死一个名字，别人没有那个类就会直接报 `Impossible to load Strategy`。
需要临时覆盖时，在命令行上加 `--strategy <类名>`（命令行优先于配置）。

**回测前还要做一件事**：把历史数据目录挂进来 —— 在 `.env` 里设
`CK_HEDGE_DATA_DIR=<你已有的数据目录>`。原因是 fork 自带的 `user_data/data/` 是空的，
不挂就会报 `No history for ... found`。

> ⚠️ `CK_HEDGE_DATA_DIR` **留空会直接报挂载错误**：compose 的 `${VAR:-默认}`
> 把空值当成"已设置"，于是挂载源变成空串。要么整行删掉（用默认值），
> 要么写一个真实存在的目录。

### 4.3 从源码

```bash
git clone https://github.com/ericchegncn/CK_Quant_Hedge.git
cd CK_Quant_Hedge

python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .

freqtrade create-userdir --userdir user_data
# 把 config.json 放进来，确认 trading_mode/margin_mode/hedge_mode 三项
freqtrade trade --config user_data/config.json
```

### 4.4 Android APK

每次 Release 都附带 APK（`CK-Quant-Hedge-Android-*.apk` + SHA-256），见
[Releases](https://github.com/ericchegncn/CK_Quant_Hedge/releases)。
它是 WebUI 的手机客户端，连的是**你自己的服务器**，与双向持仓开关无关
（服务器开了就有两条腿，客户端会显示成两行）。

---

## 5. 配置：怎么开双向持仓

### 5.1 三个必需开关

```json
{
    "trading_mode": "futures",
    "margin_mode": "cross",
    "hedge_mode": true,
    "max_open_trades": 20
}
```

| 参数 | 取值 | 说明 |
|---|---|---|
| `trading_mode` | `futures` | 双向持仓是**合约**能力。现货没有 `positionSide` 概念，开启无效。 |
| `margin_mode` | `isolated` / `cross` | **最容易踩错的一个**，见 5.4。 |
| `hedge_mode` | `true` | 总开关。默认 `false`（关闭时与上游逐字节一致）。 |
| `max_open_trades` | 按**腿数**算 | 一个币最多 2 条腿（多 + 空）。20 个币想全部在场就得给 40。给少了不会报错，只是排不进去。 |
| `position_stacking` | 回测时需要 | **仅回测**，见 5.3。 |

> 配置文件支持 `//` 注释 —— freqtrade 用 rapidjson 解析且已开 `PM_COMMENTS`，
> 所以可以直接在配置里写中文说明。完整示例见
> `docs/examples/hedge-dryrun.example.json`。

### 5.2 `max_open_trades` 按「腿数」算，不是按币数

这是新手最容易困惑的一点：`max_open_trades: 20` 在双向模式下意味着
"最多 20 条**腿**"，也就是最多 10 个币的多空两条腿同时在手。

### 5.3 `position_stacking`（只在回测里需要）

回测器默认"一个币只允许一笔在场"，不开这个就永远只有一条腿（与实盘不一致）。
**实盘不需要它** —— 方向门禁本身已经允许反向腿共存。

### 5.4 逐仓 vs 全仓：双向持仓最关键的一次选择

| | 逐仓 `isolated` | 全仓 `cross` |
|---|---|---|
| 强平层级 | **单腿**：每条腿只用自己的保证金兜底 | **账户级**：整个钱包兜底 |
| 强平距离 | 约 `1/杠杆`（价格口径） | 直到账户权益耗尽 |
| 表现 | 走反的腿会被**强平清场**，损失被单腿保证金封顶 | 走反的腿**不爆也不停**，长期占用保证金与槽位（"僵尸腿"，需要靠策略侧的结构控制） |
| 风险 | 单腿爆仓（可预期、可封顶） | 账户级回撤（不可封顶，必须靠仓位上限约束） |

**选择原则**：想"损失封顶、可预期"用逐仓；想"单腿不被强平、能等回来"用全仓 ——
但用全仓必须自己把每条腿的最大占用框住
（`max_open_trades` × 单腿最大保证金必须远小于钱包）。

### 5.5 杠杆

本分支不改变杠杆逻辑：`leverage()` 返回多少就用多少（受交易所上限约束）。
注意一个**只在合约下成立的换算**：

```
保证金波动 = 价格距离 × 杠杆
```

即 2% 的价格波动在 25x 下是 50% 的保证金波动。**凡是以"价格百分比"设定的阈值
（止损、网格间距、止盈），都要乘一遍杠杆再来判断它是不是合理。**

---

## 6. 回测

### 6.1 用示例策略跑通（验证能力）

见第 0 节。三个要点：`--strategy-path user_data/strategy`（示例策略不在默认目录）、
`--export trades`（为了逐笔核对）、`--timerange`。

### 6.2 怎么确认「同币两条腿同时在场」

只看汇总表**不够** —— 它只说明多空都交易过，不能证明**同时**。直接读导出的逐笔最可信：

> 注意：本版本的 `--export-filename` 已废弃（会被忽略），回测结果会以
> `user_data/backtest_results/backtest-result-<时间戳>.zip` 落盘。下面这段读的就是它。

```python
import glob, json, os, zipfile
from collections import defaultdict

newest = sorted(glob.glob("user_data/backtest_results/backtest-result-*.zip"),
                key=os.path.getmtime)[-1]
with zipfile.ZipFile(newest) as z:
    # zip 里最大的那个 .json 就是逐笔结果
    inner = max((n for n in z.namelist() if n.endswith(".json")),
                key=lambda n: z.getinfo(n).file_size)
    data = json.loads(z.read(inner))

strategy = next(iter(data["strategy"]))
by_pair = defaultdict(list)
for t in data["strategy"][strategy]["trades"]:
    by_pair[t["pair"]].append(t)

total = 0
for pair, trades in sorted(by_pair.items()):
    longs  = [t for t in trades if not t["is_short"]]
    shorts = [t for t in trades if t["is_short"]]
    overlap = sum(
        1 for a in longs for b in shorts
        if a["open_date"] < b["close_date"] and b["open_date"] < a["close_date"]
    )
    total += overlap
    print(f"{pair:16s} 多头 {len(longs):3d} 笔 | 空头 {len(shorts):3d} 笔 | 同时在场组合 {overlap}")

print("\n双向持仓成立 ✓" if total else "\n未发现重叠 ✗")
```

`同时在场组合 > 0` 就是"同币多空腿同时在场的直接证据"。
（也可以用 `freqtrade backtesting-analysis` 看逐笔。）

> 示例策略的出场阈值是**刻意不对称**的（多头等到 RSI>70、空头等到 RSI<30）。
> 如果对称，多头会在空头进场前先平掉，两条腿永远不重叠 ——
> 那样这个示例就演示不出双向持仓，是个容易踩的坑。

### 6.3 自己写策略时的两个硬约束

1. **入场信号必须写在列上**（`enter_long` / `enter_short`）。
   只实现 `get_entry_signal()` 的策略在**回测**里一笔都不会开 ——
   那个钩子只有实盘主循环会调用。
2. **同一根 K 线的 `enter_long` 与 `enter_short` 互斥**（回测器行为）。
   想要"双向同时在场"，要么让两条腿在不同 K 线开出来，
   要么在 `confirm_trade_entry` 里做同向去重、反向放行。

### 6.4 数据准备（`--datadir` 的坑）

```bash
freqtrade download-data --config <config> --timeframes 15m --days 365
```

- 回测时 `--datadir` **只能从命令行给**：配置里写的 `datadir` 会被
  `create_datadir()` 直接覆盖。
- 路径必须指到**带交易所子目录**的那一层，例如 `user_data/data/binance`
  （少一层就会报 `No history for ... found`）。
- **币安期货 ticker 没有买卖价** ⇒ 定价必须 `use_order_book: true`，
  否则报 `Ticker pricing not available`。

---

### 6.5 在容器里跑回测（而不是本机 venv）

`docker compose run` 的**第一个参数是服务名**（本仓库的服务名就是 `freqtrade`），
不是命令名 —— 写成别的名字会报 `no such service`。

```bash
docker compose run --rm freqtrade backtesting \
  --userdir ./user_data \
  --config ./user_data/config_Hedge_Grid.json \
  --strategy <策略类名> \
  --timerange 20260101-20260812 --timeframe-detail 1m --fee 0.001 --breakdown month
```

三条硬规则：

1. `--config` / `--userdir` / `--datadir` 是**容器内路径**。
   相对路径（`./user_data/...`）也可以用 —— 容器的工作目录是 `/freqtrade`，
   所以 `./user_data` 就等于 `/freqtrade/user_data`。
   但**宿主机路径**（`D:\...`、`/CK_Quant_Hedge/...`）在容器里不存在，别写进去。
2. **历史数据要挂进去**：fork 自带的 `user_data/data/` 一般是空的，
   回测会报 `No history for ... found`。compose 里已经留好一个数据挂载点，
   只要在 `.env` 里设一下 `CK_HEDGE_DATA_DIR=<你已有的数据目录>` 即可
   （默认值 `./user_data/data/binance` 等于没额外挂）。
3. 加 `--rm`，否则每次回测都留下一个已退出的容器。

---

## 7. 模拟盘（dry-run）验证

`dry_run: true` 时**不会向交易所发任何订单**，但主循环、钱包、方向门禁全部真实运行，
是上线前最有价值的一步。跑起来后重点看四件事：

1. 同一个币种能**同时**看到多头与空头两条腿（WebUI 里显示成两行）
2. 平仓不报错 —— 这是 `reduceOnly` 被正确抑制的直接证据
3. **没有** `positionSide` 相关的拒单
4. 槽位按腿消耗（`/status` 的条数受 `max_open_trades` 限制）

```bash
freqtrade trade --config user_data/config_hedge_dryrun.json --strategy <你的策略>
```

`config_hedge_dryrun.json` 是配套的模拟盘配置样例（40 币、stake 1、全仓、带中文注释）；
把 `docs/examples/hedge-dryrun.example.json` 复制过去改两处也能用。

---

## 8. 实盘上线清单

- [ ] `trading_mode: futures`、`hedge_mode: true`（漏了就是单向，**不会报错**）
- [ ] `margin_mode` 是你想要的（逐仓=损失封顶 / 全仓=不会单腿爆但账户风险敞口更大）
- [ ] `max_open_trades` ≥ 你要同时持有的**腿数**（币数 × 2）
- [ ] **交易所账户本身已切到 Hedge Mode**（币安 App/网页端 → 合约设置）——
      交易所没开、程序开了，`positionSide` 会被拒
- [ ] 单腿最大保证金 × 最大腿数 ≪ 钱包余额
- [ ] 先在 `dry_run: true` 下跑够时间，确认第 7 节的四件事
- [ ] 回测 / 模拟盘 / 实盘三者用**同一份**策略文件（本分支的策略文件可做到单文件自足）

---

## 9. 六个坑（都已在代码里处理，但你得知道它们存在）

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

---

## 10. 常见问题排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 回测里只有一条腿 | `position_stacking` 没开，或策略同 K 线双信号被互斥掉 | 配置开 `position_stacking: true`；两条腿分不同 K 线开 |
| 回测一笔都不开 | 策略只写了 `get_entry_signal()` | 把信号写到 `enter_long`/`enter_short` **列**上 |
| `Ticker pricing not available` | 合约用了 ticker 定价 | `entry_pricing` / `exit_pricing` 都设 `use_order_book: true` |
| `No history for ... found` | `--datadir` 层级不对 | 指到 `user_data/data/<交易所>` 那一层 |
| 下单全部失败、报 positionSide | 交易所账户没切 Hedge Mode | 去币安切到双向持仓；或把 `hedge_mode` 设回 `false` |
| 平仓报 reduceOnly 相关错误 | hedge 开着却发了 reduceOnly | 升级到本分支（已抑制）；确认 `hedge_mode: true` 生效 |
| 一个币只进得去一条腿 | `max_open_trades` 按币数给了 | 按**腿数**给（币数 × 2） |
| **某个币一笔都不开**（别的币正常） | 下单量低于该币的**最小名义价值**（BTC 期货约 100 USDT）；freqtrade 会**静默跳过**，日志里没有明显报错 | 提高 `stake_amount`（≈ 最小名义 ÷ 杠杆），或给策略实现 `leverage()` 上杠杆 |
| 走反的腿长期不回来 | 全仓下的"僵尸腿" | 这是设计取舍，靠策略侧限制单腿最大占用（少档 / 小仓位） |
| `no such service: <名字>` | `docker compose run` 的第一个参数是**服务名**，不是命令名 | 本仓库服务名是 `freqtrade`（`docker compose config --services` 可查） |
| `Config file ".../xxx.json" not found` | `.env` 里的 `CK_HEDGE_CONFIG` 指向的文件不存在（`.env` 优先于 compose 默认值） | 对上真实文件名；或删掉该行用默认 `config.json` |
| `Impossible to load Strategy X` | 配置里的 `strategy` 与真实类名不一致，或命令行 `--strategy` 写了别的名字 | 用 `list-strategies` 看真实类名，改配置或改命令行（**别只改一处**） |
| `No strategy specified` | 配置里没有 `strategy` 字段（compose 不再兜底策略名） | 在配置里加 `"strategy": "<类名>"` |
| `No history for ... found` | 没把历史数据挂进容器（fork 的 `user_data/data/` 是空的） | 在 `.env` 里设 `CK_HEDGE_DATA_DIR=<你的数据目录>` |
| 挂载报错 / `invalid mount config` | `.env` 里的 `CK_HEDGE_DATA_DIR` **留空** | 整行删掉（用默认值）或写真实目录 —— 空值会被当作"已设置" |

---

## 11. 测试

```bash
pytest tests/exchange/test_hedge_mode.py tests/freqtradebot/test_hedge_mode.py \
       tests/rpc/test_hedge_mode.py tests/plugins/test_hedge_mode.py \
       tests/test_wallets.py -q
```

契约测试覆盖：`positionSide` 的注入与关闭时的缺省、`reduceOnly` 的抑制、
按方向的入场门禁与 whitelist 剔除、`/forceenter` 的方向过滤、
按币保护锁的方向收敛、跨保证金强平价计入反向腿，
以及**跑真实主循环 `process()` 的端到端用例**（同币两条腿同时在场、只平其中一条）。

## 12. 已知限制

- **回测器没有 hedge 概念**：见 6.3 的两个硬约束。
- **同一币种的多空两条腿不共享本地保证金计算**（全仓下由交易所账户统一处理，
  但本地风控仍按腿算）。
- **UI 是预编译包**：本仓库不含 WebUI 源码，界面能力与上游一致
  （API 契约本身是逐笔/逐仓位，两条腿自然显示为两行）。

---

## 许可

本分支与上游 freqtrade 一样按 **GPL-3.0** 发布，见 `LICENSE`。
