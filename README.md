# Maestro + pytest + LLM APP 自动化测试平台使用说明书

| 项目 | 内容 |
| --- | --- |
| 版本 | V1.1 |
| 适用范围 | 本地 Android Studio 模拟器 |
| 说明 | 本文描述当前可用功能和已知限制；发布前请先阅读限制与排障 |

本平台读取 `Cases`、`Fixtures`、`Config` 三个 Sheet，把结构化中文步骤转换为 Flow IR，再编译为 Maestro YAML、检查语法；通过 pytest 管理前后夹具并在 Android 模拟器上实际运行。Maestro CLI 用于执行，Maestro MCP 只在可修复的文本定位失败后收集页面层级/截图并诊断。源 Excel 不修改，运行结果生成副本。

## 1. 环境搭建

### 1.1 前提与版本边界

- 已验证的环境为 macOS、本地 Android Studio 模拟器 `Pixel_5`、Maestro CLI `2.10.0`、目标包 `aippt.com.mm`；其他系统/版本尚未验证。准备 Python 3.11、Node.js/npm、Android SDK 的 `adb` 与 `emulator` 命令、Maestro CLI，以及目标 App APK 或预装包。
- 创建或启动一台 Android AVD，确认启动完成且包名与 Excel `app_id` 相同。当前只支持模拟器；本地真机、iOS、云设备和并发控制多台设备不在一期范围。
- 平台运行时断开 Maestro Studio 对同一模拟器的连接；不要同时让其他 Maestro CLI/MCP 操作该设备。
- 用测试账号和专用 AVD；用例输入的账号、YAML、截图、日志和结果文件会保存在本地。输入 ASCII 账号/密码时，先确认模拟器输入法能正确输入英文字符。密码管理器或系统弹窗可能遮挡目标控件，不建议将关闭凭据服务作为普通运行的默认步骤。

### 1.2 安装和检查

在项目根目录 `maestro-llm-test-platform/` 执行：

```bash
python3.11 -m pip install -e '.[dev]'
npm --prefix frontend ci
python3.11 --version
node --version
npm --version
maestro --version
adb devices -l
emulator -list-avds
```

安装依赖通常只需首次或依赖变更时执行；版本/设备检查用于初次配置和排障，不必每次重复。若 `python3.11` 命令不可用，使用本机指向 Python 3.11 的命令；切勿在未确认解释器版本时混用系统 Python。`adb devices -l` 应列出状态为 `device` 的 `emulator-...`；`emulator -list-avds` 应包含 Config 中的 `avd_name`。若终端提示 `emulator: command not found`，把 Android SDK 的 `emulator/` 加入 `PATH`，或直接使用其绝对路径；平台也可通过 `EMULATOR_COMMAND` 指定绝对路径。如目标包已安装，可用 `adb -s <device_id> shell pm path <app_id>` 验证；否则在 Excel Config 提供可读的 APK 路径，由设备准备阶段安装。

### 1.3 环境变量与启动

后端读取进程环境变量，不会自动加载 `.env`。可从[变量示例](.env.example)复制所需值并通过终端或进程管理器导出。最低需要保证 `MAESTRO_COMMAND`、`ADB_COMMAND`、`EMULATOR_COMMAND` 可找到各自可执行文件，`APP_ID`/`AVD_NAME` 与 Excel 一致。示例：

```bash
export APP_ID=aippt.com.mm
export AVD_NAME=Pixel_5
export RUNTIME_DIR=./runtime
make dev PYTHON=python3.11
```

若程序找不到工具，再额外导出 `MAESTRO_COMMAND`、`ADB_COMMAND`、`EMULATOR_COMMAND` 的绝对路径。`ANDROID_DEVICE_ID` 可在只有一台在线模拟器时留空；有多台时在 Excel Config 中指定目标 ID。`LLM_BASE_URL`、`LLM_MODEL` 及可选 `LLM_API_KEY` 配齐后使用兼容结构化输出的 LLM；不配置时使用离线规则翻译器，只接受下文的固定中文句式。LLM 只生成 IR，YAML 始终由平台编译器生成；不要把 API Key 填入 Excel。`RUNTIME_DIR` 决定服务端的工作簿、生成物和 Run 产物根目录。

