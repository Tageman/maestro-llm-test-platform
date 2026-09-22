# M3 技术设计符合性审计

## 结论

M3 新增实现符合冻结的领域模型、目录结构、Flow IR、Run 状态机和前后端接口原则，并通过真实 Android 模拟器验证。M0/M1 遗留的 `TD-01～TD-03` 仍属于非阻断的渐进式目录/依赖结构偏差；M2、M3 没有扩大这些偏差。

| 冻结设计项 | M3 实现 | 结论 |
| --- | --- | --- |
| CLI/MCP 边界 | 正常执行始终为 pytest→Maestro CLI；只有 `LOCATOR` 失败后才串行启动 MCP 获取诊断证据 | 符合 |
| Flow IR/YAML 边界 | MCP 不直接写 YAML；受控修复器只替换一个非断言文本 Selector，并验证命令/顺序/断言不变 | 符合 |
| Run 状态机 | 诊断与修复使用冻结的 `DIAGNOSING`、`REPAIRING`，所有迁移与事件持久化 | 符合 |
| pytest 生命周期 | 每个重试仍由同一 pytest item 发起，完整 Fixture 链重新执行 | 符合 |
| 目录结构 | `attempts/<case>/aN`、`repairs/<case>/<repair>`、`result/` 独立留证，不覆盖前次 Attempt | 符合 |
| 源数据只读 | 源 Excel 与已批准 Generation 不覆盖；Run 复制 YAML，结果写入新工作簿 | 符合 |
| API V1 | Run summary/detail、Artifact 与结果下载加入冻结 V1 合约；未知 ID/路径逃逸被拒绝 | 符合 |
| 前端恢复 | 结果页使用持久化 Run ID 读取终态和 Case 证据，不依赖页面内临时 Generation 状态 | 符合 |

详细验收证据见 `docs/m3-status.md`。M0/M1 的历史符合性审计仍见 `docs/m0-m1-design-conformance.md`。
