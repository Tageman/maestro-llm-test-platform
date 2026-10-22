# V2 技术设计：操作闭环、执行版本与稳定复跑

## 1. 设计状态与基线

| 项目 | 内容 |
| --- | --- |
| 版本 / 日期 | V2.0 设计提案 / 2026-10-22 |
| 对应需求 | [requirements-v2.md](requirements-v2.md)，V2-R01～R14 |
| 当前代码基线 | `ec94ff7`；不将工作区未提交的 M4 补丁算作已发布实现 |
| 当前契约 | REST `/api/v1`，OpenAPI 文档版本 1.2.0，Flow IR 1.0 |
| 本文性质 | 目标设计，尚未实施或冻结为最终接口；下文“新增/扩展”均指待实现 |

沿用 React/TypeScript/Vite、FastAPI/Pydantic、文件系统 Repository、pytest、Maestro CLI/MCP。优先补齐产品层和可追溯执行语义，不引入远程调度、不默认换数据库、不改用 LLM 直接执行 YAML。

产品 V2 不等于 URL 必须改为 `/api/v2`。V2-A/B 采用 `/api/v1` 的增量接口；实现时同步版本化 OpenAPI 和 TypeScript 类型，预期下一个兼容契约版本为 1.3.0。本文不是已经生效的 OpenAPI 文件。

## 2. 架构与目录

调用顺序：页面资源路由 → API 客户端 → History / ExecutionPlan / Run 应用服务 → 领域校验与 Repository → 原 pytest / CLI / MCP 适配器。

建议目录（标为新增的模块按阶段创建，不在文档任务中预建空代码）：

```text
frontend/src/
  app/                         # 新增：资源路由、全局错误边界
  features/workbooks/          # 新增：历史、校验、Case 筛选
  features/generations/        # 新增：版本、审批、差异
  features/runs/               # 扩展：历史、确认、详情、比较
  features/settings/           # V2-C：生成 Profile
  api/                         # 从 api.ts 拆分：类型化请求、Problem、事件连接
backend/src/maestro_app/
  api/v1/routes/               # 扩展 history、plans、preflights、profiles、batches
  application/                # 新增 history_service、execution_plan_service、
                              # preflight_service、comparison_service；C 阶段再加 promotion/batch
  domain/                     # 新增执行计划、指纹、预检、来源模型；保留既有模型
  infrastructure/             # 新增目录读模型、计划/幂等记录仓储；复用原原子写工具
backend/tests/                 # 单元、集成、协议兼容测试
frontend/tests/                # 新增组件及浏览器 E2E
docs/                         # 需求、设计、后续阶段验收记录
```

前端当前没有路由和查询库。实施 V2-A 时先确定轻量资源路由/请求缓存方案并锁定依赖，不能在类型和文档里假定某库已安装。服务端增加 SPA 深链接回退配置时，必须排除 `/api/*`，API 404 不得返回 HTML。

## 3. 领域模型与不变量

| 模型 | 新增/扩展字段 | 不变量 |
| --- | --- | --- |
| WorkbookSummary | source_sha256、名称、创建时间、catalog_health | 每次导入独立 workbook_id，同名不覆盖；源 Excel 只读 |
| GenerationManifest | schema_version、compiler_version、source/config/IR/YAML 哈希、generator provenance、parent_generation_id、promoted_from | 批准版本内容不可原地改变；修改生成新 ID；历史缺字段为 unknown |
| ExecutionPlan | plan_id、generation_id、source_run_id、selection_kind、requested_case_ids、ordered_case_ids、fixture_closure、execution_fingerprint、effective_config、expires_at | 服务端计算范围与闭包；计划创建不触发设备执行；有效期 30 分钟 |
| RunOrigin | kind: fresh / rerun / failed_subset / selected / batch、parent_run_id、plan_id、batch_id | 新 Run 独立记录；父 Run 只用于追溯，不能作为可变执行数据源 |
| PreflightReport | report_id、plan_id、device_id、checked_at、expires_at、checks[]、acknowledgements[] | 每项 pass/fail/unknown；报告绑定指纹；机器检查和人工确认分开 |
| StateContract | required_conditions、setup_fixture_ids、cleanup_policy、data_policy | 引用已存在/批准 Fixture；不可夹带任意 shell/YAML；默认 preserve |
| RunComparison | left/right run_id、compatibility、case_deltas、timing_deltas | 不修改原 Run；不把缺失/未执行记为通过 |
| LLMProfile（C） | profile_id、strategy、provider、base_url、model、parameters、secret_ref、revision | API 不返回密钥；Generation 记录脱敏快照，不执行时动态读取最新 Profile |
| RunBatch（C） | batch_id、plan_snapshot、requested_count、child_run_ids、state | 有限串行；一次只派发一个子 Run；失败或取消即停止后续派发 |

