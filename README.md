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

三个参数均可选，不传则启动后在界面中选择。

---

## 独立可执行文件

编译单文件 `.exe`，对方无需安装 Python。

### 系统要求

| 系统 | 支持 |
|------|------|
| Windows 10 / 11 (x64) | ✅ |
| Windows 7 / 8.x | ❌ Python 3.9 起官方停止支持 Win7，`python3*.dll` 依赖 Win8 专有 API（`api-ms-win-core-path-l1-1-0.dll`），无法通过补丁或运行库解决 |

### 构建

```bash
pip install pyinstaller pillow
pyinstaller labelImg.spec        # 产物 → dist/labelImg.exe（约 44 MB）
```

---

## 功能

### 标注操作

| 功能 | 说明 |
|------|------|
| **画框标注** | `W` 创建，鼠标拖拽；右键拖动可移动/复制框 |
| **格式切换** | 工具栏按钮切换 Pascal VOC（XML）/ YOLO（TXT）/ CreateML（JSON） |
| **标签输入** | 文本框手动输入，支持历史记录自动补全（大小写不敏感） |
| **困难样本** | 勾选「难以辨认」标记当前框为困难，训练时可排除 |
| **撤销栈** | `Ctrl+Z` 撤销，上限 50 步，覆盖创建/删除/复制/粘贴 |
| **复制上一张标注** | `Ctrl+V` 将上一张图片的所有框和标签复制到当前图片 |
| **单一类别模式** | `Ctrl+Shift+S` 切换，开启后跳过标签选择，自动复用上一个标签 |
| **强制画正方形** | `Ctrl+Shift+R` 切换，拖拽时锁定宽高比 1:1 |
| **亮度辅助** | `Ctrl+Shift++` / `Ctrl+Shift+-` 调整图片叠加遮罩亮度，改善暗图或过曝图的标注体验 |

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `W` | 创建标注框 |
| `A` / `D` | 上一张 / 下一张图片 |
| `Ctrl+S` | 保存 |
| `Ctrl+R` | 修改默认保存目录 |
| `Ctrl+O` | 打开图片 |
| `Ctrl+U` | 打开目录 |
| `Ctrl+D` | 复制当前框和标签 |
| `Ctrl+V` | 复制上一张图片的所有标注 |
| `Ctrl+Shift+D` | 删除当前图片 |
| `Delete` | 删除选中框 |
| `Ctrl+Z` | 撤销 |
| `Space` | 标记已确认 |
| `Ctrl++` / `Ctrl+-` | 放大 / 缩小 |
| `Ctrl+Shift++` / `Ctrl+Shift+-` | 调亮 / 调暗图片（叠加遮罩） |
| `Ctrl+Shift+R` | 切换强制画正方形 |
| `Ctrl+Shift+S` | 切换单一类别模式 |
| `?` / `H` | 快捷键帮助面板 |

### 键盘控制顶点（核心特色）

选中标注框后，可用键盘精确调整矩形：

| 按键 | 功能 |
|------|------|
| `C` | 进入角点模式 / 顺时针切换顶点 |
| `Z` | 逆时针切换顶点 |
| `↑ ↓ ← →` | 移动当前选中的顶点（矩形随之变形）；未选中顶点时移动整个框 |
| `Esc` | 退出角点模式，回到整体移动 |

长按方向键带 **指数加速**（`KeyAccelerator`），时间越长每 tick 步长越大，粗调细调一把搞定。蓝色高亮圆点指示当前选中的顶点。

### 增强功能

| 功能 | 触发 | 说明 |
|------|------|------|
| **标签统计面板** | `Ctrl+T` | 展示标签名、出现次数、涉及图片数，可双击跳转、勾选多标签筛选翻页 |
| **批量重命名** | 统计面板右键标签 | 统一重命名所有标注文件中的指定标签 |
| **定位标注文件** | 文件列表右键图片 | 在文件管理器中打开对应的 XML/TXT/JSON |
| **显示/隐藏标签** | 菜单 `View > Display Labels` | 切换标注框上是否显示标签文字 |
| **重置设置** | 菜单 `File > Reset All` | 将所有界面设置恢复为默认值 |
| **窗口状态持久化** | 自动 | 关闭时记住窗口最大化状态，下次启动恢复 |

---

## 类别文件

程序启动时可通过第二个参数指定类别文件（每行一个标签名），或通过菜单 `File > Open Default Class File` 加载。不指定时使用内置默认列表。

---

## 修改 UI 文案

文案在 `resources/strings/*.properties` 中。修改后需编译资源：

```bash
pyrcc5 -o libs/resources.py resources.qrc
```

> `libs/resources.py` 已纳入版本管理，改文案后必须重新编译并提交此文件。

---

## License

MIT License — 详见 [LICENSE](LICENSE)。
原项目 Copyright (c) 2015 [Tzutalin](https://github.com/tzutalin)