浏览器访问 `http://127.0.0.1:5173`；`http://127.0.0.1:8000/api/v1/health` 应返回健康响应。服务运行时保持该终端打开，用 `Ctrl+C` 停止。每次使用 Web 页面都需重新启动服务；`export` 只在当前终端会话生效，可按需要持久配置。验证当前代码可运行 `make verify PYTHON=python3.11`；不要让默认 `python3` 意外指向未安装依赖的解释器。

## 2. 填写 Excel 与执行

1. 从项目外的原始 Excel 模板复制一份（原始示例可能含测试账号，不随公开代码提交），保留 `Cases`、`Fixtures`、`Config` 名称与第 5 行表头。从第 6 行填业务数据；不要填写结果列。原始模板用于示范，不应直接覆盖历史验收证据。
2. 在 `Config` 填项目包名、Maestro 可执行文件、目标模拟器、超时及修复上限。`maestro_command` 是本机 CLI 命令或绝对路径，不是 YAML API 地址。`launch_clear_state` 控制默认启动；显式启动/清状态步骤优先，见第 4 节。
3. 在 `Fixtures` 定义前置/后置步骤和依赖；在 `Cases` 引用直接需要的夹具。若 `FX-LOGIN-READY` 依赖 `FX-APP-RESET`，Case 只写 `FX-LOGIN-READY`，平台会自动展开、去重并先执行 reset。依赖关系优先于同层的 `执行顺序` 数值；后置清理按逆序执行。依赖缺失、停用、跨阶段或成环会阻断。
4. 在 Web 页面上传 `.xlsx`。先检查启用 Case/Fixture 数、Config 数、每个问题的 Sheet/行/列和 Fixture 计划。`error` 必须修好并重新上传；出现 `warning` 时应走人工复核。
5. 选择“人工预览”或“无人值守”，点击“生成全部 IR 与 YAML”。人工预览可逐 Flow 查看源步骤→IR/命令→选择器/断言→完整 YAML 和语法结果，逐项确认；“批量确认无警告项”不会代替有 warning 项的人工复核。全部获准后 Generation 才变为 `ready`。无人值守仅自动批准语法通过且无 warning 的 Flow；有 warning 时暂停在待确认状态，逐项人工复核后仍可沿用原模式执行。旧版带 warning、但无人工确认来源的批准必须重新复核。无人值守生成后仍需手动点击下一步启动 Run。
6. 点击“连接模拟器并执行”。平台检查设备/包，生成 pytest 用例及夹具，Maestro CLI 在模拟器上运行。`LOCATOR` 失败仅在 MCP 页面证据存在唯一文本候选时，才受控修改失败步骤的 Selector、检查语法并从完整前置 Fixture 链重跑；断言/环境/夹具/超时/未知错误不会被自动改写。
7. 在“真实执行控制台”观察 Run/Case/Attempt/Repair；终态后下载“结果 Excel”和 Artifact，查看 HTML 报告。浏览器刷新可用 `http://127.0.0.1:5173/?run=<run_id>` 重开已持久化 Run。`COMPLETED` 表示全部 Case 通过；`COMPLETED_WITH_FAILURES` 表示流程结束但有业务失败；`FAILED` 表示 Run 级错误；`CANCELLED` 为安全终止。
8. 另行检查控制台的导出状态：`pending` 为导出中，`completed` 为交付副本已写入 `output_dir/<run_id>/`，`failed` 为导出失败。导出失败不改变用例结果，也不会删除 runtime 中的原始证据；“Case 全部通过”不等于“已成功导出”。目标目录必须可写，已有 Run 目录不覆盖。副本中的 `export-manifest.json` 记录文件哈希；若存在 `.export-incomplete`，不得当作完整交付。副本是交付时快照，`result/summary.json` 保留导出前的执行结果；最新导出状态以 `run.json` / API 为准，后续导出完成事件仅记录在服务端权威 Run 中。

## 3. 用例编写规范与夹具逻辑

每个非空步骤单独一行，以 `1. `、`2. ` 或 `1、`、`2、` 连续编号。`【】` 内写页面上可见的准确文案。例如 `点击【登录】按钮` 会映射为文本选择器的 `tapOn: "登录"`；不要把“登录按钮”四字当成文案。离线规则翻译器支持：

