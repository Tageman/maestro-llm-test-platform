# 一期五里程碑验收基线

## 文档信息

| 项目 | 内容 |
| --- | --- |
| 版本 | V1.3 |
| 状态 | Frozen |
| 冻结日期 | 2026-09-22（M4 验收口径细化） |
| 覆盖范围 | M0～M4 |
| 需求验收基线 | 正式需求 AC-001～AC-013 |

本文档把研发计划中的“任务完成标准、退出条件和质量门禁”统一为可执行、可留证、可阻断的里程碑验收标准。V1.3 在 V1.2 基础上细化 M4 的步骤、预期、证据和阻断规则；不改变正式需求、冻结技术设计或里程碑范围。M4 尚未执行验收，不得把规划状态写为通过。里程碑范围或验收口径变化时必须升级版本并记录影响。

## 1. 通用验收规则

1. 所有 P0 验收项必须通过；任一 P0 项失败时，里程碑不得签收。
2. 验收结果必须包含执行日期、环境版本、输入版本、实际结果和证据路径。
3. 自动化检查以退出码、JUnit、结构化摘要或哈希为主要证据，不以口头确认替代。
4. 人工界面检查必须留存截图或录屏，并记录浏览器、分辨率和检查人。
5. 已知缺陷必须分级。不得遗留未关闭的 Blocker/P0；P1 只有在 M4 可由产品负责人书面豁免。
6. 每个里程碑通过后冻结对应契约；破坏性变更必须回归受影响里程碑。
7. 验收环境中 Maestro Studio、Maestro CLI 和 Maestro MCP 不得并发控制同一模拟器；平台负责的 CLI/MCP 调用必须串行。

## 2. M0 技术基线

| ID | 验收步骤 | 预期结果 | 必需证据 |
| --- | --- | --- | --- |
| M0-AC-01 | 校验技术设计、OpenAPI 和 Flow IR Schema | 五项技术设计为 Frozen V1；OpenAPI 3.1 和 JSON Schema 校验通过 | 文档版本、校验输出 |
| M0-AC-02 | 执行 `make dev` 并访问前后端 | 前端入口与 `/api/v1/health` 均返回 HTTP 200；停止命令后无遗留服务 | 启停日志、健康响应 |
| M0-AC-03 | 探测本机工具、设备和目标包 | Maestro、ADB、Emulator、MCP 可用；唯一设备为 `emulator-5554`；`Pixel_5` 和 `aippt.com.mm` 可识别 | Capability Report |
| M0-AC-04 | 语法检查并执行最小启动 Flow | `check-syntax` 通过；真实模拟器执行 1/1 通过；JUnit failures=0 | Flow、CLI 日志、JUnit |
| M0-AC-05 | 由后端 MCP 客户端完成初始化、设备枚举、层级和截图 | MCP 进程可启动、请求、超时控制和关闭；层级及图片可读取 | server-info、tools、devices、hierarchy、截图 |
| M0-AC-06 | 执行后端测试与前端构建 | 测试全部通过；前端生产构建通过；不得有未关闭 P0 缺陷 | pytest 与构建日志 |

M0 通过门禁：M0-AC-01～06 全部通过，正常执行路径固定为 Maestro CLI，诊断路径固定为 Maestro MCP。

## 3. M1 离线生成闭环

