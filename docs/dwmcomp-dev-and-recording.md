# `dwmcomp` 开发、测试与 60fps 录屏验证指南

本文档面向后续维护或开发本仓库的同事，说明轻量 X11 合成器 `tools/dwmcomp.c` 的设计原理、本地开发调试方法，以及如何在 `ubuntu24.04` 虚机中自动录制 60fps 视频并做逐帧验证。

---

## 1. 背景与解决的问题

在原生 X11 + `dwm`（无合成器或运行普通 `picom`）环境下，窗口布局与客户端渲染是异步的，容易出现肉眼可见的闪烁：

1. **分屏开窗闪烁（1 → 2）**：打开第二个 Alacritty 时，`dwm` 先把第一个窗口缩到右半屏并映射新窗口，但新窗口（OpenGL + 32-bit ARGB）还需要 1~5 帧（宿主机约 16ms、虚机软件渲染约 83ms）才能完成首帧绘制，中间会短暂露出半边桌面背景。
2. **关窗闪烁（2 → 1）**：关闭一个平铺窗口时，该窗口先从屏幕上消失，几毫秒后 `dwm` 才将剩余窗口放大回全屏，期间会露出一瞬半边背景。
3. **空 workspace 开窗闪烁（0 → 1）**：新窗口刚映射时若放行了服务端初始 damage、局部小尺寸帧或未画完的透明帧，会出现首帧跳变或闪烁。

我们选择实现一个独立的轻量 X11 合成器 `tools/dwmcomp.c`，而不是侵入式修改 `dwm.c`：

- **完全解耦 `dwm`**：无需修改或重启 `dwm`，直接启动/停止 `tools/dwmcomp` 即可热生效或回退。
- **双边原子同步**：开窗、缩放、关窗时冻结前台输出，等新旧窗口均在后台离屏绘制完毕后，再通过双缓冲单帧原子呈现在屏幕上。

---

## 2. `tools/dwmcomp.c` 核心实现速览

核心代码集中在 `tools/dwmcomp.c`（基于 `XComposite`、`XDamage`、`XFixes`、`XRender`、`XShape`）：

- **双缓冲离屏合成**：通过 `XCompositeRedirectSubwindows(..., CompositeRedirectManual)` 接管子窗口，渲染至离屏 `back_pic`，最后单次 `XRenderComposite` 呈现到 Composite Overlay Window（并把 Overlay 的 `ShapeInput` 设为空区域以透传所有鼠标事件）。
- **壁纸与异形窗口支持**：
  - 读取 root 的 `_XROOTPMAP_ID` / `ESETROOT_PMAP_ID`（设置 `RepeatNormal`）绘制桌面壁纸；
  - 对每个窗口应用 `XFixesCreateRegionFromWindow(..., WindowRegionBounding)` 裁剪，兼容 `dwm` 的 XShape 蓝色点阵 `focusoverlay` 等异形窗口。
- **原子帧冻结与解冻机制**：
  - **开窗（`MapNotify`）**：标记 `waiting_paint = 1`，同步并排空该窗口的初始服务端 damage（`drain_win_damage`）；直到收到**覆盖完整窗口面积**且（对 32-bit ARGB 窗口）**中心与右下角 alpha 均非 0** 的客户端绘制 `DamageNotify` 后才解冻。
  - **缩放（`ConfigureNotify` 尺寸变化）**：释放旧 pixmap，同样将缩放中的可见窗口置为 `waiting_paint = 1` 并排空初始 damage，同时在窗口缩小时启动短合并窗口（`SHRINK_COALESCE_MS = 16ms`），确保紧随其后的新窗口 `MapNotify` 合并进同一帧。
  - **关窗（`UnmapNotify` / `DestroyNotify`）**：若关闭的是屏幕内普通窗口且仍有其他可见窗口，触发 `UNMAP_COALESCE_MS = 35ms` 合并等待，由 `dwm` 放大剩余窗口后的 `ConfigureNotify` 接力冻结直到重绘完毕。
  - **绘制前竞态守卫（`paint_all`）**：绘制前先 `XGrabServer` + `XSync`，若发现 `XPending(dpy) > 0`（说明 `dwm` 已在服务端发出新的 `Configure`/`Map`/`Unmap` 尚未被消费），立即放弃本次绘制并先消费事件进入冻结，彻底杜绝半屏撕裂/错位帧。
  - **超时兜底**：`FREEZE_TIMEOUT_MS = 200ms`、`RESIZE_TIMEOUT_MS = 140ms`，防止异常客户端卡死画面。

---

## 3. 本地编译与宿主机开发调试

### 3.1 编译依赖（Debian / Ubuntu）

```sh
sudo apt-get install -y \
  libxcomposite-dev libxdamage-dev libxfixes-dev libxrender-dev libxext-dev libx11-dev
```

### 3.2 编译

```sh
make dwmcomp
```

产物位于 `tools/dwmcomp`（已加入 `.gitignore`，不会提交到 Git）。`Makefile` 会在链接前先 `rm -f tools/dwmcomp`，因此即使宿主机当前正在运行旧版 `dwmcomp`，重新编译也不会报 `Text file busy`。

