# ECS 多 Agent 调用链授权设计方案

> 基于 Trust Graph 既有讨论，对比两种「用户委托 + Agent 互调」授权模型，给出判定规则、选型建议与推荐落法。

---

## 1. 问题定义

业务常见形态：

```text
User 使用 Agent_A
  → A 调用 Agent_B
  → B 再调用 Agent_C
  → （通常由末端 Agent 访问 Connector / 资源）
```

需要同时满足：

1. **调用通道成立**：存在 `A→B`、`B→C` 等 Agent 互调授权  
2. **用户侧授权成立**：在需要代表用户办事的节点上，证明 User 有权使用该 Agent  
3. **避免两种极端**：  
   - 极端松：只要有一条 Agent 链就能一路透传，用户未授权的 Agent 也被用上  
   - 极端紧：链上每个 Agent 都要 User 显式授权，编排稍一变长就频繁改用户授权  

本文对比两种方案，并给出推荐组合。

---

## 2. 公共前提（两种方案都成立）

### 2.1 图上至少有两类边

| 边 | 含义 |
| --- | --- |
| `User → Agent`（DELEGATES_TO / 使用授权） | 用户被允许使用该 Agent（可带 scope：数据归属、能力包、额度等） |
| `Agent → Agent`（CAN_INVOKE） | 上游 Agent 被允许调用下游 Agent |

二者正交：

- 有 `User→A` 无 `A→B`：用户能用 A，但 A 不能调 B  
- 有 `A→B` 无用户侧依据：不能自动等于用户授权了 B  

### 2.2 信任方向

```text
User → Agent_A → Agent_B → Agent_C
```

即「用户信任入口 Agent，再沿预置调用网向下」，不是反向。

### 2.3 运行时判定入口

每次进入某个 Agent（或该 Agent 出站访资源前）调用：

```text
evaluate(initiator_user, actor_agent, caller_agent?, chain, action, resource, ...)
```

差异只在于：**进入某个 Agent 时，除了 `caller→actor` 边之外，还要不要强制存在 `User→actor`。**

---

## 3. 方案一：Agent 标记「是否检查用户权限」

### 3.1 授权时配置

边：

```text
User → Agent_A
Agent_A → Agent_B
Agent_B → Agent_C
```

（本方案**不要求**预置 `User→B`、`User→C`，除非某 Agent 标记为需要检查。）

Agent 节点增加字段，例如：

| 字段 | 含义 |
| --- | --- |
| `require_user_grant` | 进入该 Agent 时，是否必须存在 `User → 该 Agent` 的授权 |

示例标记：

| Agent | `require_user_grant` | 含义 |
| --- | --- | --- |
| Agent_A | `true` 或入口默认检查 | 用户必须有权使用入口 |
| Agent_B | `false` | 内部协作节点，不强制 User→B |
| Agent_C | `true` | 敏感/末端节点，必须有 User→C |

> 入口 Agent 建议始终检查 `User→A`（可用默认规则，不必每个都配 false）。

### 3.2 运行时判定

进入 Agent_X 时：

1. 若 X 是入口（由 User 直接发起）：必须存在 `User→X`  
2. 若 X 由上游 Caller 调入：必须存在 `Caller→X`  
3. 若 `X.require_user_grant == true`：还必须存在 `User→X`  
4. 若 `X.require_user_grant == false`：不要求 `User→X`，仅靠调用边进入  
5. 最终访资源时，再叠加 scope / 风险 / Connector 权限（与既有 Trust Graph 一致）

### 3.3 用例子走一遍

配置：

```text
User→A
A→B，B.require_user_grant=false
B→C，C.require_user_grant=true
（无 User→B，无 User→C）
```

| 路径 | 结果 | 原因 |
| --- | --- | --- |
| User→A | 通过 | 有 User→A |
| User→A→B | 通过 | 有 A→B，且 B 不检查用户授权 |
| User→A→B→C | **拒绝** | 虽有 B→C，但 C 要求检查，且无 User→C |

若补上 `User→C`，则 `A→B→C` 可通过（在其它 scope 满足时）。

### 3.4 优点

- 用户授权面小：中间编排/工具型 Agent 不必人人授一遍  
- 业务链加长时，常只改 **Agent 互调边** 与节点标记，不必频繁改 User 授权  
- 与「能力包内编排、末端才验用户」的产品直觉一致  
- 敏感点可精确打标（如资金、个税、主数据写入 Agent）

### 3.5 风险与约束

- `require_user_grant=false` 配错会形成「影子通道」：用户只授了 A，却摸到本不该碰的内部 Agent  
- 必须配套：**下游白名单、调用目的、scope 交集、默认 false 仅限内部非敏感 Agent**  
- 标记建议由**产品/安全模板**维护，不让终端用户改  
- 审计必须写清：进入 B 是因「调用边 + 免检标记」，不是因 User 直接授权 B  

### 3.6 适用