| ID / 映射 | 验收步骤 | 预期结果 | 必需证据 | 阻断规则 |
| --- | --- | --- | --- | --- |
| M1-AC-01 / AC-001 | 1. 记录源 Excel SHA-256；2. 通过 `POST /api/v1/workbooks` 导入；3. 读取摘要与校验接口；4. 再次计算源文件哈希 | 状态为 `valid`；识别 1 条启用 Case、2 个启用 Fixture、19 个 Config；errors=0、warnings=0；源哈希前后一致；持久化快照保留来源行号 | 导入 API 响应、`snapshot.json`、验收摘要中的前后哈希 | Sheet/表头不符、必填缺失、类型/枚举错误、源文件发生变化或数量不符，立即阻断生成 |
| M1-AC-02 / AC-001 | 分别注入必填缺失、非法枚举、重复 ID、中文分隔符、不可观测预期、配置冲突；调用校验接口后尝试创建生成任务 | 每个问题均产生 `severity=error`，包含 Sheet、行、列和错误码；生成入口返回 HTTP 409 与 `WORKBOOK_VALIDATION_FAILED` | 参数化校验测试、错误样本、pytest JUnit、409 接口断言 | 存在任一 error 时禁止创建 Generation；warning 不自动批准，必须进入人工确认 |
| M1-AC-03 / AC-002 | 1. 构造直接与间接依赖；2. 验证相同依赖去重；3. 注入缺失依赖和循环；4. 解析基线 Case 夹具闭包 | 拓扑排序稳定；基线顺序严格为 `FX-APP-RESET → FX-LOGIN-READY` 且各出现一次；缺失依赖与循环均可定位 | `fixture_plans` 快照、DAG 单元测试、导入校验报告 | 缺失、跨阶段非法依赖或依赖环均阻断生成；不得以 Excel 行顺序掩盖依赖错误 |
| M1-AC-04 / AC-003、004 | 1. 验证 LLM 请求启用严格 JSON Schema 且不接收 YAML；2. 对返回结果做 Flow IR Schema 与 `flow_id/app_id` 身份校验；3. 将同一 IR 编译两次；4. 对 3 个基线 Flow 执行真实 `maestro check-syntax`；5. 注入语法失败并验证修复成功与达到上限两条路径 | LLM 边界只产出 Flow IR；身份漂移被拒绝；两次 YAML 字节完全一致；`FX-APP-RESET`、`FX-LOGIN-READY`、`TC-HOME-001` 语法检查 exit=0；修复不改变初始文件，次数不超过 `max_syntax_repair`，成功后产生人工复核 warning，耗尽上限后失败 | LLM 适配器单元测试、语法修复上下限测试、`detail.json`、初始/最终 YAML、YAML SHA-256、真实语法输出 | IR Schema/身份校验失败、出现白名单外命令、编译不确定或达到语法修复上限仍失败，Generation 进入 `failed` 且不得批准 |
| M1-AC-05 / AC-005 | 1. 在 Web 工作台上传基线 Excel；2. 发起 review 生成；3. 逐个切换 3 个 Flow；4. 检查原文→命令、选择器、断言、IR、完整 YAML；5. 单个批准或批量批准 | 页面同时展示导入摘要、校验结果、夹具计划、Flow 队列和映射详情；未批准时为 `awaiting_review`；3 个语法通过的 Flow 批准后为 `ready`、approved=3 | UI 截图、浏览器检查记录、生成详情接口、最终 `generation.json` | 有 error、语法失败、未处理 warning 或任一未批准 Flow 时不得进入 `ready`；批量批准自动排除带 warning 的 Flow |

M1 通过门禁：M1-AC-01～05 全部通过，基线 Excel 可稳定完成离线生成，所有生成 YAML 语法检查通过。

## 4. M2 真实执行 MVP