| Excel 步骤/预期示例 | 目标语义 |
| --- | --- |
| `1. 清除APP状态并启动APP` | `launchApp`，清状态并停止旧进程；适合 reset 夹具 |
| `1. 点击【登录】按钮` 或 `1. 点击【邮箱】输入框` | `tapOn` 该文案 |
| `2. 输入【test-user@example.invalid】` | `inputText`；此前必须有点击输入框步骤；这是不可投递的示例地址 |
| `3. 向下滑动直到显示【提交】` | `scrollUntilVisible` |
| `4. 点击系统返回` | `back` |
| 预期 `1. 页面显示【欢迎】` | `assertVisible` |
| 预期 `1. 页面不显示【错误提示】` | `assertNotVisible` |
| 预期 `1. 【页数】当前值显示为【3】` | 对值 `3` 做可见性断言；不是绑定特定控件 ID 的属性断言 |

文字描述必须可观察、可映射。`页面正常`、`操作成功`、绝对坐标等会被阻断；不支持的句式在生成阶段失败，需改写 Excel 或配置可用的 LLM 翻译器。LLM 也只生成受 Schema/白名单约束的 IR，不能绕过编译器插入任意 Maestro 命令。文本选择器不唯一时应改进用例文案或页面可访问性；一期自动修复不会改断言、生成坐标或凭图像猜目标。

`Fixtures.阶段` 为“前置”或“后置”；`作用域` 为“用例”“模块”“会话”，映射到 pytest 的 function/module/session。用例级每个 Attempt 执行；模块级按 `Cases.模块` 跨 Case 复用；会话级跨本次 Run 的 Case 复用。包含共享夹具时使用同一 pytest 工作进程，并按模块首次出现顺序分组执行，模块内保持原顺序。Fixture 的“模块”列是分类说明，不决定缓存边界。

定位修复重试前会结束旧共享作用域，再为该 Case 重建完整夹具链；后续 Case 共享新一轮初始化，所以有重试时，会话夹具不保证全 Run 只执行一次。共享清理失败会回溯影响该作用域消费者；进程中断时清理结果标为未知，不报告成功。

`Fixtures.依赖夹具ID` 只写直接依赖，间接依赖由平台计算；依赖须存在、启用且同阶段，宽作用域不能依赖窄作用域（会话不能依赖模块/用例，模块不能依赖用例）。共享运行的默认启动每轮只执行一次；显式启动/清状态夹具须位于最宽作用域，且所有所选 Case 引用一致，禁止 Case 或更短作用域重启破坏共享状态。只有用例级夹具时仍按独立 Attempt 启动。

`Cases.前置夹具ID` 和 `后置夹具ID` 可按 Config 的单字符分隔符填写多个（当前基线是半角 `;`）。`标签` 固定用半角 `;`，如 `smoke;home`，供分类/筛选，不决定执行顺序；不要使用中文分号、中文逗号或英文逗号。

## 4. 字段解释

### 4.1 `Cases`（第 5 行表头，A～Y）

| 列/字段 | 如何填写或读取 |
| --- | --- |
| A 用例ID | 必填，全工作簿唯一；字母开头，只能用字母、数字、`_`、`-`，如 `TC-HOME-001` |
| B 模块 | 必填，业务模块名称 |
| C 标题 | 必填，简洁描述验证点 |
| D 前置夹具ID | 可空；直接引用前置 Fixture ID，多个用 `fixture_id_separator` 分隔 |
| E 后置夹具ID | 可空；直接引用后置 Fixture ID，多个用同一分隔符 |
| F 优先级 | 必填，`P0`、`P1`、`P2`、`P3`；当前用于元数据，不自动改变执行顺序 |
| G 标签 | 可空；半角 `;` 分隔，如 `smoke;home`，不得重复 |
| H 是否启用 | 必填，`是`/`否`；只有启用 Case 被执行 |
| I 操作步骤 | 必填，连续编号，使用第 3 节支持的句式 |
| J 预期结果 | 必填，连续编号，写明确可见/不可见断言 |
| K 生成状态 | 输出列；结果副本中表示已生成 |
| L 初始YAML文件 | 输出列；Run 内初始 Case YAML 相对路径 |
| M 执行状态 | 输出列；`PASSED`、`FAILED`、`BLOCKED`、`FIXTURE_FAILED`、`ENV_ERROR`、`TIMEOUT` 等 Case 状态 |
| N 执行次数 | 输出列；该 Case 的 Attempt 数，含首次执行 |
| O 自动修复次数 | 输出列；该 Case 的受控 Repair 数 |
| P 失败步骤 | 输出列；最近一次失败的源步骤编号；若修复后通过仍可能保留先前失败信息 |
| Q 失败类型 | 输出列；最近一次失败类型，如 `LOCATOR`、`ASSERTION` |
| R 失败原因 | 输出列；最近一次失败原因，不等于最终 Case 一定失败 |
| S 最终YAML文件 | 输出列；Run 内当前最终 Case YAML 相对路径 |
| T 报告路径 | 输出列；与该 Case 关联的 pytest/Maestro JUnit 相对路径 |
| U 截图/日志路径 | 输出列；该 Case 关联证据的相对路径，多条换行分隔 |
| V 开始时间 | 输出列；结果副本中以 UTC 写入的时间 |
| W 结束时间 | 输出列；同上 |
| X 执行耗时(秒) | 输出列；Case 执行耗时 |
| Y 备注 | 可空；人工说明，不影响翻译或执行 |

