# M2 真实执行 MVP 状态

## 结论

| 项目 | 结果 |
| --- | --- |
| 里程碑 | M2 真实执行 MVP |
| 实现状态 | **Complete** |
| 正式验收状态 | **ACCEPTED** |
| 状态日期 | 2026-09-20 |
| 自动化回归 | 50 passed，JUnit 已落档 |
| 前端构建 | TypeScript + Vite production build passed |
| Blocker | 无；`B-M2-001`、`B-M2-002` 均已关闭 |

pytest Fixture 生命周期、Maestro CLI 真实执行、Android 模拟器准备、Run 状态机、事件/SSE、取消/超时/输出控制、报告和前端 Run 控制台已经实现并通过正式验收。修正版冻结基线连续 3 个 review Run 全部 `COMPLETED`，pytest 与 Maestro JUnit 均无 failure/error；同一输入的 unattended Generation 也完成 1 个真实 `COMPLETED` Run。M2-AC-01～05 全部通过，M2 正式签收。

签收没有弱化 `立即生成` 或 `尽情发挥` 断言、跳过 Fixture、加入坐标点击或把历史失败误计入三连。原始 Excel 保持不变，修正版仅调整 `Cases!I6` 的实际控件文案；编译器在 YAML 边界转义正则元字符，保持 Flow IR 的字面值语义。

## 验收环境和输入

| 项目 | 实际值 |
| --- | --- |
| 平台 | macOS，本地受控环境 |
| Maestro CLI | 2.10.0 |
| ADB | 36.0.2-14143358 |
| Android Emulator | 36.5.11.0 |
| Python | 3.11.0（最终回归与签收 Run）；3.13.3（早期诊断 Run） |
| Node.js / npm | 25.7.0 / 11.10.1 |
| AVD / Device | `Pixel_5` / `emulator-5554` |
| App ID | `aippt.com.mm` |
| 原始源文件 | `Maestro_pytest_LLM_APP_测试用例模板.xlsx`，SHA-256 `e112ec7a17357e560c5199430c61364c43b8906f479f82b2f34b444b69f48480` |
| 签收源文件 | `Maestro_pytest_LLM_APP_测试用例模板_M2修正版.xlsx`，SHA-256 `cf7003c01653dec128e9a5cdd7f45297d6ec753e7275fd69b342bfbefb65982d` |
| Review Workbook / Generation | `7027470374bb439b8caff0ff726812ef` / `fcda5b86527b47b4937e77c998c7786b` |
| Unattended Workbook / Generation | `e6689bbbd3eb486787d9adc1aeb1b762` / `d9f38fd69dcc4d66baa1a39de3ea479f` |

为解决 AVD 资源不足，真实验收使用 4 CPU、4096 MB、headless cold boot。Gboard 已切换为 `en-US / LatinIme`，邮箱可以按原文输入。2026-09-20 的受控三连与 unattended Run 仅临时改变专用 AVD 的三项 secure setting；两次执行结束后均自动恢复，并由证据文件与 ADB 二次读取核验。

## M2 验收矩阵

| ID | 实际结果 | 关键证据 | 状态 |
| --- | --- | --- | --- |
| M2-AC-01 | Maestro/ADB、唯一 emulator、AVD 名、boot、App 包均由设备准备器校验并持久化；额外记录输入法和 autofill 状态 warning | 每个 Run 的 `artifacts/device-preparation.json`；`test_device_manager.py` | PASS |
| M2-AC-02 | 生成 pytest；Case 与 item 1:1；依赖去重；setup 成功、Case 失败、setup 失败三路径均验证；已注册 teardown 在失败后逆序执行 | `test_pytest_lifecycle.py`、生成的 `test_generated.py`、pytest JUnit、flow trace | PASS |
| M2-AC-03 | review/unattended 均通过真实 `RunService`、状态机、事件持久化和结果聚合；两种模式均产生真实设备 `COMPLETED` 终态；Run API、Case、cancel、SSE 与 `Last-Event-ID` 续传通过；桌面与 390×844 Run 入口走查通过，console error/warn=0 | review 三连、`unattended-real-run.json`、`test_run_service.py`、`test_runs_api.py`、真实 `run.json/events`、浏览器走查记录 | PASS |
| M2-AC-04 | 修正版冻结基线连续执行 3 个独立 review Run；三轮均在 `Pixel_5/emulator-5554` 按同一顺序执行且 `COMPLETED`，Case `PASSED`，JUnit 零失败 | `corrected-three-runs.json`、三个 Run 的 JUnit/trace/log/artifacts | PASS |
| M2-AC-05 | 参数数组、`shell=False`、独立 pytest 进程组、TERM→KILL、取消、超时、异常清理、完整日志+控制台上限、单 worker 均有测试 | `test_managed_pytest_process.py`、pytest JUnit | PASS |