### 3.3 宿主机热启动与日志调试

不需要重启 `dwm`（注意：X11 同一时间只能运行一个合成器，若正在运行 `picom` 需先停掉）：

```sh
pkill picom || true
pkill dwmcomp || true
./tools/dwmcomp -v
```

加上 `-v` 后，终端会输出每一次冻结、合并与解冻的毫秒级日志，便于定位新场景问题。正常的一次 1 → 2 分屏与 2 → 1 关窗日志类似：

```text
dwmcomp: freeze on resize win=0x2200003 geom=555x763+709+21 t=2629591
dwmcomp: freeze on map win=0x2c00003 geom=681x763+0+21 argb=1 t=2629591
dwmcomp: unfreeze win=0x2200003 on damage#1 area=555x763+0+0 dt=8ms t=2629599
dwmcomp: unfreeze win=0x2c00003 on damage#1 area=681x763+0+0 dt=17ms t=2629608
dwmcomp: coalesce on unmap win=0x2c00003 until=+35ms t=2630704
dwmcomp: freeze on resize win=0x2200003 geom=1280x779+0+21 t=2630704
dwmcomp: unfreeze win=0x2200003 on damage#1 area=1280x779+0+0 dt=7ms t=2630711
```

如果看到 `unfreeze ... on timeout`，说明某类应用未触发预期 `DamageNotify` 或未满足全区域/非透明校验，可据此调整判定条件。按 `Ctrl+C` 或 `pkill dwmcomp` 会优雅释放 Overlay 并恢复原生 X11 直出。

---

## 4. 虚机（VM）60fps 自动化录屏流程

闪屏问题在宿主机 GPU 下往往只持续 **1 帧（~16.7ms）**，在虚机软件渲染下会放大到 **5 帧（~83ms）**，且便于自动化回归验证。仓库已封装好虚机 60fps 录屏测试链路：

- 控制入口：`tests/vm-debug.sh`（子命令 `flash-repro`）
- 远端录屏脚本：`tests/repro-alacritty-flash-remote.sh`

### 4.1 准备虚机

```sh
# 1. 如虚机未启动，先启动 ubuntu24.04
virsh start ubuntu24.04

# 2. 等待约 15 秒自动登录进入 dwm 后，检查状态与工具
./tests/vm-debug.sh status

# 3. 如需确认虚机运行的是当前仓库最新未修改版 dwm
./tests/vm-debug.sh deploy
```

> 若虚机尚未安装录屏与 X11 调试工具，执行一次 `./tests/vm-debug.sh setup-tools` 即可（会安装 `ffmpeg`、`xdotool`、`wmctrl`、`scrot`、`x11-utils`、`python3-xlib` 等）。

### 4.2 一键录制 60fps 对比视频

命令格式：

```sh
./tests/vm-debug.sh flash-repro <mode> <输出mp4文件名>
```

视频与日志会自动拉回到本地 `vm-artifacts/` 目录。常用测试模式：

| 模式 (`mode`) | 说明 | 推荐命令 |
| :--- | :--- | :--- |
| `baseline` | 无合成器基线，稳定复现 5 帧露背景闪烁 | `./tests/vm-debug.sh flash-repro baseline opt0-baseline.mp4` |
| `picom-default` | 对比默认无淡入 `picom`（如虚机未装会自动 `apt install picom`） | `./tests/vm-debug.sh flash-repro picom-default opt1-picom-default.mp4` |
| `picom-fade` | 对比开启淡入动画的 `picom` | `./tests/vm-debug.sh flash-repro picom-fade opt1-picom-fade.mp4` |
| `dwmcomp` | 测试本地编译的 `tools/dwmcomp`（双浅米色 Alacritty 1 → 2） | `./tests/vm-debug.sh flash-repro dwmcomp opt5-custom-compositor.mp4` |
| `dwmcomp-contrast` | 浅米色终端开深黑（`#1e222a`）Alacritty 高对比度测试 | `./tests/vm-debug.sh flash-repro dwmcomp-contrast opt5-custom-compositor-contrast.mp4` |
| `dwmcomp-lifecycle` | **最推荐的回归验收模式**：一镜到底连测 `0→1`、`1→2`、`2→1`、`1→0`、`0→1(深色)` 全部 5 次切换 | `./tests/vm-debug.sh flash-repro dwmcomp-lifecycle opt5-dwmcomp-lifecycle.mp4` |

### 4.3 录屏脚本的工作原理（方便自定义扩展）

`tests/repro-alacritty-flash-remote.sh` 在虚机内按以下顺序执行：

