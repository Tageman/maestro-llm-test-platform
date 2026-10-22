# M4 证据追溯与增量复核（2026-10-22）

后续小范围收尾已修复本文发现的 MCP 设备/截图缺口；最新 360 项测试、91.07% 分支覆盖率及真实增量验收进度见 [小范围收尾记录](m4-small-closeout-20261022.md)。本文保留前一批发现及证据，不表示缺口始终未修复。

本表补充 `m4-release-review-20261021.md`，不代替签署。裁决保持 **HOLD**。测试路径相对 `backend/tests/`；自动测试多使用合成输入/替身，不能充当真实业务验收或人工走查。

## 本次增量

发现 Maestro 适配器原先以“退出码为 0 且 JUnit 文件存在”判成功，可将损坏/失败报告误判通过。新增 `infrastructure/maestro_report.py`，CLI 和生成的 pytest 共用校验：XML 可读、合法 JUnit 根、至少一个 testcase、计数有效且与记录一致、没有 failure/error/skipped 或非成功状态。pytest trace 保留 `report_error`，校验失败抛出执行失败，不继续当作通过。

测试替身也改为输出完整 testcase，不能以空 XML 掩盖问题。`unit/test_maestro_report.py` 覆盖缺失、损坏、错误根、空结果、失败/错误/跳过、错误统计与状态、有效标准/实际 Maestro 格式及不可读报告。`unit/test_maestro_cli.py` 验证命令参数及有效报告。

报告校验增量全量回归为 296 项、0 失败/错误/跳过，核心分支覆盖 713/784=90.94%，证据单独保存在 `runtime/acceptance/m4-quality-20261022-report-validation/`，不覆盖 10 月 21 日结果。之后追加 AVD 与持久化测试，最终 **313 项通过、0 失败/错误/跳过，核心分支覆盖仍为 90.94%**，证据使用 `runtime/acceptance/m4-quality-20261022-final/`（gate.json、pytest.xml、coverage.json、step 日志）。质量脚本新增 `--output`，显式指定的目录必须尚不存在。使用 10 月 21 日全新安装的 venv 执行；本批未重新安装依赖或改动前端，仅有原有 Starlette/httpx 弃用警告。

新增 `unit/test_avd_startup_contract.py`：虚拟时钟/launcher 验证启动→上线→开机→包检查，列表超时/不存在/异常、启动器不可用、不上线、boot 未完成/异常/超时/不可用。`unit/test_run_repository.py` 新增 JSON/字节写入的 mkstemp/fsync/replace 故障注入：旧记录保持不变、错误向上传播、无残留临时文件；损坏 Run 不会从恢复清单静默消失。两文件定向测试共 19 项通过，不启动真实模拟器、不制造真实磁盘耗尽。

### 版本影响

10 月 21 日五阶段退出 PASS 仍然是其 `code-manifest.json` 对应的历史证据。本次改变报告判定，不改变 guardian、锁、恢复状态机或共享 Fixture 调度；不能声称旧 69 文件清单与当前源码完全一致。已用新校验器离线重验该批 FINALIZING 场景的 6 份真实成功 Maestro XML，均通过，但这不等于重新连接设备执行。正式候选冻结后还需要本版本业务端到端回归；若再次修改进程/恢复链路，须重做受影响退出阶段。

## AC-001～013 自动化追溯

下表列出已有可复现入口与仍缺的发布级证据；不把“有测试”写成整项 AC 已签收。

| AC | 自动化入口 | 本版本发布证据仍需补齐 |
| --- | --- | --- |
| 001 导入与校验 | `unit/test_excel_importer.py`；`integration/test_m1_api.py` | 冻结业务 Excel 的 SHA、行号、配置、校验响应与版本绑定 |
| 002 Fixture DAG | `unit/test_fixture_graph.py`；`integration/test_shared_scopes.py` | 业务基线依赖闭包、真实执行次序；共享范围增量走查 |
| 003 IR | `unit/test_flow_ir.py`；`unit/test_translation_and_yaml.py` | 业务基线 Generation 的 IR、输入映射及翻译器配置 |
| 004 确定性 YAML/语法 | `unit/test_compiler_contract.py`；`unit/test_generation_repair.py` | 当前候选生成 YAML 的真实 check-syntax 日志/哈希 |
| 005 人工预览确认 | `integration/test_m1_api.py` | UI 预览/批准记录及对应操作者/Generation |
| 006 执行与无人值守 | `integration/test_run_service.py`；`integration/test_run_failfast.py`；warning 门禁 API 测试 | review 与 unattended 各独立真实业务 Run；无 warning 绕过 |
| 007 Android 环境 | `unit/test_device_manager.py`；`unit/test_android_test_environment.py` | 当前候选设备/AVD/包/CLI 版本及准备记录 |
| 008 pytest 生命周期 | `unit/test_pytest_lifecycle.py`；`integration/test_shared_scopes.py` | 业务链 trace/JUnit；旧设备退出用例只证明当时会话共享计数 |
| 009 MCP 定位修复 | `unit/test_mcp_client.py`；`unit/test_locator_repair.py`；`integration/test_m3_repair_run.py` | 本版本真实失败→层级/截图→唯一候选→diff→pytest 重试链 |
| 010 断言不修复 | `unit/test_failure_classifier.py`；`unit/test_locator_repair.py`；`integration/test_m3_repair_run.py` | 本版本真实断言失败、零修复、IR/YAML 不变、失败报告 |
| 011 有界重试 | `integration/test_m3_repair_run.py::test_retry_cap_stops_current_case_and_continues_next_case`；共享 epoch 测试 | 与当前业务 Run/Attempt/Repair 证据绑定 |
| 012 Excel 副本 | `unit/test_result_workbook.py`；`integration/test_m4_delivery.py` | 真实业务源/结果哈希、字段验证及 manifest；不得重写退出注入的历史产物 |
| 013 报告追溯 | `integration/test_runs_api.py`；`integration/test_restart_recovery.py`；`unit/test_run_exporter.py` | 当前业务报告/下载/UI 走查；最终包清单及哈希 |