根据冻结规则，M2-AC-01～05 已全部通过，M2 总状态为 `ACCEPTED`。

## 真实执行诊断链

| Run | 关键结果 | 结论 |
| --- | --- | --- |
| `run-20260917T033316-076b82b567` | `FX-APP-RESET` 通过；首次登录输入阶段超时 | 证明 pytest→Maestro 真实链、Fixture 阻断和证据落盘有效 |
| `run-20260917T074013-33ea6624ed` | 4 CPU/4096 MB 后驱动稳定；Gboard 把 `mail` 转成中文 | 定位为中文输入引擎环境问题 |
| `run-20260917T075241-c20d624a7a` | 英文输入后测试邮箱正确，登录成功进入首页；密码保存遮罩覆盖断言 | 业务登录链已通过，失败点为 Android 系统 UI；公开文档不披露账号 |
| `run-20260917T075626-650d92e199` | 临时点击 `Not now` 后下一轮仍重复出现遮罩 | 证明一次性人工关闭不能满足无人值守和三连验收 |
| `run-20260920T051551-88ea467aa1` | 两个 setup Fixture 通过；Case 页面显示 `确认设置(1)`，精确定位 `确认设置` 失败 | 系统遮罩已消失；发现冻结用例定位契约问题 |
| `run-20260920T051913-e5a7567dc6` | 同一链路和同一定位点失败 | 第 2 次稳定复现 |
| `run-20260920T052154-4fe8ff3182` | 同一链路和同一定位点失败 | 第 3 次稳定复现 |
| `run-20260920T053618-30aaaae642` | 修正版 review Run：Fixture、Case、报告均通过 | 正式三连 1/3 |
| `run-20260920T053949-6efc6f9fbc` | 修正版 review Run：Fixture、Case、报告均通过 | 正式三连 2/3 |
| `run-20260920T054241-fec096a6dd` | 修正版 review Run：Fixture、Case、报告均通过 | 正式三连 3/3，M2-AC-04 关闭 |
| `run-20260920T054733-802b0088e5` | unattended ready Generation 真实执行通过 | M2-AC-03 真实无人值守缺口关闭 |

2026-09-17 的两个遮罩失败 Run 均正确把失败归入 setup Fixture，Case 主体未越过失败前置。2026-09-20 的三个 Run 则均由两个 setup Fixture 成功进入 Case，再把定位失败归入 Case；五个 Run 终态均为 `COMPLETED_WITH_FAILURES`。两种归类都符合生命周期和阻断设计。

## 已解除 Blocker `B-M2-001`

### 现象

输入引擎切为英文后，登录动作和凭据均正确；Google Password Manager 在首页上方弹出 `Save password to Google?`。Maestro 对 `立即生成` 的可见性断言因此失败。点击 `Not now` 只影响当前一次，下次清状态登录仍会弹出。

### 解除结果

- 负责人已明确授权在专用 `Pixel_5` AVD 上临时关闭三个服务。
- `TemporaryCredentialServicesGuard` 在首次修改前保存原值，校验 AVD 后临时关闭，并在三轮结束后恢复、逐项验证。
- `runtime/m2-acceptance-20260920/evidence/credential-services.json` 终态为 `RESTORED`；ADB 二次读取与原值完全一致。
- 三轮 `FX-LOGIN-READY` 均通过，证明密码保存遮罩不再是当前阻断。

## 已解除 Blocker `B-M2-002`

### 现象和证据

