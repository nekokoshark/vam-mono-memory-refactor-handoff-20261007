# Mono 队列复用候选

重构 order_reclaim：按 kind/size 独立核查、按已注册堆页数限制遍历、同密度链跳过重排。
四项原策略及应用 DLL1.5.0 保持，测试详情见 VERIFICATION.txt。
用户正常退出后已冷安装并核验81项快照；下次自然启动加载。尚无游戏内存收益结论。

游戏正常退出后，在此目录运行 `powershell -NoProfile -File install.ps1 -Mode Install`。
冷恢复1C使用 `-Mode Restore`。安装器复用相邻已审查工具并更新运行快照。
`ROLLBACK.sh`只恢复并测试独立副本，保留候选；它不替换游戏。
新版本自然启动后的固定字段采样：`python capture.py PID`，不调用游戏方法或扫描对象内容。