## 外部适配器四类分支

“已测”指所列自动化分支，不代表在线第三方服务验收。统一入口 `unit/test_adapter_failure_contracts.py` 简称 adapter tests。

| 边界 | 成功 | 超时 | 不可用 | 异常输出 | 裁决 |
| --- | --- | --- | --- | --- | --- |
| 命令执行器 | adapter tests 真实 Python 子进程 | 同左，短 deadline | 同左，不存在命令 | 由消费方解释输出 | 该执行器分支已测 |
| Maestro YAML 语法 | `test_maestro_cli`、`test_generation_repair` | adapter tests | adapter tests | 非零语法错误与修复上限 | 已测 CLI exit-code 契约，不解析自由文本成功文案 |
| Maestro Flow JUnit | `test_maestro_cli`、`test_maestro_report` | pytest 生命周期/进程测试 | 命令适配器及早期失败集成测试 | 本次新增 report 校验双入口 | 本次补齐报告有效性；真实业务重跑待完成 |
| ADB 在线设备准备 | `test_device_manager` | adapter tests | adapter tests | 非法 devices 输出阻断显式目标设备 | 已测在线选择分支，不等于 AVD 启动矩阵完整 |
| AVD 自动启动/开机 | `test_avd_startup_contract` 全准备链 | 同文件不上线、boot 卡住及命令超时 | launcher/list-avds 不可用 | 非法 AVD 列表、boot 输出 | 本次补齐模拟分支；真实启动新 AVD 未重跑 |
| MCP | `test_mcp_client` | adapter tests 真实 stdio 无响应 | adapter tests 命令不存在/EOF | 初始化非法结果、JSON 错误、工具 error | 已测基础协议；诊断服务设备核对当前用子串匹配，截图仅验证 base64、不验证图像内容，不能据此关闭错误设备/无效证据门禁 |
| LLM IR | `test_translation_and_yaml` | 同文件 timeout 测试 | adapter tests URLError | 非 JSON、空 choices、非法 IR；身份漂移 | 已测模拟 HTTP 契约，不声明付费在线 LLM 已验收 |
| 文件持久化/Excel/导出 | `test_run_repository`、`test_result_workbook`、`test_run_exporter` | 本地同步 I/O 当前无 deadline 契约 | 导出复制失败；本次新增临时文件/刷盘/原子替换故障 | 损坏 Run、越界证据、符号链接、结果字段一致性 | **部分完成**；超时需明确经认可的 N/A 或有界机制，不能自定豁免 |

## 发布剩余动作（按顺序）

1. 收紧 `mcp_diagnostics.py` 的设备精确匹配与截图有效性，再补诊断服务和编排门禁测试（不得只测分类器）。当前子串匹配可能将 `emulator-55540` 误当 `emulator-5554`；有效 base64 也不一定是图片。这两项作为发布阻断项保留，尚未在本批修改。确认同步文件 I/O 的超时验收口径。AVD 启动/开机和核心原子写入故障分支已补测。
2. 冻结候选源码/环境/业务输入，跑 review/unattended 正式业务链，按上表关联全部 13 项；安全合成用例和历史 M1～M3 PASS 不替代。
3. 核验用户已有的非开发人员走查记录。需要文件/路径、操作者、日期、版本与结论；旧版需补共享作用域、恢复、导出相关差异。
4. 前置门禁满足后形成固定交付包/哈希、缺陷裁决与产品/测试签署。未提供的签名保持空缺，不自动发布、打标签或推送。
