# M0/M1 技术设计符合性审计

## 结论

| 口径 | 结论 |
| --- | --- |
| M0/M1 里程碑功能验收 | 保持 `Accepted`；已有证据仍有效 |
| 冻结领域模型、Flow IR、状态机、API 主契约 | 符合 |
| CLI / MCP 职责边界、源 Excel 只读、确定性编译 | 符合 |
| 严格分层与目录结构逐项一致 | 部分符合 |
| 外部真实 LLM 联调 | 未执行；适配器契约测试已通过 |
| 综合设计符合性 | **Partially conformant；阻断 M2 的偏差须在 M2 签收前关闭** |

M0/M1 是按技术设计的核心原则和里程碑范围实施的，但不能表述为“逐条 100% 无偏差”。本审计不追溯撤销已经通过的功能验收；新增偏差项进入 M2 技术债门禁。

## 逐项审计

| 设计项 | M0/M1 实际情况 | 判定 | M2 处理 |
| --- | --- | --- | --- |
| 领域模型 | Workbook、Case、Fixture、Config、Flow IR、Run、CaseRun、Attempt 等已建立，Domain 未依赖 FastAPI、openpyxl、pytest 或 subprocess | 符合 | M2 补齐 `generation_id`、设备、事件和执行结果字段 |
| Flow IR | Pydantic + JSON Schema；无坐标；命令白名单；`source_ref` 可回溯 | 符合 | 保持冻结，不做破坏性变更 |
| 状态机 | Frozen RunState 图和非法迁移保护已实现 | 符合但尚未接入真实 Run 编排 | M2 RunService 必须只通过状态机迁移 |
| API V1 | M0/M1 路径与 OpenAPI 基本一致，统一 request ID 和 Problem 错误已实现 | 符合 | 实现 `/runs`、事件流、取消和 Case 查询 |
| 正常执行/诊断边界 | Maestro CLI 用于正常执行，MCP 仅用于探测、层级、截图和后续诊断 | 符合 | M2 继续禁止 MCP 绕过 pytest 生命周期 |
| 源 Excel 只读 | 上传后保存不可变快照；真实验收前后 SHA-256 一致 | 符合 | Run 只复制快照和生成物 |
| YAML | LLM/规则翻译器只产出 IR；确定性编译；真实 `check-syntax`；保留 initial/final | 符合 | Run 消费已批准 final YAML |
| pytest 生命周期 | M0/M1 未生成 pytest，技术设计 API 描述中出现“pytest 预览”，但研发计划明确 PY-01/PY-02 属于 M2 | 阶段性未实现，非 M1 越界缺陷 | M2 必须生成、collect 并真实执行 |
| Application 依赖规则 | `WorkbookService`、`GenerationService` 和 `SyntaxChecker` 仍直接引用 Infrastructure 具体类型 | 偏差 `TD-01` | M2 引入 Protocol 端口；新 Run 编排不得继续扩大反向依赖 |
| LLM 适配器位置 | OpenAI-compatible HTTP 实现在 Application 模块内，按冻结分层应属于 Infrastructure | 偏差 `TD-02` | 后续重构为基础设施适配器；不改变 FlowTranslator 端口 |
| 前端目录 | React 功能完整，但当前 `App.tsx/api.ts/types.ts/styles.css` 为扁平结构，未完全采用冻结的 features/components/api/types/styles 目录 | 偏差 `TD-03` | M2 新增 Run 功能按 feature 模块组织；M1 文件渐进迁移 |
| 外部进程规则 | 已使用参数数组、`shell=False`、超时和退出码；统一取消、进程组和输出上限尚未实现 | M2 阻断项 `TD-04` | M2-AC-05 前关闭 |
| 真实 LLM | Base URL、模型、Key、Schema、超时和错误路径已测试；没有用户提供的真实服务凭据 | 环境说明 `TD-05`，非代码阻断 | 可独立联调，不阻断本地 M2 执行 |

## M2 设计门禁

M2 不得签收，除非同时满足：

1. Run 编排通过端口调用设备、pytest 和 Maestro 适配器，不在 API 层直接启动外部进程。
2. 状态变化经过 `RunStateMachine` 并持久化事件；刷新从 `run.json` 和事件文件恢复。
3. pytest 是 Fixture/Case 生命周期入口；正常执行不调用 MCP。
4. 外部 pytest 进程使用独立进程组，支持超时、输出文件、输出上限和取消后清理子进程。
5. Run 目录符合冻结结构，源 Excel 与 M1 生成物只复制、不覆盖。

## M2 关闭情况（2026-09-18）

| M2 设计门禁 | 实现情况 | 结论 |
| --- | --- | --- |
| Run 只通过端口调用外部能力 | `application/ports.py` 定义仓储、设备、pytest 生成/执行端口；Run API 不启动进程 | 已关闭 |
| 状态机与事件持久化 | 所有 Run 迁移经 `RunStateMachine`；`run.json` 与单调事件文件可重读 | 已关闭 |
| pytest 为生命周期入口 | 生成 pytest fixtures/items，由 pytest 调 Maestro；正常执行未调用 MCP | 已关闭 |
| 进程控制 | 参数数组、`shell=False`、独立 pytest 进程组、TERM/KILL、超时与输出上限均实现并测试 | 已关闭 |
| Run 目录与只读输入 | 每个 Run 复制 Excel/YAML，生成报告和证据，不覆盖 M1 或用户源文件 | 已关闭 |

因此，M2 新增部分符合冻结技术设计，并已通过正式验收。M0/M1 已签收功能仍有效；严格逐目录审计仍保持 `Partially conformant`，原因是 `TD-01`～`TD-03` 的遗留结构偏差，而不是 M2 运行链偏离设计。M2-AC-01～05 的最终证据与历史阻断关闭记录详见 `docs/m2-status.md`。

## M3 收束补充（2026-09-22）

M3 保持相同边界：pytest 仍是正常执行与 Fixture 生命周期入口；MCP 只在已分类的定位失败后调用；修复器不能修改断言或命令结构；每次状态迁移、Attempt、Repair、结果副本与 Artifact 哈希均持久化。真实定位修复和断言保护 Run 均通过冻结门禁。详见 `docs/m3-design-conformance.md` 与 `docs/m3-status.md`。
