# 外部服务依赖（硬依赖）

> 本文件声明 StarWhisper **运行所必需的、但不在本仓库内**的外部服务。
> 一句话：**StarWhisper 无法独立运行** —— 识图主链路必须有一个自建的 astrometry 求解服务在线。

最后更新：2026-10-06

---

## 1. 依赖总览

```
StarWhisper (:8000)                     ← 本仓库
    │  HTTP POST /solve（multipart/form-data）
    ▼
astrometry-api-server (:8010)           ← 依赖 ① 自建，Go
    │  go.mod replace → ../astrometry-go-client
    ▼
astrometry-go-client                    ← 依赖 ② 自建，Go（fork 自上游 DiarmuidKelly/astrometry-go-client）
    │  exec solve-field（PATH 前置 /opt/astrometry/0.98/bin）
    ▼
astrometry.net 0.98-21-gf33d1e76         ← 依赖 ③ 第三方运行时（C++，/opt/astrometry/0.98/）
    │  读 astrometry.cfg → add_path /root/.astrom/4100
    ▼
4100 系列索引 × 12（339M）                ← 依赖 ④ 数据（astrometry.net 官方下载）
```

依赖 ①② 是**自建仓库**，依赖 ③④ 是**第三方运行时与数据**。四者缺一，识图即不可用。

---

## 2. 依赖明细

### ① astrometry-api-server（必需）

| 项 | 值 |
|---|---|
| 作用 | 提供 `/solve`、`/analyse`、`/health`、`/version` HTTP 接口 |
| 仓库 | `git@gitcode.com:chenpi_1/astrometry-api-server.git` |
| 本机路径 | `/root/Projects/astrometry/astrometry-api-server/` |
| 编译产物 | `/root/Projects/astrometry/astrometry-api-server/bin/astrometry-api-server` |
| 服务地址 | `http://127.0.0.1:8010`（`.env` 的 `ASTROMETRY_SERVICE_URL`）|
| 健康检查 | `curl -s http://127.0.0.1:8010/health` |
| 版本自证 | `curl -s http://127.0.0.1:8010/version` |
| 托管方式 | tmux 会话 `astrometry-api` |
| 运维脚本 | `/root/Projects/astrometry/astrom_service.sh` |

### ② astrometry-go-client（必需）

| 项 | 值 |
|---|---|
| 作用 | 上面那个 server 的解算库，构造 solve-field 参数、管理进程组与超时 |
| 仓库 | `git@gitcode.com:chenpi_1/astrometry-go-client.git` |
| 本机路径 | `/root/Projects/astrometry/astrometry-go-client/` |
| 引用方式 | server 的 `go.mod` 用 **相对路径** `replace ... => ../astrometry-go-client` |

> ⚠️ 两个仓库必须**同级放置**。绝对路径 replace 曾在 2026-10-06 之前存在（`/root/service/...`），
> 换机器直接构建失败；改成相对路径后只要同层即可。

### ③ astrometry.net 0.98 运行时（必需）

| 项 | 值 |
|---|---|
| 作用 | 真正的解算引擎（`solve-field` / `astrometry-engine`） |
| 版本 | `0.98-21-gf33d1e76`（**不能降级到 Ubuntu apt 的 0.93**）|
| 路径 | `/opt/astrometry/0.98/{bin,lib/python,etc}` |
| 配置 | `/opt/astrometry/0.98/etc/astrometry.cfg` |

### ④ 4100 系列索引（必需）

| 项 | 值 |
|---|---|
| 作用 | 星表数据，solve-field 的匹配依据 |
| 路径 | `/root/.astrom/4100/index-4107.fits` ~ `index-4118.fits`（12 个，339M）|
| 来源 | http://data.astrometry.net/4100/ |
| 覆盖视场 | 1.1° ~ 70°（4119 未下载，超出即无解）|

---

## 3. 依赖挂了会怎样

