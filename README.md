# bls — B 站一键开播

一条命令完成：调 B 站接口开播 → 拿到推流地址与密钥 → 拉起 OBS → 自动写入推流码 → 开始推流。

```bash
bls go
```

关播反向一条：

```bash
bls stop
```

## 依赖

- Linux（在 Arch + OBS 33.0.1 上验证）
- OBS Studio 32+（自带 obs-websocket 5）
- Python 3.11+
- `uv`

## 安装

```bash
cd bili-live-obs
uv venv
uv pip install -e .
```

安装后 `uv run bls --help` 可用。想直接敲 `bls`，可以把 `.venv/bin` 加进 `PATH`，
或在 `~/.bashrc` 里加 `alias bls='uv run --project ~/Projects/bili-live-obs bls'`。

## 首次使用（三步）

**1. 手动开一次 OBS，完成首次启动向导**

OBS 第一次启动会弹向导。必须先手动跑一遍并配好场景、来源——本工具只管推流码和推流开关，
不负责配置画面。向导没做完，工具启动 OBS 时会卡在向导窗口上。

**2. 确认 obs-websocket 已启用**

OBS → 「工具」→「WebSocket 服务器设置」，确认「启用 WebSocket 服务器」已勾选，
端口默认 4455。本工具不会改这个设置。

**3. 登录并体检**

```bash
uv run bls login      # 终端里出现二维码，用 B 站 App 扫
uv run bls doctor     # 体检：OBS、websocket、登录、分区
```

登录态存在 `~/.config/bls/credentials.json`（权限 0600），大约 30 天有效，过期后重跑 `bls login`。

## 日常使用

```bash
uv run bls go --area 27    # 第一次指定分区，之后会被记住
uv run bls go              # 以后就这一条
uv run bls status          # 看登录、B 站开播状态、OBS 是否在推流
uv run bls stop            # 停推 + 关播
```

`go` 成功后打印直播间地址。

## 命令说明

| 命令 | 作用 |
| --- | --- |
| `bls login` | 扫码登录，保存登录态 |
| `bls go` | 开播并自动配置 OBS 推流 |
| `bls go --area <id>` | 指定分区，并记住 |
| `bls go --dry-run` | 只打印将要做的事，不开播 |
| `bls go --force` | B 站已开播但没有本机记录时，跳过确认直接重开 |
| `bls stop` | 停 OBS 推流 + 关播 + 清除本机推流码 |
| `bls stop --bili-only` | 只关 B 站端（OBS 起不来时收尾用） |
| `bls stop --obs-only` | 只停 OBS 推流 |
| `bls status` | 登录态、B 站开播状态、OBS 推流状态 |
| `bls doctor` | 环境体检 |
| `bls doctor --areas` | 打印直播分区表 |

## 配置

`~/.config/bls/config.toml`：

```toml
obs_binary = "obs"      # OBS 可执行文件，可用绝对路径
obs_port = 4455         # obs-websocket 端口
obs_profile = ""        # 空 = 沿用 OBS 上次使用的 profile
obs_collection = ""     # 空 = 沿用 OBS 上次使用的场景集
area_id = 0             # 直播分区，0 表示未设置
launch_obs = true       # false = OBS 未运行时报错，不自动拉起
```

如果你有多个 OBS profile，且希望工具总是写进某一个，就设 `obs_profile`。
`bls doctor` 发现多个 profile 时会提示。

## 它做了什么

`bls go` 的顺序：

1. 检查登录态，失效就扫码
2. 用 uid 换直播间号
3. 如果 B 站已经在播、且本机存着上次的推流码 → 直接复用，不重复开播
4. 否则调开播接口拿推流地址与密钥
5. OBS 没开就拉起来（`--minimize-to-tray`）
6. 通过 obs-websocket 写入自定义推流服务（`rtmp_custom`）
7. 开始推流
8. 轮询 OBS 已发出字节数，连续两次增长才算成功

## 出问题怎么办

先跑 `uv run bls doctor`。常见情况：

| 现象 | 原因与处理 |
| --- | --- |
| `开播失败：目标分区需要人脸认证（code 60024）` | 该分区要求人脸认证。命令会原地给出认证二维码（B 站若下发链接）并等你回车重试；也可以 `bls go --area <别的分区>` |
| `本次开播需要人脸认证（code 60043）` | B 站对这次开播要求活体认证。命令会画出官方人脸认证页的二维码（`blackboard/live/face-auth-middle.html`），用手机 B 站 App 扫完、按提示做人脸，回车就自动重试开播 |
| `web 在线开播已下线（code 60037）` | 接口策略变了。这是已知风险，见下 |
| `登录已失效` | 重跑 `bls login` |
| `OBS 没起来` | 先手动开一次 OBS 完成向导；检查 websocket 是否启用 |
| `数据没有发出去` | 推流地址失效、网络不通或码率过高。此时 B 站端仍开着播，用 `bls stop` 收尾 |
| 二维码扫不出来 | 终端对二维码支持不好，用 `bls login` 打印的 PNG 文件路径，拿手机扫那个文件 |

## 已知限制

- **走的是 B 站非公开接口**。开播接口不是公开 API，B 站改协议或收紧风控时可能失效。
  所有接口调用集中在 `src/bls/bilibili.py`，出问题时改这一个文件即可。
- **不配置画面**。场景、来源、编码器、码率都要你自己在 OBS 里配好。
- **分区 id 会变**。新增或下线分区后，配置里记的 id 可能失效，`doctor` 会查出来。
- **推流码状态文件**存在 `~/.config/bls/live_state.json`，`bls stop` 成功后会删除。
  如果手动关掉了直播而没跑 `stop`，下次 `go` 会提示「B 站已开播但没有本机记录」。

## 开发

```bash
uv run pytest -q
```

## 免责

个人自用工具，登录凭据与推流密钥都只存在本机。请遵守 B 站直播相关协议。
