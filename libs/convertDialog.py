# -*- coding: utf-8 -*-
"""
格式转换对话框 — 支持批量标注格式互转。
通过 CONVERSIONS 列表扩展新的转换类型。
"""
import os

from PIL import Image as PILImage

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from libs.pascal_voc_io import PascalVocWriter, XML_EXT


# ── 转换函数 ──────────────────────────────────────────────

def yolo_to_voc(annotation_dir, image_dir, output_dir, status_callback):
    """批量将 YOLO .txt 转换为 PascalVOC .xml。

    Args:
        annotation_dir: 待扫描的目录（含 .txt / classes.txt）
        image_dir:      图片所在目录（与原图目录可以不同）
        output_dir:     输出 .xml 的目录
        status_callback: status(msg, processed, total) 用于更新 UI

    Returns:
        (success_count, fail_count, skip_count)
    """
    # 收集所有 .txt 文件
    txt_files = [f for f in os.listdir(annotation_dir)
                 if f.lower().endswith('.txt') and f != 'classes.txt']
    total = len(txt_files)
    if total == 0:
        status_callback('未找到 YOLO .txt 文件', 0, 0)
        return 0, 0, 0

    # 读取 classes.txt（优先 annotation_dir，fallback 到 image_dir）
    classes_path = os.path.join(annotation_dir, 'classes.txt')
    if not os.path.isfile(classes_path):
        classes_path = os.path.join(image_dir, 'classes.txt')
    class_list = []
    if os.path.isfile(classes_path):
        with open(classes_path, 'r', encoding='utf-8') as f:
            class_list = [line.strip() for line in f if line.strip()]
    if not class_list:
        status_callback('classes.txt 为空或不存在，将使用类别索引作为标签名', 0, total)

    IMG_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}

    success = 0
    fail = 0
    skip = 0

    for idx, txt_name in enumerate(txt_files):
        status_callback(f'正在处理 [{idx + 1}/{total}] {txt_name}', idx + 1, total)

        stem = os.path.splitext(txt_name)[0]
        txt_path = os.path.join(annotation_dir, txt_name)

        # 查找对应的图片文件（先找 image_dir，再找 annotation_dir）
        img_path = None
        for ext in IMG_EXTS:
            candidate = os.path.join(image_dir, stem + ext)
            if os.path.isfile(candidate):
                img_path = candidate
                break
        if img_path is None:
            for ext in IMG_EXTS:
                candidate = os.path.join(annotation_dir, stem + ext)
                if os.path.isfile(candidate):
                    img_path = candidate
                    break
        if img_path is None:
            skip += 1
            continue

        try:
            # 读取图片尺寸
            pil_img = PILImage.open(img_path)
            width, height = pil_img.size
            channels = len(pil_img.getbands())
            img_size = [height, width, channels]
            pil_img.close()

            # 创建 PascalVOC Writer
            folder_name = os.path.basename(os.path.dirname(img_path))
            img_file_name = os.path.basename(img_path)
            writer = PascalVocWriter(folder_name, img_file_name, img_size,
                                     local_img_path=img_path)

            # 解析 YOLO .txt
            with open(txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) != 5:
                        continue

                    class_idx = int(parts[0])
                    x_center = float(parts[1]) * width
                    y_center = float(parts[2]) * height
                    w = float(parts[3]) * width
                    h = float(parts[4]) * height

                    x_min = max(round(x_center - w / 2), 0)
                    y_min = max(round(y_center - h / 2), 0)
                    x_max = min(round(x_center + w / 2), width)
                    y_max = min(round(y_center + h / 2), height)

                    if class_idx < len(class_list):
                        label = class_list[class_idx]
                    else:
                        label = f'class_{class_idx}'

                    writer.add_bnd_box(x_min, y_min, x_max, y_max, label, 0)

            # 保存 .xml
            xml_path = os.path.join(output_dir, stem + XML_EXT)
            writer.save(target_file=xml_path)
            success += 1

        except Exception as e:
            fail += 1
            print(f'[转换失败] {txt_name}: {e}')

    return success, fail, skip


