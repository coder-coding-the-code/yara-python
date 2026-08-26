# ECS Trust Graph × OpenFGA 关系模型草图（方案一）

> 承接《多 Agent 调用链授权设计方案》的推荐落法：默认方案一（`require_user_grant`）+ 能力包。  
> 本文只描述类型、关系、元组和判定怎么拆，不实现代码。

---

## 1. 目标与分工

OpenFGA / SpiceDB 擅长回答关系问题：

- 张三是否被授权使用 Agent A / 能力包 P？
- Agent A 是否被允许调用 Agent B？
- SP-B 是否被允许经 Connector 访问某资源？
- 张三是否被允许查看李四的某份数据？

它**不擅长单独一次 Check 就表达**三方语义：「张三经 A 进入 B，且 B 免检」。  
因此采用混合：

| 层 | 存什么 / 算什么 |
| --- | --- |
| **Agent Registry** | 节点属性：`require_user_grant`、风险等级、环境、是否入口 |
| **OpenFGA（关系）** | 边：用户授权、互调、SP、Connector、资源、能力包、数据分享 |
| **Trust Manager** | 编排多次 Check，按方案一分支 |
| **OPA / Cedar（策略）** | `max_depth`、金额档、风险义务、环境隔离 |
| **Token Exchange（可选）** | 运行时每跳衰减的委托令牌，作为图判定的会话证明 |

**原则：关系进图；开关与度量进注册表/策略；会话证明进令牌。**

---

## 2. 类型（Type）

| 类型 | 对应 Trust Graph 节点 | 说明 |
| --- | --- | --- |
| `user` | HumanPrincipal | Org–Person–Role 落到用户主体 |
| `agent` | Agent | 智能体；**不**把 SP 合成进来 |
| `service_principal` | ServicePrincipal | 动态签发的机器身份 |
| `pack` | 能力包 | 用户侧授权的稳定单元 |
| `connector` | Connector | ERP 等连接器 |
| `resource` | Resource | 报销单 API、某张表 |
| `organization` | Org/Tenant | 信任域、组织关系 |
| `approval`（可选） | 短期票据 | 审批通过后的 TTL 授权 |

---

## 3. 关系（Relation / 边）

### 3.1 `user`

| 关系 | 主体 | 含义 |
| --- | --- | --- |
| `manager` | `user` | 上级（组织权限：可查下属数据） |
| `data_viewer` | `user` | 被显式分享「可看我的数据」的人 |

### 3.2 `pack`（能力包）

| 关系 | 主体 | 含义 |
| --- | --- | --- |
| `grantee` | `user` | 谁被授予该包（用户只授这一条） |
| `entry` | `agent` | 入口 Agent |
| `member` | `agent` | 包内所有 Agent（含内部节点，用于白名单） |
| `user_granted` | `agent` | 包为用户展开的强检授权对象（A、C 等 `require_user_grant=true` 的节点） |

用户授权「报销编排包」= 写一条 `user` → `pack.grantee`。  
强检 Agent 的用户授权由包展开，不必每人写 `User→C`。

### 3.3 `agent`

| 关系 | 主体 | 含义 | 对应原边 |
| --- | --- | --- | --- |
| `owner` | `user` | Human Owner | `OWNS` |
| `grant` | `user`、`pack#grantee` | 用户可使用该 Agent | `DELEGATES_TO` |
| `can_invoke` | `agent` | 谁可以调用**本** Agent | `CAN_INVOKE`（方向：调用方是主体，被调方是对象） |
| `runs_as` | `service_principal` | 运行身份 | `RUNS_AS` |
| `in_pack` | `pack` | 属于哪个包（便于白名单） | — |

说明：

- `grant` 只表示「用户有权使用该 Agent」，**不含**细 `actions` 列表。细动作由能力包模板 / 策略展开。  
- `require_user_grant` **不建议做成 OpenFGA 关系**，放在 Agent Registry。图里用有没有 `grant` 来回答「用户授没授」；要不要查这一条由标记决定。  
- 方案二模式 = 包内所有 `member` 都列入 `user_granted`，进入任一节点都查 `grant`。

### 3.4 `service_principal`

| 关系 | 主体 | 含义 |
| --- | --- | --- |
| `of_agent` | `agent` | 此 SP 属于哪个 Agent |
| `env` | 条件或标签 | prod/dev（也可用 condition） |
| `can_use` | `connector` | 允许使用的连接器 |

### 3.5 `connector` / `resource`

| 对象 | 关系 | 主体 | 含义 |
| --- | --- | --- | --- |
| `connector` | `caller_sp` | `service_principal` | 哪些 SP 能用它 |
| `resource` | `accessed_via` | `connector` | 经哪些连接器可达 |
| `resource` | `can_query` / `can_submit` | `connector#caller_sp` 或 `service_principal` | 动作级访问 |
| `resource` | `owner` | `user` | 数据归属人（个人数据时） |
| `resource` | `viewer` | `user`、`user#manager`、`user#data_viewer` | 谁能看这份数据 |

