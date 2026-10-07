# Mono 分配—回收策略层联动重构

生产目标：`F:\vam1.22.0.12\Mono\EmbedRuntime\mono.dll`。保留原非移动标记器、对象地址、大小类别、TLS fast path、清扫/清零、原锁、黑名单、最大堆及 OOM 路径。

| 路径 | 新行为 |
|---|---|
| 小对象 pending reclaim 链 | 按原 marked 密度分八档，较密页优先复用；稳定保持档内顺序，原 kind 2/3 uncollectable 链不排序 |
| GC 收尾 | 原空块合并提前至退提交预算之前；原合并/VM/页头算法继续负责底层一致性 |
| 普通已退提交空块分配 | 原页头拆分与登记，仅重新提交所需前缀；尾部维持退提交。黑名单内部切分保留原路径 |
| 扩堆批量 | **已纠正上轮回归**：完整恢复原 speculative/fallback 批量，不再按碎片化空闲总量压小；适配器仅保留数值计数，4096 项区段表保持原样 |
| 整块退提交 | 保留 256MiB 整块空闲提交储备，原 unmap/remap 负责真实 VM 与原计数 |

这是分配/回收策略层重构，不是新标记器。稀疏但仍有活对象的页保留，不移动对象或合并其空槽。

## 验证

`validate.ps1 BASELINE` / `validate.ps1 MODIFIED`；设置 `PYTHON_BIN` 为记录中的 Python 后执行 `ROLLBACK.sh`，只在独立副本恢复原版本并重跑。

实际原 Mono 的 32MiB pinned、512MiB 暂存、4×32 并发、混合页/字符串/引用/25,000 Dispose；百万小对象不同密度页＋262,144 次复用；768MiB 暂存退出后300MiB新分配；原最大堆/OOM/恢复均覆盖。真实空链与原 free/unmapped 计数闭合，Windows Mono OS 提交与原 native 增量对齐。

新增原 Mono 区段压力用例：8192 个 8KiB 数组隔项退出形成洞，随后保留 50000 个 16KiB 数组。拒用版 F3F46BBA 保留 46336 项时达 3914 区段，测试在致命上限前停止；基线、修正版、回滚完成全部 50000 项、均为 82 区段，内容检查通过。实际游戏区段数未捕获，游戏加载仍需实测。`lastReturned` 同时修正为合并及退休全边界的正净退提交，避免把合并后毛退提交当 OS 净下降。

数值见 `COMPARISON.json`；精确命令/输入/输出/退出码见 `VERIFICATION.txt`。这里的差额是隔离 Mono 提交/耗时，不是游戏驻留收益。未新增显式游戏 GC；容量变化仍可能改变自动 GC 时机。

## 冷安装与恢复

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Mode Install`

恢复本轮生产基线（年龄1版本）：

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Mode Restore`

安装器检查游戏已退出、目标/来源哈希和路径，原子替换并更新运行快照。状态见 `DEPLOYMENT.json`。不会启动或结束游戏。
