# `dwmshell` 桌面小组件系统

`dwmshell` 是独立于 `dwm`（窗口管理）和 `dwmcomp`（合成器）之外的**桌面 Shell 层**，用于承载基于 HTML/CSS/JS 的桌面小组件。

## 核心特点

- **基于标准 EWMH `_NET_WM_WINDOW_TYPE_DESKTOP` 协作**：
  - `dwmshell` 创建正常的受管理窗口并声明 `DESKTOP` 类型，不再自行维护底层堆叠；
  - `dwm` 统一负责桌面窗口的层级（始终压在普通窗口与 `barwin` 之下）、无边框、不参与平铺、不抢焦点、跨工作区显示、且不污染状态栏 tag 指示与焦点脉冲计数；
  - `dwmcomp` 识别 `DESKTOP` 窗口类型并排除开窗/缩放/关窗冻结，同时以 `PictOpOver` 合成圆角透明卡片。
- **文件夹热加载**：直接往 `~/.config/dwmshell/widgets/` 放一个包含 `widget.json` 和 `index.html` 的目录，1 秒内自动生效，编辑立即热刷新。
- **本地 HTTP API（适合脚本与 AI Agent）**：默认监听 `http://127.0.0.1:17777`，可动态创建/更新/推送数据/删除小组件。

## 启动

```sh
./tools/dwmshell/dwmshell.py -v
```

如果不想加载内置示例小组件（`aqi` / `todo` / `system`），加 `--no-builtin`。`aqi` 小组件会由 `dwmshell` 后端从仓库根目录或 `~/.config/dwmshell/.env` 读取 `aqi_token`，前端不暴露密钥。

## 添加自定义小组件（无需改代码、无需重启）

在 `~/.config/dwmshell/widgets/sleep/` 新建两个文件：

`widget.json`（`x`/`y` 支持负数表示从右边/底边贴齐）：

```json
{
  "title": "Sleep",
  "x": 36,
  "y": 48,
  "width": 260,
  "height": 130,
  "enabled": true
}
```

`index.html`：

```html
<!doctype html>
<html>
<body style="margin:0;background:transparent;font-family:sans-serif">
  <div style="height:100vh;padding:18px;border-radius:18px;background:rgba(28,30,36,.82);color:#fff;box-sizing:border-box">
    <div style="font-size:12px;opacity:.7">LAST NIGHT</div>
    <div id="val" style="font-size:32px;font-weight:700;margin-top:8px">7h 42m</div>
  </div>
  <script>
    window.dwmshell.onData((d) => {
      if (d && d.text) document.getElementById('val').textContent = d.text;
    });
  </script>
</body>
</html>
```

## 通过 CLI / Agent 动态推送

```sh
# 查看运行中的小组件
./tools/dwmshell/dwmshell-ctl.py list

# 动态创建一个小组件
./tools/dwmshell/dwmshell-ctl.py push note \
  --x 36 --y 48 --width 260 --height 120 \
  --html '<div style="padding:16px;border-radius:16px;background:rgba(28,30,36,.85);color:#fff;font-family:sans-serif">Hello from Agent!</div>'

# 实时推送数据到已有小组件（不刷新页面）
./tools/dwmshell/dwmshell-ctl.py data sleep '{"text":"8h 10m"}'

# 移除或禁用小组件
./tools/dwmshell/dwmshell-ctl.py remove note
```

## 小组件内置 JS API (`window.dwmshell`)

- `window.dwmshell.id`：当前小组件 ID
- `window.dwmshell.onData(fn)` / `window.dwmshell.getData()`：接收实时推送数据
- `window.dwmshell.loadState()` / `window.dwmshell.saveState(obj)`：持久化小组件交互状态到 `~/.local/state/dwmshell/<id>.json`
- `window.dwmshell.getSystem()`：获取 CPU / 内存 / 负载 / 运行时间
- `document.documentElement.classList.contains('dwmshell-occupied')`：当桌面有活动窗口时自动加上该 class，可做柔和变暗