动作不必做成几十种关系。起步用 `can_query` / `can_submit`；更细的 API 动作放策略或 Connector 自己的 scope。

---

## 4. 模型示意（OpenFGA DSL 语义，非运行代码）

```text
type user
  relations
    define manager: [user]
    define data_viewer: [user]

type pack
  relations
    define grantee: [user]
    define entry: [agent]
    define member: [agent]
    define user_granted: [agent]

type agent
  relations
    define owner: [user]
    define grant: [user, pack#grantee]
    define can_invoke: [agent]
    define runs_as: [service_principal]
    define can_use: grant                    # 用户直达/强检时用
    define can_be_invoked: can_invoke        # 上游 Agent 调入时用

type service_principal
  relations
    define of_agent: [agent]
    define can_use_connector: [connector]

type connector
  relations
    define allowed_sp: [service_principal]
    define can_access: [resource]

type resource
  relations
    define owner: [user]
    define viewer: owner or manager from owner or data_viewer from owner
    define connector: [connector]
    define can_query: allowed_sp from connector
    define can_submit: allowed_sp from connector
```

`resource.viewer` 用于跨人数据：默认仅 owner；上级走 `manager`；分享走 `data_viewer`。

---

## 5. 报销编排包：元组怎么落

场景：

```text
张三使用入口 A
A 调内部 B（免检）
B 调末端 C（强检，真正碰报销单 API）
C 以 SP-C 经 ERP Connector 访问报销单 API
```

### 5.1 节点属性（Registry，不是 FGA 元组）

| Agent | require_user_grant | 说明 |
| --- | --- | --- |
| A 报销编排助手 | true | 入口 |
| B 发票识别 | false | 内部工具，不直连 ERP |
| C ERP 单据 Agent | true | 末端，碰财务数据 |

约束：B 的 SP **不得**拥有对报销单 API 的 `can_submit`。免检节点不能直连 L3+ 资源。

### 5.2 能力包与用户授权

| 主体 | 关系 | 对象 | 含义 |
| --- | --- | --- | --- |
| `user:zhangsan` | `grantee` | `pack:expense-orch` | 张三拥有该包 |
| `agent:a` | `entry` | `pack:expense-orch` | 入口 |
| `agent:a` / `b` / `c` | `member` | `pack:expense-orch` | 包内白名单 |
| `pack:expense-orch#grantee` | `grant` | `agent:a` | 包展开：用户授 A |
| `pack:expense-orch#grantee` | `grant` | `agent:c` | 包展开：用户授 C |
| （无） | `grant` | `agent:b` | **故意不写**：B 免检，不靠用户边 |

李四同理只加 `user:lisi` `grantee` `pack:expense-orch`。  
**业务以后加上内部 Agent D（免检）**：只加 `member` 与 `A/B→D` 互调边，不动用户。  
**加上敏感 Agent E（强检）**：加 `user_granted`/`grant` 展开 + 互调边；按产品策略提示用户确认包升级。

### 5.3 互调边

| 主体 | 关系 | 对象 |
| --- | --- | --- |
| `agent:a` | `can_invoke` | `agent:b` |
| `agent:b` | `can_invoke` | `agent:c` |

没有 `agent:a can_invoke agent:c` 时，A 不能跳过 B 直接调 C（除非另写边）。

### 5.4 身份与资源

| 主体 | 关系 | 对象 |
| --- | --- | --- |
| `sp:c-prod` | `of_agent` / `runs_as` 反向 | `agent:c` |
| `sp:c-prod` | `can_use_connector` | `connector:erp` |
| `connector:erp` | `can_access` | `resource:expense-api` |
| `user:zhangsan` | `owner` | `resource:expense-doc-001`（若按单据实例） |

银行付款 API：**不写**任何 `can_access` 边 → 默认拒绝。

---

## 6. Trust Manager 如何用多次 Check 实现方案一

OpenFGA 每次 Check 仍是「主体 + 关系 + 对象」。进入 Agent X 时由 Trust Manager 组合：

```text
can_enter(user, caller, agent, pack):

  1. agent 必须是 pack.member（白名单）
  2. 若 caller 为空（用户直达）:
       Check(user, can_use, agent)           # 即 grant
       且 agent 必须是 pack.entry（或等价入口规则）
  3. 若 caller 非空:
       Check(caller, can_invoke, agent)
       若 Registry.require_user_grant(agent) == true:
           Check(user, can_use, agent)       # 无 User→agent（含包展开）则拒绝
       否则:
           不查 grant                        # 方案一：B 仅凭 A→B 进入
  4. 策略：depth <= pack.max_depth；env 匹配
```

对应前文例子：

