# Analytics Lab

自部署的 Superset、Metabase 与 Rybbit 对比环境，包含独立的 ClickHouse、MySQL、OpenObserve，以及共享的 120 天模拟业务数据。安装完成后可直接查看经营指标、用户漏斗和留存，无需手动建库或配置图表。

## 启动

需要 Docker Engine、Docker Compose v2+、Python 3.10+。首次启动会下载镜像、安装 Superset 数据库驱动并初始化数据，需联网。参考资源：4 核、16 GB 可用内存（包含新增的独立 Rybbit 服务组）；首次下载与构建需预留磁盘空间。

```bash
git clone https://github.com/zhYou/analytics-lab.git
cd analytics-lab
python3 lab.py up
cat ACCESS.txt
```

如果本机的 `python3` 被版本管理器接管，可以使用 `/usr/bin/python3 lab.py up`。

脚本自动生成随机密码，保存于 `.env` 和 `ACCESS.txt`，权限为 `600`。这两个文件、生成数据、日志和截图均不提交到 Git。请保留原 `.env`；修改密码并不会自动修改已持久化的数据库账号。

| 应用 | 地址 | 登录名 |
| --- | --- | --- |
| Superset 6.1.0 | http://localhost:8088 | `admin` |
| Metabase OSS 0.65.2 | http://localhost:3000 | `admin@analytics.test` |
| Rybbit 2.9.2 | http://localhost:3001 | `admin@analytics.test` |
| OpenObserve | http://localhost:5080 | `admin@analytics.test` |

四个应用的演示密码见本地 `ACCESS.txt`。宿主机所有发布端口均只绑定 `127.0.0.1`。此配置用于本机功能评估，使用 HTTP；跨机器部署需要自行设置入口、TLS 和访问控制。

## 查看效果

两套 BI 都创建以下仪表盘，共 13 张图表：

- **经营总览 · 三数据源**：净收入、支付订单、注册用户、收入趋势、渠道与产品收入、客户排行、事件量趋势。
- **用户分析 · 漏斗与留存**：每日活跃、新增注册、7 日转化漏斗、注册周留存、事件分布。

