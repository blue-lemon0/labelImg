# LabelImg 启动运行指南

## 环境要求

本仓库基于 **conda `labelimg` 环境**（Python 3.8 + PyQt5 + lxml）运行，该环境已配置好所有依赖。

conda 路径：`D:\xxx\software\miniconda3\envs\labelimg`

---

## 启动方式

### 方式一：在 repo 目录直接运行（推荐）

```powershell
# 1. 激活 conda 环境
conda activate labelimg

# 2. 进入仓库目录
cd D:\xxx\project\PycharmProjects\labelImg

# 3. 启动
python labelImg.py
```

> **为什么在目录里运行？** 因为 `labelImg.py` 内部通过 `from libs.xxx import xxx` 导入同目录下的 `libs/` 模块。在 repo 根目录下运行能确保加载到**本仓库修复后的版本**，而不是 conda site-packages 里的旧版。

### 方式二：指定图片目录和预定义类别（可选）

```powershell
conda activate labelimg
cd D:\xxx\project\PycharmProjects\labelImg
python labelImg.py D:\path\to\images D:\path\to\predefined_classes.txt
```

### 方式三：直接用 conda 环境的 Python 运行（不激活环境）

```powershell
& "D:\xxx\software\miniconda3\envs\labelimg\python.exe" labelImg.py
```

**注意**：方式三需要在 `D:\xxx\project\PycharmProjects\labelImg` 目录下执行。

---

## 首次使用前准备

编译 Qt 资源文件（仅首次需要）：

```powershell
conda activate labelimg
cd D:\xxx\project\PycharmProjects\labelImg
pyrcc5 -o libs/resources.py resources.qrc
```

> 如果 `libs/resources.py` 已存在可跳过此步。

---

## 验证修复

启动后正常标注图片即可。之前的闪退 bug 已在 `libs/ustr.py` 中根因修复：

```python
def ustr(x):
    """py2/py3 unicode helper"""
    if x is None:        # ← Python 3 下直接透传 None 导致下游 .encode() 崩溃
        return ""
    ...
```

**根因**：`ustr()` 本应是"字符串辅助函数"，但 Python 3 分支直接 `return x`，遇到 None 就原样透传。之后 `generate_color_by_text()` 里 `s.encode('utf-8')` 在 None 上调用就闪退。

**修复方式对比**：

| 方式 | 位置 | 评价 |
|------|------|------|
| `if s is None: s = ""` | `utils.py` generate_color_by_text | 只堵了一个调用点，治标 |
| **`if x is None: return ""`** | **`ustr.py` ustr** | 函数本该返回 str，根因修复，所有调用点受益 ✅ |

---

## 目录结构说明

```
labelImg/
├── labelImg.py          # 主入口
├── libs/                # 核心库
│   ├── utils.py         # ⚡ 修复文件（generate_color_by_text None 防御）
│   ├── ustr.py          # Python 2/3 字符串兼容
│   ├── canvas.py        # 画布绘制
│   ├── labelFile.py     # 标注文件读写
│   ├── pascal_voc_io.py # Pascal VOC 格式
│   └── yolo_io.py       # YOLO 格式
├── data/                # 预定义类别文件
├── README_RUN.md        # 本文件
└── README.rst           # 原始文档
```