- 冻结 Excel 的 `Cases!I6` 第 3 步为 `点击【确认设置】`，Generation 据此生成 `tapOn: 确认设置`。
- 用户约定是按按钮实际文案直接翻译 Maestro 文本定位。
- 选择“尽情发挥”后，页面按钮实际显示 `确认设置(1)`。
- 三轮 Maestro JUnit 均报告 `Element not found: Text matching regex: 确认设置`；截图可见 `确认设置(1)`。

### 修复与边界

- M2 门禁明确不包含自动定位修复；MCP 层级诊断和受控 Selector 修复属于 M3。
- 未对失败的运行副本做自动修复，也未将定位放宽为 `确认设置.*`。
- 保留原文件，创建修正版 Excel，把 `Cases!I6` 第 3 步改为实际完整文案 `点击【确认设置(1)】`，重新导入、生成并复核。
- 修复编译器的字面选择器语义：Maestro 把字符串当正则时，编译器自动转义括号等元字符，生成 `确认设置\\(1\\)`；Excel 作者无需编写正则。
- 新旧工作簿逐单元格比对只有 `Cases!I6` 一处值差异，三个 Sheet、公式和目标样式保持不变。

### 解除结果

新 review Generation 3/3 Flow 语法检查和人工复核通过；连续 3 个真实 Run 全部 `COMPLETED`。另建 unattended Generation 并真实执行通过。`B-M2-002` 关闭，不依赖 M3 自动修复倒签 M2。

## 自动化与构建证据

- `runtime/m2-acceptance-20260920/pytest-junit-final.xml`：50 项回归全部通过。
- `runtime/m2-acceptance-20260920/corrected-generation/summary.json`：review 工作簿校验、生成、语法检查和 3/3 复核证据。
- `runtime/m2-acceptance-20260920/evidence/corrected-three-runs.json`：3 个连续 `COMPLETED` review Run。
- `runtime/m2-acceptance-20260920/evidence/corrected-credential-services.json`：三连的原值、临时关闭和 `RESTORED` 证据。
- `runtime/m2-acceptance-20260920/corrected-unattended-generation/summary.json`：unattended 自动批准并达到 `ready`。
- `runtime/m2-acceptance-20260920/evidence/unattended-real-run.json`：真实 unattended `COMPLETED` Run。
- `runtime/m2-acceptance-20260920/evidence/unattended-credential-services.json`：unattended Run 环境事务 `RESTORED`。
- `runtime/m2-acceptance-20260917/evidence/english-ime-run-1.json`：英文输入后的真实 Run 摘要。
- `runtime/m2-acceptance-20260917/evidence/post-dismiss-run-1.json`：一次性关闭遮罩后的复现摘要。
- `runtime/runs/run-20260917T075241-c20d624a7a/`：登录成功但首次密码遮罩证据。
- `runtime/runs/run-20260917T075626-650d92e199/`：遮罩重复出现证据。
- 前端 `npm run build`：production build passed。
- 本地浏览器：review 3/3 后 Run 入口可见；390×844 下 `scrollWidth=clientWidth=375`；console error/warn=0。

## M2 实现收束

- 领域层：Run/CaseRun/Attempt/RunEvent/DevicePreparation 与冻结状态机已接入真实编排。
- 应用层：通过 Protocol 端口编排仓储、设备、pytest 生成和进程执行。
- 基础设施层：设备准备、pytest 包、Maestro 子进程、JUnit/trace/日志与持久化完成。
- API/UI：创建/查询/取消 Run、Case 查询、SSE 续传和 Run 控制台完成。
- 安全控制：外部命令无 shell 拼接，进程组可取消，输出有上限且完整日志保留。
- 环境事务：临时凭据服务变更为显式 opt-in，只允许已配置 emulator，支持证据快照、异常恢复和恢复校验。
- 未进入 M2：MCP 自动诊断/定位修复、结果 Excel 回写，按冻结计划保留至 M3。

## 签收结论

M2 已满足冻结的实际模拟器执行步骤、预期结果、必需证据和阻断规则。M3 可在此基线上进入六类故障分类、Maestro MCP 页面层级诊断、受控定位修复、重试上限和 Excel 结果回写；M2 的签收不依赖这些后续能力。
