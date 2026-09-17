# CK Quant

**隐私优先、支持网页与 Android 远程管理的 Freqtrade 二次发行版**

**[English](README.md) | [中文](README.zh-CN.md)**

[![GitHub Release](https://img.shields.io/github/v/release/ericchegncn/CK_Quant?display_name=tag)](https://github.com/ericchegncn/CK_Quant/releases/latest)
[![Docker Hub](https://img.shields.io/docker/v/ericchenghz/ck-quant?label=Docker%20Hub&sort=semver)](https://hub.docker.com/r/ericchenghz/ck-quant/tags)
[![Android APK](https://img.shields.io/badge/Android-APK-3DDC84?logo=android&logoColor=white)](https://github.com/ericchegncn/CK_Quant/releases/latest)

---

> ## 🔀 本仓库是 **CK Quant Hedge** 分支 —— 支持**双向持仓（Hedge Mode）**
>
> 同一个币种可以**同时持有多头与空头两条腿**。这是上游 freqtrade 明确不提供的能力。
>
> - Docker 镜像：**`ericchenghz/ck-quant-hedge`**
> - 安装部署、配置方法与**每一个双向持仓参数的说明**：**[docs/hedge-mode.md](docs/hedge-mode.md)**
> - 本仓库**只含框架能力** —— 不含任何私人策略、实盘配置与凭据，
>   由 `.github/workflows/privacy-guard.yml` 在每次推送时自动校验。
> - `hedge_mode` **默认关闭**：关闭时单向代码路径与上游逐字节一致。

---

## 特性

| 功能 | 说明 |
|---|---|
| **崩溃安全订单恢复** | 应对快速反手交易时的交易所订单恢复，防止无限重启循环 |
| **合成冰山单** | 可选：把大订单拆成多个隐藏小子单（入场/出场） |
| **卡片式响应式 UI** | 半透明、移动端友好的 WebUI，支持 7 种语言（简中/繁中/英/德/日/法/韩） |
| **经鉴权的管理后台** | 在线编辑/校验配置与策略、自动备份、安全重载/重启 |
| **Android App** | 手机连接量化服务器、管理机器人、操作订单 |
| **CK Quant 桌面版** | 面向小白用户的 Windows 工作台：终身机器码授权、凭据加密、AI 助手、串行回测、G1-G10 确定性门禁、巡检和经确认的模拟盘部署 |
| **Tick 级回测引擎** | 内存友好的引擎，用真实逐笔成交撮合出场（而非猜测 OHLCV 路径） |
| **真实钱包回撤** | 权益回撤 = 已平仓收益 + 未平仓浮盈（市值计价） |
| **涨跌幅排名交易对** | 按涨跌幅选涨幅榜 + 跌幅榜，可与成交额/静态列表混合 |
| **实时盈利因子** | 计入未平仓浮盈 —— 机器人运行期间统计不滞后 |

---

## CK Quant 桌面版

Windows 桌面版位于 [`desktop/`](desktop/)。商业模式为一次支付 **10,000 USDT、绑定机器码的终身授权**，不再采用订阅制。客户软件只包含验签公钥；注册码由单独且被 Git 忽略的厂商工具使用私钥签发。

“一键自主运行”仅以 Freqtrade 官方公开 `SampleStrategy` 的 15m 适配版为研究起点，不会把用户私人策略作为模板。导入的私人策略、自动生成的变体、API 凭据、回测结果和审计数据都只保存在本机应用数据目录，不进入 GitHub、Docker 镜像或安装包。

回测通过本机 CK Quant Docker 容器严格串行执行；缺少证据的门禁会显示“尚未评估”，不会伪装成通过。部署模拟盘前需要用户明确确认，实盘资金启用仍保留独立的人工确认步骤。

安装、激活和开发说明见 [`desktop/README.md`](desktop/README.md)。

---

## 安装（Docker）

**前置要求**：安装 Docker（含 Compose v2）。无需本地 Python 环境。

```bash
mkdir CK_Quant
cd CK_Quant

# 下载 compose 文件
curl -L https://raw.githubusercontent.com/ericchegncn/CK_Quant/main/docker-compose.yml \
  -o docker-compose.yml

# 拉取镜像并创建用户目录
docker compose pull
docker compose run --rm CK_Quant create-userdir --userdir user_data
> The compose service runs with `working_dir: /CK_Quant`, so relative
> paths like `user_data` land inside the mounted volume.
> (Absolute path also works: `--userdir /CK_Quant/user_data`)


# 生成初始配置
docker compose run --rm CK_Quant new-config --config user_data/config.json
```

**镜像选择**：

| 镜像 | 用途 |
|---|---|
| `ericchenghz/ck-quant:stable` | 普通交易（推荐） |
| `ericchenghz/ck-quant:stable-freqai` | FreqAI 模型（LightGBM/XGBoost/RF） |
| `ericchenghz/ck-quant:stable-freqai-rl` | FreqAI + PyTorch 强化学习 |

在 `.env` 中设置 `CK_QUANT_IMAGE` 切换镜像。

### 首次配置

执行 `new-config` 后，编辑 `user_data/config.json` 设置关键项：

```jsonc
{
    "exchange": {
        "name": "binance",
        "key": "YOUR_API_KEY",       // 从交易所获取（合约需开通）
        "secret": "YOUR_API_SECRET", // 注意保密 —— 绝不进入镜像
        "pair_whitelist": ["BTC/USDT:USDT", "ETH/USDT:USDT"]
    },
    "stake_amount": 100,             // 每笔固定金额
    "max_open_trades": 5,
    "dry_run": true                  // 先以模拟盘运行！
}
```

> **务必先以 `dry_run: true` 模拟盘运行**，充分理解机制与预期盈亏后再切换
> `false` 实盘。合约交易请创建**已勾选"开通合约"**的 API 密钥。

### 放入策略并启动

```bash
# 1. 把你的私有策略复制到 user_data/strategies/
# 2. 复制 .env.example 为 .env，设置 CK_QUANT_STRATEGY 为你的策略类名
cp .env.example .env
#    CK_QUANT_STRATEGY=YourStrategyName

# 3. 启动
docker compose up -d
docker compose logs -f --tail 200
```

WebUI 默认监听 <http://127.0.0.1:8080>（可通过 `CK_QUANT_WEBUI_BIND` / `CK_QUANT_WEBUI_PORT` 修改）。

配置、策略、数据库、凭据、模型和日志全部保存在本地 `user_data` 目录 —— **敏感数据绝不进入镜像**。

> **安全提示**：不要把管理/API 端口暴露到公网。远程使用请配置 HTTPS
> 反向代理或可信 VPN，并使用高强度独立密码和 JWT 密钥。建议先连接
> `dry_run` 实例完成验证。

---

## 功能使用指南

### 1. 多语言 WebUI 与 Android App

WebUI 提供 7 种语言和经鉴权的管理后台：

- 修改常用或完整配置参数，保存前服务端校验
- 在线修改策略参数或策略文件
- 自动创建配置/策略备份，保存后安全重载或重启机器人
- 查看运行状态，通过 Freqtrade API 管理订单和持仓
- 查看管理员操作审计记录

管理员功能**默认关闭**，需在 `config.json` 中显式启用：

```json
"ck_quant_admin": {
  "enabled": true,
  "config_edit": true,
  "strategy_edit": true
}
```

**Android APK**：从
[GitHub Releases](https://github.com/ericchegncn/CK_Quant/releases/latest)
下载。安装后输入服务器地址以及 `api_server` 用户名和密码即可连接。
完整配置、反向代理和安全说明见
[docs/ck_quant_mobile_admin.md](docs/ck_quant_mobile_admin.md)。

### 2. 涨跌幅排名交易对（GainersLosersPairList）

按涨跌幅动态选择涨幅榜 + 跌幅榜，支持**两种模式**：

- `filter`（默认）：原生 freqtrade 过滤链 —— 只在上家输出的候选里排名
- `union`：从全市场独立选择，并与上家结果**合并**（成交额 + 涨跌幅 + 静态可共存）

```jsonc
"pairlists": [
    {
        "method": "VolumePairList",
        "number_assets": 20,
        "sort_key": "quoteVolume",
        "refresh_period": 300
    },
    {
        "method": "GainersLosersPairList",
        "gainers_count": 10,      // 涨幅榜前 10
        "losers_count": 5,        // 跌幅榜前 5
        "direction": "both",      // both / gainers / losers
        "mode": "union",          // union（混合并集）或 filter
        "refresh_period": 300
    }
]
```

验证方式：

```bash
docker compose run --rm CK_Quant test-pairlist \
    --userdir user_data --config user_data/config.json
```

完整教程：[docs/gainers-losers-pairlist.md](docs/gainers-losers-pairlist.md)。

### 3. Tick 级回测引擎

用真实逐笔成交（tick）撮合出场，解决 OHLCV 回测的精度问题：

```text
同一根 15m bar 内，止损和止盈都被触及 —— 谁先谁后？
  OHLCV 回测：只能猜（假设路径）→ 系统性偏向乐观 ❌
  Tick 回测：真实 tick 序列逐笔判断 → 精确 ✅
```

**实测**（ETH 2025-07，0.5% 止损）：7.1% 的交易触发顺序判断错误，
且 OHLCV 总盈亏方向与真实 tick 相反。止损越紧误差越大。

```bash
# 下载 tick 数据（binance.vision，按周分块）
python scripts/download_vision_chunked.py ETHUSDT 20250701 20250731 \
    user_data/data/binance/futures/trades_eth

# 运行 tick 回测
python -m freqtrade.ck_quant.tick_backtest \
    --config user_data/config.json --strategy MyPrivateStrategy \
    --data-dir user_data/data/binance/futures/trades_eth \
    --timerange 20250701-20250731 --pair "ETH/USDT:USDT" \
    --stoploss 0.005 --takeprofit 0.005
```

详见 [docs/advanced-tick-backtest.md](docs/advanced-tick-backtest.md)。

### 4. 合成冰山单

把一笔大订单拆成多个小子单，交易所同一时刻只看到一个，前一片成交后再补：

```json
{
    "iceberg_orders": {
        "enabled": true,
        "entry": true,
        "exit": true,
        "visible_ratio": 0.1,
        "max_slices": 10,
        "replenish_interval": 5.0,
        "size_jitter": 0.0
    }
}
```

详见 [docs/advanced-iceberg.md](docs/advanced-iceberg.md)。

### 5. 一键发布

```bash
python scripts/release.py 2026.8          # 构建镜像 → 推送 Docker Hub → 打 tag → 创建 Release
python scripts/release.py 2026.8 --dry-run  # 预览
```

---

## 回测

```bash
docker compose run --rm CK_Quant backtesting \
    --userdir user_data \
    --config user_data/config.json \
    --strategy YourStrategy \
    --timeframe 15m --timeframe-detail 1m \
    --timerange 20260101-20260801 \
    --fee 0.001
```

> 务必使用 `--timeframe-detail 1m` 获得可信结果 —— 纯 15m 回测系统性乐观
> （大样本实测收益高估约 12 倍）。

---

## Freqtrade 上游

[![Freqtrade CI](https://github.com/freqtrade/freqtrade/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/freqtrade/freqtrade/actions/workflows/ci.yml)
[![DOI](https://joss.theoj.org/papers/10.21105/joss.04864/status.svg)](https://doi.org/10.21105/joss.04864)
[![codecov](https://codecov.io/gh/freqtrade/freqtrade/branch/develop/graph/badge.svg?token=AD5BG3ATKI)](https://codecov.io/gh/freqtrade/freqtrade)
[![Documentation](https://readthedocs.org/projects/freqtrade/badge/)](https://www.freqtrade.io)
[![Discord Server](https://img.shields.io/badge/Freqtrade_Discord-4E4E4E?logo=discord)](https://discord.gg/p7nuUNVfP7)

本项目源自 Freqtrade，保持 GPL-3.0 许可。架构说明见
[CK_QUANT.md](CK_QUANT.md)。

## 免责声明

本软件仅供学习研究使用。请勿投入你输不起的资金。**使用本软件风险自负**，
作者及其关联方对你的交易结果不承担任何责任。

请务必先在 Dry-Run（模拟盘）运行，充分理解其机制与预期盈亏后再投入实盘。

---

## 许可证

GPL-3.0 — 见 [LICENSE](LICENSE)。