| ID / 映射 | 验收步骤 | 预期结果 | 必需证据 | 阻断规则 |
| --- | --- | --- | --- | --- |
| M2-AC-01 / AC-007 | 1. 校验 Maestro、ADB；2. 枚举在线 Android 模拟器；3. 按 `android_device_id` 或唯一在线规则选择；4. 无在线设备时检查并启动 `avd_name`；5. 等待 `sys.boot_completed=1`；6. 检查或安装 `app_id` | 基线环境选择且仅选择 `emulator-5554`；AVD 名为 `Pixel_5`；设备状态为 `device`；`aippt.com.mm` 已安装；设备准备结果持久化 | 设备准备 JSON、ADB/AVD/包检查日志、状态事件 | 多设备未指定、指定设备离线/非模拟器、AVD 不存在、启动超时、ADB 不可用、包缺失或 APK 安装失败均在执行前阻断；Maestro Studio 与 CLI/MCP 并发控制时阻断 |
| M2-AC-02 / AC-008 | 1. 生成 pytest 文件和原 ID 元数据；2. `--collect-only`；3. 执行前置成功、Case 失败、前置失败三类测试；4. 核对后置 Fixture；5. 检查依赖去重和作用域 | 启用 Case 与 pytest item 1:1；基线只收集 `TC-HOME-001`；前置顺序为 `FX-APP-RESET → FX-LOGIN-READY` 且各一次；前置失败时 Case 主体不运行；Case 失败/异常和部分前置成功后均执行已注册清理；后置按逆序 | 生成的 pytest、collection 文本、三路径 JUnit、Flow trace JSONL、生命周期单元/集成测试 | 收集数/ID 不一致、重复 Fixture、Case 在前置失败后仍运行、Case 失败后未清理或清理顺序错误，任一项阻断 |
| M2-AC-03 / AC-006、007 | 1. 从 review `ready` Generation 创建 Run；2. 从 unattended `ready` Generation 创建 Run；3. 订阅 SSE；4. 刷新并重新读取 Run；5. 验证状态迁移 | 两种模式均执行 `Fixture → Case → Cleanup`；状态只按 Frozen 图迁移；事件序号单调且可用 `Last-Event-ID` 续传；刷新/后端读取不把终态误报为运行中 | `run.json`、事件文件、SSE 抓取、API 响应、状态机测试、UI 截图 | Generation 非 `ready`、review 未全批准、已有活动 Run、非法状态迁移或持久化失败时阻断；不得绕过 pytest 直接编排业务 Flow |
| M2-AC-04 / AC-006～008 | 1. 对冻结基线连续创建 3 个独立 Run；2. 每次确认设备与包；3. 由 pytest 执行真实链；4. 对比三次顺序和报告 | 三次均在 `Pixel_5/emulator-5554` 完成；每次链顺序一致；pytest 和 Maestro JUnit failures=0；Run 终态为 `COMPLETED`；每次有独立目录且无跨 Run 污染 | 三个 Run ID、各自 `run.json`、pytest JUnit、Maestro JUnit、trace、stdout/stderr、产物清单 | 任一次失败、顺序漂移、Fixture 重复、使用错误设备、证据缺失或源 Excel 哈希变化时不得签收 M2 |
| M2-AC-05 / AC-006 | 1. 检查所有外部命令参数；2. 注入超时；3. 注入取消；4. 生成超量输出；5. 验证 `pytest_workers` | 参数数组传递且 `shell=False`；pytest/子 Maestro 位于独立进程组；超时返回明确类型；取消先 TERM 后 KILL；控制台只保留配置上限、完整输出写文件；`pytest_workers=1` | 进程集成测试、取消/超时日志、输出文件与截断标记、Config 快照 | shell 拼接、worker>1、无法终止子进程、无输出上限、超时/取消后遗留活动进程均阻断 |

M2 通过门禁：M2-AC-01～05 全部通过，形成可执行 MVP；自动修复和结果 Excel 不作为 M2 门禁。

## 5. M3 无人值守闭环

