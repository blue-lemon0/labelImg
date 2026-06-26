# LabelImg

> 本项目基于 [tzutalin/labelImg](https://github.com/tzutalin/labelImg) 修改和扩展。
> 原项目已停止积极开发并合并至 [Label Studio](https://github.com/heartexlabs/label-studio)。

图像标注工具，在图片上画框打标签，支持 Pascal VOC / YOLO / CreateML 格式导出。

![Python](https://img.shields.io/badge/python-3.13-blue)
![PyQt5](https://img.shields.io/badge/PyQt5-5.15-green)

---

## 快速开始

```bash
pip install -r requirements.txt
python labelImg.py [图片路径] [类别文件] [保存目录]
```

均为可选，缺省则在界面中选择。

---

## 构建与打包

编译单文件 `.exe`，对方无需安装 Python。

### 环境准备

前置依赖安装见[快速开始](#快速开始)。

### 编译资源文件

改完 `resources/strings/*.properties` 文案后需重新编译：

```bash
pyrcc5 -o libs/resources.py resources.qrc
```

> `libs/resources.py` 已纳入版本管理，改文案后必须重新编译并提交。

### 打包为独立 exe

| 目标系统 | 构建方式 | Python | 产物 |
|----------|----------|--------|------|
| **Windows 8 / 8.1 / 10 / 11** | `pyinstaller labelImg.spec` | 3.13（最新） | `dist/labelImg.exe` |
| **Windows 7** | `build_win7.ps1` | 3.8（独立 venv） | `dist_win7/labelImg_win7.exe` |

#### Win8+ 主流构建

```bash
pip install pyinstaller pillow
pyinstaller labelImg.spec        # → dist/labelImg.exe
```

使用项目主线的 Python 版本，跟随功能更新。

#### Win7 兼容构建

> **仅用于首次发布兼容，后续不再积极维护。**

**为什么 Win7 需要单独打包？**  
Python 3.9 起，python.org 官方 64 位安装包的 `python3*.dll` 导入了 `api-ms-win-core-path-l1-1-0.dll`（提供 `PathCchCombineEx` 等函数）。该 DLL 是 **Windows 8 引入的 API 集**，Win7 不存在，也无法通过补丁添加。因此 Python 3.9~3.13 的 exe 均无法在 Win7 启动。

最后一批不依赖此 API 的官方版本是 **Python 3.8.x**（`python38.dll` 只依赖 `api-ms-win-crt-*`，Win7 可通过 KB2999226 获得 Universal CRT 支持）。

**前置条件：** 安装 [Python 3.8.10](https://www.python.org/downloads/release/python-3810/)（默认路径 `%LOCALAPPDATA%\Programs\Python38`）

**构建：**

```powershell
.\build_win7.ps1                   # → dist_win7\labelImg_win7.exe
```

如遇执行策略错误（`UnauthorizedAccess`），加 `-ExecutionPolicy Bypass`：

```powershell
powershell -ExecutionPolicy Bypass -File build_win7.ps1
```

脚本会自动创建 venv、安装依赖（PyQt5 + lxml + PyInstaller + Pillow）并打包。

**限制：** Python 3.8 已于 2024 年 10 月终止安全更新；此构建仅打包当前版本，不会跟随主分支更新功能。

---

## 功能

### 快捷键

完整列表见程序内面板（`?` / `H` 打开）：

| 功能 | 快捷键 |
|------|--------|
| 创建标注框 | `W` |
| 翻页 | `A` / `D` |
| 保存 | `Ctrl+S` |
| 撤销 | `Ctrl+Z` |
| 删除选中框 | `Delete` |
| 复制上一张标注 | `Ctrl+V` |
| 进入顶点模式 / 切换顶点 | `C` / `Z` |
| 切换标注框 | `X` / `Shift+X` |
| 移动顶点 | `↑ ↓ ← →` |
| 退出顶点模式 | `Esc` |
| 标签统计 | `Ctrl+T` |

方向键长按带指数加速，兼顾粗调与细调。蓝色高亮圆点指示当前顶点。

### 其他功能

| 功能 | 触发 | 说明 |
|------|------|------|
| 切换格式 | 工具栏按钮 | Pascal VOC / YOLO / CreateML |
| 添加标签 | 文本框 | 已有标签下拉补全，删框即消失 |
| 批量重命名 | 统计面板右键菜单 | 统一重命名指定标签 |
| 定位标注文件 | 文件列表右键菜单 | 在资源管理器中打开 |
| 记住缩放位置 | 工具栏开关 | 翻页时保持缩放与滚动位置 |
| 窗口状态 | 自动 | 关闭时记住最大化，下次启动恢复 |

---

## 类别文件

程序启动时可通过第二个参数指定类别文件（每行一个标签名），或通过菜单 `File > Open Default Class File` 加载。不指定时使用内置默认列表。

---

## License

MIT License — 详见 [LICENSE](LICENSE)。
原项目 Copyright (c) 2015 [Tzutalin](https://github.com/tzutalin)
