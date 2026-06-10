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

---

## 待办

### 功能
- [x] **标签统计面板**：全量扫描数据集，展示标签名 + 出现次数 + 涉及图片数 + 疑似拼写错误告警（`Ctrl+T`）
- [ ] **历史标签补全**：输入标签时从历史标签自动补全 / 下拉候选，减少重复打字
- [ ] **批量操作**：多选标签，批量删除 / 重命名
- [ ] **标注框属性面板**：选中框时显示 x/y/w/h 坐标 + 标签名，可直接编辑数值微调
- [ ] **撤销栈增强**：当前仅 `Ctrl+V` 粘贴可撤销；扩展到创建框、删除框、移动框等操作
- [ ] **窗口布局持久化**：关闭时记住窗口位置 / 大小 / 分割条位置，下次启动恢复

### 重构
- [x] **拆分 labelImg.py**：`__init__` 从 ~490 行压缩至 ~130 行；提取 `_setup_ui_widgets()` / `_create_actions_and_menus()` 两个独立方法