| ID / 映射 | 验收步骤 | 预期结果 | 必需证据 | 阻断规则 |
| --- | --- | --- | --- | --- |
| M3-AC-01 / AC-009～011 | 1. 分别注入 YAML 语法、文本定位、业务断言、设备/进程环境、Fixture 生命周期、执行超时六类失败；2. 使用同一分类器重复判定；3. 注入未知错误；4. 核对 Case/Attempt 状态与失败类型 | 六类样本分别稳定映射为 `YAML_SYNTAX`、`LOCATOR`、`ASSERTION`、`ENVIRONMENT`、`FIXTURE`、`TIMEOUT`；同一输入结果确定；未知错误为 `UNKNOWN`；只有 `LOCATOR` 可进入自动修复 | 六类及 UNKNOWN 参数化测试、分类输入/输出 JSON、pytest JUnit、Attempt 记录 | 任一类型误判、分类不确定、UNKNOWN 或非定位失败进入自动修复，立即阻断；错误证据不足时不得猜测失败类型 |
| M3-AC-02 / AC-009 | 1. 复用 M2 中“点击【确认设置】”但页面实际为“确认设置(1)”的真实失败样本；2. 进入 `DIAGNOSING` 后串行启动 Maestro MCP 并绑定同一 `device_id`；3. 调用 `inspect_screen` 和 `take_screenshot`；4. 从层级证据提取唯一文本候选；5. 进入 `REPAIRING`，仅替换失败 `tapOn` 的 SelectorIR；6. 保存修复前后 YAML 和统一 diff，执行 `check-syntax`；7. 重新由 pytest 执行完整链 | MCP 层级与截图均落盘；候选有页面证据且唯一；补丁只把失败选择器从 `确认设置` 改为字面值 `确认设置(1)`，编译后正确转义括号；命令数量、类型、顺序、输入数据及所有断言不变；不产生坐标；修复后真实重试通过 | M2 原始失败 Run/日志、MCP server/tool 响应、层级 JSON、PNG 截图、RepairRecord、before/after YAML、diff、语法检查输出、重试 pytest/Maestro 报告、状态事件 | MCP 不可用或未绑定目标设备、层级/截图任一缺失、候选为零或不唯一、候选无证据、补丁触碰失败操作以外字段、引入坐标、修改断言、语法检查失败或未通过 pytest 重试，均阻断自动修复和 M3 签收 |
| M3-AC-03 / AC-010 | 1. 构造可稳定复现的真实 `assertVisible`/`assertNotVisible` 失败；2. 执行并分类；3. 比较初始与最终 IR/YAML；4. 检查 RepairRecord、Attempt 和终态 | 分类为 `ASSERTION`；修复次数为 0；不创建断言补丁，不删除、替换或弱化预期；Case 为 `FAILED`，Run 为 `COMPLETED_WITH_FAILURES`，失败截图、日志和报告保留 | 真实失败 JUnit/日志/截图、初始与最终 YAML 哈希、零 RepairRecord/零 diff 证明、Case/Run JSON | 断言失败进入 `REPAIRING`、断言目标或命令发生任何变化、Case 被误报为通过、失败证据缺失，任一项阻断 |
| M3-AC-04 / AC-011 | 1. 连续制造可修复与不可修复定位失败；2. 核对首次执行加重试的 Attempt 编号；3. 检查每次 trace 的前置 Fixture；4. 验证 `max_locator_repair=2`、`max_total_run_attempts=3`；5. 在当前 Case 达上限后观察后续独立 Case | Attempt 严格为 a1～a3；修复最多 2 次、总执行最多 3 次；每次重试均重新执行完整 `FX-APP-RESET → FX-LOGIN-READY → Case → Cleanup`，同一 Attempt 内依赖不重复；达到上限后当前 Case 失败且后续独立 Case 继续；无无限循环 | 每次 Attempt 独立 trace/JUnit/Maestro 报告/日志、RepairRecord 列表、事件流、上限与多 Case 集成测试 | 超过任一上限、重试绕过 pytest、未重跑完整前置链、同一 Attempt 重复 Fixture、当前 Case 失败阻止配置允许的后续独立 Case、进程或状态机循环，任一项阻断 |
| M3-AC-05 / AC-012 | 1. 执行前记录源 Excel SHA-256；2. 结束后在 `run/result/` 生成带时间戳副本；3. 按源行写入 Case 的生成状态、执行状态、执行次数、自动修复次数、失败步骤/类型/原因、初始/最终 YAML、报告、证据路径、开始/结束/耗时；4. 写临时文件并重读校验；5. 再次计算源文件 SHA-256 | 源 Excel 字节与哈希完全不变；仅产生一个命名含时间戳的结果工作簿；字段写入正确源行，路径位于对应 Run 且可访问；原子改名后可由 openpyxl 重读并与 Run 汇总一致；即使业务失败也输出结果副本 | 源文件前后 SHA-256、结果工作簿、写回 manifest/校验日志、自动化字段断言、API 下载响应 | 原文件被修改、覆盖既有结果、写错行/字段、结果不可重读、字段与 Run 不一致、路径逃逸 Run 目录或写回失败被静默忽略，任一项阻断；写回失败必须使 Run 为 `FAILED` 而非伪完成 |
| M3-AC-06 / AC-013 | 1. 从 Run 总览进入 Case 详情；2. 展开每次 Attempt 和 Repair；3. 下载结果 Excel 与至少一个受控 Artifact；4. 依据 manifest 逐项校验 SHA-256；5. 刷新页面后重新读取终态 | 每次尝试分别保留 pytest JUnit、Maestro JUnit/HTML（Maestro 实际可生成的格式）、完整日志、层级/截图、初始/最终 YAML 和 diff；统一摘要与 Artifact manifest 可由 Run→Case→Attempt→Repair 追溯；下载接口拒绝未知 ID 和路径穿越；UI 展示失败原因、修复前后选择器、证据链接和结果文件，刷新后终态不丢失 | Run 目录树、`summary.json`、Artifact manifest 与哈希校验、API 200/404 安全测试、前端生产构建、结果页截图 | 任一必需产物缺失或被后续 Attempt 覆盖、manifest 哈希不符、Case ID 无法追溯、下载可路径穿越、UI 无法访问失败/修复/结果证据，任一项阻断 |

