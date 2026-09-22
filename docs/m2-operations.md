# M2 本地模拟器运行说明

## 适用范围

本说明适用于一期 Android Studio Emulator、本地 Maestro CLI 2.10.0 和单 worker pytest 执行。真机、iOS、云端设备、自动定位修复和结果 Excel 回写不在 M2 范围。

## 1. 准备专用 AVD

1. 在 Android Studio Device Manager 中确认存在 `Pixel_5`，建议至少配置 4 CPU、4096 MB 内存。
2. 启动 AVD，等待 `adb shell getprop sys.boot_completed` 返回 `1`。
3. 确认目标包存在：`adb -s emulator-5554 shell pm path aippt.com.mm`。
4. 断开 Maestro Studio。平台运行期间不得让 Studio、CLI 或 MCP 并发控制同一设备。
5. 将 Gboard 当前输入语言切到 English (US)。`Config.language=zh-CN` 表示用例语言，不等于 Android 键盘输入引擎。
6. 对专用测试 AVD 关闭自动填充/密码保存提示，或在系统设置中把默认自动填充服务设为 `None`。这会削弱该 AVD 的凭据保存能力，只应对不承载个人数据的专用测试设备执行；需要时在验收后恢复 Google 服务。

运行前可检查：

```bash
adb devices -l
adb -s emulator-5554 emu avd name
adb -s emulator-5554 shell dumpsys input_method | rg 'currentEntry='
adb -s emulator-5554 shell settings get secure autofill_service
```

期望输入法状态包含 `languageTag=en-US`。自动填充服务非 `null` 时，设备准备证据会记录 warning；若登录后出现 `Save password to Google?`，它会遮挡页面并阻断无人值守断言。

## 2. 安装与配置

```bash
python3.11 -m pip install -e '.[dev]'
export ANDROID_DEVICE_ID=emulator-5554
export AVD_NAME=Pixel_5
export MAESTRO_STARTUP_GRACE_SECONDS=180
```

`MAESTRO_STARTUP_GRACE_SECONDS` 只覆盖 Maestro Android Driver 冷启动；Excel 中的 `test_timeout_ms` 从首条 Maestro 命令真正开始时计时。两者不会互相吞占。

## 3. 执行单次验证

```bash
maestro-app-m2-verify \
  --generation-id <ready-generation-id> \
  --repeat 1 \
  --evidence runtime/m2-acceptance/single-run.json
```

执行链固定为：

```text
ready Generation
  -> 生成 pytest 包并 collect-only
  -> 准备 emulator / AVD / app
  -> pytest setup Fixtures
  -> Maestro Case
  -> pytest teardown Fixtures（逆序）
  -> 聚合 JUnit / trace / artifacts
  -> COMPLETED 或明确失败终态
```

## 4. M2 正式三连验收

```bash
maestro-app-m2-verify \
  --generation-id <ready-generation-id> \
  --repeat 3 \
  --evidence runtime/m2-acceptance/three-runs.json
```

三个独立 Run 必须全部满足：

- `state=COMPLETED`；
- pytest JUnit 与所有 Maestro JUnit 均无 failure/error；
- `FX-APP-RESET -> FX-LOGIN-READY -> TC-HOME-001` 顺序一致且各执行一次；
- 设备均为 `Pixel_5/emulator-5554`；
- 每个 Run 有独立目录、源 Excel 副本、生成 pytest、事件、日志、报告和截图/层级产物；
- 源 Excel SHA-256 不变。

任一轮失败即退出码非零，M2 不得签收；修好环境后必须重新从第 1 轮开始计数。

### 4.1 受控临时关闭凭据服务

仅在负责人明确授权、且目标为专用 `emulator-*` 测试设备时使用：

```bash
export ANDROID_DEVICE_ID=emulator-5554
export AVD_NAME=Pixel_5

maestro-app-m2-verify \
  --generation-id <ready-generation-id> \
  --repeat 3 \
  --evidence runtime/m2-acceptance/evidence/three-runs.json \
  --settings-evidence runtime/m2-acceptance/evidence/credential-services.json \
  --temporarily-disable-credential-services
```

守卫会先校验设备确为配置的 AVD，再依次执行：

1. 读取并落档 `autofill_service`、`credential_service`、`credential_service_primary` 原值；
2. 临时删除三个 secure setting，并验证读取值均为 `null`；
3. 执行全部 Run；
4. 正常结束、Run 失败、Python 异常或 `SIGTERM` 时恢复原值并逐项比对；
5. 证据终态必须为 `RESTORED`，ADB 二次读取必须与 `original_values` 完全一致。

`SIGKILL`、宿主机断电等不可捕获退出无法承诺自动恢复；证据文件在首次修改前已经保存原值，并包含人工恢复说明。不得把该开关默认化，也不得用于真机或承载个人凭据的 AVD。

## 5. Run 目录

每个 `runtime/runs/<run-id>/` 至少包含：

- `run.json`：持久化状态与 Case 汇总；
- `events/*.json`：单调递增、不可覆盖的事件；
- `source/*.xlsx`：只读来源副本；
- `generated/pytest/`、`generated/fixtures/`、`generated/cases/`：冻结执行输入；
- `reports/pytest-junit.xml`、`reports/maestro/`、`reports/flow-trace.jsonl`；
- `artifacts/device-preparation.json`、`artifacts/logs/`、`artifacts/maestro/`；
- `result/summary.json`。

## 6. 常见阻断

| 现象 | 分类 | 处理 |
| --- | --- | --- |
| 多台 emulator 在线且 Config 未指定设备 | 设备准备阻断 | 填写 `android_device_id` 或只保留一台在线 emulator |
| `Maestro Android driver did not start up in time` | 环境/资源 | 冷启动 AVD、提高 AVD CPU/内存、确认 Studio 未连接 |
| ASCII 邮箱被提交成中文 | 输入环境 | 切换 Gboard 到 English (US)，不修改用例文本或断言 |
| 登录成功后出现 `Save password to Google?` | 系统遮罩 | 在专用 AVD 关闭自动填充/密码保存服务后重新开始三连验收 |
| `确认设置` 定位不到但页面显示 `确认设置(1)` | 用例/定位契约 | M2 不做自动定位修复；按实际完整控件文案修正 Excel 并重新生成、复核，或进入 M3 的 MCP 受控定位修复 |
| setup Fixture 失败 | Fixture 阻断 | Case 不执行；已注册 teardown 仍按 pytest 规则运行 |
| 超时或取消 | 进程控制 | 平台先终止 pytest 进程组，再强制清理；检查完整日志而非只看控制台尾部 |

## 7. 参考规范

- [Maestro test output directory](https://docs.maestro.dev/cli/test-output-directory)
- [Maestro debug output](https://docs.maestro.dev/troubleshooting/debug-output)
- [Maestro device targeting](https://docs.maestro.dev/maestro-flows/flow-control-and-logic/specify-and-start-devices)
- [Maestro inputText](https://docs.maestro.dev/api-reference/commands/inputtext)
- [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