Superset 可直接打开 [经营总览](http://localhost:8088/superset/dashboard/business-overview/) 和 [用户分析](http://localhost:8088/superset/dashboard/user-analytics/)。Metabase 仪表盘链接写入 `ACCESS.txt`，也可从“经营与用户分析 · 演示”集合进入。

Superset 用热力图展示周留存；Metabase 用明细表展示相同结果。可以在原有图表上继续试用筛选、可视化编辑和 SQL 编辑器。这里的漏斗和留存由 ClickHouse SQL 计算，BI 负责展示；它们并不提供 PostHog 式的事件建模和无代码漏斗配置。

## 数据来源

| 数据源 | 数据 | BI 连接方式 |
| --- | --- | --- |
| ClickHouse | 用户、订单、行为事件及分析视图 | 两套 BI 直接连接 `analytics_demo`，只读账号 |
| MySQL 8.0.36 | 同一批用户、订单、客户收入视图 | 两套 BI 直接连接 `analytics_demo`，只读账号 |
| OpenObserve | `default/business_events` 原始事件流 | 先调用真实搜索 API 聚合，再写入 ClickHouse 的 `openobserve_demo` 副本 |

**OpenObserve 在此方案中通过 API 接入**。BI 中名为“OpenObserve · API 聚合副本”的连接使用 ClickHouse 驱动，查询 API 产出的快照。`refresh_openobserve.py` 不从本地事件文件构造快照；它调用 `/api/default/_search`。刷新时间与数量记录在 `fixtures/openobserve-refresh.json`。这条路径需要手动运行 `python3 lab.py refresh`，没有配置实时同步。

宿主机数据连接：ClickHouse HTTP `127.0.0.1:8123`，MySQL `127.0.0.1:3307`；只读账号与密码见 `ACCESS.txt`。容器内部使用服务名 `clickhouse:8123`、`mysql:3306`。初始化使用的管理员密码保存在 `.env`。PostgreSQL 只用于 BI 自身元数据，不发布端口。

数据全部由脚本生成，不包含生产记录。首次运行固定时间锚点和随机种子，以便重复执行时数量保持一致。生成文件在 `fixtures/`；库中已有不匹配的数据时，导入脚本会停止，避免重复追加或覆盖。

## 指标口径

- 净收入：订单状态为 `paid` 的金额合计，退款订单不计入；不是财务结算口径。
- 每日活跃用户：当天发生 `feature_used` 的去重用户。
- 漏斗：`signup_completed → activation_completed → purchase_completed`，按事件顺序匹配，完整转化窗口为注册起 7 天。历史支付后来退款仍会计入发生过的支付事件；最近注册用户可能尚未走完观察窗口。
- 周留存：按注册周分组，观察后续自然周是否发生 `feature_used`；分母为该注册周全体用户，周一作为一周起点，仅展示已结束的周，最多 8 周。第 0 周为注册当周活跃率。
- 生成事件时间和 ClickHouse 日分桶使用 UTC；Metabase 显示时区设置为 Asia/Shanghai，日级指标使用预先计算的日期字段。

这是一份固定模拟数据，后续日期会自然变旧。当前留存视图按运行当天判断自然周是否结束；长期保留此数据时，新结束的周可能因缺少后续事件而显示偏低或为零。重复执行 `up` 保留时间锚点，并重新配置演示图表；建议另存自己编辑的图表。

## 日常操作

```bash
python3 lab.py status   # 服务状态
python3 lab.py verify   # 登录、全部图表查询、来源对账、端口绑定检查
python3 lab.py refresh  # 重新读取 OpenObserve API、刷新聚合副本并验证
python3 lab.py stop     # 停止容器，保留数据
python3 lab.py up       # 启动并重新应用演示配置
```

持久化数据保存在 `analytics-lab_*` Docker volumes 中，停止或重建容器不会清空。需要彻底删除演示环境时，可在本项目目录运行 `docker compose down --volumes`，该命令会删除本项目的全部持久化数据。重新初始化前还需移走本地 `fixtures/`，以生成新的时间锚点。

此仓库只管理部署和初始化代码，不会自动把在 BI 页面上修改的图表导回 Git。Superset 可另行使用导入/导出工作流做配置管理；这里没有搭建完整 GitOps 流程。

## 验证

`verify.py` 对真实运行实例执行集成检查：健康检查、管理员登录、全部 Superset 图表和 Metabase 卡片查询、三数据源记录数、OpenObserve 聚合总量以及宿主机端口绑定。初始化和验证会在本机运行，GitHub 不接收本地凭据或数据库内容。


## Rybbit 原生产品分析

[Rybbit](https://github.com/rybbit-io/rybbit) 固定使用 `v2.9.2`，拥有独立的 ClickHouse 26.3.17.4、PostgreSQL 17.4、Redis 8.6.4，避免应用迁移与原 BI 演示库耦合。Caddy 将前端和 API 代理至同一入口 `http://localhost:3001`；其余 Rybbit 服务不发布宿主机端口。

登录使用 `admin@analytics.test` 和本地 `ACCESS.txt` 中的同一演示密码。默认私有站点为“模拟 SaaS · 经营与行为”，提供：

- [概览](http://localhost:3001/1/main?wellKnown=all-time)：访问量、用户、渠道、地区、页面。
- [事件](http://localhost:3001/1/events?wellKnown=all-time)：注册、激活、功能使用、结算、支付、退款、支付失败。
- [会话漏斗](http://localhost:3001/1/funnels?wellKnown=all-time)：已保存“注册页面 → 完成注册 → 完成激活”和“查看定价 → 开始结算 → 支付完成”；可在页面继续新建、修改、筛选。
- [留存](http://localhost:3001/1/retention)：按首次活动分组的日/周留存。
- [用户](http://localhost:3001/1/users?wellKnown=all-time)和[路径](http://localhost:3001/1/journeys?wellKnown=all-time)：用户属性、活动轨迹、页面与事件路径。

初始站点 ID 为 1；若在页面新建过站点，实际链接以 `ACCESS.txt` 为准。概览、事件等链接选择全部时间，避免固定数据变旧后默认“今天”看不到记录。留存使用 Rybbit 自身的滚动观察范围，可在页面切换。

数据复用原 4,000 名用户、119,271 条事件，并为每笔支付成功或失败事件各补一条定价页访问和开始结算事件，共 6,542 条衍生记录，合计 **125,813 条记录**。用户姓名和全部属性均为模拟值。演示 session 沿用原数据的“用户 + UTC 日期”分组，衍生结算步骤放入对应支付 session；它用于试用分析功能，不模拟真实 SDK 的会话超时。

`bootstrap_rybbit.py` 通过 Rybbit API 初始化账号、私有站点和已保存漏斗；为了保留 120 天历史时间，历史事件和模拟用户属性直接写入 Rybbit 专属演示数据库。重复运行时核对数量，遇到部分导入或数量不符会停止，不自动覆盖。实际业务接入应使用 Rybbit tracker/SDK/API；已有 ClickHouse/MySQL/OpenObserve 表不会自动转成 Rybbit 事件。

**指标对比要保留口径差异**：Rybbit 漏斗按 `session_id` 匹配会话内顺序，原 BI 漏斗按用户计算注册后 7 天内转化。Rybbit 原生留存按首次活动与后续活动计算，原 BI 按注册周与 `feature_used` 计算。两者数值无需一致。当前不生成浏览器会话回放数据。

```bash
python3 lab.py up                  # 启动全部组件、幂等初始化并验证
python3 bootstrap_rybbit.py        # 单独重新应用 Rybbit 演示数据与漏斗
python3 verify_rybbit.py           # 验证原生健康、私有访问、数量、漏斗、留存与用户
```

本机 HTTP 预览保留上游镜像的 Secure Cookie 配置。Chromium 对 localhost 允许此行为；Python 初始化客户端仅对固定 localhost 入口使用相同的 Cookie 例外。远程部署请配置正式域名和 HTTPS。注册入口在本机演示中保留开启；站点默认私有。


用户详情建议从“Users”列表点击进入，以继承当前分析时间范围。上游 `v2.9.2` 的详情页不读取通用 `wellKnown` 日期参数；直接打开或刷新详情可能回到 Today，并偶发 React hydration 警告（其他页面冷加载时也观察到过一次）。此处保留上游官方镜像，已验证从列表进入的正常操作流程。