- 明确区分「编排/工具 Agent」与「用户能力 Agent」  
- 链路经常扩展（多 B、多 C），但用户侧希望稳定只授入口或少数敏感点  

---

## 4. 方案二：进入每个 Agent 都要求存在 User→该 Agent

### 4.1 授权时配置

边：

```text
User → Agent_A
User → Agent_B          （要用到 B 时必须有）
Agent_A → Agent_B
Agent_B → Agent_C
```

（若要用 C，还必须有 `User→C`。）

### 4.2 运行时判定

进入 Agent_X 时（含被上游调入）：

1. 必须存在 `User→X`  
2. 若由 Caller 调入，还必须存在 `Caller→X`  
3. **两条都有**才能进入；缺一不可  

等价理解：Agent 互调边只解决「通道」，用户边解决「名义」；链上每个落地 Agent 都要双重满足。

### 4.3 用例子走一遍

配置：

```text
User→A
User→B
A→B
B→C
（无 User→C）
```

| 路径 | 结果 | 原因 |
| --- | --- | --- |
| User→A | 通过 | 有 User→A |
| User→A→B | 通过 | 有 A→B **且** User→B |
| User→A→B→C | **拒绝** | 有 B→C，但无 User→C |

### 4.4 优点

- 规则极简单、最好审：谁被用到，用户图上必有边  
- 无「免检标记」误配风险  
- 与最小授权、可解释性最强（尤其强合规行业）  

### 4.5 风险与约束

- 编排一加长，User 侧授权要跟着加：`User→B`、`User→C`…  
- 易回到「需求变动就频繁改用户授权」的痛点  
- 可用角色/能力包批量展开缓解，但模型本质上仍是「每 Agent 一授」  

### 4.6 适用

- Agent 数量少、链路短、几乎每个 Agent 都直接代表用户碰敏感资源  
- 合规要求「任何代用户执行的 Agent 必须有显式用户授权记录」  

---

## 5. 方案对比

| 维度 | 方案一：节点标记是否检查用户权限 | 方案二：每跳都要 User→Agent |
| --- | --- | --- |
| 用户授权数量 | 少（入口 + 标记为 true 的节点） | 多（链上每个用到的 Agent） |
| 链路扩展成本 | 主要改 Agent→Agent 与标记 | 常要同步加 User→新 Agent |
| 安全性 | 依赖标记与模板治理，配错风险更高 | 更强、更直观 |
| 可解释性 | 需审计「免检进入」原因 | 最好解释 |
| 与能力包关系 | 很契合：包内中间节点免检，末端强检 | 能力包需展开为多条 User 边 |
| 实现复杂度 | 中（多一个节点策略字段） | 低（规则统一） |
| 对应旧概念 | 接近「受控透传 / 内部节点不验用户授」 | 接近「passthrough 极严：每跳都要用户边」 |

---

## 6. 与既有 Trust Graph 概念的映射

| 既有概念 | 方案一 | 方案二 |
| --- | --- | --- |
| `DELEGATES_TO`（User→Agent） | 入口必有；`require_user_grant=true` 的节点必有 | 每个进入的 Agent 都必有 |
| `CAN_INVOKE`（Agent→Agent） | 调入下游的必要通道 | 同样必要，但不足够 |
| `passthrough_delegation` | 可用标记模型吸收：免检节点≈允许调用链继续，强检节点≈要求用户边 | 可视为恒要求用户边，透传只传 scope 不省略用户边 |
| `max_depth` | 仍建议保留为包内深度天花板，防止免检节点被无限串联 | 同样可保留，但是二道闸 |
| 能力包 | **强烈推荐**：用户授包；包决定哪些节点免检/强检及内部调用网 | 用户授包时自动展开多条 User→Agent |

说明：

- 方案一里，**不要用 `max_depth` 表达业务加了谁**；业务加 C 应改调用网 + C 的 `require_user_grant`。  
- 方案二里，业务加 C 必须补 `User→C`（或由能力包自动补）。  

---

## 7. 推荐方案：方案一为主，方案二为敏感档

### 7.1 推荐策略

采用 **方案一（节点检查标记）作为默认模型**，并用模板把标记收紧；对高敏感域可选「方案二模式」能力包（包内所有节点 `require_user_grant=true`）。

理由：

1. 解决「业务链变长导致用户授权频繁变更」——中间编排节点免检，用户稳定授入口/能力包  
2. 末端或高风险 Agent 强检，避免信任被一路传到资金/主数据等节点  
3. 需要强合规时，不换引擎，只把包内标记全打成 `true`，即退化成方案二  

### 7.2 节点标记规范（建议默认值）

