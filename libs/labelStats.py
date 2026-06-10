# -*- coding: utf-8 -*-
"""标签统计对话框：扫描数据集，展示标签名 + 出现次数 + 涉及图片数 + 疑似拼写错误告警。"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QPushButton, QHeaderView,
                             QLabel, QMessageBox, QProgressDialog)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from collections import Counter, defaultdict
import difflib
import os

from libs.constants import DEFAULT_ENCODING


class LabelStatsDialog(QDialog):
    """标签统计对话框，以表格展示全数据集的标签分布。

    双击任意行 → 跳转到包含该标签的第一张图片。
    点击【跳转】→ 激活过滤模式，a/d 只在该标签的图片间跳转。
    """

    TABLE_HEADERS = ['标签名', '标注框数', '涉及图片数', '疑似拼写错误', '操作']

    def __init__(self, stats, parent=None, on_jump_to=None, on_navigate=None,
                 total_img_count=0):
        """
        Args:
            stats: dict, {label_name: {'box_count': int, 'image_count': int, 'images': set}}
            on_jump_to: callable(img_path), 双击行时回调
            on_navigate: callable(label_name), 点击【跳转】时回调，用于激活过滤翻页
            total_img_count: 数据集总图片数（含未标注），用于进度显示
        """
        super(LabelStatsDialog, self).__init__(parent)
        self._stats = stats
        self._on_jump_to = on_jump_to
        self._on_navigate = on_navigate
        self._total_img_count = total_img_count
        self.setWindowTitle('标签统计')
        self.resize(760, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build_ui(stats)

    def _build_ui(self, raw_stats):
        layout = QVBoxLayout(self)

        # 汇总信息
        total_boxes = sum(v['box_count'] for v in raw_stats.values())
        total_labels = len(raw_stats)
        total_images = len(set().union(*(v['images'] for v in raw_stats.values())))

        if self._total_img_count > total_images:
            summary = QLabel(
                f'数据集总计：{total_images} / {self._total_img_count} 张图片有标注，'
                f'{total_labels} 种标签，{total_boxes} 个标注框'
            )
        else:
            summary = QLabel(
                f'数据集总计：{total_images} 张图片，{total_labels} 种标签，{total_boxes} 个标注框'
            )
        summary.setStyleSheet('font-weight: bold; padding: 6px;')
        layout.addWidget(summary)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSortingEnabled(True)

        # 填充数据（按 box_count 降序）
        sorted_items = sorted(raw_stats.items(),
                              key=lambda x: (-x[1]['box_count'], x[0]))
        self.table.setRowCount(len(sorted_items))

        # 拼写检查：两两比较相似度
        spell_warnings = self._detect_spelling_errors(list(raw_stats.keys()))

        for row, (label, info) in enumerate(sorted_items):
            # 显示名：空标签显示为 (空标签)
            display_label = label if label else '(空标签)'
            item0 = QTableWidgetItem(display_label)
            if not label:
                item0.setForeground(QColor('#E57373'))
                item0.setToolTip('标注框存在但标签名为空')
            self.table.setItem(row, 0, item0)
            self.table.setItem(row, 1, QTableWidgetItem(str(info['box_count'])))
            self.table.setItem(row, 2, QTableWidgetItem(str(info['image_count'])))

            similar = spell_warnings.get(label, [])
            similar_str = ', '.join(similar) if similar else ''
            item = QTableWidgetItem(similar_str)
            if similar:
                item.setForeground(QColor('#E57373'))
                item.setToolTip('建议统一拼写')
            self.table.setItem(row, 3, item)

            # 【跳转】按钮
            nav_btn = QPushButton('跳转')
            nav_btn.label_name = label  # 存真实标签名（含空字符串）
            nav_btn.clicked.connect(self._on_navigate_clicked)
            self.table.setCellWidget(row, 4, nav_btn)

        # 双击行 → 跳转到包含该标签的图片
        if self._on_jump_to:
            self.table.cellDoubleClicked.connect(self._on_row_double_clicked)

        layout.addWidget(self.table)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _on_navigate_clicked(self):
        """点击【跳转】：激活标签过滤翻页模式。"""
        button = self.sender()
        label = button.label_name
        if self._on_navigate:
            self._on_navigate(label)
        self.accept()

    def _on_row_double_clicked(self, row, _column):
        """双击行：跳转到该标签所在的第一个张图片。"""
        # 获取该行对应的真实标签名（从第 0 列取）
        label = self._row_labels_from_table(row)
        images = self._stats[label]['images']
        if images:
            first_img = next(iter(images))
            if self._on_jump_to:
                self._on_jump_to(first_img)
            self.accept()

    def _row_labels_from_table(self, visual_row):
        """获取指定视觉行的真实标签名（row_labels 存的是排序后的数据行）。"""
        # 由于用了 setSortingEnabled，视觉行可能已乱序，
        # 直接从第 0 列 text 反查真实 label
        display = self.table.item(visual_row, 0).text()
        if display == '(空标签)':
            return ''
        # 从 _stats 里找（避免显示文本和真实名不一致）
        for lbl in self._stats:
            if lbl == display:
                return lbl
        return display

    @staticmethod
    def _detect_spelling_errors(labels):
        """两两比较标签，返回 {label: [相似标签列表]}。"""
        warnings = {}
        for i, a in enumerate(labels):
            for j, b in enumerate(labels):
                if i >= j:
                    continue
                if not a or not b:
                    continue  # 跳过空标签
                ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
                if ratio > 0.75:
                    warnings.setdefault(a, []).append(b)
                    warnings.setdefault(b, []).append(a)
        return warnings


def scan_label_statistics(img_list, default_save_dir):
    """全量扫描图片列表，提取标注文件中的标签信息。

    Returns:
        dict: {label_name: {'box_count': int, 'image_count': int, 'images': set}}
        空标签会以 '' 空字符串作为 key 存入。
    """
    from xml.etree import ElementTree
    from libs.yolo_io import TXT_EXT
    from libs.create_ml_io import JSON_EXT
    from libs.pascal_voc_io import XML_EXT

    stats = defaultdict(lambda: {'box_count': 0, 'image_count': 0, 'images': set()})

    for img_path in img_list:
        basename = os.path.splitext(os.path.basename(img_path))[0]
        anno_path = None

        # 按优先级查找：XML > TXT > JSON
        if default_save_dir:
            for ext in (XML_EXT, TXT_EXT, JSON_EXT):
                candidate = os.path.join(default_save_dir, basename + ext)
                if os.path.isfile(candidate):
                    anno_path = candidate
                    break
        else:
            for ext in (XML_EXT, TXT_EXT, JSON_EXT):
                candidate = os.path.splitext(img_path)[0] + ext
                if os.path.isfile(candidate):
                    anno_path = candidate
                    break

        if not anno_path:
            continue

        labels = _extract_labels(anno_path, img_path)
        for label in labels:
            key = label if label else ''
            stats[key]['box_count'] += 1
            stats[key]['images'].add(img_path)

    # 将 set 转为 count
    result = {}
    for label, info in stats.items():
        result[label] = {
            'box_count': info['box_count'],
            'image_count': len(info['images']),
            'images': info['images'],
        }

    return result


def scan_label_to_indices(img_list, default_save_dir):
    """全量扫描，返回 label_name → [索引列表] 的映射。

    专供过滤翻页使用，结果按索引升序排列。
    空标签统一记作 key=''。
    """
    from libs.pascal_voc_io import XML_EXT
    from libs.yolo_io import TXT_EXT
    from libs.create_ml_io import JSON_EXT

    mapping = defaultdict(list)

    for idx, img_path in enumerate(img_list):
        basename = os.path.splitext(os.path.basename(img_path))[0]
        anno_path = None

        if default_save_dir:
            for ext in (XML_EXT, TXT_EXT, JSON_EXT):
                candidate = os.path.join(default_save_dir, basename + ext)
                if os.path.isfile(candidate):
                    anno_path = candidate
                    break
        else:
            for ext in (XML_EXT, TXT_EXT, JSON_EXT):
                candidate = os.path.splitext(img_path)[0] + ext
                if os.path.isfile(candidate):
                    anno_path = candidate
                    break

        if not anno_path:
            continue

        labels = _extract_labels(anno_path, img_path)
        seen = set()
        for label in labels:
            key = label if label else ''
            if key not in seen:
                mapping[key].append(idx)
                seen.add(key)

    return dict(mapping)


def scan_single_annotation(img_path, default_save_dir):
    """扫描单张图片的标注文件，返回 {label: box_count}。

    Args:
        img_path: 图片绝对路径
        default_save_dir: 标注文件目录（或 None，表示与图片同目录）

    Returns:
        dict, {label_name: box_count}，空标签 key 为 ''
    """
    from libs.pascal_voc_io import XML_EXT
    from libs.yolo_io import TXT_EXT
    from libs.create_ml_io import JSON_EXT
    from collections import Counter

    basename = os.path.splitext(os.path.basename(img_path))[0]
    anno_path = None

    if default_save_dir:
        for ext in (XML_EXT, TXT_EXT, JSON_EXT):
            candidate = os.path.join(default_save_dir, basename + ext)
            if os.path.isfile(candidate):
                anno_path = candidate
                break
    else:
        for ext in (XML_EXT, TXT_EXT, JSON_EXT):
            candidate = os.path.splitext(img_path)[0] + ext
            if os.path.isfile(candidate):
                anno_path = candidate
                break

    if not anno_path:
        return {}

    labels = _extract_labels(anno_path, img_path)
    counter = Counter(labels)
    result = {}
    for label, count in counter.items():
        key = label if label else ''
        result[key] = count
    return result


def _extract_labels(anno_path, img_path):
    """从单个标注文件中提取所有标签名。"""
    from libs.pascal_voc_io import XML_EXT
    from libs.yolo_io import TXT_EXT
    from libs.create_ml_io import JSON_EXT
    import json

    ext = os.path.splitext(anno_path)[1].lower()

    if ext == XML_EXT:
        return _extract_labels_from_xml(anno_path)
    elif ext == TXT_EXT:
        return _extract_labels_from_txt(anno_path)
    elif ext == JSON_EXT:
        return _extract_labels_from_json(anno_path, img_path)
    return []


def _extract_labels_from_xml(xml_path):
    """解析 Pascal VOC XML 文件，返回标签名列表。空名称统一转为 ''。"""
    from xml.etree import ElementTree
    try:
        tree = ElementTree.parse(xml_path)
        root = tree.getroot()
        labels = []
        for obj in root.findall('object'):
            name_elem = obj.find('name')
            if name_elem is not None:
                text = name_elem.text
                labels.append(text if text else '')
        return labels
    except Exception:
        return []


def _extract_labels_from_txt(txt_path):
    """解析 YOLO txt 文件，通过同目录 classes.txt 获取标签名。"""
    labels = []
    try:
        dir_path = os.path.dirname(os.path.abspath(txt_path))
        classes_file = os.path.join(dir_path, 'classes.txt')
        if not os.path.isfile(classes_file):
            return []
        with open(classes_file, 'r', encoding=DEFAULT_ENCODING) as f:
            classes = [line.strip() for line in f if line.strip()]

        with open(txt_path, 'r', encoding=DEFAULT_ENCODING) as f:
            for line in f:
                parts = line.strip().split()
                if parts:
                    idx = int(parts[0])
                    if 0 <= idx < len(classes):
                        labels.append(classes[idx])
    except Exception:
        pass
    return labels


def _extract_labels_from_json(json_path, img_path):
    """解析 CreateML JSON 文件，返回标签名列表。空名称统一转为 ''。"""
    import json
    try:
        with open(json_path, 'r', encoding=DEFAULT_ENCODING) as f:
            data = json.load(f)
        basename = os.path.basename(img_path)
        for entry in data:
            if entry.get('image') == basename:
                result = []
                for ann in entry.get('annotations', []):
                    lbl = ann.get('label', '')
                    result.append(lbl if lbl else '')
                return result
    except Exception:
        pass
    return []
