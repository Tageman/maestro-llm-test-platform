# M4 小范围收尾（2026-10-22）

范围冻结：仅 MCP 设备匹配、截图有效性、对应自动化/真实模拟器增量回归，以及已有验收材料核验。不加入真机、并发、视觉修复或文件 I/O 隔离进程等二期能力。**技术收尾与正式发布签署分开，本文不代签。**

## 实现

- 设备解析：支持 Maestro 2.10 的 `content[].text` JSON 设备列表、直接 `devices` 和 `structuredContent.devices`；只读取结构化记录中的 `device_id` 做完全相等比较，要求 `connected=true`、`platform=android`、`type=emulator`。说明文字、名称字段、相似 ID、重复/冲突列表、缺少字段、离线和未知结构不作为命中证据；阻断后不调用 inspect/screenshot。
- 截图验证：必须只有一个图像，声明 PNG 或 JPEG，声明/data URL/实际格式一致。先限制编码与解码大小，再检查完整边界、图像容器（PNG CRC）、完整像素解码与单帧限制。上限 16 MiB、1600 万像素、单边 8192。无效内容不落成有效截图、不返回候选、不写补丁、不启动修复重试；Case 保持原失败，诊断错误可追溯。
- 兼容性：历史真实 Maestro 2.10 返回 `image/jpeg`，旧实现误以 `.png` 保存。新实现原样保存已验证字节并使用 `.jpg`，PNG 使用 `.png`；不转换图片、不修改历史产物。首版仅允许 PNG 的方案在历史格式复核时被发现不兼容，已修正，不能将那一轮自动测试当作最终验收。
- 新增 Pillow `>=12,<13` 依赖，隔离新环境实际安装 12.3.0。README/使用说明同步升级安装命令、诊断限制及排障信息。

## 自动验证与证据

- `unit/test_mcp_diagnostics.py`：设备列表包装、相似/离线/冲突/畸形数据、两种真实图像格式、损坏/截断/错误 CRC/不可解码像素、MIME 不符、超大和多图等分支。
- `integration/test_m3_repair_run.py`：使用真实诊断服务、模拟 MCP 传输验证错误设备/无效图像不进入 REPAIRING、不追加 Attempt、不生成 diff，仍生成结果工作簿；有效证据能修复并重试。
- 新环境安装/ASGI 启动/前后端验证：`runtime/acceptance/m4-clean-install-20261022-closeout/`。该轮为 358 项测试通过（JPEG 两项补测加入前），前端生产构建通过。
- 最终质量证据：`runtime/acceptance/m4-quality-20261022-closeout-v2/`，**360 项通过、0 失败/错误/跳过，核心分支覆盖 714/784=91.07%**；同目录保留 gate.json、JUnit、coverage.json 及日志，不覆盖前轮证据。
- 历史真实 `devices.json` 与 JPEG 响应离线重验已通过；当前真实 MCP 预检也已通过，设备 ID 精确匹配，当前 JPEG 完整解码且“创建”是唯一相关候选。预检证据在 `runtime/acceptance/m4-mcp-preflight-20261022/`，不代替完整执行与修复链。

## 真实模拟器增量验收

脚本 `scripts/verify_m4_mcp_closeout.py`：在独立目录生成安全导航工作簿，以真实 syntax-check、pytest、Maestro CLI/MCP 执行以下三条路径；均不清数据、不安装业务 APK、不修改系统凭据服务，不触碰原用户 Excel。

1. review 正常：由脚本批准自己生成的合成用例，验证 Fixture→Case→Cleanup，终态 COMPLETED。不是非开发人员人工预览签收。
2. unattended 定位修复：故意让只读导航文本不匹配，要求严格设备/图片门禁通过后得到唯一层级候选，只修操作 Selector；完整 pytest 链重试一次、断言不变、最终通过。
3. 断言失败：期望文本故意不存在，要求 COMPLETED_WITH_FAILURES、ASSERTION、零修复、一次 Attempt、清理已完成。

每条路径保存输入哈希、Generation/Run、原始产物与结果副本；重建 FastAPI 应用生命周期后经 TestClient 实际路由下载全部 Artifact 与结果 Excel，逐项校验哈希。不是浏览器人工 UI 走查。脚本冻结源码/Schema/脚本/依赖声明哈希并在每条路径后检查未变；失败保存 FAIL，重跑用新目录。

启动准备记录：本次原无在线设备；启动既有 Pixel_5 后持续 offline，旧启动快照加载失败。仅停止本次启动的进程，以 `-no-snapshot-load -no-snapshot-save -gpu software` 冷启动后恢复在线；未删除 AVD 或 App 数据，未改持久 AVD 配置。模拟器由本次任务启动，不会因 pytest 工作进程清理而被关闭。

首轮 `runtime/acceptance/m4-mcp-closeout-20261022-v1/` 保留 FAIL：Run `run-20261022T064747-449ab8f86d` 被 App 再次启动后出现的“新人礼包”遮罩挡住，S/PS 无法定位“创建”，Case 为 FIXTURE_FAILED、清理 failed，Run 为 COMPLETED_WITH_FAILURES，没有假成功。待该轮完全退出后，依据失败截图人工点击弹窗 X 恢复起始页面；这是验收环境准备，不是平台自动坐标修复，不写入生成 YAML。随后使用 v2 新目录、同一源码与同一验收规则重跑，原失败产物不改写。

## 发布材料与后移项

用户已说明有非开发者走查记录，本轮再次请求文件/路径及签署人、日期、结论。在收到并核验前保持“待材料核验”，不写成已签署。原业务基线 AC-001～013 的追溯仍须由对应业务材料证明，安全合成增量验收只证明本次技术变化。

本地同步 I/O 硬超时不在本批实现；建议按健康本地磁盘的一期适用范围后移，但 M4-AC-02 对该边界的 N/A/限制仍需负责人确认，不悄悄豁免。没有签署时，不打正式 release/tag、不标 M4 ACCEPTED。