### 4.2 `Fixtures`（第 5 行表头，A～R）

| 列/字段 | 如何填写或读取 |
| --- | --- |
| A 夹具ID | 必填，全工作簿唯一，ID 规则与 Case 相同，如 `FX-LOGIN-READY` |
| B 标题 | 必填，夹具目的 |
| C 阶段 | 必填，`前置`/`后置` |
| D 作用域 | 必填，`用例`/`模块`/`会话` |
| E 模块 | 可空，夹具所属业务模块；目前作为元数据 |
| F 依赖夹具ID | 可空；多个按 `fixture_id_separator` 分隔，不能自依赖/成环/跨阶段依赖 |
| G 执行顺序 | 必填，整数；仅在依赖约束允许的同层候选间决定先后，同值按 ID 稳定排序 |
| H 是否启用 | 必填，`是`/`否`；启用夹具不能依赖停用夹具 |
| I 操作步骤 | 必填，连续编号，规则同 Case |
| J 预期结果 | 必填，连续编号，规则同 Case |
| K 生成状态 | 模板预留结果列；当前结果副本尚不逐夹具回写 |
| L YAML文件 | 同上 |
| M 执行状态 | 同上 |
| N 自动修复次数 | 同上 |
| O 失败类型 | 同上 |
| P 失败原因 | 同上 |
| Q 最后执行时间 | 同上 |
| R 备注 | 可空；人工说明 |

夹具的实际执行证据请在 Run 的 trace、Attempt JUnit/日志和 Artifact 中查看。K～Q 当前不回写。

### 4.3 `Config`（第 5 行表头，A～E）

`A 配置项`为固定键，`B 值`为用户填写值，`C 必填`记录模板要求，`D 说明`/`E 示例`是说明文字。19 个配置键必须保留；只有 `apk_path`、`android_device_id`、`avd_name` 的值可以留空。布尔值写半角 `true`/`false`，整数写非负十进制数字（超时必须大于 0，总 Attempt 至少 1）。

| 配置项 | 含义及填写规则 |
| --- | --- |
| `project_name` | 项目名称，非空 |
| `app_id` | Android 包名，必须与目标 App 一致；基线 `aippt.com.mm` |
| `apk_path` | 可空；未预装 App 时填写本机可读 APK 路径 |
| `android_device_id` | 可空；多个在线模拟器时填写目标 `emulator-...` ID |
| `avd_name` | 可空；无在线设备而需启动 AVD 时提供名称，如 `Pixel_5` |
| `maestro_command` | Maestro CLI 可执行文件名或绝对路径，如 `/absolute/path/to/maestro`；不是 Maestro YAML API 地址 |
| `execution_target` | 一期固定 `android_emulator` |
| `output_dir` | 交付导出根目录，支持用户指定的绝对目录；相对目录以本项目根目录为基准。导出到 `<output_dir>/<run_id>/`，已有目录不覆盖；拒绝 `..`、符号链接和与 Run 重叠的路径。权威证据仍在 `RUNTIME_DIR/runs/<run_id>/` |
| `test_timeout_ms` | 单 Flow 超时毫秒，必须大于 0；基线 120000 |
| `max_syntax_repair` | 生成阶段语法修复次数上限，≥0；基线 3 |
| `max_locator_repair` | 执行阶段文本定位修复次数上限，≥0；基线 2 |
| `max_total_run_attempts` | 每 Case 总执行次数上限，含第一次，≥1；基线 3 |
| `continue_on_failure` | `false`：当前 Case 的后置清理及允许修复全部完成后，若仍未通过，后续 Case 标记 `BLOCKED`、执行次数 0；修复后通过则继续。`true` 继续后续独立 Case。取消始终优先 |
| `launch_clear_state` | 每个隔离 Attempt 的默认启动是否清 App 状态。前置链或 Case 中已有显式启动/清状态命令时，由显式步骤接管，不改写、不重复执行默认启动；否则在前置夹具前执行系统启动 Flow。`false` 表示默认启动但不清状态 |
| `pytest_workers` | 一期固定 `1`，禁止同设备并发 |
| `result_writeback` | `true` 在 Run 终态生成结果 Excel 副本；`false` 不生成该副本 |
| `language` | 一期固定 `zh-CN`，指用例描述语言，不是模拟器键盘布局 |
| `fixture_id_separator` | 夹具 ID 列表的单字符分隔符；基线半角 `;`；`标签`仍固定使用半角 `;` |
| `allow_assertion_rewrite` | 一期必须为 `false`；禁止自动修改预期断言 |

