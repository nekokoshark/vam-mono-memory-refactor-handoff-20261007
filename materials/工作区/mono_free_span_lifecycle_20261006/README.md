# Mono 空闲区段生命周期重构

已正常退出后冷安装；游戏未自动启动。改造是整块空闲合并与提交储备的一体化决策，不改变GC次数。
预算内保留原选择；超预算混合区段直接合并为冷块，避免先补提交再退提交。原扩堆、4096区段、64KiB温区和256MiB储备保持。
基线/候选/副本回滚各十组真实Mono测试通过；27个区段用例中的768MiB是避免的累计往返流量，不是游戏驻留收益。

候选：MODIFIED_FILE.dll；已安装：F:/vam1.22.0.12/Mono/EmbedRuntime/mono.dll。
冷恢复16AAF：游戏正常退出后运行 `powershell -NoProfile -File install.ps1 -Mode Restore`。
`ROLLBACK.sh`只恢复/测试独立副本，不替换游戏。验证细节及准确命令见VERIFICATION.txt。
本包供当前本地工程复用，脚本依赖相邻既有模块；单DLL本身没有新增外部依赖。
原算法参考：[Mono allchblk.c](https://raw.githubusercontent.com/mono/mono/mono-2-10/libgc/allchblk.c)，实际ABI以本地DLL审计为准。
