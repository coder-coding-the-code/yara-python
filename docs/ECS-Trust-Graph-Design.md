# ECS Trust Graph 设计说明

> 基于《ECS 安全解决方案指南与产品路线图》及相关讨论整理  
> 主题：Trust Graph、Service Principal、委托链、授权维护与跨人数据访问

---

## 1. Trust Graph 是什么

**Trust Graph（Agent 信任图）** 把系统里「谁信任谁、能委托谁、能访问什么」建成一张可计算的关系图，而不是零散的权限配置。

### 1.1 要回答的问题

1. 这次调用是否允许（Agent A 能否调 Skill / Agent B）
2. 有效身份是谁（Service Principal + 用户委托如何合成）
3. 数据 / 动作范围是什么
4. 责任链是谁（Human Owner / 发起人）
5. 变更影响面多大（吊销某人 / 某 SP 后波及哪些 Agent）

### 1.2 与周边概念

| 概念 | 关系 |
| --- | --- |
| Trust Level / Trust Profile | 节点上的信任属性 |
| Service Principal | 边上的「以谁的身份运行」 |
| Connector 信任 | Agent–Resource 边的一种 |
| Security Profile Migration | 换环境时要 **Trust 重建**，不能直接复制 |
| Runtime Policy Validator | 执行前查图：委托 / 访问是否仍成立 |
| Audit Trace | 把图上的路径固化成可追溯证据 |

一句话：**Trust Graph = Agent 世界的零信任关系网**——不只管「有没有权限」，还管「信任如何形成、如何传播、如何收回」。

### 1.3 预置关系 vs 执行时判定

| | 授权中心（预先维护） | 执行链（运行时） |
| --- | --- | --- |
| 是什么 | 完整的信任 / 授权关系图 | 对已有图做路径查找 + scope 交集 |
| 例子 | 张三可委托 A；A 可 invoke B；B 可 use Connector | 本次请求能否走通 `张三→A→B→资源` |
| 是否越跑越多 | 不会因执行自动加永久信任 | 顶多发短期审批票据 |

**信任关系在授权中心预先建好；执行链只是查询与消费它，不是边跑边“攒信任”。**

---

## 2. Service Principal 如何理解

**Service Principal（SP）** 是 Agent 运行时真正用来做事的**机器身份**：回答「这个 Agent **以谁的身份**跑、**拿到哪些实际授权**」。

### 2.1 与 Human 的分工

```
Human Owner（人负责）
    └── Agent ID（这个智能体是谁）
            └── Service Principal（以什么身份、带什么权限执行）
                    └── Action / Connector / Resource
```

| 角色 | 含义 |
| --- | --- |
| Human Owner | Org–Person–Role，最终责任人 |
| 任务发起人（User Principal） | 这次任务是谁发起的 |
| Service Principal | Agent 调用 API、访问系统时出示的身份 |

**Human Principal 回答「为谁办事」；Service Principal 回答「谁在办事」。二者不能合成一个。**

### 2.2 为什么不能直接用 Human 当 SP

1. **审计分不清**：日志全是张三，无法区分人操作还是 Agent 代行  
2. **权限错配 / 过大**：Agent 继承个人全部能力，易造成过度代理  
3. **生命周期绑死在人身上**：离职、改密、会话过期导致 Agent 挂掉或失控；无人值守任务也无法跑  
4. **多人共用 Agent 时说不通**：一个报销助手服务多人，不能把 SP 等同于某一个用户  
5. **止损边界不同**：可单独吊销 Agent SP，而不必停掉用户账号  

### 2.3 离职 / 换岗如何解决

人变了，改的是责任与委托映射；Agent 的执行身份是平台签发的 SP，不背个人账号。

| 层 | 离职 / 换岗时 |
| --- | --- |
| Human Owner | 改绑到新人 |
| 用户委托边 | 禁用旧人的 `DELEGATES_TO` |
| Service Principal | 通常保留；复核 / 轮换即可 |
| 个人账号 | 正常关闭，不影响 Agent 运行身份 |

