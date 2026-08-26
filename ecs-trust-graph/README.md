# ECS Guardian Trust

基于《ECS 安全解决方案指南与产品路线图》中的 **Agent Trust Graph**，以及 `docs/` 下三份设计说明，用开源组件落地的 **Guardian Trust** 控制面。

## 用了哪些开源能力

| 开源项目 / 标准 | 在本方案中的角色 |
| --- | --- |
| [OpenFGA](https://github.com/openfga/openfga) 关系模型（Zanzibar ReBAC） | 存「谁授了谁、谁能调谁、谁能碰哪」 |
| NetworkX | 信任图分析、影响面（blast radius）、可视化布局 |
| FastAPI | Trust Manager HTTP 控制面 |
| 可选 `openfga/openfga` 容器 | 生产可替换内存引擎；演示默认内嵌兼容引擎，无需 Docker |

关系判定遵循 `docs/ECS-Trust-Graph-OpenFGA-Model.md`：**关系进图；`require_user_grant` 进 Registry；金额 / 深度 / L0–L5 风险进策略层。**

## 快速开始

```bash
cd ecs-trust-graph
pip install -r requirements.txt
python -m ecs_trust
```

打开 http://127.0.0.1:8080 使用 Command Center。

```bash
cd ecs-trust-graph
PYTHONPATH=. pytest tests -q
```

## 设计对应

- 默认 **方案一**：入口 A 与末端 C 强检 `User→Agent`（由能力包 `pack#grantee` 展开），内部发票识别 B 仅凭 `CAN_INVOKE` 进入。
- **方案二** 能力包 `expense-strict`：包内全部节点进入都查用户授权。
- 人 / Agent / Service Principal 分离；出站身份是执行者 SP。
- 跨人访问必须另有 `resource.viewer`（本人 / 上级 manager / 显式 data_viewer）。
- 银行付款 API 默认无边，零信任拒绝。
- 超额走义务票据，不永久改委托边。
- 离职删除该人元组，不影响共用 Agent 的 SP 与其他用户。

## 目录

```
ecs-trust-graph/
  openfga/model.fga     # OpenFGA DSL 真相源
  ecs_trust/            # ReBAC 引擎 + Trust Manager + API
  web/                  # Guardian Command Center
  tests/
docs/                   # 设计说明（Trust Graph / 调用链 / OpenFGA 模型）
```
