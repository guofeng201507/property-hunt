# Property Hunt

Personal Singapore landed property research tool. Local-first, SQLite + Streamlit + MCP.

面向个人买房的本地工具，重点支持两条线：

- **半独立 / 排屋收租**：街道租金、gross yield、land psf、剩余 lease、流动性。
- **低买高卖 / 估值差**：URA caveat、街道成交中位数、折价、规划催化、MP2025 / 地籍约束。

数据来自 URA、data.gov.sg（MP2025 / SLA 地籍）；INLIS 用于人工尽调。所有数据和服务都在本机运行。

## 功能

- URA 私宅成交、租赁合同、规划决定采集
- SQLite 街道统计、sale/rent comps、yield、估值差
- MP2025 Land Use / LHA / Conservation / Height + SLA 地籍富化
- 最近 MRT 站点与直线距离（LTA MRT Station Exit）
- 剩余 lease 风险提示与过滤
- Streamlit 四个页面：收租筛选、估值差、Watchlist、规划信号
- Watchlist 手动录入 + INLIS 尽调记录
- MCP stdio server，可接入 Qoder / Codex

## 功能总览

| 模块 | 功能 |
|---|---|
| 数据采集 | 从 URA 拉取私宅成交、租赁合同、Written Permission；从 data.gov.sg 下载 MP2025 图层、SLA 地籍、LTA MRT 出口；本地 SQLite 存储，Parquet 保留原始快照 |
| 市场统计 | 按街道 / 类型 / tenure / 面积段计算成交中位数、land psf、租金中位数、rent psf、gross yield、成交量、租赁样本量、流动性、confidence |
| 收租筛选 | 面向半独立 / 排屋 / 独立式，按 yield、land psf、剩余 lease、MRT 距离、zoning、LHA 等筛选 |
| 估值差 | 找出低于同街道 / 类型 / tenure / 面积段中位数的近期成交，显示折价、lease left、规划/地籍约束和 risk flags |
| Watchlist | 手动录入正在看的房源，自动计算 comps、discount、估算租金和 gross yield；显示 MP2025 zoning、GPR、LHA、conservation、地籍 lot、最近 MRT |
| 规划信号 | 查看 URA Written Permission 已批/已拒记录，筛选重建 / 分割 / 合并相关项目 |
| 地理富化 | 用成交点做 point-in-polygon，给街道补齐 Land Use、GPR、Height、LHA、Conservation、SLA lot 和最近 MRT |
| INLIS 尽调 | 生成 POI / PTI / PTIEI / PTICM / LP / CII 检查清单，记录每套房源的尽调结果和文件路径 |
| MCP | 通过 stdio 暴露查询、估值、规划、watchlist、INLIS 工具，可接入 Qoder / Codex |
| 数据模式 | demo 模式用内置样例跑通链路；live 模式用真实 URA 数据，demo/live 共用 SQLite，切换时需移走旧库 |

这个工具**不做**：实时成交、自动抓取商业挂牌、全岛门牌级自动匹配、自动估值模型、投资建议。它做的是把公开官方数据整理成可查询的街道级研究底稿，再用 Watchlist + INLIS 对具体房源做人工核验。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- URA Data Service AccessKey（真实数据模式需要）

## 快速开始

### 1. 安装依赖

```bash
git clone https://github.com/guofeng201507/property-hunt.git
cd property-hunt
make setup
```

等价于：

```bash
uv sync --extra dev
```

### 2. 配置 URA AccessKey