Case 身份默认为 `(workbook_id, case_id)`；同一 Generation 的 Run 可直接比较。不同导入文件即使 case_id 同名也不自动认定相同用例；V2-B 跨版本只展示差异和“不保证同基线”，不引入未经定义的逻辑项目合并。

### 3.1 指纹与批准

采用 SHA-256。规范化 JSON 固定键排序、UTF-8 和数值编码；数组保留语义顺序。文件哈希针对保存的确切字节，不对 YAML 任意重排后宣称同版本。

- `generation_fingerprint`：源 Excel 哈希、有效生成配置、IR Schema/编译器版本、逐 Flow IR/YAML 哈希、生成策略与脱敏模型/提示词版本。
- `execution_fingerprint`：Generation 指纹、选择及实际顺序、Fixture 闭包、模式和有效执行配置。设备/App 实测版本作为运行环境快照，单独参与比较，不伪装成生成输入。
- 批准绑定 Flow 内容哈希及审批依据。旧版本缺指纹时可从现有完整文件计算执行快照，但生成器来源缺失仍记 unknown；不得补造审批者或模型信息。文件损坏/内容与批准不一致时拒绝执行。
- 密钥不进入指纹、日志、URL 或浏览器存储。Profile 修订号和非敏感参数足以标识配置来源。

### 3.2 IR 与编译器兼容

V2-A/B 保留 `schemas/flow-ir-v1.schema.json`，不为 UI 历史/重跑向 Flow IR 塞入设备、Run 或审批状态。计划、预检、指纹各自是服务端 DTO/Schema。

V2-C 的修复提升必须把受控 selector 修改映射回对应 IR 节点，重新校验并确定性编译；仅有 Run 内 YAML diff 且无法证明 IR 对应关系时拒绝提升。提升后的 YAML 不得靠手工拼接绕过编译器。旧 Generation、源 Excel、旧 Run 原封保留。

## 4. 执行计划、选择与 Fixture

创建计划时依次校验 Generation ready、选中 Flow 的批准/语法/warning 门禁、Case 存在且可执行、Fixture 依赖图、配置和内容完整性。

选择规则：

1. `selection.kind=all` 才表示全部可执行 Case；`selected` 要求非空且唯一 case_ids；未知 ID 422。`original_scope` 从父 Run 的 selected_case_ids 获取。`failed_subset` 根据父 Run 的最终 Case 结果计算。
2. 默认失败集合为 FAILED、FIXTURE_FAILED、ENV_ERROR、TIMEOUT；`include_blocked`、`include_not_run` 默认为 false；结果为空返回 `EMPTY_SELECTION`，不生成全量计划。
3. 父 Run 必须终态；其结果快照哈希进入计划。创建 Run 时再次核对，防止晚到共享清理结果改变失败集合。导出仍 pending 时可查看计划，但开始重跑须等待结果收口或明确服务端判定执行结果已固定。
4. 展开所选 Case 的 Fixture 依赖闭包，检测缺失/环/宽 scope 依赖窄 scope。共享 scope 沿用 `Cases.module` 分组规则，返回实际执行顺序及排序原因；用户勾选顺序不是隐藏的新执行规则。
5. function 作用域每 Attempt；module 为本 Run 当前轮次的 Case 模块；session 为本 Run 当前共享轮次。修复重试仍先关闭旧共享轮次再重建完整链；清理失败不得继续重试。
6. 任意新 Run 均重新创建 pytest 生命周期，不继承旧 Run 的 Fixture 缓存或“此前通过”状态。失败子集只初始化该子集真正需要的共享 Fixture。

