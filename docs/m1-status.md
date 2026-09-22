# M1 离线生成闭环验收状态

## 结论

| 项目 | 结果 |
| --- | --- |
| 里程碑 | M1 离线生成闭环 |
| 状态 | **Accepted** |
| 验收日期 | 2026-09-17 |
| 验收范围 | Excel 导入校验、Fixture DAG、Flow IR、LLM 适配边界、确定性 YAML、语法修复上限、人工/无人值守生成模式、Web 预览审批 |
| 自动化回归 | 33 passed |
| 前端构建 | TypeScript + Vite production build passed |
| P0 / Blocker | 0 个未关闭 |

M1-AC-01～05 全部通过。基线 Excel 已完成 `Excel → 校验 → Fixture 计划 → Flow IR → YAML → maestro check-syntax → 人工确认` 的真实离线闭环。M1 不连接设备、不执行业务用例；Android 模拟器执行属于 M2。

## 验收环境和输入

| 项目 | 实际值 |
| --- | --- |
| 平台 | macOS，本地受控环境 |
| Maestro CLI | 2.10.0 |
| Python | 3.11.0 |
| Node.js / npm | 25.7.0 / 11.10.1 |
| 输入文件 | `Maestro_pytest_LLM_APP_测试用例模板.xlsx` |
| 源文件 SHA-256 | `e112ec7a17357e560c5199430c61364c43b8906f479f82b2f34b444b69f48480` |
| 最终验收 Workbook ID | `6401b7eaa4b5486780af5fa2e5662257` |
| 最终验收 Generation ID | `d2ac87b3278d41a6b770513706215f88` |
| Web 验收 Generation ID | `2b50bad5821c42f4ab24bec9cced5625` |

源文件在验收前后哈希一致。系统只在运行目录保存不可变副本、快照和生成产物，没有覆盖用户源 Excel。

## 验收步骤、预期结果、证据和阻断规则

| ID | 验收步骤 | 预期结果 | 实际结果与必需证据 | 阻断规则验证 | 状态 |
| --- | --- | --- | --- | --- | --- |
| M1-AC-01 | 记录源哈希；上传基线 Excel；读取摘要和校验报告；再次计算源哈希 | 1 个启用 Case、2 个启用 Fixture、19 个 Config；0 error、0 warning；哈希不变 | 验收摘要记录 `1/2/19/0/0`，哈希前后一致；快照保留 `source_row` | Sheet/表头、必填、类型、枚举或哈希不符即失败 | PASS |
| M1-AC-02 | 独立注入必填缺失、非法枚举、重复 ID、中文分隔符、不可观测预期、配置约束错误；尝试生成 | 每个 error 精确定位 Sheet/行/列；非法工作簿生成返回 409 | 覆盖 `Cases!C6`、`Cases!F6`、`Cases!A7`、`Cases!D6`、`Cases!J6`、`Config!B20`；API 返回 `WORKBOOK_VALIDATION_FAILED` | 任一 error 禁止创建 Generation；warning 不能被批量自动确认 | PASS |
| M1-AC-03 | 验证直接/间接依赖、去重、同层排序、缺失依赖、循环和基线闭包 | 基线严格为 `FX-APP-RESET → FX-LOGIN-READY`，各一次；缺失/循环可定位 | `fixture_plans.TC-HOME-001` 与预期一致；缺失依赖定位 `Fixtures!F7`；DAG 单元测试通过 | 缺失、停用依赖、跨阶段依赖、自依赖、循环均阻断 | PASS |
| M1-AC-04 | 验证严格 JSON Schema LLM 请求、IR 身份校验、确定性编译、语法修复上下限；对 3 个真实 Flow 运行 Maestro | LLM 只产出 IR；相同 IR 生成相同 YAML；修复不覆盖 initial，次数受 Config 限制；3 个 Flow 语法均为 OK | OpenAI-compatible 适配器覆盖结构化输出、身份漂移和超时；33 项测试通过；3 个 Flow 均 `syntax_attempts=1`、`syntax_repairs=0`、`syntax_output=OK` | IR/身份/白名单失败、编译不确定或修复耗尽均进入 `failed`，禁止批准 | PASS |
| M1-AC-05 | 浏览器上传；切换人工/无人值守；review 生成；逐个检查映射与 YAML；批量确认；检查 390×844 | 显示摘要、DAG、原文、命令、选择器、断言、完整 YAML；review 从 0/3 到 3/3；移动端无横向溢出 | Web 最终状态为 `ready`、approved=3；两种模式可切换；控制台 error/warn=0；桌面与移动截图已保存 | error、语法失败、未处理 warning 或未批准 Flow 不能进入 review `ready`；批量确认排除 warning | PASS |

