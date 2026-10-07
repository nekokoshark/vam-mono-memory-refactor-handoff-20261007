# Mono 小对象页复用生命周期候选

Mono 小对象页取用生命周期已冷安装 D4685C71；下次自然启动生效。 本次冷恢复基线为 A1A8F07D。

## 改造对比
- 原路径：小对象需要新页时，按原空闲桶搜索，可能先取冷块。
- 新路径：先验证最多 32 个已提交空闲块提示，再交给原 nth 分配器；没有成功提示就回原完整搜索。
- 提示不拥有对象，地址按位取反；每次取用重新核对字段与双向链，原黑名单/拆分/计账继续执行。
- 原 56 个状态字段保持顺序和类型；追加 6 个计数器、32 个提示，共 94 个 64 位字。
- 原 GC、锁、对象/像素语义、扩堆和 4096 区段上限均保持。没有增加 GC、调小扩堆批量或每帧扫描。

## 证据
基线/候选/副本回滚各 13 组原 Mono 测试通过。专门复用夹具的相同分配负载新增提交为 65536/0/65536 B。
普通 warm 夹具仍为 10931 次 cold remap；一次耗时不作为加速结论。尚无游戏峰值、立即返回水位或持续增长斜率的候选实测。
现场累计退提交约 89 GiB、前缀重提交约 91 GiB，是先前 A1 会话的流量，不是物理节省或波动的完整归因。

## 文件和使用
部署产物是 MODIFIED_FILE.dll；正常退出后由本地 install.ps1 冷替换 Mono\EmbedRuntime\mono.dll。
恢复本次基线用 install.ps1 -Mode Restore；ROLLBACK.sh 只恢复独立测试副本并验证，不修改游戏。
不自动停止/启动游戏。Mono 底层更新与 VaM.Memory.dll 1.5.0 独立，本次没有修改后者。

四工件、精确测试命令/输入/原样输出/退出码及恢复状态见 VERIFICATION.txt；嵌套命令在 *_COMMANDS.json。
DLL 是单文件替换产物；源码构建、安装和复验工具复用本地相邻工程与游戏托管库，ZIP 不代表独立移植构建环境。
包位置：F:\vam1.22.0.12\Mono_Warm_Reuse_Lifecycle_20261007.zip

原源码对照：[Mono allchblk.c](https://raw.githubusercontent.com/mono/mono/mono-2-10/libgc/allchblk.c)、[隐藏指针契约](https://raw.githubusercontent.com/mono/mono/mono-2-10/libgc/include/gc.h)。实际本地 DLL 审计决定 ABI。