M3 通过门禁：M3-AC-01～06 全部通过，AC-009～AC-013 均有自动化证据，达到一期功能完整状态。

## 6. M4 验收发布（规划基线，待执行）

验收顺序为契约核对与环境锁定 → AC-001～013 追溯与真实基线 Run → 自动化质量 → 故障注入 → 恢复与独立操作 → 发布裁决。所有注入故障使用隔离工作簿/Run，不覆盖冻结基线或历史 M0～M3 证据。`docs/m4-plan.md` 记录研发拆分和待关闭风险；本节是最终签收门禁。

| ID / 映射 | 验收步骤 | 预期结果 | 必需证据 | 阻断规则 |
| --- | --- | --- | --- | --- |
| M4-AC-01 / AC-001～013 | 1. 固定代码版本、冻结 Excel SHA-256、AVD/设备/包和工具版本；2. 逐条将 AC-001～013 映射到自动测试、真实 Run 或人工检查；3. 用冻结基线从导入、校验、Fixture DAG、IR/YAML、语法检查、review 与 unattended 两种模式，走到 pytest/Maestro Android 模拟器执行、MCP 定位修复、结果 Excel 与报告；4. 注入带 warning 的无人值守生成，复核人工确认门禁；5. 复核源哈希 | 13 项均有本版本 PASS 证据；review 与 unattended 均能建立并完成独立 Run；基线 Case `PASSED`、Run `COMPLETED`；带 warning 的 Flow 不得无人值守自动批准；Fixture 顺序及各次重试一致；结果副本可读，源 Excel 哈希不变；Excel Config 与实际执行契约一致 | 带 AC ID、构建/输入/环境版本的追溯矩阵；导入/Generation/Run ID；warning 门禁测试与 API/UI 记录；pytest 与 Maestro JUnit、trace、MCP 证据、结果 Excel、报告、前后 SHA-256 | 任一 AC 缺证或失败、带 warning Flow 自动批准、设备与包不符、源文件变化、Fixture/断言被静默改写、配置项与实际行为不一致时阻断；不得用 M0～M3 的旧 PASS 直接替代 M4 本版本回归 |
| M4-AC-02 / 全量质量 | 1. 在干净安装环境运行后端全量测试与前端生产构建；2. 使用分支覆盖率统计核心纯逻辑（导入校验、Fixture DAG、IR 编译/修复门禁、失败分类、Run 状态机和结果聚合/写回）；3. 对 Maestro、ADB/Emulator、MCP、LLM、文件持久化等外部适配器逐项测成功、超时、不可用、异常输出 | 核心纯逻辑合并分支覆盖率 ≥85%；列出的各适配器四类分支均有可复现断言；测试、静态/构建检查全部通过，无跳过而未说明的关键门禁 | 覆盖范围清单、branch coverage 机器报告、pytest JUnit/退出码、适配器用例矩阵、前端构建日志与版本 | 覆盖率不足、以语句覆盖率冒充分支覆盖率、关键适配器缺任一分支、测试失败、构建失败或仅在开发机缓存下通过，阻断 |
| M4-AC-03 / AC-009～011 | 1. 隔离注入 `YAML_SYNTAX`、`LOCATOR`、`ASSERTION`、`ENVIRONMENT`、`FIXTURE`、`TIMEOUT`，另测 `UNKNOWN`；2. 对 LOCATOR 测唯一候选成功、零/多候选、MCP 不可用、错误设备及 `max_locator_repair`/`max_total_run_attempts` 上限；3. 模拟设备/进程断连；4. 逐次核对状态、清理、重试和补丁 diff | 分类确定；仅有页面层级和截图支持的唯一文本定位候选可改失败操作 Selector；断言、数据、命令顺序不变；不可修复分支停在上限内并留证；断连后不得无限重试或误报 PASS，已建立清理义务得到执行或明确记载无法清理 | 故障注入输入/输出、Attempt/Repair JSON、MCP 层级/截图、before/after YAML 与 diff、各次 JUnit/trace、进程与设备日志、上限断言 | 任一非定位失败进入修复、无证据修改 Selector、断言被弱化、超过上限、未重跑完整 pytest Fixture 链、断连后遗留后台进程或假成功，阻断 |
| M4-AC-04 / 持久化恢复 | 1. 对已完成 Run 先刷新页面、再重启后端并按 Run ID 读取；2. 分别在设备准备、运行、诊断/修复、结果写回阶段注入后端退出；3. 重启后审计 `run.json`、事件、子进程与产物；4. 对非终态执行恢复检查并选择安全终止或经证明的显式恢复，新 Run 才能再次执行外部操作 | 已完成 Run 的终态、结果 Excel、报告和证据下载在刷新/重启后不丢；非终态不会自动重放 Maestro/pytest 或变成假 `COMPLETED`，最终可追溯地进入安全终态或经显式恢复继续；无孤儿子进程和重复副作用 | 每阶段故障注入记录、重启前后 Run/Event/Artifact 快照、进程列表、API/UI 截图、恢复决策及测试结果 | 终态丢失、非终态永久悬挂、未记录而自动重放、重复执行/写回、孤儿进程、状态机非法跳转或证据损坏，阻断 |
| M4-AC-05 / 交付可用性 | 1. 非开发人员在全新本地环境仅按 `docs/user-guide-v1.md` 安装依赖、设置环境/模拟器/包；2. 填写或复制三 Sheet 基线，解释各字段及 Fixture 依赖；3. 完成上传、校验、人工预览确认、真实执行、结果下载和一次排障；4. 记录问题并复走 | 操作者不借助开发人员隐性知识完成基线 Run；能辨认 warning/error、`COMPLETED` 与 `COMPLETED_WITH_FAILURES`、源 Excel 与结果副本；文档命令/字段/截图入口与产品一致，已知功能限制醒目标明 | 操作人、环境、时间、逐步记录、反馈与修订、屏幕证据、Run/结果文件、文档评审签字 | 关键步骤需要口头补充、字段说明与当前实现矛盾、不能独立运行/下载/排障、未说明配置限制或操作人未签收，阻断 |
| M4-AC-06 / 正式发布 | 1. 从固定版本与锁文件在干净环境复现安装/构建/测试；2. 核对交付清单、版本与校验和；3. 复核源 Excel SHA-256、AC 门禁及缺陷等级；4. 由产品/测试负责人签署发布裁决 | 发布包可复现；源 Excel 未改；M4-AC-01～05 均 PASS；Blocker/P0 为零；P1 全部关闭或逐项取得产品负责人书面豁免；发布版本与证据版本一致 | 复现日志、发布包/版本标签/哈希、交付物清单、缺陷台账与 P1 豁免、签署记录 | 任一前置门禁失败、未复现、缺少清单/签署、遗留 Blocker/P0、P1 无书面豁免或源哈希变化，禁止标记 M4 `ACCEPTED` 和一期正式发布 |

M4 通过门禁：M4-AC-01～06 必须全部为 PASS，且不存在未关闭 Blocker/P0；验收记录依第 7 节逐项填写。M4 规划文档和使用说明的完成不等于 M4 通过。

## 7. 验收记录格式

每次里程碑验收使用以下字段：

- `milestone`、`acceptance_id`、`status: PASS | FAIL | BLOCKED`
- `tested_at`、`tester`、`environment`
- `input_version`、`build_version`、`actual_result`
- `evidence_paths`、`defect_ids`、`note`