复制环境变量示例：

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
URA_ACCESS_KEY=你的_access_key
```

AccessKey 申请地址：

```text
https://eservice.ura.gov.sg/maps/api/reg.html
```

Registration 页面选择 **Real Estate Applications**，提交后在邮箱查收 AccessKey。Token 由程序自动换取，不需要手动保存。

### 3. 先跑 demo（可选）

不填 AccessKey 也可以先用内置样例数据看界面：

```bash
make demo
make app
```

打开：

```text
http://127.0.0.1:8501
```

> demo 和 live 共用 `db/property.db`。看完 demo 要切真实数据时，先把 demo 库移走：
>
> ```bash
> mkdir -p db/backup
> mv db/property.db* db/backup/
> make ingest
> ```

### 4. 拉真实数据

```bash
make ingest
```

默认行为：

- URA 成交：4 个 batch，覆盖近 5 年
- URA 租赁：最近 8 个季度
- URA 规划决定：当前年份
- 自动重算街道统计
- 如果 MP2025/地籍图层已存在，自动重新富化

单独刷新：

```bash
uv run python scripts/run_ingest.py --mode live --dataset transactions
uv run python scripts/run_ingest.py --mode live --dataset rentals --rental-quarters 8
uv run python scripts/run_ingest.py --mode live --dataset planning --year 2026
```

### 5. 下载 MP2025 / 地籍图层

```bash
make geo
```

会下载并加载：

- MP2025 Land Use Layer
- MP2025 Landed Housing Area Layer
- MP2025 Conservation Area Boundary
- MP2025 Building Height Control
- SLA Cadastral Land Parcel
- LTA MRT Station Exit

首次约 330 MB，下载后存放在 `data/geo/`，该目录不进入 git。

### 6. 启动看板

```bash
make app
```

打开：

```text
http://127.0.0.1:8501
```

## 常用命令

| 命令 | 作用 |
|---|---|
| `make setup` | 安装依赖 |
| `make demo` | 加载内置样例数据 |
| `make ingest` | 拉真实 URA 数据并重算统计 |
| `make geo` | 下载/刷新 MP2025 + 地籍并富化街道 |
| `make app` | 启动 Streamlit |
| `make mcp` | 启动 MCP stdio server |
| `make test` | 运行测试 |

## 页面说明

### 收租筛选

- 选择 landed 类型、district、最少成交/租赁样本、最少剩余 lease
- 可按 MRT 站名筛选，并设置最大直线距离；例如输入 `KEMBANGAN`
- 按 gross yield 排序
- 同时显示 land psf、lease left、zoning、GPR、LHA、conservation、MRT、confidence
- **不要只看 yield**：短 lease 会制造高 yield 假象

### 估值差

- 对比同街道 / 类型 / tenure / 面积段的成交中位数
- 显示折价、样本数、lease left、zoning、LHA、conservation、confidence
- 折价可能来自地块形状、lease decay、保护区、噪音/路冲、流动性差，需要结合 risk flags 判断

### Watchlist

- 手动录入正在看的房源：地址、类型、要价、land sqft、built-up sqft、租金、tenure、lease start
- 自动计算 land psf、sale comps、discount、估算租金、gross yield
- 显示 MP2025 zoning / GPR / LHA / conservation / 地籍 lot
- 附 INLIS 尽调 checklist 和已记录结果
- 支持删除 watchlist

### 规划信号

- URA Written Permission 已批/已拒记录
- 可按街道和月份筛选
- 可只看重建 / 分割 / 合并相关

## MCP 接入

配置示例在 `.mcp.json.example`：

```json
{
  "mcpServers": {
    "property-hunt": {
      "command": "/path/to/property-hunt/.venv/bin/python",
      "args": ["-m", "property_hunt.mcp_server"],
      "env": {
        "PROPERTY_HUNT_DB": "/path/to/property-hunt/db/property.db"
      }
    }
  }
}
```

把路径替换成你的实际项目路径，然后放进 Qoder / Codex 的 MCP 配置。

可用工具：

```text
get_data_status
search_street
get_sale_comps
get_rent_comps
estimate_yield
get_value_gap
get_planning_signals
watchlist_add
watchlist_list
watchlist_delete
get_property_brief
get_due_diligence_checklist
due_diligence_add
due_diligence_list
```

## 数据源

| 数据 | 来源 | 接入 |
|---|---|---|
| 私宅成交 | URA Data Service | REST API，免费 |
| 私宅租赁合同 | URA Data Service | REST API，免费 |
| Written Permission | URA Data Service | REST API，免费 |
| MP2025 图层 | data.gov.sg / URA | GeoJSON 下载 |
| SLA 地籍 | data.gov.sg / SLA | GeoJSON 下载 |
| MRT 站出口 | data.gov.sg / LTA | GeoJSON 下载 |
| 业主/地契/抵押/caveat | SLA INLIS | 网页按次付费，无公开 API |

## 数据口径与限制

- **URA 成交没有门牌号**：只有 project / street / district 级别。具体门牌需要 Watchlist 手动录入，或通过 INLIS / REALIS / 商业挂牌补全。
- **URA 成交基于 caveat**：覆盖大多数但非全部交易；没有 caveat 的交易不保证出现在成交数据里。
- **有地租赁面积是区间**：租赁合同没有精确门牌，面积也是区间；有地租金样本相对薄。
- **短 lease 会制造高 yield**：工具默认要求剩余 lease ≥40 年，可在页面调整。
- **MP2025 是规划图层**：有地住宅实际可建体量还受 Envelope Control、Landed Housing Guidelines、保护区等约束，不能只看 GPR。
- **地籍 lot 是近似定位**：街道级富化用成交点做 point-in-polygon，精确宗地/边界仍需 INLIS survey plan。
- **MRT 距离是直线距离**：取最近 MRT 出口的直线距离，不是步行距离；实际步行可能因马路/河道绕行更长。
- **不是投资建议**：所有 yield、discount、confidence 都是基于公开数据的估算，实际交易需律师、建筑师、估价师和 INLIS 尽调。

## 目录结构

```text
property-hunt/
  data/
    fixtures/            # demo 数据
    raw/                 # URA 原始 Parquet 快照（gitignored）
    geo/                 # MP2025/地籍/MRT GeoJSON（gitignored）
  db/
    property.db          # SQLite（gitignored）
  scripts/
    run_ingest.py        # URA 采集
    run_geo.py           # 下载 geo + 富化
  sql/
    schema.sql
  src/property_hunt/
    app.py               # Streamlit
    comps.py             # comps/yield/value gap/watchlist
    geo.py               # MP2025/地籍富化
    ingest.py            # 数据入库
    mcp_server.py        # MCP stdio server
    normalize.py
    ura.py
  tests/
