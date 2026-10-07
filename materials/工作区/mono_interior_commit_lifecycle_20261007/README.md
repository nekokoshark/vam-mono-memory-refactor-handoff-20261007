# Mono 内部取用生命周期重构

原黑名单选址后，先仅拆分元数据并保留两侧冷状态，再由原共有路径按需提交。不是改GC次数或缩小扩堆。
三臂各12组通过；27内部用例和真实Windows展开检查通过。普通组累计提交4.50GiB→6.38MiB→4.50GiB，不等于游戏驻留收益。
候选A1A8F07D；已冷安装，下次自然启动生效。
`install.ps1 -Mode Install/Restore`只在游戏正常退出后替换底层DLL；`ROLLBACK.sh`仅测独立副本。
精确路径/命令/初次失败及复跑记录见VERIFICATION.txt。本地接线脚本复用相邻原工程工具；单DLL没有新增外部依赖。
参考：[原Mono区段分配源码](https://raw.githubusercontent.com/mono/mono/mono-2-10/libgc/allchblk.c)；实际ABI以AUDIT_INTERIOR.json中的本地DLL为准。
