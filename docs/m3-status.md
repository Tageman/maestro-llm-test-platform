# M3 MCP 自动诊断、受控修复与结果闭环状态

## 结论

| 项目 | 结果 |
| --- | --- |
| 里程碑 | M3 无人值守诊断、修复、重试与结果回写 |
| 实现状态 | **Complete** |
| 正式验收状态 | **ACCEPTED** |
| 状态日期 | 2026-09-22（真实模拟器 Run 于 2026-09-20 完成，最终回归与 UI 走查于 2026-09-22 收束） |
| 自动化回归 | 68 passed |
| 前端构建 | TypeScript + Vite production build passed |
| 真实 Android 验收 | 定位修复成功分支 + 断言保护失败分支均完成 |
| Blocker | 无 |

M3-AC-01～06 已全部通过。平台能够对 pytest/Maestro 失败作确定性分类，只允许 `LOCATOR` 进入 Maestro MCP 诊断；从同一模拟器的页面层级提取唯一文本候选后，只替换失败操作的 Selector，重新执行语法检查并由 pytest 重跑完整 Fixture 链。断言失败不会进入修复。每次 Attempt 的日志、JUnit、层级、截图、补丁和哈希账本独立保存，终态生成只读源文件之外的结果 Excel 与统一 HTML 报告。

## 验收环境与最终 Run

| 项目 | 实际值 |
| --- | --- |
| Maestro CLI | 2.10.0 |
| AVD / Device | `Pixel_5` / `emulator-5554` |
| App ID | `aippt.com.mm` |
| 定位修复 Generation | `b444c2237cb74abbb5e884a06a502a3c` |
| 定位修复 Run | `run-20260920T080235-f5b3551d85`，`COMPLETED` |
| 断言保护 Generation | `06914bacaa484c00aaf8fff077d76aa9` |
| 断言保护 Run | `run-20260920T075718-25d2b3b18a`，`COMPLETED_WITH_FAILURES` |

两个真实 Run 都使用 `TemporaryCredentialServicesGuard`。`assertion-credential-services-final.json` 与 `locator-credential-services-final-v2.json` 均为 `RESTORED`，恢复值与原值逐项一致，`errors=[]`。

## M3 验收矩阵

| ID | 实际步骤与结果 | 必需证据 | 状态 |
| --- | --- | --- | --- |
| M3-AC-01 | 六类已知失败与 `UNKNOWN` 由同一确定性分类器判定；只有 `LOCATOR` 进入诊断条件。真实断言失败又由生成 YAML 的断言上下文校正为 `ASSERTION` | `test_failure_classifier.py`、`test_m3_repair_run.py`、两个真实 Run 的 Attempt JSON | PASS |
| M3-AC-02 | 复用 M2 的 `确认设置` 失败；A1 分类 `LOCATOR`、失败步骤 3；MCP 绑定 `emulator-5554`，唯一候选 `确认设置(1)`；diff 仅修改对应 `tapOn` 并转义括号；`check-syntax` 通过；A2 重跑 Fixture 后通过 | `locator-evidence-final-v2.json`；Run 的 `repairs/`、MCP hierarchy/screenshot、A1/A2 JUnit/trace/log | PASS |
| M3-AC-03 | 将预期改为不存在文案，真实 `assertVisible` 失败；仅 1 次 Attempt，类型 `ASSERTION`，0 Repair，Run 正确为有失败；初始与最终 YAML SHA-256 均为 `1c0619c…aa2df` | `assertion-evidence-final.json`；失败 screenshot/hierarchy/JUnit/log；结果 Excel；相同 YAML 哈希 | PASS |
| M3-AC-04 | 自动化样例让首个 Case 连续失败，严格停止于 a1～a3/2 次修复；每个 Attempt 均重新执行两级 Fixture；随后独立 Case 继续并通过。真实定位 Run 的 A1/A2 也分别保留完整 Fixture 链 | `test_retry_cap_stops_current_case_and_continues_next_case`；真实 A1/A2 trace 与独立报告 | PASS |
| M3-AC-05 | 两条真实路径均生成带时间戳结果副本并重读。定位结果写入 `PASSED / 2 / 1 / step 3 / LOCATOR`；断言结果写入 `FAILED / 1 / 0 / ASSERTION`。两个源 SHA 前后均一致 | 两个 `result/writeback-manifest.json`、结果 `.xlsx`、openpyxl 字段断言与 LibreOffice PDF 渲染检查 | PASS |
| M3-AC-06 | 每个 Attempt 独立保存 pytest/Maestro JUnit、完整日志、层级、截图；Run 生成 `summary.json`、`artifacts.json`、`report.html`。结果页通过 `?run=<id>` 直达，展示 A1/A2、Repair、哈希与下载链接；完整证据账本可展开至 MCP 文件；浏览器刷新后完整恢复终态 | Run 目录、Artifact manifest、API 200/404 测试、生产构建、Codex 本地浏览器结果页与截图观察 | PASS |

