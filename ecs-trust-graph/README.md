# ECS Guardian Trust

v2：**NetworkX 属性图 + Cedar 判定**。设计见 `docs/ECS-Trust-Graph-v2-Design.md`。

不再用 OpenFGA 当真相源，也不再有 `require_user_grant` / `User→内部 Agent`。

| 开源 | 角色 |
| --- | --- |
| NetworkX | 身份、INVOKE 拓扑、SP 访问边、数据权、授权快照 |
| Cedar (`cedarpy`) | start_task / hop / egress 的 permit·forbid |
| FastAPI | 控制面与 Command Center |

```bash
cd ecs-trust-graph
pip install -r requirements.txt
PYTHONPATH=. pytest tests -q
python -m ecs_trust   # http://127.0.0.1:8080
```