环境迁移链：

```
Development Identity → Testing Identity → Deployment Identity → Production Service Principal
```

每层都要 **重建 SP 并重新授权**，禁止把个人 / 开发凭据直接拷到生产。

### 2.4 多人共用同一 Agent 时要几个 SP

**多数情况：Agent 本身一个 SP；张三和李四不各发一个 SP。**

| 身份 | 数量 | 含义 |
| --- | --- | --- |
| Service Principal | 通常 1 个 | Agent 以什么机器身份跑 |
| 发起人 / 委托身份 | 每人 1 个 | 这次任务是谁发起、数据范围按谁算 |

```
张三发起                李四发起
    │                      │
    ▼                      ▼
同一 Agent ── SP-prod（一个）
    │                      │
 on-behalf-of 张三     on-behalf-of 李四
```

按人头拆 SP 通常没必要；按环境、租户、职责（只读 vs 可写）拆 SP 更合理。

---

## 3. 节点与边（数据模型）

### 3.1 节点类型

| 节点类型 | 关键属性 | 说明 |
| --- | --- | --- |
| Org / Tenant | orgId, trustDomain | 信任域边界 |
| HumanPrincipal | org, person, role, status | Org–Person–Role |
| Agent | agentId, type, trustLevel, status | 智能体主体 |
| ServicePrincipal | spId, env, scopes, expiresAt | 运行身份 |
| Skill | skillId, riskLevel | 可调用能力 |
| Connector | connectorId, system, authType | 外部系统入口 |
| Resource | resourceId, classification, riskLevel, env | 表 / API / 设备等 |

原则：**人、Agent、SP 分开建模。**

### 3.2 边类型

| 边类型 | from → to | 含义 |
| --- | --- | --- |
| OWNS | Human → Agent | 产品 / 生产责任人 |
| RUNS_AS | Agent → ServicePrincipal | Agent 的机器身份 |
| DELEGATES_TO | Human → Agent | 允许 Agent 代其执行 |
| CAN_INVOKE | Agent → Agent | 跨 Agent 调用 |
| CAN_USE | Agent/SP → Connector | 连接器信任 |
| CAN_ACCESS | SP/Connector → Resource | 资源访问 |
| TRUSTS | Agent → Agent | 同级信任（须严格限制传递） |
| MEMBER_OF | * → Org/Tenant | 租户 / 域归属 |

### 3.3 信任方向

自然语言「A 信任 B」= 图上 `A → B`（信任者 → 被信任者）。

```
张三 信任 Agent_A
Agent_A 信任 Agent_B
Agent_B 信任 Connector / 资源能力
```

即：

```
User → Agent_A → Agent_B → …
```

**不是** Agent 反向信任 User。

注意：

- **信任方向**：信任者 → 被信任者  
- **权限收窄方向**：沿链路做 scope **交集**，下游不能放大上游权限  

### 3.4 Trust Graph 存什么

主要存**授权 / 信任关系**，例如：

| 业务理解 | 图上形态 |
| --- | --- |
| 张三可以委托哪些 Agent | `Human → DELEGATES_TO → Agent` |
| Agent A 可以 invoke 哪些 Agent | `Agent A → CAN_INVOKE → Agent B` |
| Agent B 可以用哪些资源 | `B → RUNS_AS → SP → CAN_USE → Connector → CAN_ACCESS → Resource` |

**不主要存：** 对话内容、LLM 输出、每次临时请求（请求是 `evaluate` 输入）；决策日志可进审计库。

---

## 4. 边上的字段（中心设计）

每条边建议具备：`scope`、`trust_level`、`delegatable`、`max_depth`、`risk_cap`、`valid_from/valid_to`、`status`。

