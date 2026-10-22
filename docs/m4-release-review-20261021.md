# M4 发布复核（2026-10-21）

发布裁决：**HOLD，尚未 ACCEPTED**。本记录不代替产品/测试签署，不创建发布标签或对外发布。代码仍在当前工作区，设备验收以文件内容哈希冻结，尚无签署的 release commit。

2026-10-22 增量：报告有效性校验、AVD 自动启动/开机分支、原子持久化故障测试及 AC-001～013 对照见 [证据追溯矩阵](m4-evidence-matrix-20261022.md)。下文 10 月 21 日五阶段证据保留为当时版本，不冒充更新后源码已经重做设备验证；发布仍 HOLD。

## 本次交付

1. 跨 Case Fixture 已实现：function/module/session 真正生命周期、模块分组、重试重建、共享清理失败回溯、取消未知、Excel 真实执行次数。设计与说明同步到技术设计 V1.3、README 和使用说明书。
2. 可重复的真实模拟器退出验收脚本：`scripts/verify_m4_device_exit.py`。只杀自己创建的验收后端，原模拟器和其它服务保持；覆盖准备、运行、诊断、修复、写回五阶段。
3. 干净安装脚本：`scripts/verify_m4_clean_install.py`。新 venv、新 node_modules，使用说明同款 editable 安装、Schema/ASGI 启动检查、后端全量测试和前端构建。是既有主机上的隔离新环境，不宣称全新 macOS 人工安装。

## 当前门禁

| 门禁 | 裁决 | 证据或缺口 |
| --- | --- | --- |
| R08 共享作用域实现 | PASS（自动化） | `backend/tests/integration/test_shared_scopes.py`，依赖图及恢复单测；包含真实 pytest 子进程，不是缓存历史 PASS |
| 核心覆盖率、全量测试 | PASS | `runtime/acceptance/m4-quality/`；新虚拟环境最终复测 276 项、0 失败/错误/跳过，713/784=90.94%（阈值 85%）；仅有 Starlette 测试客户端依赖弃用提示，不影响当前测试 |
| 干净环境安装构建 | PASS | `runtime/acceptance/m4-clean-install-20261021-v2/evidence.json`、freeze、startup、JUnit、npm ci/build 日志 |
| 五阶段真实设备退出 | PASS（技术退出场景） | `runtime/acceptance/m4-device-exit-20261021-v3/summary.json`；准备、运行、诊断、修复、写回全部通过；不替代 M4-AC-01 正式业务回归或人工 UI 走查 |
| M4-AC-01 正式业务回归 | BLOCKED / 证据未齐 | 当前安全合成用例不代替冻结业务 Excel 的 AC-001～013 及 review/unattended 全链本版本追溯 |
| M4-AC-02 完整适配器矩阵 | 部分完成 | 命令/MCP/设备/语法/LLM 已补正常、超时、不可用、异常返回测试；完整跨适配器及产物有效性矩阵仍须逐项复核，不仅凭覆盖率关闭 |
| M4-AC-03 故障矩阵 | 部分完成 | 分类、修复边界、上限、取消/恢复已有自动化；须与正式 AC 追溯及当前真实 Run 对齐 |
| M4-AC-05 非开发者走查 | 待核验 | 用户已说明“已有走查记录”，但文件、操作人、时间、对应版本、签字尚未提供；新作用域/恢复需核对增量走查 |
| M4-AC-06 版本与发布签署 | BLOCKED | 前置门禁未齐；缺固定发布版本、最终包/哈希、产品/测试负责人签署，不推断授权签名 |

## 适配器证据索引

### 真实设备最终结果

Pixel_5 / emulator-5554，App `aippt.com.mm`，Maestro 2.10.0。冻结的 69 个执行源码/脚本/Schema 文件与验收后内容哈希一致。五阶段均验证恢复后进入 FAILED 而非假完成、原执行证据及源合成 Excel 不变、恢复幂等、原 Artifact 条目不变且仅新增恢复审计记录、API 能下载恢复报告。观察到的专属子进程数量依次为 0、3、5、2、0，全部退出；没有停止模拟器或其它服务。