# ── 转换注册表 ──────────────────────────────────────────
# 添加新转换类型只需在此列表中追加一项：
#   (显示名称, 描述, 处理函数(annotation_dir, image_dir, output_dir, status_callback))
CONVERSIONS = [
    ('YOLO → PascalVOC',
     '将 YOLO .txt 标注转换为 PascalVOC .xml 格式',
     yolo_to_voc),
    # 未来在此添加新转换条目
]


# ── 对话框 ────────────────────────────────────────────────

class ConvertDialog(QDialog):
    """格式转换对话框。"""

    def __init__(self, parent=None, anno_dir='', img_dir='', out_dir=''):
        """
        Args:
            parent: 父窗口
            anno_dir: YOLO .txt 所在目录（默认值）
            img_dir:  图片所在目录（默认值）
            out_dir:  .xml 输出目录（默认值）
        """
        super().__init__(parent)
        self.setWindowTitle('格式转换')
        self.setMinimumWidth(540)

        self._default_anno = anno_dir
        self._default_img = img_dir
        self._default_out = out_dir

        self._init_ui()
        self._converting = False

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── 转换类型 ──
        type_label = QLabel('转换类型:')
        self.type_combo = QComboBox()
        for name, desc, _ in CONVERSIONS:
            self.type_combo.addItem(name)
        self.type_combo.setToolTip(CONVERSIONS[0][1] if CONVERSIONS else '')
        layout.addWidget(type_label)
        layout.addWidget(self.type_combo)
        layout.addSpacing(6)

        # ── 目录选择 ──
        dir_group = QGroupBox('目录设置')
        form_layout = QFormLayout(dir_group)
        form_layout.setLabelAlignment(Qt.AlignRight)

        # 标注文件目录
        self.anno_edit = QLineEdit(self._default_anno)
        self.anno_edit.setPlaceholderText('YOLO .txt 文件所在目录...')
        anno_browse = QPushButton('浏览...')
        anno_browse.clicked.connect(lambda: self._browse('anno'))
        anno_row = QHBoxLayout()
        anno_row.addWidget(self.anno_edit)
        anno_row.addWidget(anno_browse)
        form_layout.addRow('标注目录:', anno_row)

        # 图片目录
        self.img_edit = QLineEdit(self._default_img)
        self.img_edit.setPlaceholderText('原始图片所在目录...')
        img_browse = QPushButton('浏览...')
        img_browse.clicked.connect(lambda: self._browse('img'))
        img_row = QHBoxLayout()
        img_row.addWidget(self.img_edit)
        img_row.addWidget(img_browse)
        form_layout.addRow('图片目录:', img_row)

        # 输出目录
        self.out_edit = QLineEdit(self._default_out)
        self.out_edit.setPlaceholderText('转换后 .xml 输出目录...')
        out_browse = QPushButton('浏览...')
        out_browse.clicked.connect(lambda: self._browse('out'))
        out_row = QHBoxLayout()
        out_row.addWidget(self.out_edit)
        out_row.addWidget(out_browse)
        form_layout.addRow('输出目录:', out_row)

        layout.addWidget(dir_group)

        # ── 提示 ──
        hint = QLabel('提示：三个目录可以相同（所有文件混放），也可以不同。\n'
                      '     例如：标注在 annotations/，图片在 images/，输出到 annotations/')
        hint.setStyleSheet('color: #888; font-size: 12px;')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # ── 状态 / 进度 ──
        self.status_label = QLabel('')
        self.status_label.setStyleSheet('color: #888;')
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # ── 按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.convert_btn = QPushButton('开始转换')
        self.convert_btn.clicked.connect(self._on_convert)
        self.convert_btn.setStyleSheet(
            'QPushButton { padding: 6px 24px; font-weight: bold; }')

        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.close)

        btn_layout.addWidget(self.convert_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _browse(self, field):
        current = getattr(self, f'{field}_edit').text().strip()
        directory = QFileDialog.getExistingDirectory(
            self, '选择目录', current or os.path.expanduser('~'))
        if directory:
            getattr(self, f'{field}_edit').setText(directory)
            self.status_label.setText('')

    def _on_convert(self):
        if self._converting:
            return

        anno_dir = self.anno_edit.text().strip()
        img_dir = self.img_edit.text().strip()
        out_dir = self.out_edit.text().strip()

        errors = []
        if not anno_dir or not os.path.isdir(anno_dir):
            errors.append('标注目录无效或不存在')
        if not img_dir or not os.path.isdir(img_dir):
            errors.append('图片目录无效或不存在')
        if not out_dir:
            errors.append('请指定输出目录')
        if errors:
            QMessageBox.warning(self, '提示', '\n'.join(errors))
            return

        # 确保输出目录存在
        os.makedirs(out_dir, exist_ok=True)

        conv_idx = self.type_combo.currentIndex()
        conv_name = CONVERSIONS[conv_idx][0]

        reply = QMessageBox.question(
            self, '确认转换',
            f'即将执行格式转换：\n\n'
            f'  转换类型: {conv_name}\n'
            f'  标注目录: {anno_dir}\n'
            f'  图片目录: {img_dir}\n'
            f'  输出目录: {out_dir}\n\n'
            f'不会覆盖原标注文件。确定继续吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        self._run_conversion(anno_dir, img_dir, out_dir)

    def _run_conversion(self, anno_dir, img_dir, out_dir):
        self._converting = True
        self.convert_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(100)

        conv_func = CONVERSIONS[self.type_combo.currentIndex()][2]

        def status_callback(text, processed, total):
            if total > 0:
                self.progress_bar.setMaximum(total)
                self.progress_bar.setValue(processed)
            self.status_label.setText(text)
            QApplication.processEvents()

        def do_convert():
            try:
                success, fail, skip = conv_func(anno_dir, img_dir, out_dir, status_callback)
                self.progress_bar.setMaximum(100)
                self.progress_bar.setValue(100)

                parts = []
                if success:
                    parts.append(f'{success} 个成功')
                if skip:
                    parts.append(f'{skip} 个跳过（未找到对应图片）')
                if fail:
                    parts.append(f'{fail} 个失败（详情见控制台）')
                msg = '转换完成。' + '，'.join(parts) if parts else '未找到可转换的文件。'
                QMessageBox.information(self, '完成', msg)
            except Exception as e:
                QMessageBox.critical(self, '错误', f'转换过程异常: {e}')
            finally:
                self._converting = False
                self.convert_btn.setEnabled(True)

        QTimer.singleShot(50, do_convert)


# ── 批量删除对话框 ──────────────────────────────────────────

class CleanDialog(QDialog):
    """批量删除标注文件对话框 — 独立于转换功能，转换确认后手动清理原著文件使用。"""

    def __init__(self, parent=None, anno_dir=''):
        super().__init__(parent)
        self.setWindowTitle('删除标注文件')
        self.setMinimumWidth(540)
        self.setMinimumHeight(280)

        self._default_anno = anno_dir
        self._init_ui()
        self._scanning = False
        self._scan()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # ── 说明 ──
        desc = QLabel('选择要删除的标注文件类型和目录，删除操作不可撤销，请谨慎使用。')
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── 文件类型选择 ──
        type_label = QLabel('删除类型:')
        self.type_combo = QComboBox()
        self.type_combo.addItem('YOLO 标注文件 (*.txt)', ('.txt',))
        self.type_combo.addItem('PascalVOC 标注文件 (*.xml)', ('.xml',))
        self.type_combo.addItem('CreateML 标注文件 (*.json)', ('.json',))
        self.type_combo.addItem('全部标注文件 (txt/xml/json)', ('.txt', '.xml', '.json'))
        self.type_combo.currentIndexChanged.connect(self._scan)
        layout.addWidget(type_label)
        layout.addWidget(self.type_combo)
        layout.addSpacing(6)

        # ── 目录选择 ──
        dir_layout = QHBoxLayout()
        dir_label = QLabel('目标目录:')
        self.dir_edit = QLineEdit(self._default_anno)
        self.dir_edit.setPlaceholderText('标注文件所在目录...')
        self.dir_edit.textChanged.connect(self._scan)
        browse_btn = QPushButton('浏览...')
        browse_btn.clicked.connect(self._browse)
        dir_layout.addWidget(dir_label)
        dir_layout.addWidget(self.dir_edit, 1)
        dir_layout.addWidget(browse_btn)
        layout.addLayout(dir_layout)
        layout.addSpacing(6)

        # ── 预览 / 统计 ──
        self.preview_label = QLabel('')
        self.preview_label.setStyleSheet('color: #888;')
        layout.addWidget(self.preview_label)

        self.preview_list = QTextEdit()
        self.preview_list.setReadOnly(True)
        self.preview_list.setMaximumHeight(120)
        self.preview_list.setPlaceholderText('将在扫描后显示前 20 个文件...')
        layout.addWidget(self.preview_list)

        # ── 按钮 ──
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.delete_btn = QPushButton('删除文件')
        self.delete_btn.setStyleSheet(
            'QPushButton { padding: 6px 24px; font-weight: bold; color: red; }')
        self.delete_btn.clicked.connect(self._on_delete)

        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(self.close)

        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _browse(self):
        current = self.dir_edit.text().strip()
        directory = QFileDialog.getExistingDirectory(
            self, '选择目录', current or os.path.expanduser('~'))
        if directory:
            self.dir_edit.setText(directory)

    def _scan(self):
        """扫描目录，更新预览"""
        if self._scanning:
            return
        self._scanning = True

        directory = self.dir_edit.text().strip()
        if not directory or not os.path.isdir(directory):
            self.preview_label.setText('')
            self.preview_list.clear()
            self.delete_btn.setEnabled(False)
            self._scanning = False
            return

        exts = self.type_combo.currentData()
        all_files = []
        for f in os.listdir(directory):
            if any(f.lower().endswith(ext) for ext in exts):
                all_files.append(f)

        all_files.sort()
        count = len(all_files)

        if count == 0:
            self.preview_label.setText('未找到匹配的标注文件')
            self.preview_list.clear()
            self.delete_btn.setEnabled(False)
        else:
            self.preview_label.setText(f'找到 {count} 个标注文件')
            # 最多显示 20 行预览
            preview_items = all_files[:20]
            self.preview_list.setText('\n'.join(preview_items))
            if count > 20:
                self.preview_list.append(f'\n... 还有 {count - 20} 个文件')
            self.delete_btn.setEnabled(True)

        self._file_list = all_files
        self._scanning = False

    def _on_delete(self):
        if self.delete_btn.property('confirming'):
            # 第二轮确认 — 实际执行删除
            self._do_delete()
            return

        directory = self.dir_edit.text().strip()
        file_count = len(self._file_list)
        if file_count == 0:
            return

        ext_label = self.type_combo.currentText().split('(')[0].strip()
        reply = QMessageBox.warning(
            self, '确认删除',
            f'即将从以下目录删除 {file_count} 个 {ext_label}：\n\n'
            f'  {directory}\n\n'
            f'此操作不可撤销！确定要删除吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)

        if reply == QMessageBox.Yes:
            # 第二轮防误触：按钮变色，点击才真正执行
            self.delete_btn.setText('再次点击确认删除')
            self.delete_btn.setStyleSheet(
                'QPushButton { padding: 6px 24px; font-weight: bold; '
                'color: white; background-color: red; }')
            self.delete_btn.setProperty('confirming', True)
            # 5 秒后复位
            QTimer.singleShot(5000, self._reset_delete_btn)

    def _reset_delete_btn(self):
        self.delete_btn.setText('删除文件')
        self.delete_btn.setStyleSheet(
            'QPushButton { padding: 6px 24px; font-weight: bold; color: red; }')
        self.delete_btn.setProperty('confirming', False)

    def _do_delete(self):
        directory = self.dir_edit.text().strip()
        files = self._file_list
        total = len(files)
        deleted = 0
        errors = 0

        self.delete_btn.setEnabled(False)
        self.delete_btn.setText('正在删除...')

        for i, fname in enumerate(files):
            try:
                os.remove(os.path.join(directory, fname))
                deleted += 1
            except Exception as e:
                errors += 1
                print(f'[删除失败] {fname}: {e}')
            # 更新状态
            self.preview_label.setText(f'正在删除 [{i + 1}/{total}]...')
            QApplication.processEvents()

        self.delete_btn.setEnabled(True)
        self.delete_btn.setText('删除文件')
        self.delete_btn.setStyleSheet(
            'QPushButton { padding: 6px 24px; font-weight: bold; color: red; }')
        self.delete_btn.setProperty('confirming', False)

        parts = [f'成功删除 {deleted} 个文件']
        if errors:
            parts.append(f'{errors} 个失败（详情见控制台）')
        QMessageBox.information(self, '完成', '，'.join(parts) + '。')

        # 重新扫描
        self._scan()
