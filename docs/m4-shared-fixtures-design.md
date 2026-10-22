# 跨 Case Fixture 生命周期设计（2026-10-20）

范围：落实既有 function/module/session 字段语义，不增加并行设备、远程运行或自动扩大修复能力。IR 1.0 与 REST 请求结构不变；运行包映射新增可选字段，旧包仍走原独立 Attempt 路径。

## 生命周期与排序

| 作用域 | 缓存边界 | 清理 |
| --- | --- | --- |
| function | 当前 Case Attempt | 当前 Attempt 结束 |
| module | `Cases.module`，不是 Fixture 分类列 | 模块最后一个 Case 结束 |
| session | 当前 Run 的共享轮次 | 最后 Case、提前停止或重试重建前 |

选中计划含 module/session 才启用共享工作进程。Case 按模块首次出现顺序分组、组内保持输入顺序；生成真实 pytest 模块和公共 conftest，不以“此前通过”代替 pytest Fixture 缓存。宽作用域依赖窄作用域在 Excel 校验阶段阻断。

所有后置夹具在前置执行前注册。启动失败、前置失败、Case 失败仍走已注册清理。提前停止不执行后续 Case，但显式关闭共享会话；超时/取消导致进程强制退出时，不保证执行设备清理，结果必须为 unknown。

## 重试与状态一致性

每次定位修复重试都是完整夹具链重跑：先清理旧 module/session，再建立新轮次，后续 Case 共享新轮次。旧轮次清理失败阻断本次重跑并保留证据，不能覆盖为成功。默认启动每轮一次；显式启动必须属于最宽作用域且所有 Case 的显式启动集合一致，避免中途重启破坏共享缓存。

Case 业务结果与清理结果分离。共享清理未收口前 cleanup_result 为 pending；正常收口为 passed；共享清理失败通过 trace 的 affected_case_ids 回溯消费者，Case/最后 Attempt 标为 FIXTURE_FAILED，业务断言已通过仍保留 business_result=passed。取消或工作进程异常退出标为 unknown。重启恢复也回溯此前已通过但共享清理未确认的消费者；FINALIZING 已完成共享清理，不无故改写其已证实结果。

## 工作进程协议及证据

- `generated/pytest/conftest.py`：真实 pytest Fixture 定义。
- `generated/pytest/test_module_NNN.py`：按 Case 模块分组的节点。
- `generated/mappings/pytest.json`：node_ids、case_node_ids、case_plans、shared_scopes、startup_plans。
- `shared-worker/NNNNNN.json` / `.done.json`：原子请求/响应；返回真实 setup/call/teardown 报告状态。
- `attempts/<case>/aN/`：每 Attempt 独立 trace、JUnit、日志；共享初始化只计真实执行次数。
- `shared-finalization/`：提前结束时的共享清理及进程中断证据；Run Artifact 同时登记 worker.log 和 shared-suite.xml。

父进程经原有 guardian 创建 pytest 子进程，继承 runtime 独占锁；仍只允许单设备、单 Run。生成的 pytest 禁止第三方插件自动加载，防止宿主插件改写结果。pytest 私有协议只封装在 shared_worker.py，当前仅接受 pytest 8，升级到 9 前须重新验证；参考 [pytest runner 实现](https://www.pytest.org/en/latest/_modules/_pytest/runner.html)。

## 验收与阻断

自动化覆盖同模块/跨模块计数、同一进程、重试重建、前置失败缓存、提前结束清理、共享清理回溯、取消未知、结果 Excel 执行次数和重启消费者状态。真实设备证据另行登记，不能用假 Maestro 代替设备验收。

任一未完成清理被显示为通过、作用域次数不符、原 Excel 被改写、子进程泄漏、不同模块错误共享、重试未重建完整链均阻断发布。人类走查与签署仍按 M4-AC-05/06 单独裁决。