当前 `CreateRunRequest.case_ids=[]` 经 `or list(available)` 会落为全量；V2-A 将其改为 422。这是有意收紧的输入校验，须在契约变更说明和回归测试中明确。省略或 null 仍保留原“全量”的旧客户端语义；新页面只走显式计划。

## 5. 预检与运行状态机

### 5.1 预检与状态条件

V2-A 继续保留原有设备准备门禁；V2-B 增加可见的预检报告，默认有效期 60 秒。检查覆盖工具可用性、目标模拟器精确 ID、App 安装/版本、计划指纹、相关未确认清理风险，以及状态契约中的可只读验证条件。

预检可以获取只读页面层级/截图，但不得执行 tap、启动/重置 App、登录或清数据。缺少权限/无法判断记 unknown。所有超时走适配器现有有界超时，页面给出对应检查原因，不无限等待。

StateContract 在执行确认页填写，作为 POST /execution-plans 的可选 `state_contract` 输入并保存为计划快照；缺省使用 preserve 数据策略和既有设备/App 必检项。新增准备 Fixture 只可从本 Generation 已批准的 Fixture 中选择，并纳入依赖闭包、顺序预览和指纹，不在执行时临时生成代码。修改契约生成新计划、重新预检，不修改旧 Run。

条件 DTO 包含 `condition_id`、`phase`、`kind`、`required`、`expected` 和 `verification`。首版 kind 限定为 device_identity、app_version、visible_selector、manual_prerequisite；selector 沿用 IR 的 text/resource_id/content_description 类型；verification 为 machine 或 manual。账号/远端数据无法由这些只读检查证明时使用 manual_prerequisite，不能默认读取业务数据库或执行任意脚本。after_setup 必需条件失败时将该 Case 标记为环境阻断，并继续原清理路径；不修改业务断言的定义。

两类状态条件分开：

- `before_setup`：执行前必须满足的工具、设备、数据/授权条件。
- `after_setup`：由已批准 Fixture 建立的页面/账号条件；预检阶段可标 deferred，在 setup 完成、Case 业务步骤前验证。若要在此时读取页面，必须处于同一设备锁内，不能边执行边外部改状态。

review 对可人工判断的 unknown 可提交确认记录；工具不可用、错设备、已知失败、内容哈希不符等硬阻断不能手工覆盖。无人值守不接受必需 unknown。清理 failed/unknown 的风险只能由新检查证实恢复，或明确的已批准恢复 Fixture 执行并核验后关闭；不是点击“忽略”就转绿。

预检通过不授予永久执行资格：创建 Run 时校验时效与指纹；进入 PREPARING_DEVICE、持有 runtime 独占锁后再次检查设备、App 与关键状态。过期或状态改变中止并留证，不存在“预检通过后任意时刻可执行”的窗口承诺。

### 5.2 状态兼容

Generation 保留 pending / generating / awaiting_review / ready / failed。派生版本从未批准状态开始，执行批准规则不变；修复提升强制人工审查。

ExecutionPlan 是独立资源，状态为 valid / expired / invalidated；PreflightReport 的展示结果为 ready / blocked / needs_confirmation。二者不扩充 RunState 枚举。

Run 沿用既有状态机：创建阶段仍经过现有校验/就绪路径；实际执行主链为 READY → PREPARING_DEVICE → RUNNING → FINALIZING → 终态，诊断/修复沿用既有分支。实时 UI 从事件和 Case 状态推导前置/业务/清理阶段，不捏造后端状态。有效状态转换以既有 `domain/state_machine.py` 为基础，不在前端直接写状态。

开始前请求失败返回 Problem，不生成假完成 Run；Run 创建后环境变化走 PREPARING_DEVICE → FAILED，记录 `ENVIRONMENT` 原因，Case 未执行不视为业务失败。运行中取消通过原取消/收尾路径落到 CANCELLED；终态不会回到 RUNNING。服务重启后的旧 Run 继续按既有恢复策略处理，用户“再跑”始终是新 Run。