冻结门禁 `M3-AC-01～06` 全部为 PASS，因此 M3 正式签收。

## 真实定位修复证据

最终 Run：`runtime/runs/run-20260920T080235-f5b3551d85/`

- A1：`FAILED / LOCATOR`，`failed_step=3`，`failed_selector=确认设置`。
- MCP：页面层级中唯一相关文本为 `确认设置(1)`；层级 JSON、截图、server/tool/device 响应均登记到 RepairRecord。
- 受控 diff 只有一行变化：`tapOn: 确认设置` → `tapOn: 确认设置\(1\)`；`assertVisible: 尽情发挥` 保持不变。
- A2：`PASSED`；A1/A2 各自执行 `FX-APP-RESET → FX-LOGIN-READY → Case`，各自有 trace、pytest JUnit 与三份 Maestro JUnit。
- 结果工作簿：`result/source_结果_20260920T080853Z.xlsx`，SHA-256 `c320d14e6afbb0d7d2235cb93283fd1397cb91c90fa44659e197ea82526ed46a`。
- 源 Excel 前后 SHA-256 均为 `e112ec7a17357e560c5199430c61364c43b8906f479f82b2f34b444b69f48480`。

## 真实断言保护证据

最终 Run：`runtime/runs/run-20260920T075718-25d2b3b18a/`

- 断言用例工作簿仅把预期改成不存在文案 `M3-断言保护-不存在`。
- Case 为 `FAILED / ASSERTION`，Run 为 `COMPLETED_WITH_FAILURES`；Attempt 数 1、Repair 数 0。
- 初始与最终 Case YAML SHA-256 完全相同：`1c0619c316976fa4a6998e1aee6e656493ce2118bf97ae7b467537c3456aa2df`。
- Maestro 在失败步骤保存层级 JSON、PNG 截图、命令清单、设备日志和 JUnit；平台没有创建 RepairRecord。
- 结果工作簿：`result/source_结果_20260920T080209Z.xlsx`，SHA-256 `af8745f7cc04a01e9897e41f9016c72cba4045c581ba0f105c391e364dcccc3c`。
- 源 Excel 前后 SHA-256 均为 `ce3d033db96f80f588de6d649928119257c8b05e769ad0071df3501487cb6d31`。

## 实现收束

- 领域模型：Attempt、RepairRecord、Artifact、CaseRunDetail 和 Run 汇总字段完成。
- 状态机：`RUNNING → DIAGNOSING → REPAIRING → RUNNING` 只用于证据充分的定位失败；终态和事件可恢复。
- 诊断与修复：MCP `list_devices / inspect_screen / take_screenshot`；唯一候选门禁；单一非断言 Selector 补丁；语法复检；无坐标。
- 生命周期：重试仍选择同一 pytest node，完整 setup/Case/teardown 重新执行；修复与 Attempt 上限来自 Config。
- 结果：源 Excel 不变，副本原子写入并重读；统一 HTML 报告、JSON 摘要和 Artifact SHA-256 manifest。
- API/UI：Artifact 和结果 Excel 下载；终态 Run 深链接；Attempt/Repair/证据台；刷新恢复。

## 过程中发现并关闭的实现缺陷

| 缺陷 | 现象 | 修复 |
| --- | --- | --- |
| M3-D-01 | pytest traceback 含源码字符串 `timed out`，普通定位失败被误判为 TIMEOUT | TIMEOUT 只接受结构化 `timed_out` 事实 |
| M3-D-02 | Maestro `[Failed] (...确认设置)` 摘要的外层右括号被并入 Selector | 仅在 `[Failed]` 摘要行剥离外层分隔符 |
| M3-D-03 | Maestro 的断言缺失也可能使用 `Element not found` 文案 | 用失败 Flow 的生成 YAML 上下文识别 assertion 命令并覆盖为 `ASSERTION` |
| M3-D-04 | 终态页面刷新后缺少 Generation 内存态，无法恢复 Case 列表 | RunSummary 返回 `selected_case_ids`，结果页支持 `?run=<id>` 直达 |

## 签收边界

M3 的自动修改范围仍严格限定为页面证据唯一、命令类型允许且非断言的文本 Selector。候选为零/多个、MCP 不可用、断言/环境/Fixture/超时/未知失败、语法复检失败或超过次数上限时都停止修复并保留失败。图像语义、多模态推理、坐标生成、批量设备和本地真机不在一期范围。
