# CK Quant Hedge `hedge-2026.8.2`

## 修复：交易所限流（429）导致机器人无限重启

**症状**：容器每 1~3 分钟重启一次（`RestartCount` 持续增长），日志出现
`freqtrade - ERROR - Fatal exception!`，进程以退出码 1 结束，`restart: unless-stopped`
随即把它重新拉起 —— 表现为"模拟盘自己在反复重启"。

**根因**（框架代码缺陷，与策略无关）：

1. 币安按出口 IP 限制 2400 请求/分钟。同一出口 IP 上运行多个机器人、或单盘持仓腿数较多时，
   止损检查与资金费率刷新会把额度打满，交易所返回 `429 Too Many Requests`。
2. ccxt 抛出 `DDoSProtection`，本应由 `fetch_funding_rates` 的兜底捕获后降级为空资金费率继续运行；
   但兜底内部使用了 `self.logger` —— 交易所类没有该属性（该文件只有模块级
   `logger = logging.getLogger(__name__)`），于是兜底自身抛出
   `AttributeError: 'Binance' object has no attribute 'logger'`。
   旁证：日志中 `fetch_funding_rates throttled by exchange` 一次都未出现，说明该兜底从未成功执行过。
3. 异常冒泡到主循环（`worker._worker`）被当作致命错误，进程退出；容器重启后立刻重新拉取全部持仓的
   资金费率/止损，再次撞上限流 → 形成"崩溃—重启—再崩溃"的死循环。
   在双向持仓模式下，单盘持仓腿数可达币种数的两倍，因此这条路径更容易被触发。

**修复**：`freqtrade/exchange/binance.py` 中两处兜底日志改用模块级 `logger`。
429（`DDoSProtection`）与 403（`OperationFailed`/`ExchangeError`）恢复为
"打印告警 + 资金费率降级为空值 + 主循环继续"，不再中断进程。

**验证**（本地 hedge 模拟盘连续观测）：

- 修复后连续运行 4 小时以上，`RestartCount = 0`、`Fatal exception` 计数 0；
- 容器内实测 `grep -c self.logger /freqtrade/freqtrade/exchange/binance.py` = 0；
- `docker events` 中不再出现自发的 `die`。

**运维建议**：双向持仓下一个币种可能占两条腿，API 压力约为单边模式的 2 倍。
建议把 `internals.process_throttle_secs` 保持在 30 秒（默认 5 秒偏激进）。

## Docker 镜像

- 发布为 `ericchenghz/ck-quant-hedge:hedge-2026.8.2`、`:stable`、`:latest`。

## Android APK

- `CK-Quant-Hedge-Android-0.1.15-debug.apk`（versionCode 16）。

## 隐私保护

- 发布源码、APK 和全部 Docker 镜像均不包含私有策略、实盘配置、API 密钥、Telegram Token、
  服务器 IP、数据库、回测结果或模型数据。