## 6. 前后端接口草案

统一前缀 `/api/v1`。新增字段兼容旧响应读取；现有 GET、审批、取消、产物下载和 SSE 保留。

| 阶段 | 方法与路径 | 语义 |
| --- | --- | --- |
| A | GET /workbooks | 分页历史；q、status、created_from/to |
| A | GET /generations | 分页历史；workbook_id、status、时间范围 |
| A | GET /runs | 分页历史；workbook_id、generation_id、state、parent_run_id、时间范围 |
| A | POST /execution-plans | 根据生成版本和选择生成不可变计划；201 |
| A | GET /execution-plans/{id} | 读取计划、依赖和执行资格 |
| A | POST /runs（扩展） | 接受 plan_id，配合 Idempotency-Key；202；与旧 generation_id/case_ids 请求互斥 |
| B | POST /preflights | `{plan_id}`，同步有界检查并持久化报告；201 |
| B | POST /preflights/{id}/acknowledgements | review 的可确认 unknown 条件、确认说明；只追加审计 |
| B | POST /runs（扩展） | 计划请求增加 preflight_id；B 阶段新 UI 必需，旧请求在服务端执行等价门禁，不能绕过 |
| B | GET /run-comparisons?left_run_id=…&right_run_id=… | 同基线比较或不兼容原因 |
| C | GET/POST /llm-profiles；PATCH /llm-profiles/{id} | 读取脱敏配置、创建/更新版本；密钥只写不读 |
| C | POST /llm-profiles/{id}/check | 用户显式发起连接检查；提示可能调用模型与费用 |
| C | POST /generations（扩展） | 增加 profile_id，保存有效 Profile 快照与来源 |
| C | POST /generations/{id}/promotions | 从指定 Run/Case/Attempt 的已验证修复派生未批准版本；201 |
| C | POST /run-batches；GET /run-batches/{id}；POST /run-batches/{id}/cancel | 创建有限串行批次、查看和取消；创建返回 202 |

列表参数：`limit` 默认 20、最大 100，`cursor` 为不透明游标；默认 `(created_at DESC, id DESC)` 稳定排序。响应 `{items, next_cursor, snapshot_at, warnings}`；首请求固定快照边界，翻页不混入新建记录。筛选改变则清空 cursor。损坏条目提供标识和警告，不泄露绝对文件路径。

计划与执行示例（目标契约，当前不可直接调用）：

```json
{
  "generation_id": "gen-example",
  "source_run_id": "run-original",
  "selection": {
    "kind": "failed_subset",
    "include_blocked": false,
    "include_not_run": false
  }
}
```

`generation_id` 必须与 source Run 一致；换版本执行应重新选择计划，不再标为原版本复跑。fresh/all/selected 计划可不传 source_run_id。

```http
POST /api/v1/runs
Idempotency-Key: <client-generated-uuid>
Content-Type: application/json

{"plan_id":"plan-example","preflight_id":"preflight-example"}
```

Problem 保留原 code/message/details 等字段，按实际既有类型做加法；目标增加 `retryable`、`action`、`resource_id`、`request_id`。前端保存结构化 Problem，不再只抛 message。action 是受限枚举（例如 open_review / run_preflight / view_active_run / inspect_cleanup），不能执行服务端返回的任意 URL 或代码。

| HTTP | 目标错误码 | 页面行为 |
| --- | --- | --- |
| 422 | EMPTY_SELECTION / INVALID_CASE_IDS / INVALID_DEPENDENCY | 留在选择页并定位字段 |
| 409 | GENERATION_NOT_APPROVED / VERSION_CHANGED / RUN_ACTIVE | 查看审批/差异或当前 Run |
| 409 | IDEMPOTENCY_CONFLICT / PREFLIGHT_EXPIRED / PREFLIGHT_BLOCKED | 保留上下文，重新检查，不自动另建 Run |
| 404 | RESOURCE_NOT_FOUND | 显示历史返回入口，不伪装空列表 |
| 503 | TOOL_UNAVAILABLE / DEVICE_UNAVAILABLE | 展示环境排障和人工重查入口 |