| 步骤 | Check | 结果 |
| --- | --- | --- |
| 张三进 A | `zhangsan can_use A`（经 pack 展开） | 允许 |
| A 进 B | `A can_invoke B`；B 免检，不查张三→B | 允许 |
| B 进 C | `B can_invoke C` **且** `zhangsan can_use C` | 无包展开到 C 则拒绝；有则允许 |
| C 访报销单 | `SP-C can_query/can_submit expense-api`，且 `zhangsan` 为数据 viewer | 再过金额策略 |

**方案二**：第 3 步永远查 `can_use`，等于包内全部 Agent 都在 `user_granted`。

---

## 7. 与旧字段的对应

| 设计讨论中的字段 | 放哪 |
| --- | --- |
| `DELEGATES_TO` / User→Agent | FGA `agent.grant`（常由 `pack#grantee` 展开） |
| `CAN_INVOKE` | FGA `agent.can_invoke` |
| `require_user_grant` | Agent Registry 属性 |
| `passthrough_delegation` | 运行时：免检进入 + 继续带 `initiator=user`；强检点再验 `grant` |
| `max_depth` | 能力包策略 / OPA，FGA 不管计数 |
| `scope.actions` | 能力包模板展开；FGA 只保留粗关系 `can_query/can_submit` |
| `scope.owners` / data_owner | `resource.owner` + `viewer` |
| `amount_limit` | OPA / 档位属性，不进关系图 |
| `RUNS_AS` | FGA `agent.runs_as` |
| `CAN_USE` / `CAN_ACCESS` | FGA SP→Connector→Resource |
| 审批票据 | 短期 tuple（`approval`）或 Token Exchange；到期删除 |

---

## 8. 跨人数据：张三查李四的表

与调用链正交，多一次 Check：

```text
Check(user:zhangsan, viewer, resource:lisi-table)
```

`viewer` 来源：

1. `owner` = 张三本人  
2. `lisi` 的 `manager` = 张三（组织权）  
3. `lisi` 的 `data_viewer` = 张三（显式分享）  
4. 都没有 → 拒绝或走 `approval` 短期 tuple  

即使链 `A→B→C` 能进入 C，**没有 viewer 也不能读李四的表**。

---

## 9. 运行时令牌（与图的关系）

图是**授权真相**；令牌是**本次任务的衰减证明**（可选但推荐）：

```text
User 授权包
  → 签发 task token：initiator=张三, pack=expense-orch, scope=self, amount_cap=5000
  → A 调 B：Token Exchange，audience=B，scope 只减不增，chain=[A,B]
  → B 调 C：再交换；C 强检时 Resource Server 仍可回查 FGA：张三对 C 是否 grant
```

令牌丢了或过期，以 FGA + Registry 为准。  
**不要**用令牌在执行中 mermaid 出新的长期 `can_invoke` 边。

---

## 10. 维护时写哪些元组

| 事件 | FGA | Registry / 策略 |
| --- | --- | --- |
| 张三开通报销包 | `zhangsan grantee pack` | 无 |
| 发布内部工具 Agent | `member` + `can_invoke` | `require_user_grant=false` |
| 发布末端 ERP Agent | `member` + `user_granted/grant` 展开 + `can_invoke` | `require_user_grant=true` |
| 签发生产 SP | `runs_as`、`can_use_connector` | SP 生命周期 |
| 张三离职 | 删/禁 `grantee`；组织 `manager` 边同步 IAM | 会话吊销 |
| 包升级加免检节点 | 只改 member/invoke | 标记 false |
| 包升级加强检节点 | 增加 grant 展开 | 标记 true；可选用户确认 |
| 超额审批 | 短期 `approval` tuple 或 obligation token | TTL |

---

## 11. 不建议用 OpenFGA 单独硬扛的部分

1. **一次 Check 表达「免检进入」** —— 用 Registry 分支 + 两次 Check 更清晰  
2. **金额比较、风险 L0–L5、双人审批流程** —— 策略引擎 / 工作流  
3. **max_depth 沿链计数** —— Trust Manager 读 chain 长度  
4. **语义防火墙、LLM 脱敏** —— ECS 运行时技能，不是 ReBAC  

---

## 12. 最小落地切片

P0 只建这些关系即可跑通方案一：

1. `pack.grantee` / `agent.grant`  
2. `agent.can_invoke`  
3. Agent Registry 上的 `require_user_grant`  
4. `agent.runs_as` → `sp.can_use_connector` → `resource.can_query|can_submit`  
5. Trust Manager 按第 6 节编排 Check  

P1 再加：`resource.viewer`（跨人）、pack 版本、审批短期 tuple、Token Exchange。

---

## 13. 一句话

**OpenFGA 存「谁授了谁、谁能调谁、谁能碰哪」；`require_user_grant` 决定进某个 Agent 时要不要查用户那条边；能力包把用户授权收成一条 `grantee`，内部链路变长时优先改互调边和包展开，而不是改每个人的图。**

---

*配套：`docs/ECS-Trust-Graph-Design.md`（总体）、`docs/ECS-Trust-Graph-Chain-Auth-Design.md`（方案一/二）。*
