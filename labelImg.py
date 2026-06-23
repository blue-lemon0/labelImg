#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import codecs
import os.path
import platform
import shutil
import subprocess
import sys
import webbrowser as wb
from functools import partial
from collections import defaultdict

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from libs.combobox import ComboBox
from libs.resources import *
from libs.constants import *
from libs.utils import *
from libs.settings import Settings
from libs.shape import Shape, DEFAULT_LINE_COLOR, DEFAULT_FILL_COLOR
from libs.stringBundle import StringBundle
from libs.canvas import Canvas, KEY_BINDINGS
from libs.zoomWidget import ZoomWidget
from libs.lightWidget import LightWidget
from libs.slide_animator import AutoCollapseDockManager
from libs.compoundWidgets import ZoomWidgetPanel, LightWidgetPanel
from libs.labelDialog import LabelDialog
from libs.colorDialog import ColorDialog
from libs.labelFile import LabelFile, LabelFileError, LabelFileFormat
from libs.toolBar import ToolBar
from libs.pascal_voc_io import PascalVocReader
from libs.pascal_voc_io import XML_EXT
from libs.yolo_io import YoloReader
from libs.yolo_io import TXT_EXT
from libs.create_ml_io import CreateMLReader
from libs.create_ml_io import JSON_EXT
from libs.ustr import ustr
from libs.hashableQListWidgetItem import HashableQListWidgetItem
from libs.labelStats import (LabelStatsDialog, scan_single_annotation,
                             resolve_annotation_path,
                             batch_rename_label)
from libs.convertDialog import ConvertDialog, CleanDialog

__appname__ = 'labelImg'


class WindowMixin(object):

    def menu(self, title, actions=None):
        menu = self.menuBar().addMenu(title)
        if actions:
            add_actions(menu, actions)
        return menu

    def toolbar(self, title, actions=None):
        toolbar = ToolBar(title)
        toolbar.setObjectName(u'%sToolBar' % title)
        # toolbar.setOrientation(Qt.Vertical)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toolbar.setIconSize(QSize(24, 24))
        if actions:
            add_actions(toolbar, actions)
        return toolbar


class StatusManager:
    """管理状态栏消息，支持自动恢复默认提示。
    
    - set_default() 保存默认消息（如保存目录路径）
    - show() 显示消息，可设置延时后自动恢复默认
    - 无空白间隙：通过定时器恢复，不依赖 showMessage 超时
    """

    def __init__(self, status_bar):
        self._bar = status_bar
        self._default = ''
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._restore_default)

        # 拦截所有消息变化：如果状态栏被清空，恢复默认
        self._bar.messageChanged.connect(self._on_message_changed)

    def set_default(self, text):
        """设置默认消息。如果当前无临时消息，立即显示。"""
        self._default = text
        if not self._timer.isActive():
            self._restore_default()

    def clear_default(self):
        """清除默认消息。"""
        self._default = ''
        if not self._timer.isActive():
            self._bar.clearMessage()

    def show(self, text, delay=0):
        """显示消息。如果 delay > 0，超时后自动恢复默认。
        
        Args:
            text: 要显示的消息
            delay: 若 > 0，则在此毫秒后自动恢复默认
                   若为 0，消息一直保持到下次 show() 或 set_default() 调用
        """
        self._timer.stop()
        self._bar.showMessage(text)
        if delay > 0:
            self._timer.start(delay)

    def _restore_default(self):
        if self._default:
            self._bar.showMessage(self._default)
        else:
            self._bar.clearMessage()

    def _on_message_changed(self, text):
        """状态栏消息变化时的回调。
        
        如果状态栏变空白且有默认消息，则恢复默认。
        覆盖所有来自任何源的 clearMessage/showMessage('') 调用。
        """
        if not text and self._default:
            self._bar.showMessage(self._default)