## 7. 存储、幂等与故障恢复

继续使用文件系统：workbooks、generations、runs 原路径不变；新增 `plans/<id>.json`、`preflights/<id>.json`、`idempotency/<key_hash>.json`，C 阶段再加 profiles 和 batches。路径只接受受管 ID，不将客户端路径拼接成读取能力。

历史读模型先扫描轻量元数据并建立可重建内存目录；启动全量加载，进程内写入后刷新。列表不得逐条加载截图、原 Excel 或大日志。需要跨重启加速时再落可重建索引，不让索引成为唯一事实来源；只有性能数据证明必要才引入 SQLite。用于启动恢复的 RunRepository.list_runs 保持 fail-closed，不能为了列表可读而忽略可能仍活动的损坏 Run 并解除运行锁。

幂等创建协议：

1. 前端一次“确认执行”生成一个随机 key，网络超时重发复用此 key；显式“再跑一次”生成新 key。后端按 key 哈希索引，并比较规范化请求哈希。
2. 同 key/同请求返回同 run_id；同 key/不同请求返回 409。幂等重放查找先于“已有活动 Run”的冲突判断，避免自己的重试被误当并发。
3. 持有现有运行锁及短时元数据写锁，先持久化 reservation（key、请求哈希、预留 run_id、状态），再写 Run 和 committed 映射；原子替换并 fsync。多个文件不是事务，不能假装一次 rename 就完成跨文件原子性。
4. 只有映射与 Run 均持久化后才允许启动外部进程。崩溃恢复遇 reserved 无 Run，标记该请求 interrupted，后续相同 key 返回明确冲突/恢复说明，不自动派发；若 Run 已存在，则映射回该 Run 并按原恢复策略收口，不再次执行。
5. 幂等记录至少保留至关联 Run 生命周期结束；V2 不实现自动历史删除，因此不提前清除 key。清理与保留策略以后单独设计。

绝对导出目录继续支持，但新导出名包含 run_id，并以不覆盖策略创建；证据读取只能通过已登记 Artifact ID。创建文件失败必须呈现 export_status/error，不把运行结果 Excel 的缺失解释为执行通过。

## 8. 前端交互与实时更新

建议页面路由：`/workbooks`、`/workbooks/:id`、`/generations/:id`、`/runs`、`/runs/:id`、`/settings`。兼容旧 `?run=<id>` 并规范化到 Run 详情。URL 保存资源 ID、筛选和分页上下文，不保存密钥或工作簿内容。

所有详情按路由 ID 请求服务器恢复，不依赖上一页 useState。快速切换时 AbortController 取消旧请求，并用资源 ID/请求序号校验返回；取消只是性能优化，不能作为防止旧响应覆盖的唯一保障。未保存选择在离开前提示；执行确认以服务端 plan 为准。

详情优先消费既有 `/runs/{id}/events` SSE，游标使用已有 event_id/sequence，按 Run+sequence 去重。重连传 Last-Event-ID 或 after；事件只触发类型化状态更新/必要的详情拉取。运行中增量请求当前 Case 详情，不等到全部结束才展示。

SSE 异常后退避重连（1/2/5/10 秒上限），降级为带退避的 REST 轮询；同一 Run 只保留一个活动通道，隐藏页降频。显示“连接中断，最后更新于…”，不能将旧画面当实时状态。终态且 export_status 非 pending 后停止自动订阅；终态先到、导出尚未收口时继续有界低频查询并提供手动刷新。

UI 不据“API 在线”推断“设备可操作”。操作按钮派生自权限/状态/计划校验结果；后端重复校验是最后门禁。运行详情把 business_result 与 cleanup_result 分开，并对 pending/unknown 使用明确文字。

## 9. V2-C 增量设计

### 9.1 LLM 配置

规则模式为无需密钥的可选策略。LLM Profile 引用服务端 secret_ref，首次实现优先复用环境变量/本机受限文件；前端只写新密钥，不回读、不写 localStorage，不把密钥放进生成 provenance。Profile 修改产生 revision，已生成版本的快照不变。

