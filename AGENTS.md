## Always output Chinese

## VM 调试说明

这个仓库有一台现成的 libvirt/QEMU 虚机可用于复现 `dwm` 图形问题。

- 虚机名：`ubuntu24.04`
- 默认 IP：`192.168.122.48`
- 默认用户名：`test`
- 默认密码：`test`

推荐直接使用仓库里的脚本，而不是手写一长串 ssh/scp 命令：

- 部署当前 `qemu` 配置版本到虚机：`./vm-debug.sh deploy`
- 给虚机安装复现和取证工具：`./vm-debug.sh setup-tools`
- 查看虚机状态、`dwm` 进程、日志、工具是否安装：`./vm-debug.sh status`
- 拉取当前 `dwm` 日志：`./vm-debug.sh log`
- 自动复现 `magicgrid`/`ffplay` 路径并回传产物：`./vm-debug.sh repro`

`./vm-debug.sh repro` 会把以下产物拉回本地目录 `vm-artifacts/`：

- 复现前截图
- 复现后截图
- `xwininfo -root -tree` 输出
- `wmctrl` 输出
- `/tmp/dwm.log`
- 远端复现 trace

如果虚机 IP、用户名或密码变化，可以在执行脚本前覆盖环境变量：

- `VM_IP`
- `VM_USER`
- `VM_PASS`

例如：

```sh
VM_IP=192.168.122.50 VM_USER=test VM_PASS=test ./vm-debug.sh status
```

## 这次 magicgrid 标题栏 bug 的真实根因

这次问题不是普通的 workspace 切换逻辑错误，真实根因是 `swallow` 和额外的 `titlewin` 叠加后发生了泄漏。

现象路径：

1. 进入 `magicgrid` workspace
2. 打开 terminal
3. 在 terminal 里启动 `ffplay`
4. `ffplay` 被 `swallow` 补丁吞并
5. 切到别的 workspace 后，黑色标题栏残留

原因：

- `magicgrid` 为每个 client 额外创建了一个独立的 X11 window，保存在 `Client.titlewin`
- `swallow(p, c)` 会把被吞并的子 client `c` 从 client 链表里摘掉，并把 `p->win` / `c->win` 做交换
- 但原先代码没有处理 `c->titlewin`
- 结果是：`c` 虽然不再被 `dwm` 当成正常 client 管理，但它的 `titlewin` 还留在 root window 上，变成孤儿窗口
- 后续切 workspace 时，这个孤儿 `titlewin` 不会再经过正常的 client hide/unmanage 流程，所以看起来像“标题栏一直留着”

## 最终保留的核心修复

最终只保留一个核心修复，不保留调试性改动：

- 文件：`dwm.c`
- 函数：`swallow(Client *p, Client *c)`
- 修复：在 `detach(c)` / `detachstack(c)` 之前调用 `destroytitlebar(c)`

这样做的原因很直接：

- 被吞并的子 client `c` 即将离开正常 client 管理链
- 它对应的独立标题栏 window 不能继续留在 root 上
- 在 `swallow()` 中立刻销毁它，才能从生命周期上彻底收口

也就是说，这次真正的 fix 不是“额外补更多隐藏逻辑”，而是：

- 找到 `titlewin` 生命周期真正断裂的地方
- 在 `swallow()` 里补齐清理

## 修改原则

处理这类问题时，优先保留“生命周期正确”的核心修复，避免把临时调试日志、额外兜底显隐逻辑长期留在主代码里。