class MainWindow(QMainWindow, WindowMixin):
    FIT_WINDOW, FIT_WIDTH, MANUAL_ZOOM = list(range(3))

    def __init__(self, default_filename=None, default_prefdef_class_file=None, default_save_dir=None):
        super(MainWindow, self).__init__()
        self.setWindowTitle(__appname__)

        self._init_state(default_filename, default_prefdef_class_file, default_save_dir)

        # ---- 左侧 QSplitter（在 _setup_ui_widgets 之前创建，scroll 直接进 splitter） ----
        self._left_placeholder = QWidget()
        self._left_placeholder.setMinimumWidth(80)
        self._left_splitter = QSplitter(Qt.Horizontal)
        self._left_splitter.setHandleWidth(8)
        self._left_splitter.setOpaqueResize(True)
        self._left_splitter.addWidget(self._left_placeholder)   # 左：占位

        self._setup_ui_widgets()
        # 首次填充预设标签下拉列表（从 predefined_classes / 历史标签）
        self._refresh_default_label_combo()

        # 侧边栏自动折叠 + 边缘唤醒（独立，零耦合）
        self._side_mgr = AutoCollapseDockManager(self)
        self._side_mgr.register(self.dock)
        self._side_mgr.register(self.file_dock)

        self._init_actions_and_menus()

        self.status_manager = StatusManager(self.statusBar())
        self.status_manager.show('%s started.' % __appname__)

        settings = self.settings

        # 窗口状态恢复
        size = settings.get(SETTING_WIN_SIZE, QSize(600, 500))
        position = QPoint(0, 0)
        saved_position = settings.get(SETTING_WIN_POSE, position)
        for i in range(QApplication.desktop().screenCount()):
            if QApplication.desktop().availableGeometry(i).contains(saved_position):
                position = saved_position
                break
        self.resize(size)
        self.move(position)

        self.update_path_info()
        self.restoreState(settings.get(SETTING_WIN_STATE, QByteArray()))
        if settings.get(SETTING_WIN_MAXIMIZED, False):
            self.setWindowState(self.windowState() | Qt.WindowMaximized)
        Shape.line_color = self.line_color = QColor(settings.get(SETTING_LINE_COLOR, DEFAULT_LINE_COLOR))
        Shape.fill_color = self.fill_color = QColor(settings.get(SETTING_FILL_COLOR, DEFAULT_FILL_COLOR))
        self.canvas.set_drawing_color(self.line_color)
        Shape.difficult = self.difficult

        def xbool(x):
            if isinstance(x, QVariant):
                return x.toBool()
            return bool(x)

        if xbool(settings.get(SETTING_ADVANCE_MODE, False)):
            self.actions.advancedMode.setChecked(True)
            self.toggle_advanced_mode()

        self.update_file_menu()

        # 加载文件可能耗时，放入队列异步执行
        if self.file_path and os.path.isdir(self.file_path):
            self.queue_event(partial(self.import_dir_images, self.file_path or ""))
        elif self.file_path:
            self.queue_event(partial(self.load_file, self.file_path or ""))
        elif self.last_open_dir and os.path.isdir(self.last_open_dir):
            self.queue_event(partial(self.import_dir_images, self.last_open_dir))

        # 回调绑定
        self.zoom_widget.valueChanged.connect(self.paint_canvas)
        self.light_widget.valueChanged.connect(self.paint_canvas)

        self.populate_mode_actions()

        # 在状态栏右侧显示鼠标坐标
        self.label_coordinates = QLabel('')
        self.statusBar().addPermanentWidget(self.label_coordinates)

        # 启动时同步工具栏按钮样式
        self._update_format_ui(
            {LabelFileFormat.PASCAL_VOC: FORMAT_PASCALVOC,
             LabelFileFormat.YOLO: FORMAT_YOLO,
             LabelFileFormat.CREATE_ML: FORMAT_CREATEML}[self.label_file_format])

        # 如果启动时传入的是目录，直接打开
        if self.file_path and os.path.isdir(self.file_path):
            self.open_dir_dialog(dir_path=self.file_path, silent=True)

        # 全局事件过滤器：在子控件之前拦截自定义快捷键
        self.installEventFilter(self)

        # ---- 替换左侧 placeholder 为实际工具栏 ----
        if self._left_placeholder is not None:
            idx = self._left_splitter.indexOf(self._left_placeholder)
            self._left_splitter.insertWidget(idx, self.tools)
            self._left_placeholder.setParent(None)
            self._left_placeholder.deleteLater()
            self._left_placeholder = None
            self._left_splitter.setSizes([140, max(self.width() - 140, 400)])
        # 拖拽信号 + 折叠计时器
        self._left_splitter.splitterMoved.connect(self._on_left_splitter_moved)
        self._left_tools_saved_width = 140
        self._collapse_check_timer = QTimer(self)
        self._collapse_check_timer.setSingleShot(True)
        self._collapse_check_timer.setInterval(200)
        self._collapse_check_timer.timeout.connect(self._check_left_collapse)

    def _init_state(self, default_filename, default_prefdef_class_file, default_save_dir):
        """初始化所有 self.* 状态属性（与 UI 无关）。"""
        self.settings = Settings()
        self.settings.load()
        self.os_name = platform.system()
        self.string_bundle = StringBundle.get_bundle()

        self.default_save_dir = default_save_dir
        self.label_file_format = self.settings.get(SETTING_LABEL_FILE_FORMAT, LabelFileFormat.PASCAL_VOC)

        self.m_img_list = []
        self.dir_name = None
        self.label_hist = []
        self.last_open_dir = None
        self.cur_img_idx = 0
        self.img_count = 0

        self._nav_labels = set()
        self._nav_active = False
        self._label_to_indices = {}
        self._img_label_map = {}
        self._stats_cache = None

        self.dirty = False
        self._undo_stack = []
        self._no_selection_slot = False
        self._beginner = True
        self.screencast = "https://youtu.be/p0nR2YsCY_U"

        self.load_predefined_classes(default_prefdef_class_file)
        self.default_label = self.label_hist[0] if self.label_hist else ""
        if not self.label_hist:
            print("Not find:/data/predefined_classes.txt (optional)")

        self.image = QImage()
        self.file_path = ustr(default_filename)
        self.recent_files = []
        self.max_recent = 7
        self.line_color = None
        self.fill_color = None
        self.zoom_level = 100
        self.fit_window = False
        self._saved_zoom = None
        self._saved_scroll_h = 0
        self._saved_scroll_v = 0
        self._preserve_zoom = False
        self.difficult = False

        if self.settings.get(SETTING_RECENT_FILES):
            self.recent_files = self.settings.get(SETTING_RECENT_FILES)

        self.last_open_dir = ustr(self.settings.get(SETTING_LAST_OPEN_DIR, None))

        save_dir = ustr(self.settings.get(SETTING_SAVE_DIR, None))
        if self.default_save_dir is None and save_dir is not None and os.path.exists(save_dir):
            self.default_save_dir = save_dir

    # ---------------------------------------------------------------------------
    # UI 构建：控件、停靠面板、画布
    # ---------------------------------------------------------------------------

    def _setup_ui_widgets(self):
        """创建主界面控件（标签列表、画布、停靠面板等）。"""
        get_str = lambda sid: self.string_bundle.get_string(sid)

        self.label_dialog = LabelDialog(parent=self, list_item=self.label_hist)

        self.items_to_shapes = {}
        self.shapes_to_items = {}
        self.prev_label_text = ''

        list_layout = QVBoxLayout()
        list_layout.setContentsMargins(0, 0, 0, 0)

        # 默认标签控件：复选框 + 可编辑下拉框（支持键入新标签或从已有标签选择）
        self.use_default_label_checkbox = QCheckBox(get_str('useDefaultLabel'))
        self.use_default_label_checkbox.setChecked(False)
        self.default_label_combo = QComboBox()
        self.default_label_combo.setEditable(True)
        self.default_label_combo.setInsertPolicy(QComboBox.NoInsert)
        self.default_label_combo.setPlaceholderText("输入或选择已有标签…")
        if self.default_label:
            self.default_label_combo.setEditText(self.default_label)
        self.default_label_combo.currentTextChanged.connect(self._update_default_label)
        # 下拉列表项右键菜单：从预选列表移除
        self.default_label_combo.view().setContextMenuPolicy(Qt.CustomContextMenu)
        self.default_label_combo.view().customContextMenuRequested.connect(
            self._show_dropdown_context_menu)

        use_default_label_qhbox_layout = QHBoxLayout()
        use_default_label_qhbox_layout.setContentsMargins(0, 0, 0, 0)
        use_default_label_qhbox_layout.addWidget(self.use_default_label_checkbox)
        use_default_label_qhbox_layout.addWidget(self.default_label_combo)
        use_default_label_container = QWidget()
        use_default_label_container.setLayout(use_default_label_qhbox_layout)

        # 编辑与「难以辨认」按钮控件
        self.diffc_button = QCheckBox(get_str('useDifficult'))
        self.diffc_button.setChecked(False)
        self.diffc_button.setToolTip("勾选后，当前选中的框标记为「难以辨认」\n评估模型时可选择排除此类样本（Pascal VOC difficult 标准）")
        self.diffc_button.stateChanged.connect(self.button_state)
        self.edit_button = QToolButton()
        self.edit_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        # 将控件添加到标签列表布局
        list_layout.addWidget(self.edit_button)
        list_layout.addWidget(self.diffc_button)
        list_layout.addWidget(use_default_label_container)

        # 创建下拉框，用于筛选标签
        self.combo_box = ComboBox(self)
        combo_layout = QHBoxLayout()
        combo_layout.setContentsMargins(0, 0, 0, 0)
        combo_layout.setSpacing(3)
        combo_label = QLabel("标签筛选")
        combo_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        combo_layout.addWidget(combo_label)
        combo_layout.addWidget(self.combo_box)
        combo_container = QWidget()
        combo_container.setLayout(combo_layout)
        list_layout.addWidget(combo_container)

        # 创建当前标注列表
        self.label_list = QListWidget()
        label_list_container = QWidget()
        label_list_container.setLayout(list_layout)
        self.label_list.itemActivated.connect(self.label_selection_changed)
        self.label_list.itemSelectionChanged.connect(self.label_selection_changed)
        self.label_list.itemDoubleClicked.connect(self.edit_label)
        # 监听 itemChanged 以检测复选框状态变化
        self.label_list.itemChanged.connect(self.label_item_changed)
        list_layout.addWidget(self.label_list)

        self.dock = QDockWidget(get_str('boxLabelText'), self)
        self.dock.setObjectName(get_str('labels'))
        self.dock.setWidget(label_list_container)

        self.file_list_widget = QListWidget()
        self.file_list_widget.itemDoubleClicked.connect(self.file_item_double_clicked)
        self.file_list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list_widget.customContextMenuRequested.connect(
            self._pop_file_list_menu)
        file_list_layout = QVBoxLayout()
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        file_list_layout.addWidget(self.file_list_widget)
        file_list_container = QWidget()
        file_list_container.setLayout(file_list_layout)
        self.file_dock = QDockWidget(get_str('fileList'), self)
        self.file_dock.setObjectName(get_str('files'))
        self.file_dock.setWidget(file_list_container)
        self._file_dock_base = get_str('fileList')

        self.zoom_widget = ZoomWidget()
        self.light_widget = LightWidget(get_str('lightWidgetTitle'))
        self.color_dialog = ColorDialog(parent=self)

        self.canvas = Canvas(parent=self)
        self.canvas.zoomRequest.connect(self.zoom_request)
        self.canvas.lightRequest.connect(self.light_request)
        self.canvas.set_drawing_shape_to_square(self.settings.get(SETTING_DRAW_SQUARE, False))

        scroll = QScrollArea()
        scroll.setWidget(self.canvas)
        scroll.setWidgetResizable(True)
        self.scroll_bars = {
            Qt.Vertical: scroll.verticalScrollBar(),
            Qt.Horizontal: scroll.horizontalScrollBar()
        }
        self.scroll_area = scroll
        self.canvas.scrollRequest.connect(self.scroll_request)

        self.canvas.newShape.connect(self.new_shape)
        self.canvas.shapeMoved.connect(self.set_dirty)
        self.canvas.selectionChanged.connect(self.shape_selection_changed)
        self.canvas.drawingPolygon.connect(self.toggle_drawing_sensitive)
        self.canvas.installEventFilter(self)

        # scroll 直接进已有的 splitter（右），不单独设 centralWidget
        self._left_splitter.addWidget(scroll)
        self._left_splitter.setStretchFactor(0, 0)
        self._left_splitter.setStretchFactor(1, 1)
        self.setCentralWidget(self._left_splitter)

        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.file_dock)
        self.file_dock.setFeatures(QDockWidget.DockWidgetFloatable)

        self.dock_features = QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetFloatable
        self.dock.setFeatures(self.dock.features() ^ self.dock_features)
        # 信号延迟到工具栏替换后再连接

    # ---------------------------------------------------------------------------
    # 创建所有 Action + 菜单栏/工具栏
    # ---------------------------------------------------------------------------
    def _init_actions_and_menus(self):
        """创建所有 Action 并组装菜单栏、工具栏、右键菜单、快捷键。"""
        from libs.actionBuilder import build_actions
        self.actions, self.menus, self.tools = build_actions(self)

    def eventFilter(self, obj, event):
        """在子控件（如 QListWidget、Canvas）消费前拦截快捷键。

        复用与 Canvas.keyPressEvent 相同的 KEY_BINDINGS 表，
        按键与逻辑保持解耦。
        """
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape and self._nav_active:
                self._clear_nav_mode()
                return True
            # ? 键（Shift+/ 或 Key_Question）或 H 键 → 打开快捷键面板
            ctrl = event.modifiers() & Qt.ControlModifier
            if event.key() == Qt.Key_H and not ctrl:
                self.show_shortcuts_dialog()
                return True
            if event.key() == Qt.Key_Question or \
               (event.key() == Qt.Key_Slash and (event.modifiers() & Qt.ShiftModifier)):
                self.show_shortcuts_dialog()
                return True
            shift = event.modifiers() & Qt.ShiftModifier
            action = KEY_BINDINGS.get((event.key(), shift))
            if action is not None:
                self.canvas.execute_action(action, event)
                return True
        return super().eventFilter(obj, event)

    # 辅助功能 #
    def _update_format_ui(self, save_format):
        """根据格式更新工具栏按钮样式。YOLO 模式下红色高亮，其他格式恢复默认。"""
        btn = self.tools.getButtonForAction(self.actions.save_format)
        if btn:
            if save_format == FORMAT_YOLO:
                btn.setStyleSheet(
                    "QToolButton { text-align: left; padding-left: 4px;"
                    " border: 2px solid #F44336; background-color: #FFF0F0;"
                    " font-weight: bold; }")
            else:
                btn.setStyleSheet(
                    "QToolButton { text-align: left; padding-left: 4px; }")

    def set_format(self, save_format):
        if save_format == FORMAT_PASCALVOC:
            self.actions.save_format.setText(FORMAT_PASCALVOC)
            self.actions.save_format.setIcon(new_icon("format_voc"))
            self.label_file_format = LabelFileFormat.PASCAL_VOC
            LabelFile.suffix = XML_EXT

        elif save_format == FORMAT_YOLO:
            self.actions.save_format.setText(FORMAT_YOLO)
            self.actions.save_format.setIcon(new_icon("format_yolo"))
            self.label_file_format = LabelFileFormat.YOLO
            LabelFile.suffix = TXT_EXT

        elif save_format == FORMAT_CREATEML:
            self.actions.save_format.setText(FORMAT_CREATEML)
            self.actions.save_format.setIcon(new_icon("format_createml"))
            self.label_file_format = LabelFileFormat.CREATE_ML
            LabelFile.suffix = JSON_EXT

        self._update_format_ui(save_format)

    def change_format(self):
        if self.label_file_format == LabelFileFormat.PASCAL_VOC:
            # 切换到 YOLO 前弹确认框，防止误触 Ctrl+Y
            reply = QMessageBox.warning(
                self, '确认切换',
                '即将切换到 YOLO 格式！\n\n'
                '⚠ 与 PascalVOC 的重要区别：\n'
                '• 标注保存为 .txt 文件（非 XML）\n'
                '• difficult 标记会被丢弃\n'
                '• 仅存储类别索引，不含类别名称\n\n'
                '确定要继续吗？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No)
            if reply != QMessageBox.Yes:
                return
            self.set_format(FORMAT_YOLO)
        elif self.label_file_format == LabelFileFormat.YOLO:
            self.set_format(FORMAT_CREATEML)
        elif self.label_file_format == LabelFileFormat.CREATE_ML:
            self.set_format(FORMAT_PASCALVOC)
        else:
            raise ValueError('Unknown label file format.')
        self.set_dirty()

    def no_shapes(self):
        return not self.items_to_shapes

    def toggle_advanced_mode(self, value=True):
        self._beginner = not value
        self.canvas.set_editing(True)
        self.populate_mode_actions()
        self.edit_button.setVisible(not value)
        if value:
            self.actions.createMode.setEnabled(True)
            self.actions.editMode.setEnabled(False)
            self.dock.setFeatures(self.dock.features() | self.dock_features)
        else:
            self.dock.setFeatures(self.dock.features() ^ self.dock_features)

    def populate_mode_actions(self):
        if self.beginner():
            tool, menu = self.actions.beginner, self.actions.beginnerContext
        else:
            tool, menu = self.actions.advanced, self.actions.advancedContext
        self.tools.clear()
        add_actions(self.tools, tool)
        self.canvas.menus[0].clear()
        add_actions(self.canvas.menus[0], menu)
        self.menus.edit.clear()
        actions = (self.actions.create,) if self.beginner()\
            else (self.actions.createMode, self.actions.editMode)
        add_actions(self.menus.edit, actions + self.actions.editMenu)

    def set_beginner(self):
        self.tools.clear()
        add_actions(self.tools, self.actions.beginner)

    def set_advanced(self):
        self.tools.clear()
        add_actions(self.tools, self.actions.advanced)

    def set_dirty(self):
        self.dirty = True
        self.actions.save.setEnabled(True)

    def set_clean(self):
        self.dirty = False
        self.actions.save.setEnabled(False)
        self.actions.create.setEnabled(True)

    # ── 左侧工具面板折叠（QSplitter 方案） ────────────

    def _on_left_splitter_moved(self, pos, index):
        """拖拽中实时适应画布；松手后（debounce timer）检查折叠。"""
        # 拖拽中：非手动缩放模式则实时重算
        if self.zoom_mode != self.MANUAL_ZOOM:
            self.adjust_scale()
        # 松手后检查（连续拖拽会不断重启，松手 200ms 后才触发）
        self._collapse_check_timer.start()

    def _check_left_collapse(self):
        """松手后检查是否需要自动折叠。"""
        sizes = self._left_splitter.sizes()
        if 0 < sizes[0] < 40:
            self._collapse_left_tools()

    def _collapse_left_tools(self):
        """收起左面板到 0。"""
        sizes = self._left_splitter.sizes()
        if sizes[0] > 0:
            self._left_tools_saved_width = sizes[0]
        total = sum(sizes)
        self._left_splitter.setSizes([0, total])

    def _expand_left_tools(self):
        """展开左面板到保存宽度。"""
        target = getattr(self, '_left_tools_saved_width', 140)
        sizes = self._left_splitter.sizes()
        total = sum(sizes)
        self._left_splitter.setSizes([target, total - target])

    def _toggle_all_panels(self):
        """切换所有侧边面板（左工具 + 右标注/文件）。"""
        self._side_mgr.toggle_all()
        if self._left_splitter.sizes()[0] > 0:
            self._collapse_left_tools()
        else:
            self._expand_left_tools()

    def toggle_actions(self, value=True):
        """启用/禁用依赖已打开图片的控件。"""
        for z in self.actions.zoomActions:
            z.setEnabled(value)
        for z in self.actions.lightActions:
            z.setEnabled(value)
        for action in self.actions.onLoadActive:
            action.setEnabled(value)

    def queue_event(self, function):
        QTimer.singleShot(0, function)

    def status(self, message, delay=5000):
        self.status_manager.show(message, delay)

    def reset_state(self):
        self.items_to_shapes.clear()
        self.shapes_to_items.clear()
        self.label_list.clear()
        self.file_path = None
        self.image_data = None
        self.label_file = None
        self.canvas.reset_state()
        self.label_coordinates.clear()
        self.combo_box.cb.clear()

    def current_item(self):
        items = self.label_list.selectedItems()
        if items:
            return items[0]
        return None

    def add_recent_file(self, file_path):
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
        elif len(self.recent_files) >= self.max_recent:
            self.recent_files.pop()
        self.recent_files.insert(0, file_path)

    def beginner(self):
        return self._beginner

    def advanced(self):
        return not self.beginner()

    def show_tutorial_dialog(self, browser='default', link=None):
        if link is None:
            link = self.screencast

        if browser.lower() == 'default':
            wb.open(link, new=2)
        elif browser.lower() == 'chrome' and self.os_name == 'Windows':
            if shutil.which(browser.lower()):  # 'chrome' not in wb._browsers in windows
                wb.register('chrome', None, wb.BackgroundBrowser('chrome'))
            else:
                chrome_path="D:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
                if os.path.isfile(chrome_path):
                    wb.register('chrome', None, wb.BackgroundBrowser(chrome_path))
            try:
                wb.get('chrome').open(link, new=2)
            except:
                wb.open(link, new=2)
        elif browser.lower() in wb._browsers:
            wb.get(browser.lower()).open(link, new=2)

    def show_default_tutorial_dialog(self):
        self.show_tutorial_dialog(browser='default')

    def show_info_dialog(self):
        from libs.__init__ import __version__
        msg = u'Name:{0} \nApp Version:{1} \n{2} '.format(__appname__, __version__, sys.version_info)
        QMessageBox.information(self, u'Information', msg)

    def show_shortcuts_dialog(self):
        """显示快捷键速查表，按功能分组。"""
        # items: ('功能', '快捷键', is_frequent)  is_frequent=True 时为蓝色高亮
        groups = [
            ('常用功能', [
                ('创建标注框', 'W', True),
                ('上一张图片', 'A', True),
                ('下一张图片', 'D', True),
                ('进入顶点模式 / 顺时针切换顶点', 'C', True),
                ('进入顶点模式 / 逆时针切换顶点', 'Z', True),
                ('选择下一个标注', 'X', True),
                ('选择上一个标注', 'Shift+X', False),
                ('移动标注 / 顶点', '↑ ↓ ← →', True),
                ('缩放', 'Ctrl+滚轮', True),
            ]),
            ('图片导航', [
                ('打开图片', 'Ctrl+O', False),
                ('打开目录', 'Ctrl+U', False),
                ('打开标注文件', 'Ctrl+Shift+O', False),
                ('保存', 'Ctrl+S', True),
                ('另存为', 'Ctrl+Shift+S', False),
                ('修改保存目录', 'Ctrl+R', False),
                ('删除图片', 'Ctrl+Shift+D', False),
                ('记住缩放位置', '菜单/工具栏切换', False),
                ('关闭', 'Ctrl+W', False),
                ('退出', 'Ctrl+Q', False),
            ]),
            ('标注绘制', [
                ('闭合标注', 'Enter', False),
                ('取消绘制 / 退出顶点模式', 'Esc', False),
                ('标记已确认', 'Space', False),
                ('拖拽时临时约束正方形', '按住Ctrl拖拽', True),
            ]),
            ('选择与编辑', [
                ('复制标注框', 'Ctrl+D', False),
                ('复制上一张标注', 'Ctrl+V', True),
                ('删除选中框', 'Delete', True),
                ('撤销', 'Ctrl+Z', True),
                ('标注框线颜色', 'Ctrl+L', False),
                ('隐藏全部标注', 'Ctrl+H', False),
                ('显示全部标注', 'Ctrl+A', False),
            ]),
            ('视图控制', [
                ('放大', 'Ctrl++', True),
                ('缩小', 'Ctrl+-', True),
                ('缩放到 100%', 'Ctrl+=', False),
                ('适应窗口', 'Ctrl+F', False),
                ('适应宽度', 'Ctrl+Shift+F', False),
                ('拖动平移画布', '鼠标左键拖拽', False),
                ('调亮', 'Ctrl+Shift++', False),
                ('调暗', 'Ctrl+Shift+-', False),
                ('调亮度', 'Ctrl+Shift+滚轮', False),
            ]),
            ('模式切换', [
                ('单一类别模式', 'Ctrl+Shift+S', False),
                ('强制画正方形（开关）', 'Ctrl+Shift+R', False),
                ('编辑模式', 'Ctrl+J', False),
                ('高级模式', 'Ctrl+Shift+A', False),
                ('显示/隐藏标签文字', 'Ctrl+Shift+P', False),
            ]),
            ('其他', [
                ('快捷键帮助', '? / H', True),
                ('格式切换', 'Ctrl+Y', False),
                ('标签统计面板', 'Ctrl+T', False),
            ]),
        ]

        dialog = QDialog(self)
        dialog.setWindowTitle('快捷键')
        dialog.setMinimumSize(600, 420)
        dialog.resize(700, 580)

        root_layout = QVBoxLayout(dialog)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        for group_title, items in groups:
            gbox = QGroupBox(group_title)
            gbox.setStyleSheet(
                'QGroupBox { font-weight: bold; font-size: 12px; '
                'border: 1px solid #ccc; border-radius: 4px; '
                'margin-top: 8px; padding: 12px 6px 6px 6px; }'
                'QGroupBox::title { subcontrol-origin: margin; '
                'left: 10px; padding: 0 4px; }'
            )
            g_layout = QVBoxLayout(gbox)
            g_layout.setContentsMargins(4, 4, 4, 4)
            g_layout.setSpacing(0)

            table = QTableWidget(len(items), 2)
            table.setHorizontalHeaderLabels(['功能', '快捷键'])
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setSelectionMode(QTableWidget.NoSelection)
            table.setShowGrid(False)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

            BLUE = QColor('#1976D2')
            for i, (text, key, is_freq) in enumerate(items):
                func_item = QTableWidgetItem(text)
                if is_freq:
                    func_item.setForeground(BLUE)
                table.setItem(i, 0, func_item)
                key_item = QTableWidgetItem(key)
                font = key_item.font()
                font.setBold(True)
                if is_freq:
                    key_item.setForeground(BLUE)
                key_item.setFont(font)
                table.setItem(i, 1, key_item)

            # 固定表格高度以容纳全部行（避免内部滚动条）
            header_h = table.horizontalHeader().height()
            row_total = sum(table.rowHeight(r) for r in range(len(items)))
            table.setFixedHeight(header_h + row_total + 4)

            g_layout.addWidget(table)
            layout.addWidget(gbox)

        layout.addStretch()
        scroll.setWidget(content)
        root_layout.addWidget(scroll)

        close_btn = QPushButton('关闭')
        close_btn.clicked.connect(dialog.accept)
        root_layout.addWidget(close_btn, alignment=Qt.AlignCenter)

        dialog.exec_()

    def create_shape(self):
        assert self.beginner()
        if not self.canvas.editing():  # 已就绪画框 → 取消
            self.canvas.set_editing(True)
            self.actions.create.setEnabled(True)
            return
        # 进入绘制模式前快照，撤销时彻底移除刚画的框（不受 finalise 提前入栈影响）
        self._undo_stack.append(self._snapshot_shapes())
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)
        self.canvas.set_editing(False)
        self.actions.create.setEnabled(False)

    def toggle_drawing_sensitive(self, drawing=True):
        """绘制过程中，禁止切换模式（包括 W 键）。"""
        if drawing:
            self.actions.editMode.setEnabled(False)
            self.actions.createMode.setEnabled(False)  # 拖拽中禁用 W
        else:
            self.actions.editMode.setEnabled(True)
            self.actions.createMode.setEnabled(True)
            if self.beginner():
                # 取消绘制
                print('Cancel creation.')
                self.canvas.set_editing(True)
                self.canvas.restore_cursor()
                self.actions.create.setEnabled(True)

    def toggle_draw_mode(self, edit=True):
        if not edit:
            # 进入绘制模式前快照，撤销时彻底移除刚画的框
            self._undo_stack.append(self._snapshot_shapes())
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)
        self.canvas.set_editing(edit)
        self.actions.createMode.setEnabled(True)  # W 始终保持可切换
        self.actions.editMode.setEnabled(not edit)

    def set_create_mode(self):
        assert self.advanced()
        if not self.canvas.editing():  # 已在创建模式 → 切回编辑
            self.set_edit_mode()
            return
        self.toggle_draw_mode(False)

    def set_edit_mode(self):
        assert self.advanced()
        self.toggle_draw_mode(True)
        self.label_selection_changed()

    def update_file_menu(self):
        curr_file_path = self.file_path

        def exists(filename):
            return os.path.exists(filename)
        menu = self.menus.recentFiles
        menu.clear()
        files = [f for f in self.recent_files if f !=
                 curr_file_path and exists(f)]
        for i, f in enumerate(files):
            icon = new_icon('labels')
            action = QAction(
                icon, '&%d %s' % (i + 1, QFileInfo(f).fileName()), self)
            action.triggered.connect(partial(self.load_recent, f))
            menu.addAction(action)

    def pop_label_list_menu(self, point):
        self.menus.labelList.exec_(self.label_list.mapToGlobal(point))

    def edit_label(self):
        if not self.canvas.editing():
            return
        item = self.current_item()
        if not item:
            return
        text = self.label_dialog.pop_up(item.text())
        if text is not None:
            item.setText(text)
            item.setBackground(generate_color_by_text(text))
            self.set_dirty()
            self.update_combo_box()

    # Tzutalin 20160906：文件列表，双击切换图片
    def file_item_double_clicked(self, item=None):
        abs_path = ustr(item.data(Qt.UserRole))
        self.cur_img_idx = self.m_img_list.index(abs_path)
        filename = self.m_img_list[self.cur_img_idx]
        if filename:
            if self.file_path is not None and self.remember_zoom_action.isChecked():
                self._save_zoom_scroll()
                self._preserve_zoom = True
            self.load_file(filename)

    # 右键菜单：在文件管理器中定位标注文件
    def _find_annotation_path(self, img_path):
        """查找图片对应的标注文件路径（XML / TXT / JSON）。"""
        return resolve_annotation_path(img_path, self.default_save_dir)

    def _pop_file_list_menu(self, point):
        item = self.file_list_widget.itemAt(point)
        if not item:
            return
        img_path = ustr(item.data(Qt.UserRole))
        anno_path = self._find_annotation_path(img_path)

        menu = QMenu()
        if anno_path:
            action = menu.addAction('在文件管理器中定位标注文件')
            action.triggered.connect(partial(self._open_in_file_manager, anno_path))
        else:
            action = menu.addAction('在文件管理器中定位图片')
            action.triggered.connect(partial(self._open_in_file_manager, img_path))
        menu.exec_(self.file_list_widget.mapToGlobal(point))

    def _open_in_file_manager(self, path):
        """在系统文件管理器中打开并选中文件。"""
        path = os.path.normpath(path)
        if platform.system() == 'Windows':
            subprocess.Popen(['explorer', '/select,', path])
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', '-R', path])
        else:
            subprocess.Popen(['xdg-open', os.path.dirname(path)])

    # Chris 添加：difficult 标记
    def button_state(self, item=None):
        """处理 difficult 复选框，更新到当前 shape"""
        if not self.canvas.editing():
            return

        item = self.current_item()
        if not item:  # If not selected Item, take the first one
            item = self.label_list.item(self.label_list.count() - 1)

        difficult = self.diffc_button.isChecked()

        try:
            shape = self.items_to_shapes[item]
        except:
            pass
        # 同步状态
        try:
            if difficult != shape.difficult:
                shape.difficult = difficult
                self.set_dirty()
            else:  # User probably changed item visibility
                self.canvas.set_shape_visible(shape, item.checkState() == Qt.Checked)
        except:
            pass

    # 响应画布信号
    def shape_selection_changed(self, selected=False):
        if self._no_selection_slot:
            self._no_selection_slot = False
        else:
            shape = self.canvas.selected_shape
            if shape:
                self.shapes_to_items[shape].setSelected(True)
            else:
                self.label_list.clearSelection()
        self.actions.delete.setEnabled(selected)
        self.actions.copy.setEnabled(selected)
        self.actions.edit.setEnabled(selected)
        self.actions.shapeLineColor.setEnabled(selected)
        self.actions.shapeFillColor.setEnabled(selected)

    def add_label(self, shape):
        shape.paint_label = self.display_label_option.isChecked()
        item = HashableQListWidgetItem(shape.label)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        item.setBackground(generate_color_by_text(shape.label))
        self.items_to_shapes[item] = shape
        self.shapes_to_items[shape] = item
        self.label_list.addItem(item)
        for action in self.actions.onShapesPresent:
            action.setEnabled(True)
        self.update_combo_box()

    def remove_label(self, shape):
        if shape is None:
            # print('rm empty label')
            return
        item = self.shapes_to_items.get(shape)
        if item is None:
            return
        self.label_list.takeItem(self.label_list.row(item))
        del self.shapes_to_items[shape]
        del self.items_to_shapes[item]
        self.update_combo_box()

    def _validate_label_list(self):
        """检查标签列表：若列表项的 shape 已不存在于 canvas 中，标记为红色提示"""
        shapes = self.canvas.shapes
        for i in range(self.label_list.count()):
            item = self.label_list.item(i)
            shape = self.items_to_shapes.get(item)
            if shape is None or shape not in shapes:
                item.setForeground(QColor(Qt.red))
            else:
                item.setForeground(QColor(Qt.black))

    def load_labels(self, shapes, replace=True, repaint_canvas=True):
        s = []
        for label, points, line_color, fill_color, difficult in shapes:
            shape = Shape(label=label)
            for x, y in points:

                # 确保标注点不超出图片边界，超出则吸附
                x, y, snapped = self.canvas.snap_point_to_canvas(x, y)
                if snapped:
                    self.set_dirty()

                shape.add_point(QPointF(x, y))
            shape.difficult = difficult
            shape.close()
            s.append(shape)

            if line_color:
                shape.line_color = QColor(*line_color)
            else:
                shape.line_color = generate_color_by_text(label)

            if fill_color:
                shape.fill_color = QColor(*fill_color)
            else:
                shape.fill_color = generate_color_by_text(label)

            self.add_label(shape)
        self.update_combo_box()
        if replace:
            self.canvas.load_shapes(s, repaint=repaint_canvas)
        else:
            self.canvas.shapes.extend(s)
        self._validate_label_list()

    def update_combo_box(self):
        # 获取唯一的标签名，填充到下拉框
        items_text_list = [str(self.label_list.item(i).text()) for i in range(self.label_list.count())]

        unique_text_list = list(set(items_text_list))
        # 添加空行表示显示全部
        unique_text_list.append("")
        unique_text_list.sort()

        self.combo_box.update_items(unique_text_list)
        # 同步刷新预设标签下拉框的候选列表
        self._refresh_default_label_combo()

    def save_labels(self, annotation_file_path):
        annotation_file_path = ustr(annotation_file_path)
        if self.label_file is None:
            self.label_file = LabelFile()
            self.label_file.verified = self.canvas.verified

        def format_shape(s):
            return dict(label=s.label,
                        line_color=s.line_color.getRgb(),
                        fill_color=s.fill_color.getRgb(),
                        points=[(p.x(), p.y()) for p in s.points],
                        # Chris 添加：difficult 标记
                        difficult=s.difficult)

        shapes = [format_shape(shape) for shape in self.canvas.shapes]
        # 可在此扩展其他标注格式
        try:
            if self.label_file_format == LabelFileFormat.PASCAL_VOC:
                if annotation_file_path[-4:].lower() != ".xml":
                    annotation_file_path += XML_EXT
                self.label_file.save_pascal_voc_format(annotation_file_path, shapes, self.file_path, self.image_data,
                                                       self.line_color.getRgb(), self.fill_color.getRgb())
            elif self.label_file_format == LabelFileFormat.YOLO:
                if annotation_file_path[-4:].lower() != ".txt":
                    annotation_file_path += TXT_EXT
                self.label_file.save_yolo_format(annotation_file_path, shapes, self.file_path, self.image_data, self.label_hist,
                                                 self.line_color.getRgb(), self.fill_color.getRgb())
            elif self.label_file_format == LabelFileFormat.CREATE_ML:
                if annotation_file_path[-5:].lower() != ".json":
                    annotation_file_path += JSON_EXT
                self.label_file.save_create_ml_format(annotation_file_path, shapes, self.file_path, self.image_data,
                                                      self.label_hist, self.line_color.getRgb(), self.fill_color.getRgb())
            else:
                self.label_file.save(annotation_file_path, shapes, self.file_path, self.image_data,
                                     self.line_color.getRgb(), self.fill_color.getRgb())
            print('Image:{0} -> Annotation:{1}'.format(self.file_path, annotation_file_path))
            return True
        except LabelFileError as e:
            self.error_message(u'Error saving label data', u'<b>%s</b>' % e)
            return False

    def copy_selected_shape(self):
        if self.canvas.selected_shape:
            self._undo_stack.append(self._snapshot_shapes())
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)
            self.add_label(self.canvas.copy_selected_shape())
            # 修复复制后删除的问题
            self.shape_selection_changed(True)

    def combo_selection_changed(self, index):
        text = self.combo_box.cb.itemText(index)
        for i in range(self.label_list.count()):
            if text == "":
                self.label_list.item(i).setCheckState(2)
            elif text != self.label_list.item(i).text():
                self.label_list.item(i).setCheckState(0)
            else:
                self.label_list.item(i).setCheckState(2)

    def _update_default_label(self, text):
        self.default_label = text

    def _refresh_default_label_combo(self):
        """用 _label_to_indices + label_hist 里的候选标签刷新下拉列表。"""
        current = self.default_label_combo.currentText()
        labels = set()
        labels.update(self._label_to_indices.keys())
        labels.update(self.label_hist)
        labels.discard("")
        self.default_label_combo.blockSignals(True)
        self.default_label_combo.clear()
        if labels:
            self.default_label_combo.addItems(sorted(labels))
        self.default_label_combo.setEditText(current)
        self.default_label_combo.blockSignals(False)

    def _show_dropdown_context_menu(self, pos):
        """下拉列表项右键菜单：从预选列表中移除该项。"""
        index = self.default_label_combo.view().indexAt(pos)
        if not index.isValid():
            return
        text = index.data().strip()
        if not text:
            return
        menu = QMenu()
        action = menu.addAction(f'从预选列表移除「{text}」')
        action.triggered.connect(lambda checked, t=text: self._remove_from_preset_labels(t))
        menu.exec_(self.default_label_combo.view().viewport().mapToGlobal(pos))

    def _remove_from_preset_labels(self, text):
        """从 label_hist 移除，刷新下拉。若标签仍存在于标注中则自动保留。"""
        self.label_hist = [l for l in self.label_hist if l.lower() != text.lower()]
        self._refresh_default_label_combo()

    def label_selection_changed(self):
        item = self.current_item()
        if item and self.canvas.editing():
            self._no_selection_slot = True
            self.canvas.select_shape(self.items_to_shapes[item])
            shape = self.items_to_shapes[item]
            # Chris 添加：difficult 标记
            self.diffc_button.setChecked(shape.difficult)

    def label_item_changed(self, item):
        shape = self.items_to_shapes[item]
        label = item.text()
        if label != shape.label:
            shape.label = item.text()
            shape.line_color = generate_color_by_text(shape.label)
            self.set_dirty()
        else:  # User probably changed item visibility
            self.canvas.set_shape_visible(shape, item.checkState() == Qt.Checked)

    # 回调函数
    def new_shape(self):
        """弹出标签编辑器并获取焦点。

        position 必须是全局坐标。
        """
        if not self.use_default_label_checkbox.isChecked() or not self.default_label_combo.currentText():
            # 下拉候选：标注文件中已有的标签（删框保存后自动消失）
            #          + 最近 10 个尚未保存过的新标签（方便新建时选用）
            annotation_labels = sorted(self._label_to_indices.keys())
            recent_unsaved = []
            for label in reversed(self.label_hist):
                if label not in annotation_labels:
                    recent_unsaved.append(label)
                    if len(recent_unsaved) >= 10:
                        break
            all_labels = list(annotation_labels) + recent_unsaved
            self.label_dialog = LabelDialog(
                parent=self, list_item=all_labels)

            # 单类别模式（PR#106）
            if self.single_class_mode.isChecked() and self.lastLabel:
                text = self.lastLabel
            else:
                text = self.label_dialog.pop_up(text=self.prev_label_text)
                self.lastLabel = text
        else:
            text = self.default_label_combo.currentText()

        # Chris 添加：difficult 标记
        self.diffc_button.setChecked(False)
        if text is not None:
            self.prev_label_text = text
            generate_color = generate_color_by_text(text)
            shape = self.canvas.set_last_label(text, generate_color, generate_color)
            self.add_label(shape)
            if self.beginner():  # Switch to edit mode.
                self.canvas.set_editing(True)
                self.actions.create.setEnabled(True)
            else:
                self.canvas.set_editing(True)
                self.actions.createMode.setEnabled(True)
                self.actions.editMode.setEnabled(True)
            self.set_dirty()

            # 加入历史：大小写去重 + 最近最多 100 条
            self._add_to_label_hist(text)
        else:
            # self.canvas.undoLastLine()
            self.canvas.reset_all_lines()

    def _add_to_label_hist(self, text):
        """将标签加入历史记录（大小写去重，保留最近 100 条）。"""
        # 先移除同名的（大小写不敏感），保证最新拼写排在最后
        self.label_hist = [l for l in self.label_hist if l.lower() != text.lower()]
        self.label_hist.append(text)
        # 保留最近 100 条
        if len(self.label_hist) > 100:
            self.label_hist = self.label_hist[-100:]

    def scroll_request(self, delta, orientation):
        units = - delta / (8 * 15)
        bar = self.scroll_bars[orientation]
        bar.setValue(int(bar.value() + bar.singleStep() * units))

    def set_zoom(self, value):
        self.actions.fitWidth.setChecked(False)
        self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.MANUAL_ZOOM
        # 缩放系数计算可能产生浮点
        # 转为 int 避免类型错误
        self.zoom_widget.setValue(int(value))

    def add_zoom(self, increment=10):
        self.set_zoom(self.zoom_widget.value() + increment)

    def zoom_request(self, delta):
        # 获取当前滚动条位置
        # 计算百分比坐标
        h_bar = self.scroll_bars[Qt.Horizontal]
        v_bar = self.scroll_bars[Qt.Vertical]

        # 获取当前最大值，缩放后计算差值
        h_bar_max = h_bar.maximum()
        v_bar_max = v_bar.maximum()

        # 获取光标位置和画布尺寸
        # 计算目标移动量（0~1）
        # 0 = 向左移
        # 1 = 向右移
        # 上下同理
        cursor = QCursor()
        pos = cursor.pos()
        relative_pos = QWidget.mapFromGlobal(self, pos)

        cursor_x = relative_pos.x()
        cursor_y = relative_pos.y()

        w = self.scroll_area.width()
        h = self.scroll_area.height()

        # 0~1 缩放留了边距
        # 不必精准点击最边缘即可达到最大移动
        margin = 0.1
        move_x = (cursor_x - margin * w) / (w - 2 * margin * w)
        move_y = (cursor_y - margin * h) / (h - 2 * margin * h)

        # 限制在 0~1 范围内
        move_x = min(max(move_x, 0), 1)
        move_y = min(max(move_y, 0), 1)

        # 放大
        units = delta // (8 * 15)
        scale = 10
        self.add_zoom(scale * units)

        # 计算滚动条差值的差值
        # 即可以移动多远
        d_h_bar_max = h_bar.maximum() - h_bar_max
        d_v_bar_max = v_bar.maximum() - v_bar_max

        # 计算新的滚动条位置
        new_h_bar_value = int(h_bar.value() + move_x * d_h_bar_max)
        new_v_bar_value = int(v_bar.value() + move_y * d_v_bar_max)

        h_bar.setValue(new_h_bar_value)
        v_bar.setValue(new_v_bar_value)

    def light_request(self, delta):
        self.add_light(5*delta // (8 * 15))

    def set_fit_window(self, value=True):
        if value:
            self.actions.fitWidth.setChecked(False)
        self.zoom_mode = self.FIT_WINDOW if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def set_fit_width(self, value=True):
        if value:
            self.actions.fitWindow.setChecked(False)
        self.zoom_mode = self.FIT_WIDTH if value else self.MANUAL_ZOOM
        self.adjust_scale()

    def set_light(self, value):
        self.light_widget.setValue(int(value))

    def add_light(self, increment=10):
        self.set_light(self.light_widget.value() + increment)

    def _save_zoom_scroll(self):
        """记住当前缩放比例和滚动条位置，供下一张图恢复。"""
        self._saved_zoom = self.zoom_widget.value()
        self._saved_scroll_h = self.scroll_bars[Qt.Horizontal].value()
        self._saved_scroll_v = self.scroll_bars[Qt.Vertical].value()

    def toggle_polygons(self, value):
        for item, shape in self.items_to_shapes.items():
            item.setCheckState(Qt.Checked if value else Qt.Unchecked)

    def load_file(self, file_path=None):
        """加载指定文件，若为 None 则加载上次打开的文件。"""
        # 捕获保存的缩放/滚动状态后立即清空，避免非翻页路径误用
        _preserve = self._preserve_zoom and self._saved_zoom is not None
        _saved_zoom = self._saved_zoom
        _saved_h = self._saved_scroll_h
        _saved_v = self._saved_scroll_v
        self._preserve_zoom = False
        self._saved_zoom = None
        self.reset_state()
        self.canvas.setEnabled(False)
        if file_path is None:
            file_path = self.settings.get(SETTING_FILENAME)
        # 确保 filePath 是普通 Python 字符串，而非 QString
        file_path = ustr(file_path)

        # 修复：选择目录后打开新文件时的索引错误
        unicode_file_path = ustr(file_path)
        unicode_file_path = os.path.abspath(unicode_file_path)
        # Tzutalin 20160906：文件列表，双击切换图片
        # 高亮当前图片并滚动到可见区域
        if unicode_file_path and self.file_list_widget.count() > 0:
            if unicode_file_path in self.m_img_list:
                index = self.m_img_list.index(unicode_file_path)
                self.cur_img_idx = index
                self.img_count = len(self.m_img_list)
                file_widget_item = self.file_list_widget.item(index)
                file_widget_item.setSelected(True)
                self.file_list_widget.scrollToItem(file_widget_item, QAbstractItemView.PositionAtCenter)
            else:
                self.file_list_widget.clear()
                self.m_img_list.clear()

        if unicode_file_path and os.path.exists(unicode_file_path):
            if LabelFile.is_label_file(unicode_file_path):
                try:
                    self.label_file = LabelFile(unicode_file_path)
                except LabelFileError as e:
                    self.error_message(u'Error opening file',
                                       (u"<p><b>%s</b></p>"
                                        u"<p>Make sure <i>%s</i> is a valid label file.")
                                       % (e, unicode_file_path))
                    self.status("Error reading %s" % unicode_file_path)
                    
                    return False
                self.image_data = self.label_file.image_data
                self.line_color = QColor(*self.label_file.lineColor)
                self.fill_color = QColor(*self.label_file.fillColor)
                self.canvas.verified = self.label_file.verified
            else:
                # 加载图片：
                # 先读取数据，保存到标注文件时使用
                self.image_data = read(unicode_file_path, None)
                self.label_file = None
                self.canvas.verified = False

            if isinstance(self.image_data, QImage):
                image = self.image_data
            else:
                image = QImage.fromData(self.image_data)
            if image.isNull():
                self.error_message(u'Error opening file',
                                   u"<p>Make sure <i>%s</i> is a valid image file." % unicode_file_path)
                self.status("Error reading %s" % unicode_file_path)
                return False
            self.status("Loaded %s" % os.path.basename(unicode_file_path))
            self.image = image
            self.file_path = unicode_file_path
            if _preserve:
                self.canvas.pixmap = QPixmap.fromImage(image)
                self.canvas.scale = 0.01 * _saved_zoom
                if self.label_file:
                    self.load_labels(self.label_file.shapes, repaint_canvas=False)
                else:
                    self.canvas.shapes = []
                self.canvas.adjustSize()
                self.scroll_bars[Qt.Horizontal].setValue(_saved_h)
                self.scroll_bars[Qt.Vertical].setValue(_saved_v)
                self.canvas.repaint()
                self.zoom_widget.setValue(_saved_zoom)
            else:
                self.canvas.load_pixmap(QPixmap.fromImage(image))
                self.adjust_scale(initial=True)
                if self.label_file:
                    self.load_labels(self.label_file.shapes)
            self.set_clean()
            self.canvas.setEnabled(True)
            self.paint_canvas()
            self.add_recent_file(self.file_path)
            self.toggle_actions(True)
            self.show_bounding_box_from_annotation_file(self.file_path)

            counter = self.counter_str()
            self.setWindowTitle(__appname__ + ' ' + file_path + ' ' + counter)
            self.file_dock.setWindowTitle(self._file_dock_base + ' ' + counter)
            self.update_path_info()

            # 默认选择标签列表的最后一项
            if self.label_list.count():
                self.label_list.setCurrentItem(self.label_list.item(self.label_list.count() - 1))
                self.label_list.item(self.label_list.count() - 1).setSelected(True)

            self.canvas.setFocus(True)
            return True
        return False

    def counter_str(self):
        """
        Converts image counter to string representation.
        """
        base = '[{} / {}]'.format(self.cur_img_idx + 1, self.img_count)
        if self._nav_active:
            labels_shown = sorted(self._nav_labels, key=lambda x: (x == '', x))
            display = ', '.join(l if l else '(空标签)' for l in labels_shown)
            base += ' [导航: {}]'.format(display)
        return base

    def show_bounding_box_from_annotation_file(self, file_path, replace=True):
        if self.default_save_dir is not None:
            basename = os.path.basename(os.path.splitext(file_path)[0])
            xml_path = os.path.join(self.default_save_dir, basename + XML_EXT)
            txt_path = os.path.join(self.default_save_dir, basename + TXT_EXT)
            json_path = os.path.join(self.default_save_dir, basename + JSON_EXT)

            """标注文件优先级：
            PascalXML > YOLO > CreateML
            """
            if os.path.isfile(xml_path):
                self.load_pascal_xml_by_filename(xml_path, replace=replace)
            elif os.path.isfile(txt_path):
                self.load_yolo_txt_by_filename(txt_path, replace=replace)
            elif os.path.isfile(json_path):
                self.load_create_ml_json_by_filename(json_path, file_path, replace=replace)

        else:
            xml_path = os.path.splitext(file_path)[0] + XML_EXT
            txt_path = os.path.splitext(file_path)[0] + TXT_EXT
            json_path = os.path.splitext(file_path)[0] + JSON_EXT

            if os.path.isfile(xml_path):
                self.load_pascal_xml_by_filename(xml_path, replace=replace)
            elif os.path.isfile(txt_path):
                self.load_yolo_txt_by_filename(txt_path, replace=replace)
            elif os.path.isfile(json_path):
                self.load_create_ml_json_by_filename(json_path, file_path, replace=replace)
            

    def resizeEvent(self, event):
        if self.canvas and not self.image.isNull()\
           and self.zoom_mode != self.MANUAL_ZOOM:
            self.adjust_scale()
        super(MainWindow, self).resizeEvent(event)

    def paint_canvas(self):
        assert not self.image.isNull(), "cannot paint null image"
        self.canvas.scale = 0.01 * self.zoom_widget.value()
        self.canvas.overlay_color = self.light_widget.color()
        self.canvas.label_font_size = int(0.02 * max(self.image.width(), self.image.height()))
        self.canvas.adjustSize()
        self.canvas.update()

    def _fit_viewport_size(self):
        """获取稳定的视口尺寸，消除滚动条显隐导致的反馈震荡。

        用 maximumViewportSize() 得到"假设无滚动条"的视口尺寸，
        该值不随当前滚动条显隐而变，避免 resizeEvent 回路反复重算。
        """
        vp = self.scroll_area.maximumViewportSize()
        return vp.width(), vp.height()

    def adjust_scale(self, initial=False):
        value = self.scalers[self.FIT_WINDOW if initial else self.zoom_mode]()
        self.zoom_widget.setValue(int(100 * value))

    def update_path_info(self):
        """将状态栏默认消息设为当前保存目录。"""
        if self.default_save_dir:
            self.status_manager.set_default(u'保存: %s' % self.default_save_dir)

    def scale_fit_window(self):
        """计算缩放比例，使图片适应主窗口。"""
        e = 2.0  # 留 2px 边距，防止产生滚动条
        w1, h1 = self._fit_viewport_size()
        w1 -= e
        h1 -= e
        a1 = w1 / h1
        # 根据图片宽高比计算缩放值
        w2 = self.canvas.pixmap.width() - 0.0
        h2 = self.canvas.pixmap.height() - 0.0
        a2 = w2 / h2
        return w1 / w2 if a2 >= a1 else h1 / h2

    def scale_fit_width(self):
        # 边距在这里效果不太好，不加了
        w, _ = self._fit_viewport_size()
        return (w - 2.0) / self.canvas.pixmap.width()

    def closeEvent(self, event):
        if not self.may_continue():
            event.ignore()
        settings = self.settings
        # 如果是目录加载模式，启动时不加载特定文件
        if self.dir_name is None:
            settings[SETTING_FILENAME] = self.file_path if self.file_path else ''
        else:
            settings[SETTING_FILENAME] = ''

        settings[SETTING_WIN_SIZE] = self.size()
        settings[SETTING_WIN_POSE] = self.pos()
        settings[SETTING_WIN_MAXIMIZED] = self.isMaximized()
        settings[SETTING_WIN_STATE] = self.saveState()
        settings[SETTING_LINE_COLOR] = self.line_color
        settings[SETTING_FILL_COLOR] = self.fill_color
        settings[SETTING_RECENT_FILES] = self.recent_files
        settings[SETTING_ADVANCE_MODE] = not self._beginner
        if self.default_save_dir and os.path.exists(self.default_save_dir):
            settings[SETTING_SAVE_DIR] = ustr(self.default_save_dir)
        else:
            settings[SETTING_SAVE_DIR] = ''

        if self.last_open_dir and os.path.exists(self.last_open_dir):
            settings[SETTING_LAST_OPEN_DIR] = self.last_open_dir
        else:
            settings[SETTING_LAST_OPEN_DIR] = ''

        settings[SETTING_AUTO_SAVE] = self.auto_saving.isChecked()
        settings[SETTING_SINGLE_CLASS] = self.single_class_mode.isChecked()
        settings[SETTING_PAINT_LABEL] = self.display_label_option.isChecked()
        settings[SETTING_DRAW_SQUARE] = self.draw_squares_option.isChecked()
        settings[SETTING_REMEMBER_ZOOM] = self.remember_zoom_action.isChecked()
        settings[SETTING_LABEL_FILE_FORMAT] = self.label_file_format
        settings.save()

    def load_recent(self, filename):
        if self.may_continue():
            self.load_file(filename)

    def scan_all_images(self, folder_path):
        extensions = ['.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        images = []

        for root, dirs, files in os.walk(folder_path):
            for file in files:
                if file.lower().endswith(tuple(extensions)):
                    relative_path = os.path.join(root, file)
                    path = ustr(os.path.abspath(relative_path))
                    images.append(path)
        natural_sort(images, key=lambda x: x.lower())
        return images

    def change_save_dir_dialog(self, _value=False):
        if self.default_save_dir is not None:
            path = ustr(self.default_save_dir)
        else:
            path = '.'

        dir_path = ustr(QFileDialog.getExistingDirectory(self,
                                                         '%s - Save annotations to the directory' % __appname__, path,  QFileDialog.ShowDirsOnly
                                                         | QFileDialog.DontResolveSymlinks))

        if dir_path is not None and len(dir_path) > 1:
            self.default_save_dir = dir_path
            self.update_path_info()
            self._refresh_all_file_colors()
            # 缓存已失效，下次打开统计面板时重新扫描
            self._stats_cache = None
            self._clear_nav_mode()
            self._build_label_index()

        if self.file_path is not None:
            self.show_bounding_box_from_annotation_file(self.file_path)

        self.status('%s . Annotation will be saved to %s' %
                     ('Change saved folder', self.default_save_dir))


    def open_annotation_dialog(self, _value=False):
        if self.file_path is None:
            self.status_manager.show('Please select image first')
            return

        path = os.path.dirname(ustr(self.file_path))\
            if self.file_path else '.'
        if self.label_file_format == LabelFileFormat.PASCAL_VOC:
            filters = "Open Annotation XML file (%s)" % ' '.join(['*.xml'])
            filename = ustr(QFileDialog.getOpenFileName(self, '%s - Choose a xml file' % __appname__, path, filters))
            if filename:
                if isinstance(filename, (tuple, list)):
                    filename = filename[0]
            self.load_pascal_xml_by_filename(filename)

        elif self.label_file_format == LabelFileFormat.CREATE_ML:
            
            filters = "Open Annotation JSON file (%s)" % ' '.join(['*.json'])
            filename = ustr(QFileDialog.getOpenFileName(self, '%s - Choose a json file' % __appname__, path, filters))
            if filename:
                if isinstance(filename, (tuple, list)):
                    filename = filename[0]

            self.load_create_ml_json_by_filename(filename, self.file_path)         
        

    def open_dir_dialog(self, _value=False, dir_path=None, silent=False):
        if not self.may_continue():
            return

        default_open_dir_path = dir_path if dir_path else '.'
        if self.last_open_dir and os.path.exists(self.last_open_dir):
            default_open_dir_path = self.last_open_dir
        else:
            default_open_dir_path = os.path.dirname(self.file_path) if self.file_path else '.'
        if silent != True:
            target_dir_path = ustr(QFileDialog.getExistingDirectory(self,
                                                                    '%s - Open Directory' % __appname__, default_open_dir_path,
                                                                    QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks))
        else:
            target_dir_path = ustr(default_open_dir_path)
        self.last_open_dir = target_dir_path
        self.import_dir_images(target_dir_path)
        if self.default_save_dir is None:
            self.default_save_dir = target_dir_path
        self.update_path_info()
        if self.file_path:
            self.show_bounding_box_from_annotation_file(file_path=self.file_path)

    def _get_annotation_status(self, img_path):
        """检查一张图片的标注状态。

        Returns:
            0 — 无标注文件
            1 — 标注文件存在但为空（无标签）
            2 — 标注文件存在且有实际标注
        """
        anno_path = resolve_annotation_path(img_path, self.default_save_dir)
        if not anno_path:
            return 0

        ext = os.path.splitext(anno_path)[1].lower()
        try:
            with open(anno_path, 'rb') as f:
                head = f.read(4096)
            if ext == XML_EXT:
                return 2 if b'<object>' in head else 1
            elif ext == TXT_EXT:
                return 2 if any(l.strip() for l in head.split(b'\n') if l.strip()) else 1
            else:  # JSON
                return 2 if b'"shapes"' in head else 1
        except OSError:
            return 0

    def import_dir_images(self, dir_path):
        if not self.may_continue() or not dir_path:
            return

        self.last_open_dir = dir_path
        self.dir_name = dir_path
        self.update_path_info()
        self.file_path = None
        self.file_list_widget.clear()
        self._undo_stack.clear()
        self.m_img_list = self.scan_all_images(dir_path)
        self.img_count = len(self.m_img_list)
        self._clear_nav_mode()
        self._build_label_index()
        self.open_next_image()
        for imgPath in self.m_img_list:
            relative = os.path.relpath(imgPath, dir_path) if dir_path else imgPath
            item = QListWidgetItem(relative)
            item.setData(Qt.UserRole, imgPath)
            status = self._get_annotation_status(imgPath)
            if status == 0:
                item.setForeground(QColor('#888888'))
            elif status == 1:
                item.setForeground(QColor('#E57373'))
            # status == 2 → 有标注，用系统默认色，不动
            self.file_list_widget.addItem(item)

    def verify_image(self, _value=False):
        # 如果有标注且启用了自动保存，直接保存并继续
        if self.file_path is not None:
            try:
                self.label_file.toggle_verify()
            except AttributeError:
                # 如果标注文件还不存在，先保存
                # 再切换 verified 状态
                self.save_file()
                if self.label_file is not None:
                    self.label_file.toggle_verify()
                else:
                    return

            self.canvas.verified = self.label_file.verified
            self.paint_canvas()
            self.save_file()

    def open_prev_image(self, _value=False):
        # 如果有标注且启用了自动保存，直接保存并继续
        if self.auto_saving.isChecked():
            if self.default_save_dir is not None:
                if self.dirty is True:
                    self.save_file()
            else:
                self.change_save_dir_dialog()
                return

        if not self.may_continue():
            return

        if self.img_count <= 0:
            return

        if self.file_path is None:
            return

        # 跳跃翻页模式
        if self._nav_active:
            self._advance_in_nav(-1)
            return

        if self.file_path is not None and self.remember_zoom_action.isChecked():
            self._save_zoom_scroll()
            self._preserve_zoom = True

        if self.cur_img_idx - 1 >= 0:
            self.cur_img_idx -= 1
            filename = self.m_img_list[self.cur_img_idx]
            if filename:
                self.load_file(filename)

    def open_next_image(self, _value=False):
        # 如果有标注且启用了自动保存，直接保存并继续
        if self.auto_saving.isChecked():
            if self.default_save_dir is not None:
                if self.dirty is True:
                    self.save_file()
            else:
                self.change_save_dir_dialog()
                return

        if not self.may_continue():
            return

        if self.img_count <= 0:
            return
        
        if not self.m_img_list:
            return

        # 跳跃翻页模式
        if self._nav_active:
            self._advance_in_nav(+1)
            return

        filename = None
        if self.file_path is None:
            filename = self.m_img_list[0]
            self.cur_img_idx = 0
        else:
            if self.cur_img_idx + 1 < self.img_count:
                self.cur_img_idx += 1
                filename = self.m_img_list[self.cur_img_idx]

        if self.file_path is not None and self.remember_zoom_action.isChecked():
            self._save_zoom_scroll()
            self._preserve_zoom = True

        if filename:
            self.load_file(filename)

    def open_file(self, _value=False):
        if not self.may_continue():
            return
        path = os.path.dirname(ustr(self.file_path)) if self.file_path else '.'
        formats = ['*.%s' % fmt.data().decode("ascii").lower() for fmt in QImageReader.supportedImageFormats()]
        filters = "Image & Label files (%s)" % ' '.join(formats + ['*%s' % LabelFile.suffix])
        filename,_ = QFileDialog.getOpenFileName(self, '%s - Choose Image or Label file' % __appname__, path, filters)
        if filename:
            if isinstance(filename, (tuple, list)):
                filename = filename[0]
            self.cur_img_idx = 0
            self.img_count = 1
            self.load_file(filename)

    def save_file(self, _value=False):
        if self.default_save_dir is not None and len(ustr(self.default_save_dir)):
            if self.file_path:
                image_file_name = os.path.basename(self.file_path)
                saved_file_name = os.path.splitext(image_file_name)[0]
                saved_path = os.path.join(ustr(self.default_save_dir), saved_file_name)
                self._save_file(saved_path)
        else:
            image_file_dir = os.path.dirname(self.file_path)
            image_file_name = os.path.basename(self.file_path)
            saved_file_name = os.path.splitext(image_file_name)[0]
            saved_path = os.path.join(image_file_dir, saved_file_name)
            self._save_file(saved_path if self.label_file
                            else self.save_file_dialog(remove_ext=False))

    def save_file_as(self, _value=False):
        assert not self.image.isNull(), "cannot save empty image"
        self._save_file(self.save_file_dialog())

    def save_file_dialog(self, remove_ext=True):
        caption = '%s - Choose File' % __appname__
        filters = 'File (*%s)' % LabelFile.suffix
        open_dialog_path = self.current_path()
        dlg = QFileDialog(self, caption, open_dialog_path, filters)
        dlg.setDefaultSuffix(LabelFile.suffix[1:])
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        filename_without_extension = os.path.splitext(self.file_path)[0]
        dlg.selectFile(filename_without_extension)
        dlg.setOption(QFileDialog.DontUseNativeDialog, False)
        if dlg.exec_():
            full_file_path = ustr(dlg.selectedFiles()[0])
            if remove_ext:
                return os.path.splitext(full_file_path)[0]  # Return file path without the extension.
            else:
                return full_file_path
        return ''

    def _save_file(self, annotation_file_path):
        if annotation_file_path and self.save_labels(annotation_file_path):
            self.set_clean()
            self._apply_file_color(self.file_path)
            self._update_index_for_current_image()
        self.status('Saved to  %s' % annotation_file_path)

    def _apply_file_color(self, img_path):
        """根据标注状态设置文件列表中某一项的文字颜色。"""
        if not img_path:
            return
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            if item.data(Qt.UserRole) == img_path:
                status = self._get_annotation_status(img_path)
                if status == 0:
                    item.setForeground(QColor('#888888'))
                elif status == 1:
                    item.setForeground(QColor('#E57373'))
                else:
                    # 有标注 → 重置为系统默认色
                    item.setForeground(QBrush())
                break

    def _refresh_all_file_colors(self):
        """重新计算并刷新文件列表中所有项的颜色。"""
        for i in range(self.file_list_widget.count()):
            item = self.file_list_widget.item(i)
            img_path = item.data(Qt.UserRole)
            if img_path:
                status = self._get_annotation_status(img_path)
                if status == 0:
                    item.setForeground(QColor('#888888'))
                elif status == 1:
                    item.setForeground(QColor('#E57373'))
                else:
                    item.setForeground(QBrush())

    def close_file(self, _value=False):
        if not self.may_continue():
            return
        self.reset_state()
        self.set_clean()
        self.toggle_actions(False)
        self.canvas.setEnabled(False)
        self.actions.saveAs.setEnabled(False)

    def delete_image(self):
        delete_path = self.file_path
        if delete_path is not None:
            idx = self.cur_img_idx
            if os.path.exists(delete_path):
                os.remove(delete_path)
            self.import_dir_images(self.last_open_dir)
            if self.img_count > 0:
                self.cur_img_idx = min(idx, self.img_count - 1)
                filename = self.m_img_list[self.cur_img_idx]
                self.load_file(filename)
            else:
                self.close_file()

    def reset_all(self):
        self.settings.reset()
        self.close()
        process = QProcess()
        process.startDetached(os.path.abspath(__file__))

    def may_continue(self):
        if not self.dirty:
            return True
        else:
            discard_changes = self.discard_changes_dialog()
            if discard_changes == QMessageBox.No:
                return True
            elif discard_changes == QMessageBox.Yes:
                self.save_file()
                return True
            else:
                return False

    def discard_changes_dialog(self):
        yes, no, cancel = QMessageBox.Yes, QMessageBox.No, QMessageBox.Cancel
        msg = u'You have unsaved changes, would you like to save them and proceed?\nClick "No" to undo all changes.'
        return QMessageBox.warning(self, u'Attention', msg, yes | no | cancel)

    def error_message(self, title, message):
        return QMessageBox.critical(self, title,
                                    '<p><b>%s</b></p>%s' % (title, message))

    def current_path(self):
        return os.path.dirname(self.file_path) if self.file_path else '.'

    def choose_color1(self):
        color = self.color_dialog.getColor(self.line_color, u'Choose line color',
                                           default=DEFAULT_LINE_COLOR)
        if color:
            self.line_color = color
            Shape.line_color = color
            self.canvas.set_drawing_color(color)
            self.canvas.update()
            self.set_dirty()

    def delete_selected_shape(self):
        if self.canvas.selected_shape:
            self._undo_stack.append(self._snapshot_shapes())
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)
            self.remove_label(self.canvas.delete_selected())
            self._validate_label_list()
            self.set_dirty()
            if self.no_shapes():
                for action in self.actions.onShapesPresent:
                    action.setEnabled(False)

    def choose_shape_line_color(self):
        color = self.color_dialog.getColor(self.line_color, u'Choose Line Color',
                                           default=DEFAULT_LINE_COLOR)
        if color:
            self.canvas.selected_shape.line_color = color
            self.canvas.update()
            self.set_dirty()

    def choose_shape_fill_color(self):
        color = self.color_dialog.getColor(self.fill_color, u'Choose Fill Color',
                                           default=DEFAULT_FILL_COLOR)
        if color:
            self.canvas.selected_shape.fill_color = color
            self.canvas.update()
            self.set_dirty()

    def copy_shape(self):
        if self.canvas.selected_shape is None:
            # 防止误触：松开前碰到了左键
            return
        self.canvas.end_move(copy=True)
        self.add_label(self.canvas.selected_shape)
        self.set_dirty()

    def move_shape(self):
        self.canvas.end_move(copy=False)
        self.set_dirty()

    def load_predefined_classes(self, predef_classes_file):
        if os.path.exists(predef_classes_file) is True:
            with codecs.open(predef_classes_file, 'r', 'utf8') as f:
                for line in f:
                    line = line.strip()
                    if self.label_hist is None:
                        self.label_hist = [line]
                    else:
                        self.label_hist.append(line)

    def load_pascal_xml_by_filename(self, xml_path, replace=True):
        if self.file_path is None:
            return
        if os.path.isfile(xml_path) is False:
            return

        self.set_format(FORMAT_PASCALVOC)

        t_voc_parse_reader = PascalVocReader(xml_path)
        shapes = t_voc_parse_reader.get_shapes()
        self.load_labels(shapes, replace=replace)
        self.canvas.verified = t_voc_parse_reader.verified

    def load_yolo_txt_by_filename(self, txt_path, replace=True):
        if self.file_path is None:
            return
        if os.path.isfile(txt_path) is False:
            return

        self.set_format(FORMAT_YOLO)
        t_yolo_parse_reader = YoloReader(txt_path, self.image)
        shapes = t_yolo_parse_reader.get_shapes()
        print(shapes)
        self.load_labels(shapes, replace=replace)
        self.canvas.verified = t_yolo_parse_reader.verified

    def load_create_ml_json_by_filename(self, json_path, file_path, replace=True):
        if self.file_path is None:
            return
        if os.path.isfile(json_path) is False:
            return

        self.set_format(FORMAT_CREATEML)

        create_ml_parse_reader = CreateMLReader(json_path, file_path)
        shapes = create_ml_parse_reader.get_shapes()
        self.load_labels(shapes, replace=replace)
        self.canvas.verified = create_ml_parse_reader.verified

    def copy_previous_bounding_boxes(self):
        current_index = self.m_img_list.index(self.file_path)
        if current_index - 1 >= 0:
            self._undo_stack.append(self._snapshot_shapes())
            if len(self._undo_stack) > 50:
                self._undo_stack.pop(0)
            prev_file_path = self.m_img_list[current_index - 1]
            self.show_bounding_box_from_annotation_file(prev_file_path, replace=False)
            self.save_file()

    def _snapshot_shapes(self):
        """返回当前所有 shape 的可序列化快照，用于撤销。"""
        return [
            (shape.label, [(p.x(), p.y()) for p in shape.points],
             shape.line_color.getRgb() if shape.line_color else None,
             shape.fill_color.getRgb() if shape.fill_color else None,
             shape.difficult)
            for shape in self.canvas.shapes
        ]

    def _undo(self):
        """Ctrl+Z: 撤销上一步操作（创建/删除/复制/粘贴）。"""
        if not self._undo_stack:
            return
        saved = self._undo_stack.pop()
        self.label_list.clear()
        self.items_to_shapes.clear()
        self.shapes_to_items.clear()
        self.canvas.shapes.clear()
        self.load_labels(saved, replace=True)
        self.canvas.repaint()

    def toggle_paint_labels_option(self):
        for shape in self.canvas.shapes:
            shape.paint_label = self.display_label_option.isChecked()

    def toggle_draw_square(self):
        self.canvas.set_drawing_shape_to_square(self.draw_squares_option.isChecked())

    # ---------------------------------------------------------------------------
    # 标签统计面板
    # ---------------------------------------------------------------------------

    def show_label_stats(self):
        """打开标签统计对话框（优先使用缓存，免去全量重扫）。"""
        if not self.m_img_list:
            QMessageBox.information(self, '提示', '请先打开一个图片目录。')
            return

        # 首次打开或缓存无效时执行全量扫描
        if self._stats_cache is None:
            self.status('正在扫描标注文件…')
            from libs.labelStats import scan_label_statistics
            self._stats_cache = scan_label_statistics(self.m_img_list, self.default_save_dir)

        if not self._stats_cache:
            QMessageBox.information(self, '提示', '数据集中未找到标注文件。')
            return

        def _perform_batch_rename(old_label, new_label):
            """批量重命名回调。"""
            images = self._stats_cache[old_label]['images']
            anno_paths = [resolve_annotation_path(img, self.default_save_dir)
                          for img in images]
            anno_paths = [p for p in anno_paths if p]
            modified = batch_rename_label(anno_paths, old_label, new_label)
            # 重新扫描缓存
            from libs.labelStats import scan_label_statistics
            self._stats_cache = scan_label_statistics(self.m_img_list, self.default_save_dir)
            from libs.labelStats import scan_label_to_indices
            self._label_to_indices = scan_label_to_indices(self.m_img_list, self.default_save_dir)
            # 如果当前图片受到影响，直接更新画布和标签列表（不 reload 文件）
            self._sync_current_after_batch(images, 'rename', old_label, new_label)
            return True, f'已修改 {modified} 个标注文件', self._stats_cache

        dialog = LabelStatsDialog(self._stats_cache, self,
                                  on_jump_to=self.load_file,
                                  total_img_count=len(self.m_img_list),
                                  nav_labels=self._nav_labels,
                                  master_on=self._nav_active,
                                  on_batch_rename=_perform_batch_rename)
        dialog.exec_()
        master_on, checked = dialog.get_nav_state()
        self._nav_labels = checked  # 始终保存勾选状态，不管主开关
        self._nav_active = master_on
        if master_on and checked:
            self._jump_to_first_nav_image()
        self._update_title_counter()

    def show_convert_dialog(self):
        """打开格式转换对话框（批量格式互转）。"""
        # 默认标注目录 = 存放目录，图片目录 = 当前图片所在目录
        anno_dir = self.default_save_dir or self.dir_name or ''
        img_dir = self.dir_name or ''
        out_dir = self.default_save_dir or self.dir_name or ''
        dialog = ConvertDialog(self, anno_dir=anno_dir, img_dir=img_dir, out_dir=out_dir)
        dialog.exec_()

    def show_clean_dialog(self):
        """打开批量删除标注文件对话框（独立于转换，确认转换结果后清理原文用）。"""
        anno_dir = self.default_save_dir or self.dir_name or ''
        dialog = CleanDialog(self, anno_dir=anno_dir)
        dialog.exec_()

    def _sync_current_after_batch(self, affected_images, action, *labels):
        """批量操作后，直接更新当前画布的 shapes 和标签列表，不 reload 文件。

        Args:
            affected_images: set[str], 受影响的图片路径集合
            action: 'rename'
            labels: ('rename', old_label, new_label)
        """
        if not self.file_path or not affected_images:
            return
        current = os.path.abspath(self.file_path)
        if current not in {os.path.abspath(p) for p in affected_images}:
            return

        if action == 'rename':
            self._batch_rename_on_current(labels[0], labels[1])

    def _batch_rename_on_current(self, old_label, new_label):
        """重命名当前 canvas 中指定标签的所有 shape，不清除未保存修改。"""
        renamed = 0
        for shape in self.canvas.shapes:
            if shape.label == old_label:
                shape.label = new_label
                item = self.shapes_to_items.get(shape)
                if item:
                    item.setText(new_label)
                renamed += 1

        if renamed:
            self.canvas.update()
            self.status(f'已将当前图片中 {renamed} 个 "{old_label}" 重命名为 "{new_label}"')

    # ---------------------------------------------------------------------------
    # 跳跃翻页（按标签导航）
    # ---------------------------------------------------------------------------

    def _clear_nav_mode(self):
        """退出跳跃翻页模式，恢复普通翻页。保留勾选状态。"""
        if self._nav_active:
            self._nav_active = False
            self._update_title_counter()

    def _update_title_counter(self):
        """刷新窗口和文件停靠面板上的计数器显示。"""
        if self.file_path:
            counter = self.counter_str()
            self.setWindowTitle(__appname__ + ' ' + self.file_path + ' ' + counter)
            self.file_dock.setWindowTitle(self._file_dock_base + ' ' + counter)

    def _jump_to_first_nav_image(self):
        """跳到第一张包含任意勾选标签的图片。"""
        if not self._nav_labels or not self._label_to_indices:
            return
        all_indices = sorted(set().union(
            *(self._label_to_indices.get(lbl, []) for lbl in self._nav_labels)
        ))
        if all_indices and self.cur_img_idx not in all_indices:
            target_idx = all_indices[0]
            self.cur_img_idx = target_idx
            filename = self.m_img_list[self.cur_img_idx]
            if filename:
                self.load_file(filename)
                self._update_title_counter()

    def _advance_in_nav(self, direction):
        """在跳跃翻页中前进 (direction=+1) 或后退 (direction=-1)。
        计算所有勾选标签的图片索引并集，用 bisect 定位目标位置。
        """
        if not self._nav_labels:
            self._clear_nav_mode()
            return

        # 合并所有勾选标签的索引，去重排序
        all_indices = sorted(set().union(
            *(self._label_to_indices.get(lbl, []) for lbl in self._nav_labels)
        ))
        if not all_indices:
            self._clear_nav_mode()
            self.status('所选标签均无匹配图片', 3000)
            return

        cur = self.cur_img_idx
        import bisect
        pos = bisect.bisect_left(all_indices, cur)

        if direction > 0:
            next_pos = pos
            while next_pos < len(all_indices) and all_indices[next_pos] <= cur:
                next_pos += 1
            if next_pos < len(all_indices):
                target_idx = all_indices[next_pos]
            else:
                target_idx = all_indices[0]
        else:
            prev_pos = pos - 1
            while prev_pos >= 0 and all_indices[prev_pos] >= cur:
                prev_pos -= 1
            if prev_pos >= 0:
                target_idx = all_indices[prev_pos]
            else:
                target_idx = all_indices[-1]

        if self.file_path is not None and self.remember_zoom_action.isChecked():
            self._save_zoom_scroll()
            self._preserve_zoom = True

        if target_idx != cur:
            self.cur_img_idx = target_idx
            filename = self.m_img_list[self.cur_img_idx]
            if filename:
                self.load_file(filename)
                self._update_title_counter()
        else:
            total = len(all_indices)
            if total == 1:
                self.status('所选标签仅此 1 张图片，无法翻页', 3000)
            else:
                self.status('跳跃导航：已在首/尾，循环回到当前', 3000)

    def _build_label_index(self):
        """全量扫描数据集，构建索引和缓存：_label_to_indices / _img_label_map / _stats_cache。"""
        self._img_label_map = {}
        self._label_to_indices = {}
        stats = defaultdict(lambda: {'box_count': 0, 'image_count': 0, 'images': set()})

        for idx, img_path in enumerate(self.m_img_list):
            labels = scan_single_annotation(img_path, self.default_save_dir)
            if labels:
                self._img_label_map[img_path] = labels
                for label, count in labels.items():
                    if label not in self._label_to_indices:
                        self._label_to_indices[label] = []
                    self._label_to_indices[label].append(idx)
                    stats[label]['box_count'] += count
                    stats[label]['image_count'] = len(stats[label]['images']) + 1
                    stats[label]['images'].add(img_path)
            # 处理旧标注被清空的情况：img_label_map 中无此记录

        # 重建 image_count（从 images set 长度）
        self._stats_cache = {}
        for label, info in stats.items():
            self._stats_cache[label] = {
                'box_count': info['box_count'],
                'image_count': len(info['images']),
                'images': info['images'],
            }

    def _update_index_for_current_image(self):
        """保存后增量更新索引：只重扫当前图片，更新 _img_label_map / _label_to_indices / _stats_cache。

        在 _save_file() 成功后调用。
        """
        if not self.file_path or not self.m_img_list:
            return

        img_path = self.file_path
        try:
            cur_idx = self.m_img_list.index(img_path)
        except ValueError:
            return

        # 扫描当前标注文件的最新状态
        new_labels = scan_single_annotation(img_path, self.default_save_dir)
        old_labels = self._img_label_map.get(img_path, {})

        # 更新 _img_label_map
        if new_labels:
            self._img_label_map[img_path] = new_labels
        elif img_path in self._img_label_map:
            del self._img_label_map[img_path]

        # 更新 _label_to_indices
        old_label_set = set(old_labels.keys())
        new_label_set = set(new_labels.keys())

        for label in old_label_set - new_label_set:
            # 该标签不再包含此图片
            indices = self._label_to_indices.get(label)
            if indices and cur_idx in indices:
                indices.remove(cur_idx)
                if not indices:
                    del self._label_to_indices[label]

        for label in new_label_set - old_label_set:
            # 该标签新增此图片
            self._label_to_indices.setdefault(label, []).append(cur_idx)
            self._label_to_indices[label].sort()

        # 更新 _stats_cache
        for label in old_label_set - new_label_set:
            info = self._stats_cache.get(label)
            if info:
                old_count = old_labels[label]
                info['box_count'] -= old_count
                info['images'].discard(img_path)
                info['image_count'] = len(info['images'])
                if info['box_count'] <= 0 or info['image_count'] <= 0:
                    del self._stats_cache[label]

        for label in new_label_set - old_label_set:
            info = self._stats_cache.setdefault(label, {
                'box_count': 0, 'image_count': 0, 'images': set()
            })
            count = new_labels[label]
            info['box_count'] += count
            info['images'].add(img_path)
            info['image_count'] = len(info['images'])

        # 两集合共有的标签：box_count 可能变化
        for label in old_label_set & new_label_set:
            old_count = old_labels[label]
            new_count = new_labels[label]
            if old_count != new_count:
                info = self._stats_cache.get(label)
                if info:
                    info['box_count'] += (new_count - old_count)


def inverted(color):
    return QColor(*[255 - v for v in color.getRgb()])


def read(filename, default=None):
    try:
        reader = QImageReader(filename)
        reader.setAutoTransform(True)
        return reader.read()
    except:
        return default


def get_main_app(argv=None):
    """
    Standard boilerplate Qt application code.
    Do everything but app.exec_() -- so that we can test the application in one thread
    """
    if not argv:
        argv = []
    app = QApplication(argv)
    app.setApplicationName(__appname__)
    app.setWindowIcon(new_icon("app"))
    # Tzutalin 201705+：接受额外参数指定类别文件
    argparser = argparse.ArgumentParser()
    argparser.add_argument("image_dir", nargs="?")
    argparser.add_argument("class_file",
                           default=os.path.join(os.path.dirname(__file__), "data", "predefined_classes.txt"),
                           nargs="?")
    argparser.add_argument("save_dir", nargs="?")
    args = argparser.parse_args(argv[1:])

    args.image_dir = args.image_dir and os.path.normpath(args.image_dir)
    args.class_file = args.class_file and os.path.normpath(args.class_file)
    args.save_dir = args.save_dir and os.path.normpath(args.save_dir)

    # 用法：labelImg.py 图片路径 类别文件 保存目录
    win = MainWindow(args.image_dir,
                     args.class_file,
                     args.save_dir)
    win.show()
    return app, win


def main():
    """构建主应用并运行"""
    app, _win = get_main_app(sys.argv)
    return app.exec_()

if __name__ == '__main__':
    sys.exit(main())
