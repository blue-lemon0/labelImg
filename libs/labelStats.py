# -*- coding: utf-8 -*-
"""标签统计对话框：扫描数据集，展示标签名 + 出现次数 + 涉及图片数 + 疑似拼写错误告警。"""

from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTableWidget,
                             QTableWidgetItem, QCheckBox, QHeaderView, QPushButton,
                             QWidget, QLabel, QMessageBox, QProgressDialog)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from collections import Counter, defaultdict
import difflib
import os

from libs.constants import DEFAULT_ENCODING


class LabelStatsDialog(QDialog):
    """标签统计对话框，以表格展示全数据集的标签分布。

    每一行有一个勾选框，勾选的标签即为「跳跃翻页」的目标标签。
    双击任意行 → 跳转到包含该标签的第一张图片并关闭对话框。
    顶部「主开关」控制是否启用跳跃翻页模式（关闭后即恢复普通逐张翻页）。
    """

    TABLE_HEADERS = ['', '标签名', '标注框数', '涉及图片数', '疑似拼写错误']

    def __init__(self, stats, parent=None, on_jump_to=None,
                 total_img_count=0, nav_labels=None, master_on=False):
        """
        Args:
            stats: dict, {label_name: {'box_count': int, 'image_count': int, 'images': set}}
            on_jump_to: callable(img_path), 双击行时回调
            total_img_count: 数据集总图片数（含未标注），用于进度显示
            nav_labels: set[str], 当前已勾选的标签集合（用于初始化）
            master_on: bool, 总开关初始状态
        """
        super(LabelStatsDialog, self).__init__(parent)
        self._stats = stats
        self._on_jump_to = on_jump_to
        self._total_img_count = total_img_count
        self._nav_labels = nav_labels or set()  # 当前勾选的标签
        self._master_on = master_on  # 总开关初始状态
        self._label_cbs = {}    # {真实标签名: QCheckBox}
        self.setWindowTitle('标签统计')
        self.resize(760, 520)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self._build_ui(stats)

    def _build_ui(self, raw_stats):
        layout = QVBoxLayout(self)

        # ── 汇总信息 ──
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

        # ── 总开关 ──
        self._master_cb = QCheckBox('启用按标签跳跃翻页（勾选下方标签后，A / D 只在这些标签的图片间跳转）')
        self._master_cb.setChecked(self._master_on)
        self._master_cb.toggled.connect(self._on_master_toggled)
        layout.addWidget(self._master_cb)

        # ── 表格 ──
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.TABLE_HEADERS))
        self.table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        # 第 0 列表头：用真实的 QCheckBox 覆盖（与各行勾选框一致）
        header = self.table.horizontalHeader()
        self._header_cb = QCheckBox()
        self._header_cb.setChecked(False)
        self._header_cb.stateChanged.connect(self._on_header_cb_toggled)
        self._header_cb.setParent(header)
        self._header_cb.show()
        header.sectionResized.connect(lambda idx, *_:
                                      self._reposition_header_cb() if idx == 0 else None)
        header.geometriesChanged.connect(self._reposition_header_cb)
        header.setSortIndicatorShown(False)  # 隐藏排序箭头，避免与勾选框重叠
        self.table.setColumnWidth(0, 36)  # 勾选列稍加宽，容纳勾选框
        header.setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSortingEnabled(True)
        # 确保垂直表头（序号列）可见
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.verticalHeader().setMinimumWidth(32)

        # 细分隔线 + 选中文字不变白
        self.table.setStyleSheet("""
            QTableWidget { gridline-color: #ddd; }
            QTableWidget::item:selected {
                color: #000; background: #D6E8FF;
            }
            QHeaderView::section {
                border: none;
                border-bottom: 1px solid #ccc;
                border-right: 1px solid #ddd;
                padding: 3px;
            }
        """)

        # 双击行 → 跳转到该标签的首张图片
        if self._on_jump_to:
            self.table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self.table.setToolTip('双击任意行可跳转至该标签的首张图片')

        # 填充数据（按 box_count 降序）
        sorted_items = sorted(raw_stats.items(),
                              key=lambda x: (-x[1]['box_count'], x[0]))
        self.table.setRowCount(len(sorted_items))

        # 拼写检查：两两比较相似度
        spell_warnings = self._detect_spelling_errors(list(raw_stats.keys()))

        for row, (label, info) in enumerate(sorted_items):
            # ── 第 0 列：勾选框（居中） ──
            cb = QCheckBox()
            cb.setChecked(label in self._nav_labels)
            # 勾选框始终可操作，总开关 OFF 仅控制翻页效果
            cb.toggled.connect(self._on_checkbox_toggled)
            self._label_cbs[label] = cb
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.addWidget(cb)
            container_layout.setAlignment(Qt.AlignCenter)
            container_layout.setContentsMargins(0, 0, 0, 0)
            self.table.setCellWidget(row, 0, container)
            # 占位 item（排序用，空字符串让排序忽略此列）
            self.table.setItem(row, 0, QTableWidgetItem(''))

            # ── 第 1 列：标签名 ──
            display_label = label if label else '(空标签)'
            item1 = QTableWidgetItem(display_label)
            if not label:
                item1.setForeground(QColor('#E57373'))
                item1.setToolTip('标注框存在但标签名为空')
            self.table.setItem(row, 1, item1)

            # ── 第 2 列：标注框数 ──
            self.table.setItem(row, 2, QTableWidgetItem(str(info['box_count'])))

            # ── 第 3 列：涉及图片数 ──
            self.table.setItem(row, 3, QTableWidgetItem(str(info['image_count'])))

            # ── 第 4 列：疑似拼写错误 ──
            similar = spell_warnings.get(label, [])
            similar_str = ', '.join(similar) if similar else ''
            item4 = QTableWidgetItem(similar_str)
            if similar:
                item4.setForeground(QColor('#E57373'))
                item4.setToolTip('建议统一拼写')
            self.table.setItem(row, 4, item4)

        layout.addWidget(self.table)

        # ── 底部提示 ──
        hint = QLabel('💡 双击任一行可跳转至该标签的首张图片（对话框将自动关闭）')
        hint.setStyleSheet('color: #888; padding: 2px 6px; font-size: 12px;')
        layout.addWidget(hint)

        # ── 底部按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton('确认')
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def get_nav_state(self):
        """读取对话框当前状态，供 MainWindow 在关闭后调用。

        Returns:
            (master_on: bool, checked_labels: set[str])
        """
        master_on = self._master_cb.isChecked()
        checked = {label for label, cb in self._label_cbs.items() if cb.isChecked()}
        return master_on, checked

    # ── 内部回调 ──

    def _on_master_toggled(self, on):
        """总开关切换：只影响翻页行为，不锁勾选框。"""
        pass

    def _on_checkbox_toggled(self):
        """任一勾选框状态变化时：同步更新表头全选勾。"""
        if not self._label_cbs:
            return
        all_checked = all(cb.isChecked() for cb in self._label_cbs.values())
        self._header_cb.blockSignals(True)
        self._header_cb.setChecked(all_checked)
        self._header_cb.blockSignals(False)

    def _on_header_cb_toggled(self, checked):
        """点击表头全选勾 → 全选/取消全选。"""
        for cb in self._label_cbs.values():
            cb.setChecked(checked)

    def _reposition_header_cb(self):
        """将全选勾选框定位到第 0 列表头中央。"""
        header = self.table.horizontalHeader()
        pos = header.sectionViewportPosition(0)
        size = header.sectionSize(0)
        cb_size = self._header_cb.sizeHint()
        self._header_cb.setGeometry(
            pos + (size - cb_size.width()) // 2,
            (header.height() - cb_size.height()) // 2,
            cb_size.width(), cb_size.height())

    def _on_row_double_clicked(self, row, _column):
        """双击行：跳转到该标签所在的第一个张图片并关闭对话框。"""
        label = self._row_labels_from_table(row)
        images = self._stats[label]['images']
        if images:
            first_img = next(iter(images))
            if self._on_jump_to:
                self._on_jump_to(first_img)
            self.accept()

    def _row_labels_from_table(self, visual_row):
        """获取指定视觉行的真实标签名。"""
        display = self.table.item(visual_row, 1).text()
        if display == '(空标签)':
            return ''
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
