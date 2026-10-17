# 流声 · Niri 手机语音输入

面向 **Niri Wayland + Fcitx5** 的最小可用版本：手机打开网页，用任意手机键盘的语音输入功能识别文字，点击发送后，文字通过 Linux 剪贴板和模拟快捷键粘贴到当前聚焦位置。

## 1. 安装依赖

你只需要 **Python 3 + wl-clipboard + wtype**，无需 Python pip 安装：

```bash
# Arch / EndeavourOS
sudo pacman -S --needed python wl-clipboard wtype

# Fedora
sudo dnf install python3 wl-clipboard wtype

# Debian / Ubuntu（若仓库提供这些包）
sudo apt install python3 wl-clipboard wtype
```

如果当前 Niri 版本上的 wtype 不工作，可以用 `ydotool` 作为备用（需要单独启动并授权 `ydotoold`）。

## 2. 启动服务

**从 Niri 桌面内打开的终端执行**（必须继承 `WAYLAND_DISPLAY`、`NIRI_SOCKET` 等会话变量）：

```bash
cd niri-voice-input
python3 server.py
```

默认端口 `8765`，局域网可访问。

查看 Linux IP：

```bash
hostname -I
```

手机和 Linux 处于同一个 Wi-Fi/局域网时，在手机浏览器中访问：

```text
http://你的Linux局域网IP:8765
```

## 3. 测试

1. Linux 上打开 VS Code 或浏览器的普通输入框，鼠标点击使其获得输入焦点。
2. 手机上打开网页，点编辑区，使用手机输入法的麦克风进行语音转写。
3. 点「发送到 Linux」。文字应该出现在 Linux 当前光标处。
4. 如果用终端，服务端会尽量通过 Niri 的 `app_id` 自动识别并发送 `Ctrl+Shift+V`。如果终端无法粘贴，请确认终端应用支持该快捷键。

注意：Fcitx5 无需修改，手机端发送的是**已识别完成的 Unicode 文本**，通过剪贴板注入，而非模拟中文逐字敲键。

## 4. 快速排错

首先在 Niri 的终端中运行以下测试，并将焦点移至需要粘贴的输入框：

```bash
# 放入剪贴板（运行这条命令后再聚焦目标）
printf '你好 Niri + Fcitx5' | wl-copy

# 焦点已在目标输入框时，使用另一个键盘快捷键触发或者使用本工具发送
# 手动在终端里执行这条命令时，焦点可能回到终端，建议用手机实际测试
wtype -M ctrl -k v -m ctrl
```

- **页面显示缺少组件**：用 `command -v wl-copy wtype` 检查安装。
- **网页不能访问**：确认同局域网、IP、端口，以及 Linux 防火墙规则。
- **网页显示发送成功但没有文字**：成功仅代表执行了粘贴快捷键，不代表目标应用接受它；请检查目标输入框聚焦、终端特殊快捷键，以及 Niri 虚拟键盘兼容性。
- **Niri + wtype 后物理键盘暂时失效**：部分 Niri 版本有已知 issue。切换窗口焦点可能恢复；可以试备用 `ydotool`：

  ```bash
  # 前提：已安装并正确运行 ydotoold
  python3 server.py --backend ydotool
  ```

- **服务找不到 Niri 焦点窗口**：确认服务是从 Niri 的用户会话内启动，不要通过脱离会话的 root 服务启动。自动快捷键识别依赖 Niri 焦点窗口信息。

## 5. 参数

```bash
python3 server.py --host 0.0.0.0 --port 8765 --backend auto
```

`--backend auto` 默认优先 `wtype`，失败且安装了 `ydotool` 时才尝试后者，也可以强制指定 `--backend wtype` 或 `--backend ydotool`。

## 已知限制

- 不读取应用内部光标位置；由 Niri 当前键盘焦点决定注入位置。没有焦点或控件不可编辑时，不能保证成功。
- 默认会覆盖 Linux 当前剪贴板，暂不自动恢复。
- 终端中粘贴多行命令可能执行命令；请谨慎对待文本内容。
- 不含鉴权，适合你指定的**可信局域网**使用，不要暴露到公网。
- 手机端复用键盘语音输入，不使用浏览器麦克风 API；移动设备无需安装原生 App。

## 手机页面

简洁布局保留了连接状态、当前目标窗口、发送进度和发送结果（包括失败原因），同时提供文本编辑区、清空按钮和发送按钮。发送成功后自动清空文本，失败时保留草稿；输入的文字临时保存在本机浏览器。注意“已发送”表示系统已触发粘贴，并非已确认目标控件成功插入。