| 失效的依赖 | StarWhisper 的表现 |
|---|---|
| ① 服务进程挂了 / 端口不通 | `POST /api/identify/solve` → **HTTP 502** `ASTROMETRY_DOWN` |
| ① 服务活着但索引没加载 | 200 + `SOLVE_FAILED`（能通，但解不出星）|
| ③ 误用 apt 的 0.93 | 静默降级：能通但解算质量/耗时可能变化，**不会报错** |
| ④ 索引缺失 | 200 + `SOLVE_FAILED` |

**注意**：`GET /api/health` 当前的 `astrometry` 字段**只看配置**（`ASTROMETRY_MOCK` 是否为真），
不探测上游真实连通性（见 `server/routers/health.py` 的 docstring）。也就是说解算服务全挂时，
StarWhisper 依然会返回 `ok: true, astrometry: up`。**判断依赖是否真的活着，用下面的体检脚本。**

---

## 4. 体检：一条命令确认依赖是否可用

```bash
bash scripts/check_deps.sh
```

输出示例（全部 OK）：

```
[✓] astrometry 服务         http://127.0.0.1:8010/health  → healthy
[✓]   ├ 服务端 commit        edc352b（= 仓库 main 一致）
[✓]   ├ 收割者 reaper         systemd（宿主机 PID 1 负责收割孤儿进程）
[✓]   └ 解算器 solve-field   0.98-21-gf33d1e76
[✓] astrometry-api-server 仓库  /root/Projects/astrometry/astrometry-api-server（分支 main）
[✓] astrometry-go-client 仓库   /root/Projects/astrometry/astrometry-go-client（分支 main）
[✓] 解算器 prefix          /opt/astrometry/0.98（49 个工具 + python 模块 + cfg）
[✓] 4100 索引              12 / 12 个文件（339M）
[!] AI provider            ...
```

退出码：`0` = 识图链路依赖全部就绪；`1` = 有必需依赖不可用（识图会 502）。
`scripts/deploy.sh` 的预检会调用它，**依赖不通时直接中止部署**，不会把 StarWhisper
发到一个"装好了但识图用不了"的机器上。

---

## 5. 部署依赖的顺序

换机器 / 重装系统时，顺序不能反：

```bash
# 1. 先把解算服务拉起来（它不依赖 StarWhisper）
cd /root/Projects/astrometry
git clone git@gitcode.com:chenpi_1/astrometry-api-server.git
git clone git@gitcode.com:chenpi_1/astrometry-go-client.git   # 必须与上一行同级
# 装 astrometry.net 0.98 → /opt/astrometry/0.98/，下 4100 索引 → /root/.astrom/4100/
./astrom_service.sh deploy
./astrom_service.sh verify        # 含端到端冒烟解算

# 2. 再部署 StarWhisper
cd /root/Projects/StarWhisper
bash scripts/deploy.sh

# 3. 回归：用户侧真实入口
curl -X POST -F "image=@test.jpg" http://127.0.0.1:8000/api/identify/solve
```

StarWhisper 自身的 `scripts/deploy.sh` **不会**帮你装解算服务——那是另一个仓库的事。

---

## 6. 其他外部依赖（非识图链路必需）

| 依赖 | 归属 | 用途 | 挂了的后果 |
|---|---|---|---|
| AgentArts（华为云） | 托管平台 | AI 故事生成（无代码仓库，提示词在 `docs/prompts/story-photo.md`）| 故事降级到 `story_fallback.py` 离线预设，识图不受影响 |
| Open-Meteo | 公开免费 API | 观星指数的天气数据 | 观星指数页部分指标缺失 |
| astropy IERS 表 | pip 包自带 | `/api/index` 天体时刻 | 表超龄会 500（见提交 `8625fa7`）|

这些**不影响识图**，所以体检脚本里只做提示、不作为失败条件。

---

## 7. 相关文档

| 文档 | 何时读 |
|---|---|
| `docs/API.md` | 上游接口字段含义（识图的事实源）|
| `CLAUDE.md` → 关键架构事实 · 上游调用模型 | 改 identify / 超时 / 失败映射时 |
| `/root/Projects/astrometry/docs/README.md` | 要改解算服务本身时（部署形态、索引、故障排查）|