详细量化口径及全里程碑门禁见 `docs/milestone-acceptance-v1.md`。

## 生成结果

| Flow | 类型 | 映射结果 | Maestro 语法 | YAML SHA-256 |
| --- | --- | --- | --- | --- |
| `FX-APP-RESET` | Fixture | `launchApp(clearState=true, stopApp=true)` + `assertVisible("同意并接受")` | OK | `a9d359f81661e46ca4ef5f7f476633fd46e1fcf744294a731354aa3eef447435` |
| `FX-LOGIN-READY` | Fixture | 7 个操作命令 + `assertVisible("立即生成")` | OK | `b967b5d788b90746414f8737142ebbdb68833e62529dcd64c08ebfc339d0309b` |
| `TC-HOME-001` | Case | 3 个 `tapOn` + `assertVisible("尽情发挥")` | OK | `18dcad78a4b371850cf9871b7b2d904e25225df94ca82e6e8043089758437537` |

所有 YAML 由 Flow IR 确定性编译，未直接执行 LLM 返回的 YAML。Maestro 映射遵循官方命令形式：`tapOn`、`inputText`、`assertVisible`、`launchApp` 等。

## 阻断规则总表

1. 工作簿存在任何 `severity=error`：Generation 创建返回 409。
2. Fixture 引用缺失、停用、阶段错误、自依赖或循环：阻断生成。
3. LLM 返回不符合 Flow IR Schema、`flow_id/app_id` 漂移或出现白名单外命令：Generation 失败。
4. `maestro check-syntax` 失败：只允许不改变业务命令/断言的确定性结构修复；达到 `max_syntax_repair` 后失败。
5. 人工模式有未批准 Flow 或未人工处理 warning：保持 `awaiting_review`；不得进入 `ready`。
6. 语法失败的 Flow 永远不可批准；无人值守模式也不能绕过 error。
7. 源 Excel 哈希变化、验收证据缺失或存在未关闭 P0/Blocker：M1 不得签收。

## 证据索引

- `runtime/m1-acceptance-20260917/evidence/summary.json`：最终真实验收结构化摘要。
- `runtime/m1-acceptance-20260917/pytest-junit.xml`：33 项自动化回归 JUnit。
- `runtime/m1-acceptance-20260917/runtime-final/generations/d2ac87b3278d41a6b770513706215f88/`：最终 Generation、IR、初始/最终 YAML。
- `runtime/m1-acceptance-20260917/ui-ready-final.png`：桌面端 review 3/3 截图。
- `runtime/m1-acceptance-20260917/ui-mobile-final.png`：390×844 响应式截图。
- `runtime/generations/2b50bad5821c42f4ab24bec9cced5625/generation.json`：浏览器验收最终状态。

## LLM 环境说明

本次未提供外部 LLM Base URL、模型和 Key，因此真实基线使用 `rule-based-v1` 离线翻译器，以固定中文步骤语法完成可重复验收。OpenAI-compatible 适配器已实现并由自动化测试验证：Base URL、模型、Key、超时、严格 JSON Schema、Flow IR 校验、身份约束和错误上报。接入真实 LLM 只需配置环境变量，不改变 IR、编译或审批契约；是否调用第三方模型不影响 M1 本地闭环签收。

## M1 收束

- 契约：OpenAPI 与 Flow IR Schema 可解析，M1 响应字段已与实现对齐。
- 后端：Excel、DAG、翻译、编译、语法修复、持久化、审批 API 已完成。
- 前端：导入、校验、模式选择、映射预览、单个/批量审批、移动端布局已完成。
- 质量：33/33 测试通过，生产构建通过，真实 Maestro 语法检查通过。
- 交接：M2 可直接消费状态为 `ready` 的 Generation，开始 pytest Fixture 生命周期和 Android 模拟器实际执行。