| Agent 类型 | `require_user_grant` 默认 | 说明 |
| --- | --- | --- |
| 用户入口 / Companion 可见助手 | `true` | 必须有 User→该 Agent 或能力包含之 |
| 纯编排 / 规划 / 路由 | `false` | 仅内部调用，不直接碰高敏感资源 |
| 通用工具（格式转换、OCR 片段） | `false` | 不继承用户数据权或仅处理上游已脱敏片段 |
| 企业资源访问（ERP/HR/网盘） | `true` | 代用户碰业务数据前必须有用户授权 |
| 资金 / 外传 / 生产控制 | `true` + 更高 risk 义务 | 可再叠加审批，不允许仅靠免检链路摸到 |

### 7.3 能力包如何承接（避免频繁改个人授权）

用户侧只授：

```text
User → capability_pack: "expense.orchestration"
```

包定义（平台维护）包含：

```text
entry: Agent_A
invoke_graph:
  A → B
  B → C
agents:
  A: require_user_grant=true   # 可由入口规则覆盖
  B: require_user_grant=false
  C: require_user_grant=true
scope_template: owners=self, actions=..., limit_tier=standard
max_depth: 2                   # 包内天花板，防失控，不拿来日常改业务
```

当业务要从 B 再接到新的 Agent_D：

1. 改**包内**调用图与 D 的标记（安全评审）  
2. 若 D 为强检节点，包升级即表示「使用该包的用户被授予 D」或要求用户确认升级  
3. **不必**让每个用户手工改 `max_depth` 或逐条加边（除非组织策略要求用户确认）  

### 7.4 统一判定伪规则

```text
function can_enter(user, caller|null, agent, pack):
  if caller is null:  # 用户直达入口
    return has_user_grant(user, agent, pack)

  if not has_invoke(caller, agent, pack):
    return deny("missing agent invoke edge")

  if agent.require_user_grant:
    if not has_user_grant(user, agent, pack):
      return deny("user grant required for this agent")
  # else: 允许仅凭 invoke 进入（仍受 pack 白名单与 depth 约束）

  if depth_exceeded(pack.max_depth, chain):
    return deny("max_depth exceeded")

  return allow
```

访资源前额外：

```text
effective_scope = intersect(user/pack scope, 路径上 invoke 边 scope, SP/Connector/Resource scope)
data_owner / action / amount 检查
risk / obligations 检查
```

### 7.5 审计字段（两种方案都要留）

```text
initiator_user
entry_agent
current_agent
caller_agent
chain = [A, B, C]
enter_reason =
  - user_grant
  - invoke_only (require_user_grant=false)
  - user_grant+invoke
denied_reason = ...
pack_id / pack_version
```

便于回答：「为什么没授 B 还能进 B」——因为 B 标记免检且存在 A→B，且在包白名单内。

---

## 8. 场景矩阵（帮助选型落地）

| 场景 | 建议 |
| --- | --- |
| A 编排，B 做发票识别（不直接读用户 ERP） | B=`false`（方案一） |
| C 读/写用户 ERP 单据 | C=`true`，需 User 对 C 或对含 C 的包授权 |
| 短链路且每个 Agent 都碰敏感数据 | 包内全部 `true`（方案二模式） |
| 链路频繁加内部工具 Agent | 方案一，工具节点 `false` |
| 跨人查表（张三查李四） | 与链模型无关，另检 data_owner 授权 / 审批 |

---

## 9. 决策结论

1. **主推方案一**：Agent 增加 `require_user_grant`；中间节点可免用户边，敏感/末端节点强制 `User→Agent`（或能力包含之）。  
2. **方案二作为强合规档**：等价于全部节点 `require_user_grant=true`，规则更严、用户授权更多。  
3. **用能力包承接业务链变化**：加 B、加 C 优先改包内调用图与标记，而不是反复改个人的 `max_depth` 或散边。  
4. **`max_depth` 只做安全天花板**；`passthrough` 语义由「免检进入 + scope 下传」表达，末端强检防止委托失控。  

---

## 10. 开放问题（落地前需产品拍板）

1. 入口 Agent 是否允许 `require_user_grant=false`？（建议：**不允许**）  
2. 能力包升级新增强检 Agent 时，是静默生效、提示确认，还是重新授权？  
3. `require_user_grant=false` 的 Agent 是否允许持有高风险 `CAN_ACCESS`？（建议：**不允许**，免检节点不得直连 L3+ 资源）  
4. 用户撤销 `User→A` 后，是否立即切断已在 B 的会话？（建议：**是**）  

---

## 11. 一句话对照

| 方案 | 一句话 |
| --- | --- |
| 方案一 | 有没有 `User→该 Agent`，由 Agent 上的检查开关决定；关掉则可仅凭 Agent 调用边进入 |
| 方案二 | 无论谁调来，进入任一 Agent 都必须同时有 `User→该 Agent` 与调用边 |
| 推荐 | 默认方案一 + 能力包模板；敏感包可切换为方案二模式 |

---

*本文可与 `docs/ECS-Trust-Graph-Design.md` 配套使用：前者讲总体 Trust Graph，本文专攻多 Agent 链上「何时验用户授权」。*
