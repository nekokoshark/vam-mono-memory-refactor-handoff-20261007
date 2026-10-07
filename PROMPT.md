# 给接手 AI 的任务提示词

你接手 VaM 1.22.0.12 的 Mono 内存管理重构。先读取 README.md、HANDOFF_INDEX.json 和重点原始证据，再读实际 DLL、控制器及原方法夹具；不要从结论反推修改，更不要把重试成功当成故障已修复。

## 用户目标与约束
- 用户持续操作：LDR 一人场景换一次固定人物 → Westo 三人场景换两次人物 → 返回同一 LDR 固定外观换一次人物。第一趟 Westo 多预热两个人物，不等于持续泄漏。当前每趟物理占用仍涨约 2%–3%，不是严格同一 PID 的精确新增字节。
- 目标是真正重构分配、持有、复用、清扫及归还生命周期，连续操作首次完成点的水位/斜率下降，并兼顾切换卡顿。长待机后的下降不算收益；不靠强制 GC、更多 GC 次数或扩大观察记录掩盖问题。
- 保留真实消费者、地址/内容、对象身份、原标记器、原 allocator 锁、黑名单、原扩堆决策及 4096 区段上限；不为了降数值忽略 native 栈根或内部指针。
- 保留人物池/锁、画质、纹理格式/mip/readability/CPU 像素访问、服装模拟、必要插件的公开语义；不清正计数资源、不共享可变 Formula/数组、不牺牲必要衣发。
- 不自动关闭、启动或重启游戏，不自动切场景/换人/换衣。底层 DLL 只在用户正常退出后冷替换；任何安装先有稳定验证和回滚。
- 单 VaM.Memory.dll 仍为 1.5.0，SHA256=300d8335a2faedd473a09a0cb27c28df519413ffadf6c4e555f6a3b673278da8；不要另起并行静态管理表或改部署配置。

## 实际状态（重点）
1. 生产 Mono：D4685C71，全哈希 d4685c71704ef7f222feebfb93851d7f3b6d354998c2e6bc8347268e047c7b3d。
2. 精确 pending-reclaim 排序候选：427AAB71，全哈希 427aab71b5b751507ee8165869baeee6ca2a021c852691a942bc971967a1ce35。未部署，RELEASE_GATE.approved=false。
3. D4 温提示确实运行，历史 PID6052 快照 hit 15,844,611；累计 decommit 135,186,726,912 / remapPrefix 139,325,820,928 字节是流量，不是占用下降。PID/地址仅属于历史进程，不能拿去操作新进程。
4. 候选只把八档密度换成同 (kind,size) 实际标记数稳定降序，513 个计数桶。原 94 状态字保留，追加 3 计数 + 1026 取反地址暂存；7 个原钩子保持，原标记/清扫/合并/扩堆不变。排序原方法夹具同档逆序14→0→14，最新三臂各14项通过，不是游戏收益。
5. 候选此前两次原 lifecycle 夹具在释放768MiB数组、做原3次GC后仍保留，替换300MiB时扩堆，原 `avoided > 64MiB` 断言失败：AssertionError:0，exit1。D4 用相同修改臂观察也失败；字节快照/独立观察线程不稳定，尚未解释最初两次无探针故障。
6. CAPTURED_STALE_ROOT_FAILURE.json 是另一份**受控初始根后的真实失败**：GC1 明确保持 C 栈根；该槽清零后，GC2/GC3 主线程65580原扫描区间仍各见4个数组基址+1/+2等残留值，static=null、weak=alive，原断言仍0失败。这说明这次对照有保守栈根；不证明最初两次同因，更不解释游戏每趟2GB。
7. 原 GC 栈记录器只在隔离进程改原 call 0x15a038→GC_push_all 0x15b240 的调用路径，记录实际扫描区间，再交回原函数。退出后原5字节恢复；未进游戏。最近六个校准：无根清弱、有持续根保留并预期断言失败；一次短根通常结束后回收，但历史已抓到短根结束后残留。禁止把“测试根结束”误当成“全部保守副本已消失”。

## 你接下来必须完成的工作
A. 核查记录器自身是否制造/放大了根：原函数ABI、shadow space、栈扫描冷热端、callee/caller保存寄存器、返回RAX/其他易失寄存器、ctypes/libffi观察临时值、弱句柄读取的短期引用、线程Join与真实native退出、探针locals的覆盖范围。直接审计实际机器码；不要猜 RVA 或把所有残留叫碎片。
B. 将记录接到**早先原失败调用形状**，捕获自然失败时数组的真实根/标记状态；保留原输入、原3次GC和全部原断言。改观察方式必须给出互换对照，不能把成功重试替代解释。
C. 对比D4与候选：如果两者同因是夹具保守根污染，修夹具/观察生命周期而非通过删根修Mono；如果确有候选 ABI/工作区/原生生命周期回归，修根因并继续禁止部署。512位标记、原数组/地址/锁/异常及黑名单原语义不可削弱。
D. 完成边界证明之后，选择能影响持续增长的系统性分配/复用/退休切片。精确排序可能仅改善密度，量级不足时不要因代码已写就发布，也不要把自然GC容量、提交与驻留相减指定原因。
E. 基线/候选/独立副本回滚验证，原方法及真实Mono执行，失败记录保留；连续操作峰值、首次返回水位/斜率和耗时 A/B 才是游戏收益证据。不得新增协议替身并标成Unity/Mono通过。

## 阅读顺序
- materials/工作区/mono_exact_reclaim_20261007/ROOT_FINDINGS.md
- 同目录 CAPTURED_STALE_ROOT_FAILURE.json、CAPTURED_STALE_ROOT_STATUS.json、INITIAL_MODIFIED_LARGE_RETAINED_*、DIAGNOSTIC_D4_MODIFIED_LIFECYCLE_TRACE.json、ROOT_CASES.json、VERIFICATION.txt、RELEASE_GATE.json
- root_probe.c、diagnose_roots.py、trace_root_cases.py、root_scan.py、run_case.py、reclaim_controller.c、build.py、verify.py、DIFF_FILE.patch、PATCH.json
- materials/工作区/mono_allocator_lifecycle_20261006/LifecycleSample.cs，以及 mono_interior_commit_lifecycle_20261007/lifecycle_test.py（真实原方法输入和未削弱断言）
- 当前D4源码/PE构建依赖、其余原方法测试及参考DLL；完整位置见 HANDOFF_INDEX.json。

## 环境与交付
- 本包带真实 Windows x64 Mono、mscorlib/必要managed参考、原方法helper源码与DLL、原生记录器源码/DLL、pefile/capstone工具及主要构建依赖。不带Python解释器或MSVC安装。
- 需要 Windows x64、64位Python、相应MSVC与csc。仓库浏览可直接读 materials 的源码/JSON；完整二进制从ZIP解压。仅Linux/无原Mono执行器时如实做静态审计，不伪造 native PASS、驻留或收益，也不要声称包里缺少DLL。
- 保持快照原样，在隔离副本复现；QUICKSTART.ps1可在副本设置PYTHONPATH，不依赖原管理员Python绝对路径。历史 CERTIFY.ps1 的硬编码路径仍保留作为原证据，迁移时用原 validate.py 而不改断言。
- 交付：一份简短根因/未决说明、精确字段/分支修改和源代码、构建/验证工具，原方法三臂精确命令/输入/字面输出/退出状态，原哈希与独立回滚证据。明确实测、模型、累计流量和未知项；无需给小收益方向堆长文档。
- 候选批准前不安装；不要运行历史 install/deploy/commit脚本。若需要重构上线，提供冷替换包与用户退出门槛，不自行操纵游戏。
