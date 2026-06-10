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
    """标签统计对话框，以表格展示全数据集的标签分布。"""

    TABLE_HEADERS = ['标签名', '标注框数', '涉及图片数', '疑似拼写错误的标签']

    def __init__(self, stats, parent=None):
        """
        Args:
            stats: dict, {label_name: {'box_count': int, 'image_count': int, 'images': set}}
        """
        super(LabelStatsDialog, self).__init__(parent)
        self.setWindowTitle('标签统计')
        self.resize(700, 500)
        self._build_ui(stats)

    def _build_ui(self, raw_stats):
        layout = QVBoxLayout(self)

        # 汇总信息
        total_boxes = sum(v['box_count'] for v in raw_stats.values())
        total_labels = len(raw_stats)
        total_images = len(set().union(*(v['images'] for v in raw_stats.values())))

        summary = QLabel(
            f'数据集总计：{total_images} 张图片，{total_labels} 种标签，{total_boxes} 个标注框'
        )
        summary.setStyleSheet('font-weight: bold; padding: 6px;')
        layout.addWidget(summary)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
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
            self.table.setItem(row, 0, QTableWidgetItem(label))
            self.table.setItem(row, 1, QTableWidgetItem(str(info['box_count'])))
            self.table.setItem(row, 2, QTableWidgetItem(str(info['image_count'])))

            similar = spell_warnings.get(label, [])
            similar_str = ', '.join(similar) if similar else ''
            item = QTableWidgetItem(similar_str)
            if similar:
                item.setForeground(QColor('#E57373'))
                item.setToolTip('建议统一拼写')
            self.table.setItem(row, 3, item)

        layout.addWidget(self.table)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    @staticmethod
    def _detect_spelling_errors(labels):
        """两两比较标签，返回 {label: [相似标签列表]}。"""
        warnings = {}
        seen = set()
        for i, a in enumerate(labels):
            for j, b in enumerate(labels):
                if i >= j:
                    continue
                ratio = difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()
                if ratio > 0.75:
                    warnings.setdefault(a, []).append(b)
                    warnings.setdefault(b, []).append(a)
        return warnings


def scan_label_statistics(img_list, default_save_dir):
    """全量扫描图片列表，提取标注文件中的标签信息。

    Returns:
        dict: {label_name: {'box_count': int, 'image_count': int, 'images': set}}
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
            stats[label]['box_count'] += 1
            stats[label]['images'].add(img_path)

    # 将 set 转为 count
    result = {}
    for label, info in stats.items():
        result[label] = {
            'box_count': info['box_count'],
            'image_count': len(info['images']),
            'images': info['images'],
        }

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
    """解析 Pascal VOC XML 文件，返回标签名列表。"""
    from xml.etree import ElementTree
    try:
        tree = ElementTree.parse(xml_path)
        root = tree.getroot()
        return [obj.find('name').text for obj in root.findall('object') if obj.find('name') is not None]
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
    """解析 CreateML JSON 文件，返回标签名列表。"""
    import json
    try:
        with open(json_path, 'r', encoding=DEFAULT_ENCODING) as f:
            data = json.load(f)
        basename = os.path.basename(img_path)
        for entry in data:
            if entry.get('image') == basename:
                return [ann['label'] for ann in entry.get('annotations', []) if 'label' in ann]
    except Exception:
        pass
    return []