| 阶段 | 结果 | 实际注入点 |
| --- | --- | --- |
| PREPARING_DEVICE | PASS | 真设备准备与应用安装检查返回后、状态转换前 |
| RUNNING | PASS | 真实 Maestro Case 命令启动日志出现后 |
| DIAGNOSING | PASS | 真实 MCP 截图返回、MCP 连接仍打开时 |
| REPAIRING | PASS | 唯一候选修复后的 YAML 经真实 check-syntax 通过后 |
| FINALIZING | PASS | 结果工作簿写入并验证后、Run 元数据最终登记前 |

最后一轮 Run `run-20261021T020545-4bd9393a9e` 的 A1/A2/B1 在退出前均 PASSED、清理 passed；trace 证明 S 会话前置 1 次、PS 会话后置 1 次、默认启动 1 次，每个 Case 各 1 次。模块/函数级计数及失败重试由真实 pytest 子进程自动测试验证，本轮设备合成场景专门验证会话共享。写回阶段特意停在调用返回前，尚未生成由 RunService 后续登记的 writeback-manifest；该缺失符合注入位置，不能自动重写补齐，实际 Excel 文件及哈希见该阶段 pause.json。

### 自动化索引

- 真实进程成功/超时/不可用：`test_adapter_failure_contracts.py`、`test_managed_pytest_process.py`、`test_restart_recovery.py`。
- MCP 初始化、工具错误、无效 JSON-RPC、无响应/EOF/命令缺失：`test_mcp_client.py`、`test_adapter_failure_contracts.py`；设备退出脚本另验真实 MCP 存活期间后端退出。
- Android 选择、超时/不可用/异常设备列表：`test_device_manager.py`、`test_adapter_failure_contracts.py`。
- 语法错误、超时、不可用：`test_maestro_cli.py`、`test_generation_repair.py`、`test_adapter_failure_contracts.py`。
- LLM 成功、超时、不可用、非 JSON/空响应/非法 IR：`test_translation_and_yaml.py`、`test_adapter_failure_contracts.py`。本次不调用付费 LLM 服务。
- Excel/导出异常及证据一致性：`test_result_workbook.py`、`test_run_exporter.py`、`test_run_repository.py`。这些不是完整适配器矩阵已签收的声明。

## 失败记录保留

`m4-device-exit-20261020-v1`：验收脚本引用不存在枚举失败；`m4-device-exit-20261021-v2`：诊断后恢复新增 Artifact 审计条目被旧脚本误判为原证据变化。原失败记录保留，不覆盖成 PASS；v3 要求原文件哈希及原账本条目不变，只接受新增恢复报告/快照条目。

进程组探测曾遇到 EPERM；守护进程现只在进程表证实无活成员时容忍该过渡状态，否则报错。完整测试使用本机进程观察权限；不跳过失败测试。新安装产生的临时构建目录已移至忽略的 runtime 验收目录保留，可恢复，未删除用户资料。

## 签收所需补件

已有走查文件/路径；操作人与时间；代码/说明书版本；产品/测试签署人、日期和结论。记录基于旧版时补核对共享 Fixture、重试重建、清理未知、重启恢复及输出导出。获得记录后仍须核实全部前置门禁，不会把“已有记录”自动写成“已签收”。

## 技术复现

在项目根目录运行，输出目录必须是尚不存在的新目录。设备脚本当前固定使用 `emulator-5554`、Pixel_5 和 `aippt.com.mm`，要求已启动模拟器、已安装 App，并事先确认“创建”是可见且无提交副作用的导航标签；它不是可随意用于其它 App 的通用用例。

```bash
make quality PYTHON=python3.11
python3.11 scripts/verify_m4_clean_install.py --output runtime/acceptance/clean-new01
PYTHONPATH=backend/src:backend/tests python3.11 scripts/verify_m4_device_exit.py --root runtime/acceptance/device-exit-new01 --safe-text 创建
```

设备脚本支持重复 `--phase` 选择阶段；不传则跑五阶段。每阶段保存 pause.json、backend.log、输入哈希、Run/恢复报告和 evidence.json，顶层汇总 summary.json 与 code-manifest.json。输入为独立合成工作簿，不覆盖用户样例。目录及页面截图可能包含本地信息，全部保持 runtime 忽略，不纳入公开仓库。
