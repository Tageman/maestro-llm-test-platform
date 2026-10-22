# M4-R06：重启恢复与执行进程所有权

日期：2026-10-20。状态：已实现并通过本批自动化回归；不等同于 M4-AC-04 的真实模拟器全阶段签收。

## 1. 决策与范围

后端恢复采用 **安全终止旧 Run，不自动重放**。恢复阶段不调用 pytest、Maestro、MCP、ADB，不重新生成 Excel，也不重试目录交付。再次执行必须新建 Run。

服务端 Web 启动、以及 Web/验收 CLI 创建 Run 前，均先尝试获取同一个 `RUNTIME_DIR/.execution.lock`。恢复和实际执行持有同一把 POSIX `flock` 锁。服务间不以 Python 线程锁、PID 文件或文件存在与否判断是否可执行；文件永久保留，不能在运行中删除或替换。

本次是 macOS/POSIX 的本地单运行方案；不是多主机调度器，也不支持多进程服务在同一设备上使用不同 RUNTIME_DIR 绕过互斥。

## 2. 子进程生命周期

1. 执行线程激活运行锁上下文；pytest（含收集）、MCP 和通用命令适配器使用独立守护进程启动目标命令。
2. 守护进程持有运行锁描述符副本，用父进程管道监测后端存活。正常输入输出直接传给目标命令，不改 MCP JSON-RPC 协议。
3. 后端退出导致管道 EOF，或取消/超时发送 TERM 时，守护进程先 TERM 自己创建的目标进程组，宽限后 KILL 残留组成员。组长提前退出也执行后代清理。
4. 清理完成后守护进程才退出、释放锁。父服务仅关闭自己的锁描述符，不显式 `LOCK_UN`，因此后端崩溃或线程异常不能提前释放仍由守护持有的锁。
5. 新服务发现锁被持有时，不触碰旧 Run；新建 Run 返回 `RUNTIME_BUSY`。清理结束后的下一次启动检查、旧 Run 状态查询或创建请求再完成持久化恢复，避免启动恰逢清理时页面永久停留在运行中。

不按进程名或历史 PID 杀进程，避免 PID 复用和误伤其他任务。既有 Android 模拟器、ADB daemon 属于可复用设备基础设施，不在测试工作进程清理范围；平台按原有策略启动的模拟器仍可供后续 Run 复用。后台守护自身被单独强杀、进程主动逃逸到新会话、系统级权限变化不属于本次已验证的后端退出模型，不能据此声称任意异常下都无残留。

## 3. 持久化恢复规则

新增内部 Run 字段 `execution_ownership="guarded-v1"`；Flow IR 和既有 Run 状态图不变。REST RunSummary 增量增加可空的 `recovery_report_artifact_id` / `recovery_snapshot_artifact_id`，API 契约升为 1.2；前端沿用证据区下载链接展示，不需要从文件系统猜测 Artifact ID。

| 退出前状态 | 恢复后状态 |
| --- | --- |
| CREATED、AWAITING_REVIEW、READY | CANCELLED |
| VALIDATING | VALIDATION_FAILED |
| GENERATING | GENERATION_FAILED |
| PREPARING_DEVICE、RUNNING、DIAGNOSING、REPAIRING、FINALIZING | FAILED |
| 已有终态 | 保持原终态；若导出仍为 pending，单独改为 failed |

恢复通过原状态图校验。已完成 Case 的结果保留；尚未执行的 Case 为 `BLOCKED` 且不生成虚假 Attempt；存在未闭合 `attempt.started` 或活动 Case 时，记录中断，业务/清理结果为 `unknown`。已存的 Attempt 和原始日志不被删除。没有完整结束证据时，不推断业务通过或清理成功。

每个被恢复的 Run 保留：

- `recovery/before-run.json`：恢复前原始快照。
- `recovery/report.json`：旧状态、新状态、策略、所有权判断、人工核查要求和恢复前证据文件 SHA-256。
- `run.recovered` 事件：恢复决策，不伪装成一次测试执行。
- 可下载的 `recovery_snapshot` / `recovery_report` Artifact。

恢复报告先写 prepared，再写终态和事件，最后置 completed；再次启动可完成中途退出的恢复而不重复执行。事件序号同时参考已落盘事件文件，防止“事件写入后、cursor 更新前”崩溃造成覆盖。损坏或身份不匹配的 Run 记录、链接记录/证据不能静默略过，须阻断并保留现场。

