# Trust Graph v2 评测记录

评测方式：先列 v1 设计缺陷，再跑 v2 不变量/对抗用例，直到缺陷关闭或明确残留。

## Round 1 — OpenFGA + `require_user_grant`（否决）

| 缺陷 | 结论 |
| --- | --- |
| 调用拓扑与用户授权同一张图 | 不适合 |
| 边属性（额度、delegatable）塞不进 tuple | 不适合 |
| 方案一免检是节点开关，不是关系 | 不适合 |
| 多 Pack 时 grant 全局并集 | 已在代码里绕开，说明引擎不是真相源 |
| `evaluate` 上帝接口 | 不适合 |

## Round 2 — NetworkX 属性图 + Cedar（当前）

开源：NetworkX 存图，Cedar（cedarpy）判定，FastAPI 控制面。

| 检查项 | 结果 | 覆盖测试 |
| --- | --- | --- |
| 用户只授 Pack，无 User→B / User→C | 通过 | `test_no_user_to_internal_agent_grant_edges` |
| Worker 禁止出站；带资源边则图校验失败 | 通过 | `test_worker_cannot_egress` / `test_seed_rejects_worker_with_resource_edge` |
| 加内部工具不改能力指纹、无需重授 | 通过 | `test_adding_worker_does_not_require_regrant` |
| 扩大出站能力后旧快照不能用新资源；重授后才能（L4 走审批） | 通过 | `test_expanding_capability_blocks_old_grant` |
| `start_task` / `hop` / `authorize_egress` 拆分 | 通过 | `test_start_task_and_egress_are_split` |
| 本人报销 / 跨人 / 银行无边 / 超额审批 / 离职 | 通过 | `test_manager.py` |
| 跳过 OCR 直达 C | 通过 | `test_skip_ocr_blocked` |
| Cedar 参与放行 | 通过 | `test_cedar_reasons_present_on_allow` |
| HTTP + 页面 | 通过 | `test_api.py` |

评测中抓到的实现缺陷：模块级 Pack 单例被用例改写后污染全套件 → 改为每次 `build_demo` 新建 Pack。

当前：`pytest tests` **18 passed**。

## 残留（可接受，不阻断）

1. 路径是否在 workflow、数据权（本人/分享/上级）仍由 **图查询产出事实**，再交给 Cedar。这是「图负责查、策略负责判」，不是再把图塞进 ReBAC。
2. 金额/L 级在 Python 里先收成 `amount_ok` / `risk_ok`，Cedar forbid 读布尔。若要把数字比较完全放进 Cedar，下一步只改 `trust.cedar` 与 context 字段。
3. 生产身份（Keycloak / SPIFFE）未接实；模型已分人与 SP。
4. 图库可换 Neo4j/AGE，API 不用变。

## 决策

**采用 v2。** 不再维护方案一/二节点开关。v1 文档留在 `docs/ECS-Trust-Graph-*.md` 作对照。
