# ECS Trust Graph v2

> 取代「一张 ReBAC 图 + `require_user_grant`」。评测见 `ecs-trust-graph/EVALUATION.md`。

## 开源选型

| 层 | 选型 | 不选 | 原因 |
| --- | --- | --- | --- |
| 图 | **NetworkX**（属性图；规模上来可换 Neo4j / Apache AGE） | OpenFGA / SpiceDB | 边要带 scope/快照，要做路径与影响面，不是布尔 Check |
| 判定 | **Cedar**（`cedarpy`） | 把规则写进应用 if | 可分析的 permit/forbid；金额、风险、出站角色用 forbid 封死 |
| 身份 | 模型内 Human ≠ Agent ≠ SP；生产可接 Keycloak + SPIFFE | 人账号当运行身份 | 审计分得清「为谁办事 / 谁在办事」 |

OpenFGA 不再作为真相源。`openfga/model.fga` 仅作 v1 归档。

## 四层（不再用一个开关粘）

```
① 身份         人 / Agent / Service Principal
② 调用拓扑     平台维护 INVOKE；用户不可见，不叫委托
③ 能力授权     用户授 Pack 的能力快照（资源×动作×额度×出站 Agent）
④ 出站动作     SP 有边 × 快照覆盖 × 数据权 × 风险义务
```

关闭的产品决策：

1. 内部 Worker **不**查 `User→Agent`；没有出站边就不能碰个人数据（图校验强制）。
2. 包升级：只改拓扑（加 OCR）→ 旧授权仍有效；改能力指纹（加银行 API / 新出站 Agent）→ 必须重授或确认新快照。
3. 入口必须是 Pack.entry，不允许免检入口。
4. 撤包 / 离职：使该用户任务令牌失效，立即不能再出站。
5. 跨人数据与调用链正交：本人 / 分享 / 上级 / 审批，缺一则出站失败。

## 两个判定入口（拆掉上帝 evaluate）

| API | 何时 | 查什么 |
| --- | --- | --- |
| `start_task` | 用户打开助手 | 有 Pack 授权、入口匹配 → 冻结任务快照 |
| `hop` | Agent 调 Agent | 当前包工作流上是否有 INVOKE |
| `authorize_egress` | 出站 Connector/API | 出站角色 + SP 边 + 快照 + 数据权 + 金额/L 级 |

兼容层 `evaluate` = start（或沿用 session）+ 逐跳 hop + egress，供 UI 回归。

## Pack 与授权快照

Pack 声明：`entry`、`workers`、`egress`（agent → 允许的 resource 列表）、`workflow`、`actions`、额度、`risk_cap`。

用户授权保存 **capability snapshot**，不是「User→每个 Agent」：

```
resources, actions, data_scope, amount_limit, risk_cap, egress_agents
```

判定时：`effective = grant_snapshot ∩ 当前 Pack 定义`。平台缩小能力立即生效；放大能力必须新快照。

## 不变量（种子与改图时强制）

- `workers ∩ egress_agents = ∅`
- Worker 的 SP 不得拥有 Pack 资源上的 query/submit 边
- `egress` 里的 Agent 必须出现在 workflow 中
- 高风险资源（L4+）默认无访问边
- L5 禁止出站

## 报销例子（v2）

- A 编排 = entry；B OCR = worker；C ERP = egress（仅 expense-api）
- 张三授 Pack 快照；无 `User→B`、无 `User→C`
- 银行付款 API 不在快照、也无 SP 边 → 双拒绝
- 加内部 Agent D：只改 workflow/workers → 张三无需重授
- 把银行付款写入 Pack.egress → 指纹变，旧快照不能付