连接测试由用户主动触发并显示调用范围；日志脱敏，超时有界；生成后仍走 JSON Schema、IR 语义校验、编译、Maestro check-syntax 和审批。不得因用户配置任意 base_url 就默认允许将本地文件/凭据发送到该地址，界面明确数据发送目标和范围。

### 9.2 修复提升

请求必须指向原 Generation 下真实存在的 Run/Case/Attempt 及修复证据。校验 repair 类型在既有限制内、修复后验证成功、源指纹匹配，再将定位差异映射为 IR patch。共享 Fixture 改动展开所有消费者影响。复制完整 Generation 为新 ID，更新受影响 IR 并重编译，所有需审批 Flow 的批准状态清空，人工确认后才 ready。未变化 Flow 可展示历史批准参考，但不得凭参考绕过新版本批准门禁。

若修复仅在当前运行数据/页面下有效，必须在差异页提示适用条件；提升不保证任意环境有效，也不默认修改原 Excel 的步骤描述。

### 9.3 有限批量与耗时

RunBatch 状态为 queued / running / stopping / completed / stopped / failed。次数范围 1～20，不提供无限选项；使用同一批准版本和选择快照，每一轮创建独立 Run、独立 Fixture 生命周期并重新预检。单 Run 锁仍是最终防并发门禁；等待外部 Run 时显示占用，不绕过锁。

任一子 Run 非 COMPLETED、清理非 passed、导出失败或预检受阻即停止后续轮次并记录原因。取消批次阻止派发，并调用当前子 Run 原取消协议。服务重启后批次停止等待人工新建，不自动恢复派发。

耗时使用单进程单调时钟计阶段间隔，UTC 时间用于跨进程展示；缺失采样记 unknown，不算成 0。共享 Fixture 耗时单独统计、列出消费者，不能重复加到每个 Case 后再相加。展示 LLM、Maestro、Fixture/诊断耗时，避免未经测量归因“模拟器慢”。

## 10. 兼容、测试与实施顺序

| 阶段 | 实施顺序 | 验证映射 |
| --- | --- | --- |
| A1 | 固定接口 DTO、历史读模型、分页和旧数据读取 | R01/R02；AC01、AC04 |
| A2 | 计划/指纹、失败集合、Fixture 闭包、幂等与崩溃窗口 | R03/R04/R07；AC02、AC03 |
| A3 | 页面路由、历史/审批/执行确认、运行详情与结构化错误 | R01～R07；AC01～AC04 |
| B1 | 预检、StateContract、清理风险和刚执行前再校验 | R08～R10；AC05 |
| B2 | 同基线比较和稳定复跑记录 | R11；AC06 |
| C1 | Profile 与生成 provenance | R12；AC07 |
| C2 | 修复提升/IR 一致性与再审批 | R13；AC08 |
| C3 | 耗时和有限串行批次 | R14；AC09 |

关键自动化包括：历史损坏/缺字段、游标稳定性、空选择/未知 Case、共享 Fixture 子集、终态失败集合、幂等并发/崩溃窗口、旧协议兼容、过期预检与设备变化、未知清理、浏览器刷新/迟到响应/SSE 重连、不可变文件哈希、密钥脱敏、批次停止。前端构建通过不能替代这些交互测试。

旧数据读取使用可选字段/default，不批量重写既有证据。老版本没有 fingerprint/provenance 的情况必须显示“历史未记录”，而不是自动宣称与新版本可比。新 API 在特性开关后逐步启用；禁用 V2 页面仍能查看原 Run，禁止回滚时删除新证据。若出现不可兼容字段修改，先升级契约/迁移方案再实施，不在同一 API 下悄悄改义。

每阶段采用 [需求文档第 7 节](requirements-v2.md#7-交付里程碑与验收) 的一次集中验收和有界复验规则。文档本次提交只检查链接、术语、需求—设计—验收映射及 Git 范围，不运行模拟器验收、不修改既有 M4 发布结论。