`Config` 表后面的编写规范/说明行不是配置键，也不会作为运行指令解析。当前仅定位失败可自动修复；模板中若写“环境错误仅重试”，不要据此期待平台自动环境重试。

## 5. 结果、限制与排障

- Run 目录在 `RUNTIME_DIR/runs/<run_id>/`；结果 Excel 在其 `result/` 中，源 Excel 位于只读导入快照且 SHA-256 应不变。结果副本回写 `Cases` K～X 和 `Fixtures` K～Q；夹具显示最后一次实际执行结果，完整历史留在 trace。`NOT_RUN`/`DISABLED` 不代表成功，开始但无结束证据为 `INTERRUPTED`。写回 manifest 记录两类校验行和夹具执行计数。
- 上传失败：检查三个 Sheet 名、第 5 行表头、必填列、ID 唯一性、半角分隔符、夹具 DAG 和不可观察预期。根据页面上的 Sheet/行/列定位修改，再重新上传；不要修改已导入的源快照。
- 生成失败：检查步骤编号及第 3 节固定句式，查看 Flow 语法输出；LLM 未配置时无法理解任意自然语言。语法修复达到上限后不能批准 Flow。
- 无人值守出现 warning：生成进入待确认状态，逐个复核并批准后才能执行；无需改变原请求模式。旧版带 warning、但没有人工确认来源的批准会被要求重新复核。
- 设备准备失败：检查 `adb devices -l`、`emulator -list-avds`、`app_id`/`apk_path`、指定的 `android_device_id`；确保 Maestro Studio 已断开。离线、多个未指定设备、包不存在会阻断真实执行。
- 运行中失败：在 Case→Attempt 查看失败类型、失败步骤、JUnit、日志与截图。`LOCATOR` 只有唯一候选和完整 MCP 证据才会尝试修复；`ASSERTION` 需人工核对业务预期/应用行为，不能靠平台改断言。环境/Fixture/超时问题先修复环境或用例，再创建新 Generation/Run。
- 后端意外退出：服务启动或创建新 Run 前进行恢复检查。已完成 Run 保持结果；新版未完成 Run 在其工作进程清理后安全终止，不自动续跑、修复、写回或重复导出。活动 Case 的业务/清理结果不能确认时标为 unknown，未执行 Case 为 BLOCKED。按 Run ID 查看原因，并下载恢复快照/报告后再新建 Run。
- 出现 `RUNTIME_BUSY`：同一个 `RUNTIME_DIR` 仍被其他服务或清理中的守护进程占用。等待清理结束再重试；不要删除 `.execution.lock`，也不要切换 runtime 来绕过同一设备的串行限制。
- 出现 `LEGACY_PROCESS_CHECK_REQUIRED`：旧版 Run 缺少可验证的进程所有权。人工核查并停止属于该旧 Run 的 pytest/Maestro/MCP 进程、确认设备状态后，在项目根目录、使用与 Web 相同的 `RUNTIME_DIR` 执行 `python3.11 -m maestro_app.cli.recover --run-id <旧RunID> --confirm-no-owned-processes`。该命令只记录人工确认，不代为检查或杀进程，不能在未核查时执行。既有模拟器与 ADB 服务不会因测试工作进程清理而被自动关闭。

本说明书描述当前实现；已知限制已经在对应步骤标明。升级后请重新核对这些限制与实际版本是否一致。