### 4.1 委托边：`DELEGATES_TO`（张三 → Agent A）

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| scope.owners | 可代谁的数据 | `{zhangsan}` |
| scope.actions | 允许动作（可对用户隐藏，见第 8 节） | `{query, submit}` |
| scope.resources | 允许资源 | `{expense-api}` |
| scope.amount_limit | 金额上限 | `5000` |
| delegatable | 是否允许再转给其他 Agent | 默认 `false` |
| max_depth | 最多再转几跳 | `0` 或 `1` |
| downstream_agents | 允许透传的下游白名单 | `{agent:b}` |
| risk_cap | 委托风险上限 | `L2` |
| status / 有效期 | 是否生效 | active |

### 4.2 调用边：`CAN_INVOKE`（A → B）

| 字段 | 含义 | 示例 |
| --- | --- | --- |
| scope.actions / resources | A 能让 B 做的子集 | 不得大于上游委托 |
| purpose | 调用目的 | `invoice-verify` |
| passthrough_delegation | 是否把上游用户委托继续传给 B | `true/false` |
| identity_mode | B 如何识别来源 | `on_behalf_of_user + via_agent` |
| max_depth / risk_cap | 深度与风险 | — |
| approval_required | 跨 Agent 是否要审批 | — |

### 4.3 运行与访问边

- `RUNS_AS`：Agent → SP（env、status；SP 自身有 expires_at）  
- `CAN_USE`：SP → Connector  
- `CAN_ACCESS`：Connector → Resource（actions、risk_cap、data_classes）  

A、B **各自有自己的 SP**；出站访问 Connector 时，执行身份是**当前执行者**的 SP（例如 B 的 SP-B）。

---

## 5. `evaluate(...)` 输入字段

`evaluate` 传入的是**这一次动作的判定上下文**，不是整张图。

### 5.1 必填

| 字段 | 含义 |
| --- | --- |
| actor_agent_id | 当前执行出站动作的 Agent |
| initiator_human_id | 任务发起人 |
| action | 动作 |
| resource_id | 目标资源 |

### 5.2 常用可选

| 字段 | 含义 |
| --- | --- |
| data_owner_id | 业务数据归属人；缺省可=发起人 |
| amount | 金额等业务度量 |
| env | prod / dev |
| connector_id | 指定连接器 |
| skill_id | 指定 Skill |
| caller_agent_id | 上游调用方 Agent（跨 Agent 时） |
| delegation_chain | 完整调用链，如 `[A, B]` |
| session_id / task_id | 审计与会话关联 |
| obligation_tokens | 已获得的短期审批票据 |
| now | 判定时间（检查过期） |

### 5.3 返回

- `allow` / `reason`  
- `effective_identity`（发起人 + Agent + SP，跨 Agent 时含 calling/executing）  
- `effective_scope`（路径交集）  
- `risk_level` + `obligations`  
- `path`（命中边列表，供审计）  

最小集：`actor_agent_id`、`initiator_human_id`、`action`、`resource_id`。  
涉及他人数据或金额时，务必带上 `data_owner_id`、`amount`。

---

## 6. 判定规则与典型问答

### 6.1 通用步骤

1. 找执行身份：`Agent → RUNS_AS → SP`  
2. 找用户委托：`发起人 → DELEGATES_TO → Agent`（透传到下游时检查 delegatable / depth / 白名单）  
3. 找资源路径：`SP → CAN_USE → Connector → CAN_ACCESS → Resource`  
4. 全程 scope **交集**（只收缩不放大）  
5. 比对风险与义务（审批、双人控制等）  

硬规则：

1. 无边即无信任（零信任默认拒绝）  
2. 用户委托默认不可传递；传递必须显式声明  
3. `CAN_INVOKE` ≠ 用户已授权下游  
4. 用户同时委托 A 和 B ≠ A 可以 invoke B  
5. 出站身份是执行者 SP，业务主体仍是发起人 / 数据归属人  

### 6.2 情景：有张三→A，有 A→B，但张三未声明可委托 B

**默认不能**以张三名义走 A→B。  