## 4. 旧版 Run 的保守处理

旧版非终态没有可验证的守护所有权，恢复报告标记 `legacy_ownership_unverified` 和 `requires_manual_process_check=true`。平台可以保存终止判定，但不能证明旧外部进程已经退出，所以继续阻断新 Run：`LEGACY_PROCESS_CHECK_REQUIRED`。已完成且无需恢复的旧 Run 不受影响。

操作人员先确认日志、设备及相关旧 pytest/Maestro/MCP 进程已停止；不要误停无关任务。确认后，使用与 Web 相同的 `RUNTIME_DIR`，在项目根目录执行：

```bash
python3.11 -m maestro_app.cli.recover \
  --run-id <需要确认的旧RunID> \
  --confirm-no-owned-processes
```

这条命令是人工事实确认，不会代为检查/杀进程，也不会重放旧 Run。它必须获取运行锁，并记录 `run.recovery_acknowledged` 事件；不能在未核查时用它绕过阻断。

## 5. 验收步骤与阻断规则

| 验收步骤 | 预期结果 | 必需证据 | 阻断规则 |
| --- | --- | --- | --- |
| 针对所有非终态创建中断快照并恢复两次 | 合法安全终态；第二次无重复副作用 | `test_run_recovery.py` 参数化结果、恢复前后快照 | 假通过、非法转换、重复事件/覆盖原始日志 |
| 中断一个已开始 Attempt，另保留已完成/未执行 Case | 已完成不变；活动结果 unknown；未执行无虚假次数 | CaseRun、Attempt、事件断点测试 | 把活动或未执行 Case 判为通过 |
| 模拟事件已写、cursor 未更新；模拟恢复中途退出 | 原事件不覆盖，恢复可重入 | 序号与恢复故障注入测试 | 丢事件、重复回放、恢复永久悬挂 |
| 用两份服务争用同一 runtime | 活动所有者不被恢复；新执行阻断 | `test_execution_guard.py`、服务集成测试 | 第二个服务能并发操作设备 |
| SIGKILL 一个持锁的测试后端，目标及后代忽略 TERM | 守护清理目标组，之后运行锁可获取 | `test_backend_sigkill_drains_owned_group_before_lease_can_be_reacquired` | 进程残留、锁提前释放、误杀无关进程 |
| 正常组长先退出；MCP 型 stdin/stdout；命令超时/不存在 | 后代清理、协议透明、超时/不可用明确失败 | `test_restart_recovery.py`、既有进程测试 | 输出混入协议、后代残留、超时误报成功 |
| Web lifespan 启动后读取恢复 Run 和 Artifact | 安全终态与恢复报告可读取 | TestClient 启动/下载集成测试 | 只写文件却没有启动接线或下载证据 |
| 旧版未完成 Run 恢复与人工确认 | 默认阻断，明确确认后解锁且留事件 | 旧记录兼容与锁释放测试 | 无证据自动清除阻断 |
| 真实模拟器在准备、执行、诊断/修复、写回阶段退出 | 不重复设备副作用、无残留测试进程、证据完整 | 待执行的分阶段设备记录、进程/日志/API截图 | 缺证据不得将 M4-AC-04 签为 PASS |

最初恢复批次仅验证隔离 Python 进程。2026-10-21 已开始使用独立验收后端连接真实 Android 模拟器，分阶段 SIGKILL 后检查无重放、原证据不变、进程清理和 API 下载；最新结果见 M4 实施记录及 runtime 验收证据，不沿用旧批次状态。R08 跨 Case 生命周期已实现，见[共享作用域设计](m4-shared-fixtures-design.md)。恢复时若先前通过的 Case 仍依赖未完成的共享清理，其 Case/Attempt 降为 FIXTURE_FAILED、cleanup_result=unknown；FINALIZING 前已完成共享清理的结果保留。

macOS 进程组探测收到 EPERM 时，不直接视为已退出：仅在读取 `/bin/ps` 的进程组/状态元数据确认无活成员（仅僵尸或不存在）后结束等待；存在活成员或读取失败仍报错。受限沙箱可能禁止该系统查询，因此完整进程清理门禁须在具备本机进程观察权限的环境运行，不能跳过测试来通过门禁。