1. 等待 `xprop -root _NET_SUPPORTING_WM_CHECK` 就绪（防止刚重启 `gdm3` 后 Xorg 尚未登录完成）。
2. 通过 `python3-xlib` 创建一个 `1x1` 的肉粉色（`#dbb199`）Pixmap，设为 root 背景并写入 `_XROOTPMAP_ID` 与 `ESETROOT_PMAP_ID`（调用 `RetainPermanent` 保持持久），保证**无论是否启用合成器**，桌面背景都是醒目的肉粉色，与浅米色终端（`#fff9e9`）形成高对比度。
3. 按 `mode` 启动对应的合成器（`dwmcomp` 模式会先自动把本地 `tools/dwmcomp` 通过 `scp` 传到虚机）。
4. 切换到 workspace 3，用 `ffmpeg` 以 **60fps、高画质** 抓取 `:0.0`：
   ```sh
   ffmpeg -y -f x11grab -framerate 60 -video_size "$SCREEN_SIZE" -i :0.0 \
       -c:v libx264 -preset ultrafast -crf 12 -pix_fmt yuv420p \
       /tmp/dwm-alacritty-flash.mp4
   ```
5. 自动打开/关闭指定配色的 Alacritty 窗口，然后向 `ffmpeg` 发送 `SIGINT` 正常落盘 MP4（写入完整 `moov` 索引）。
6. 将视频及所有日志（`dwmcomp.log`、`dwm.log`、`vm-flash-repro-trace.log`、`ffmpeg-flash-repro.log`、`alacritty-wininfo.txt`）打包拉回本地 `vm-artifacts/`。

---

## 5. 如何拆帧做 60fps 逐帧验收

1 帧（16.7ms）的闪烁仅靠普通播放很难肉眼完全确认，**改完代码后务必做拆帧检查**。

### 5.1 使用 `ffmpeg` 无损抽全帧

```sh
mkdir -p /tmp/dwmcomp-frames
ffmpeg -y -i vm-artifacts/opt5-dwmcomp-lifecycle.mp4 \
    -fps_mode passthrough /tmp/dwmcomp-frames/f_%04d.png
```

### 5.2 用 Python 自动扫描状态切换帧

下面的单行脚本会按像素采样左半屏、中间 gap、右半屏与四角，只打印发生画面变化的帧。**通过标准**：整个 `dwmcomp-lifecycle` 视频中不应出现任何“左空右有 / 左有右空 / 闪出肉粉色 `(217, 175, 151)`”的中间过渡帧。

```sh
python3 - <<'PY'
import glob
from PIL import Image

frames = sorted(glob.glob("/tmp/dwmcomp-frames/f_*.png"))
print("Total frames:", len(frames))
prev = None
for i, f in enumerate(frames):
    im = Image.open(f)
    s = (
        im.getpixel((300, 400)),   # 左半屏
        im.getpixel((705, 400)),   # 中间 gap
        im.getpixel((1000, 400)),  # 右半屏
        im.getpixel((100, 100)),   # 左上角
        im.getpixel((1200, 750)),  # 右下角
    )
    if s != prev:
        print(f"f_{i+1:04d} (t={i/60:.3f}s): left={s[0]} mid={s[1]} right={s[2]} tl={s[3]} br={s[4]}")
        prev = s
PY
```

合格输出示例（`0→1` / `1→2` / `2→1` / `1→0` / `0→1(深色)` 全部单帧直达，0 帧过渡闪烁）：

```text
f_0001 (t=0.000s): left=(217, 175, 151) mid=(217, 175, 151) right=(217, 175, 151) ...
f_0052 (t=0.850s): left=(255, 248, 232) mid=(255, 248, 232) right=(255, 248, 232) ...
f_0107 (t=1.767s): left=(255, 248, 232) mid=(217, 175, 151) right=(255, 248, 232) ...
f_0177 (t=2.933s): left=(255, 248, 232) mid=(255, 248, 232) right=(255, 248, 232) ...
f_0229 (t=3.800s): left=(217, 175, 151) mid=(217, 175, 151) right=(217, 175, 151) ...
f_0276 (t=4.583s): left=(28, 33, 41)    mid=(28, 33, 41)    right=(28, 33, 41)    ...
```

建议同时直接打开关键切换前后的 PNG（如 `f_0106.png` 与 `f_0107.png`）肉眼核对：
- 新窗口左上角无旧窗口文字残影；
- 旧窗口光标已同步更新为非激活态；
- 蓝色点阵 `focusoverlay` 透明裁剪正常，未出现整块遮挡。

---

## 6. 常见排查（FAQ）

- **宿主机跑 `dwmcomp` 后桌面壁纸变深灰**：说明当前设壁纸的工具未写入 `_XROOTPMAP_ID` / `ESETROOT_PMAP_ID`，改用 `feh --bg-fill`、`xwallpaper` 或 `hsetroot` 设置壁纸即可实时生效。
- **修改 `dwmcomp.c` 后如何快速验证**：直接 `make dwmcomp && ./tests/vm-debug.sh flash-repro dwmcomp-lifecycle opt5-dwmcomp-lifecycle.mp4`，无需重新部署 `dwm`。
- **遇到新应用的特定闪烁怎么排查**：在宿主机或虚机运行 `./tools/dwmcomp -v`，触发闪烁后重点核对：
  1. 是否触发了 `freeze on map` / `freeze on resize` / `coalesce on unmap`；
  2. 解冻耗时 `dt` 是正常客户端绘制（几到几十毫秒）还是 `timeout`；
  3. 用 `xwininfo` 查看该应用窗口的 `Depth`（24 vs 32）、`Override Redirect State` 和初始尺寸。