除非 `张三→A` 明确 `delegatable=true`、`max_depth≥1`，且最好白名单含 B，并且 `A→B` 允许 `passthrough_delegation`。  

`CAN_INVOKE` 只说明 A/B 技术上可调用，不等于张三授权了 B。

### 6.3 情景：张三可委托 A 和 B，但没有 A→invoke→B

**不能**从 A 调到 B。  

张三可分别直接用 A 或直接用 B；缺的是 Agent 间调用边。

### 6.4 有效权限

```text
effective_scope = intersect(
  用户委托 scope,
  各跳 CAN_INVOKE scope,
  SP / Connector / Resource 访问 scope
)
```

---

## 7. 完整示例：报销助手

### 7.1 角色

| 角色 | 身份 |
| --- | --- |
| 张三 / 李四 | 普通员工 |
| 王五 | 财务 BP，Agent Human Owner |
| Agent-报销助手 | 共用 Task Agent |
| SP-报销助手-prod | 生产运行身份 |
| Connector-ERP财务 | 连接器 |
| 报销单API | L2 |
| 银行付款API | L4（高风险，默认无访问边） |

### 7.2 图结构（概念）

```
王五 ──OWNS──► Agent:报销助手 ──RUNS_AS──► SP-prod
                                              │
                                              ▼
                                         Connector:ERP
                                              │
                                   CAN_ACCESS ▼
                                         报销单API
                                    （无边指向银行付款API）

张三 ──DELEGATES_TO──► Agent   scope: owners={张三}, 本人办理能力包
李四 ──DELEGATES_TO──► Agent   scope: owners={李四}, 本人办理能力包
```

### 7.3 判定例子

| 请求 | 结果 |
| --- | --- |
| 张三提交自己 1200 元报销 | 允许 |
| 张三提交李四的单 | 拒绝（owners 不含李四） |
| 助手调银行付款API | 拒绝（无边或 risk 越界） |
| 张三提交 8000 元 | 需人工审批（超额义务） |
| 张三离职 | 禁用其 `DELEGATES_TO`；SP 与李四不受影响 |

### 7.4 跨 Agent 链（A 调 B 再访 Connector）

```
张三 --DELEGATES_TO--> A --CAN_INVOKE--> B --RUNS_AS--> SP-B
                                              --CAN_USE--> Connector
                                              --CAN_ACCESS--> Resource
```

审计至少固化：

```text
initiator = 张三
delegation_chain = [A, B]
executing_sp = SP-B
edges_used = [...]
effective_scope = {...}
decision = allow/deny
```

---

## 8. scope.actions 过多时如何优化

**不要让用户勾选底层 actions；用户只授“能办哪类事”，细动作由模板展开。**

### 8.1 分层

| 层 | 谁配置 | 粒度 |
| --- | --- | --- |
| 用户委托边 | 用户 / 管理员 | 场景 / 能力包 |
| Agent / Skill 边 | 平台模板 | 具体 actions |
| SP / Connector 边 | 资源 Owner + 安全 | API 最小权限 |

### 8.2 能力包示例

| 能力包 | 用户可见含义 | 内部展开 |
| --- | --- | --- |
| expense.self_service | 报销助手-本人办理 | query, submit + owners=self + 额度档 |
| expense.read_only | 本人只读 | query |
| invoice.invoke | 可调用发票识别 Agent | 受控 CAN_INVOKE |

用户侧委托可写成：

```text
DELEGATES_TO {
  to: agent_a,
  capability_pack: "expense.self_service",
  data_scope: "self",
  limit_tier: "standard"   # → 5000
}
```

### 8.3 其他优化

- 按风险分层：L0–L1 角色默认；L2 能力包；L3+ 单独审批  
- 用业务语言（助手、数据范围、档位），不用 API 动词列表  
- 变更改模板版本并批量重算，避免逐人改边  

`evaluate` 仍可按细 actions 判定；麻烦留在模板层。

---

## 9. 跨人数据访问：张三要查李四的某表

这是**跨主体访问**：`initiator=张三`，`data_owner=李四`。

