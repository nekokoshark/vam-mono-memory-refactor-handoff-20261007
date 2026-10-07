# Mono 回收后端候选（未部署）

这版只重写整块空闲存储回收控制器，不是完整 Mono 内存管理系统重构。
小对象块分配/复用、清扫后整块合并及扩堆决策都仍是原代码；用户已明确指出这三项尚未完成。

- 原 GC 收尾调用点 `RVA 0x157ec4` 接入编译的 `reclaim_controller.c`，原标记、对象布局、根、锁、分配器和 OS 退提交/重新提交流程不变。
- 以 256 MiB 整块空闲提交储备替代固定年龄准入；不移动对象、不退混合活页、不限制总活堆、不增加游戏 GC。
- 原 Mono 隔离测试：大额退提交第 3→1→3 次 GC；真实 Windows GC 提交减量与 native unmapped 增量完全相等。活数据/固定地址/别名/并发/混合页/Dispose 通过。
- 这不是 Unity/VR 验收或实机驻留收敛结论。具体命令、输入、输出、状态及计时见 `VERIFICATION.txt`、`COMMANDS.json`、`COMPARISON.json`。
- 生产仍是 `CD7AB354…`，候选 `85DB66A5…`；尚未执行生产安装。`install.ps1` 已在另一副本验证安装/恢复，真实游戏运行时返回 pending。
- 构建：先运行 `audit_binary.py`，再 `build.py`（本机 MSVC 路径已固定）；测试用原 .NET3.5 游戏引用。
- 副本回滚：设置 `PYTHON_BIN` 与 `PYTHONPATH=F:\vam1.22.0.12\tools\pydeps`，运行可执行 `ROLLBACK.sh`。生产恢复入口是 `install.ps1 -Mode Restore`，二者不等同。
- 后续应完成其余三条实际调用链的源/二进制审计和对应改造，再作完整联动候选；不要把本版包装成三条已完成。
