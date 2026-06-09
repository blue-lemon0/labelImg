# LabelImg — 快速开始

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
