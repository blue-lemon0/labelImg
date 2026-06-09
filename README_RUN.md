# LabelImg — 快速开始

图像标注工具，在图片上画框打标签，支持 Pascal VOC / YOLO / CreateML 格式导出。

## 项目文件说明

| 文件 | 说明 |
|------|------|
| `labelImg.py` | 主程序，运行它启动 |
| `libs/` | 核心模块（画布、导入导出、UI 等） |
| `resources/` | 图标和 UI 文案 |
| `resources.qrc` | 资源清单，改文案后编译用 |
| `requirements.txt` | Python 依赖 |
| `README_RUN.md` | 本文件 |
| `README.rst` | 上游原版文档 |
| `LICENSE` | MIT 开源许可证 |
| `__init__.py` | Python 包标记 |

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
python labelImg.py
```

## 说明

- 默认标签为空，需手动输入（之前的「预设标签」下拉框已改为文本框）
- 勾选「难以辨认」可标记当前框为困难样本（评估时可排除）
- 标签列表中有问题的项会显示为红色

## 修改 UI 文案

文案在 `resources/strings/` 下的 `.properties` 文件里。修改后需重新编译资源并提交：

```bash
pyrcc5 -o libs/resources.py resources.qrc
git add libs/resources.py
```

> `libs/resources.py` 已纳入版本管理，不编译直接改 `.properties` 不会生效。