```

## 数据刷新建议

| 任务 | 频率 |
|---|---|
| URA 成交 | 周二/周五更新后 |
| URA 规划决定 | 每日 |
| URA 租赁 | 每月 15 日后 |
| MP2025 图层 | 宪报/修订时检查 |
| 地籍 | 每月或需要时 |

## 安全

- `.env` 已在 `.gitignore` 中，不要提交 AccessKey。
- `db/property.db`、`data/geo/`、`data/raw/`、`logs/` 都不进入 git。
- 仓库是 public；提交前检查不要带入个人路径、AccessKey、INLIS 文件。
- MCP server 默认 stdio，本地运行；不要直接暴露到公网。
- INLIS 业主信息仅用于个人合规尽调，注意 PDPA。

## 常见问题

### 没有数据 / 收租页为空

先确认已经拉数据：

```bash
make ingest
make geo
```

收租页默认要求至少 3 条成交、3 条租赁、剩余 lease ≥40 年；可以适当放宽筛选。

### URA 401 / token 失败

- 检查 `.env` 里的 `URA_ACCESS_KEY` 是否正确
- 确认注册邮箱里的激活链接已经点过
- 重新运行 `make ingest`，程序会重新换取当日 token

### data.gov.sg 429

`make geo` 已内置 429 退避重试；如果仍然失败，等几分钟再跑。

### Streamlit 8501 被占用

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN
```

停掉旧进程后重新 `make app`。

### MCP 连不上

- 配置里的 Python 路径必须是项目 `.venv/bin/python`
- `PROPERTY_HUNT_DB` 必须是绝对路径
- MCP server 日志写 stderr，stdout 只走协议，不要加 `print`

## License

Personal project，未指定开源许可证。