### 9.1 默认

仅有「张三委托 Agent 且 owners={张三}」→ **拒绝**查李四数据。

### 9.2 合法放行依据（择一）

1. **组织权限**：张三是上级 / 持有可查下属的数据角色  
2. **李四显式分享**：`李四 → SHARES_WITH → 张三`（表、query、TTL）  
3. **临时审批**：返回义务 → Owner/管理员批准 → 短时票据  
4. **非个人数据**：表为共享业务资源，则不应把 data_owner 标成李四，而走资源 ACL  

### 9.3 流程

```
解析请求（initiator / data_owner / resource / action）
  → 张三对 Agent 有委托？
  → Agent/SP 对该表有 query？
  → 张三对「李四的该表」有独立依据？
      → 有则允许并加强审计
      → 无则拒绝或拉起审批
```

产品表现：先声明这是他人数据；无权则走申请，禁止静默越权成功。

---

## 10. Trust Graph 数据如何维护

### 10.1 三类数据

| 类型 | 内容 | 写入方 |
| --- | --- | --- |
| 主数据节点 | Org、Human、Agent、SP、Connector、Resource | IAM / Registry / 资源目录同步 |
| 信任与授权边 | OWNS、DELEGATES_TO、CAN_INVOKE、CAN_ACCESS… | 配置与审批流 |
| 运行时派生 | Session、evaluate 日志、审批票据 | 运行时（可过期清理） |

原则：**图是真相源的投影；禁止业务代码私自插边。**

### 10.2 典型事件

| 事件 | 维护动作 |
| --- | --- |
| 入职 | 建 Human；按角色模板发委托边 |
| 发布 Agent | 建 Agent + OWNS；再建 prod SP 与 RUNS_AS |
| 上线 Connector/资源 | Validator 通过后加访问边 |
| 额度 / 能力变更 | 改模板与边属性，或发新版本能力包 |
| 超额审批 | 发 TTL 票据，不永久改委托 |
| 换 Owner | 改 OWNS |
| 离职 | 禁用该人委托边；算 blast radius；一般不删 SP |
| 环境迁移 | Export → Sanitize → Map → Re-authorize → Validate，重建边 |
| 定期对账 | 与 IAM / Registry 比对，清理僵尸边 |

### 10.3 维护原则

1. 软删 / 禁用 + 版本，保留审计回放  
2. 高风险授边必须审批  
3. SP 轮换是一等操作  
4. 写图统一经 Trust Manager  

---

## 11. 设计原则汇总

1. **人、Agent、SP 分离**；User Principal ≠ Service Principal  
2. **Trust Graph 预置授权关系**；执行时 evaluate，不自动长信任  
3. **信任方向** User → Agent → 下游；权限沿路径求交集  
4. **委托与互调是两回事**：都要显式授权  
5. **默认不可传递**；传递需 delegatable + depth + 下游白名单  
6. **用户授能力包，系统展开放细 actions**  
7. **跨人数据**需要独立依据（组织权 / 分享 / 审批）  
8. **高风险资源默认无边**；银行付款、工控等须显式授权 + 高义务  

---

## 12. 术语表

| 术语 | 含义 |
| --- | --- |
| Trust Graph | Agent / 人 / 资源间的信任与授权关系图 |
| Human Owner | Agent 的责任人（Org–Person–Role） |
| User / Initiator Principal | 本次任务发起人 |
| Service Principal | Agent 的机器运行身份 |
| DELEGATES_TO | 用户委托 Agent |
| CAN_INVOKE | Agent 调用 Agent |
| evaluate | 运行时基于图的授权判定 |
| capability pack | 面向用户的能力包，内部展开为细 scope |
| obligation token | 审批通过后的短期放行票据 |
| blast radius | 吊销节点 / 边后的影响面 |

---

*文档依据讨论整理，可与 ECS Guardian Trust / Trust Manager / Runtime Policy Validator 产品设计对照使用。*
