# -*- coding: utf-8 -*-
"""Action/Menu/Toolbar 构建器。

将 MainWindow 中 306 行的 _create_actions_and_menus 迁移至此，
保持 MainWindow 清爽。
"""

from functools import partial

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt5.QtGui import QPainter, QPixmap, QColor, QPen, QIcon
from PyQt5.QtWidgets import (QAction, QMenu, QWidgetAction, QWidget)

from libs.utils import new_action, add_actions, format_shortcut, Struct
from libs.constants import *
from libs.compoundWidgets import ZoomWidgetPanel, LightWidgetPanel
from libs.labelFile import LabelFileFormat
from libs.formatHandler import FORMAT_REGISTRY


def build_actions(main_window):
    """创建所有 QAction 并组装菜单栏、工具栏、右键菜单、快捷键。

    Args:
        main_window: MainWindow 实例（用于访问 string_bundle、settings、
                     zoom_widget、canvas 等属性及所有 slot 方法）。

    Returns:
        tuple: (actions_Struct, menus_Struct, tools_ToolBar)
    """
    get_str = lambda sid: main_window.string_bundle.get_string(sid)
    settings = main_window.settings
    action = partial(new_action, main_window)

    quit = action(get_str('quit'), main_window.close,
                  'Ctrl+Q', 'quit', get_str('quitApp'))

    open = action(get_str('openFile'), main_window.open_file,
                  'Ctrl+O', 'open', get_str('openFileDetail'))

    open_dir = action(get_str('openDir'), main_window.open_dir_dialog,
                      'Ctrl+u', 'open', get_str('openDir'))

    change_save_dir = action(get_str('changeSaveDir'), main_window.change_save_dir_dialog,
                             'Ctrl+r', 'open', get_str('changeSavedAnnotationDir'))

    open_annotation = action(get_str('openAnnotation'), main_window.open_annotation_dialog,
                             'Ctrl+Shift+O', 'open', get_str('openAnnotationDetail'))
    copy_prev_bounding = action(get_str('copyPrevBounding'), main_window.copy_previous_bounding_boxes, 'Ctrl+v', 'copy', get_str('copyPrevBounding'))
    undo = action('撤销', main_window._undo, 'Ctrl+Z', 'undo', '撤销上一步操作（创建/删除/复制/粘贴）')

    open_next_image = action(get_str('nextImg'), main_window.open_next_image,
                             'd', 'next', get_str('nextImgDetail'))

    open_prev_image = action(get_str('prevImg'), main_window.open_prev_image,
                             'a', 'prev', get_str('prevImgDetail'))

    verify = action(get_str('verifyImg'), main_window.verify_image,
                    'space', 'verify', get_str('verifyImgDetail'))

    save = action(get_str('save'), main_window.save_file,
                  'Ctrl+S', 'save', get_str('saveDetail'), enabled=False)

    def get_format_meta(format):
        """返回 (标题, 图标名) 元组"""
        handler = FORMAT_REGISTRY[format]()
        return '&' + handler.display_name, handler.icon

    save_format = action(get_format_meta(main_window.label_file_format)[0],
                         main_window.change_format, 'Ctrl+Y',
                         get_format_meta(main_window.label_file_format)[1],
                         get_str('changeSaveFormat'), enabled=True)

    save_as = action(get_str('saveAs'), main_window.save_file_as,
                     'Ctrl+Shift+S', 'save-as', get_str('saveAsDetail'), enabled=False)

    close = action(get_str('closeCur'), main_window.close_file, 'Ctrl+W', 'close', get_str('closeCurDetail'))

    delete_image = action(get_str('deleteImg'), main_window.delete_image, 'Ctrl+Shift+D', 'close', get_str('deleteImgDetail'))

    reset_all = action(get_str('resetAll'), main_window.reset_all, None, 'resetall', get_str('resetAllDetail'))

    color1 = action(get_str('boxLineColor'), main_window.choose_color1,
                    'Ctrl+L', 'color_line', get_str('boxLineColorDetail'))

    create_mode = action(get_str('crtBox'), main_window.set_create_mode,
                         'w', 'new', get_str('crtBoxDetail'), enabled=False)
    edit_mode = action(get_str('editBox'), main_window.set_edit_mode,
                       'Ctrl+J', 'edit', get_str('editBoxDetail'), enabled=False)

    create = action(get_str('crtBox'), main_window.create_shape,
                    'w', 'new', get_str('crtBoxDetail'), enabled=False)
    delete = action(get_str('delBox'), main_window.delete_selected_shape,
                    'Delete', 'delete', get_str('delBoxDetail'), enabled=False)
    copy = action(get_str('dupBox'), main_window.copy_selected_shape,
                  'Ctrl+D', 'copy', get_str('dupBoxDetail'),
                  enabled=False)

    advanced_mode = action(get_str('advancedMode'), main_window.toggle_advanced_mode,
                           'Ctrl+Shift+A', 'expert', get_str('advancedModeDetail'),
                           checkable=True)

    hide_all = action(get_str('hideAllBox'), partial(main_window.toggle_polygons, False),
                      'Ctrl+H', 'hide', get_str('hideAllBoxDetail'),
                      enabled=False)
    show_all = action(get_str('showAllBox'), partial(main_window.toggle_polygons, True),
                      'Ctrl+A', 'hide', get_str('showAllBoxDetail'),
                      enabled=False)

    help_default = action(get_str('tutorialDefault'), main_window.show_default_tutorial_dialog, None, 'help', get_str('tutorialDetail'))
    show_info = action(get_str('info'), main_window.show_info_dialog, None, 'help', get_str('info'))
    show_shortcut = action(get_str('shortcut'), main_window.show_shortcuts_dialog, None, 'help', get_str('shortcut'))

    zoom = QWidgetAction(main_window)
    main_window.zoom_widget.setWhatsThis(
        u"Zoom in or out of the image. Also accessible with"
        " %s and %s from the canvas." % (format_shortcut("Ctrl+[-+]"),
                                         format_shortcut("Ctrl+Wheel")))
    main_window.zoom_widget.setEnabled(False)

    zoom_in = action(get_str('zoomin'), partial(main_window.add_zoom, 10),
                     'Ctrl++', 'zoom-in', get_str('zoominDetail'), enabled=False)
    zoom_out = action(get_str('zoomout'), partial(main_window.add_zoom, -10),
                      'Ctrl+-', 'zoom-out', get_str('zoomoutDetail'), enabled=False)

    zoom_org = action(get_str('originalsize'), partial(main_window.set_zoom, 100),
                      'Ctrl+=', 'zoom', get_str('originalsizeDetail'), enabled=False)
    fit_window = action(get_str('fitWin'), main_window.set_fit_window,
                        'Ctrl+F', 'fit-window', get_str('fitWinDetail'),
                        checkable=True, enabled=False)
    fit_width = action(get_str('fitWidth'), main_window.set_fit_width,
                       'Ctrl+Shift+F', 'fit-width', get_str('fitWidthDetail'),
                       checkable=True, enabled=False)
    # 将缩放控件分组，方便统一启用/禁用
    zoom_actions = (main_window.zoom_widget, zoom_in, zoom_out,
                    zoom_org, fit_window, fit_width)
    main_window.zoom_mode = main_window.MANUAL_ZOOM
    main_window.scalers = {
        main_window.FIT_WINDOW: main_window.scale_fit_window,
        main_window.FIT_WIDTH: main_window.scale_fit_width,
        # 加载文件时缩放到 100%
        main_window.MANUAL_ZOOM: lambda: 1,
    }

    light = QWidgetAction(main_window)
    main_window.light_widget.setWhatsThis(
        u"Brighten or darken current image. Also accessible with"
        " %s and %s from the canvas." % (format_shortcut("Ctrl+Shift+[-+]"),
                                         format_shortcut("Ctrl+Shift+Wheel")))
    main_window.light_widget.setEnabled(False)

    light_brighten = action(get_str('lightbrighten'), partial(main_window.add_light, 10),
                            'Ctrl+Shift++', 'light_lighten', get_str('lightbrightenDetail'), enabled=False)
    light_darken = action(get_str('lightdarken'), partial(main_window.add_light, -10),
                          'Ctrl+Shift+-', 'light_darken', get_str('lightdarkenDetail'), enabled=False)
    light_org = action(get_str('lightreset'), partial(main_window.set_light, 50),
                       'Ctrl+Shift+=', 'light_reset', get_str('lightresetDetail'), enabled=False)

    # 将亮度控件分组，方便统一启用/禁用
    light_actions = (main_window.light_widget, light_brighten,
                     light_darken, light_org)

    # 复合控件：[-] [65] [+] 在同一行
    zoom_panel = ZoomWidgetPanel(main_window.zoom_widget, zoom_in, zoom_out)
    main_window.zoom_panel = zoom_panel
    zoom_compound = QWidgetAction(main_window)
    zoom_compound.setDefaultWidget(zoom_panel)
    light_panel = LightWidgetPanel(main_window.light_widget, light_brighten, light_darken)
    main_window.light_panel = light_panel
    light_compound = QWidgetAction(main_window)
    light_compound.setDefaultWidget(light_panel)

    edit = action(get_str('editLabel'), main_window.edit_label,
                  'Ctrl+E', 'edit', get_str('editLabelDetail'),
                  enabled=False)
    main_window.edit_button.setDefaultAction(edit)

    shape_line_color = action(get_str('shapeLineColor'), main_window.choose_shape_line_color,
                              icon='color_line', tip=get_str('shapeLineColorDetail'),
                              enabled=False)
    shape_fill_color = action(get_str('shapeFillColor'), main_window.choose_shape_fill_color,
                              icon='color', tip=get_str('shapeFillColorDetail'),
                              enabled=False)

    labels = main_window.dock.toggleViewAction()
    labels.setText(get_str('showHide'))
    labels.setShortcut('Ctrl+Shift+L')

    # 一键切换所有侧边栏（带动画）
    toggle_side_panels = action('切换侧边栏', main_window._toggle_all_panels,
                                None, None, '显示/隐藏侧边标注与文件面板')

    # 标签列表右键菜单
    label_menu = QMenu()
    add_actions(label_menu, (edit, delete))
    main_window.label_list.setContextMenuPolicy(Qt.CustomContextMenu)
    main_window.label_list.customContextMenuRequested.connect(
        main_window.pop_label_list_menu)

    # 绘制正方形/矩形切换
    draw_squares_option = QAction(get_str('drawSquares'), main_window)
    draw_squares_option.setShortcut('Ctrl+Shift+R')
    draw_squares_option.setCheckable(True)
    draw_squares_option.setChecked(settings.get(SETTING_DRAW_SQUARE, False))
    draw_squares_option.setToolTip('切换后画框始终约束为正方形；'
                                    '不开启时也可按住 Ctrl 拖拽临时约束')
    draw_squares_option.triggered.connect(main_window.toggle_draw_square)
    main_window.draw_squares_option = draw_squares_option

    # 绘制复选框图标（工具栏上用，菜单已有原生勾选）
    def _checkbox_icon(checked):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(2, 2, 16, 16)
        p.setPen(QPen(QColor('#555'), 1.5))
        p.setBrush(QColor('#fff'))
        p.drawRoundedRect(rect, 2, 2)
        if checked:
            p.setPen(QPen(QColor('#2b7'), 2.5))
            p.drawLine(QPointF(5, 10), QPointF(9, 14))
            p.drawLine(QPointF(9, 14), QPointF(15, 6))
        p.end()
        return QIcon(pixmap)

    # 记住缩放位置
    checked = settings.get(SETTING_REMEMBER_ZOOM, False)
    remember_zoom_action = QAction(_checkbox_icon(checked), '记住缩放位置', main_window)
    remember_zoom_action.setCheckable(True)
    remember_zoom_action.setChecked(checked)
    remember_zoom_action.setToolTip('开启后，A/D 翻页时自动保持上一张的缩放和滚动位置')
    remember_zoom_action.toggled.connect(
        lambda c: remember_zoom_action.setIcon(_checkbox_icon(c)))
    main_window.remember_zoom_action = remember_zoom_action

    # 存储所有 Action 便于后续统一管理
    actions = Struct(save=save, save_format=save_format, saveAs=save_as, open=open, close=close, resetAll=reset_all, deleteImg=delete_image,
                     lineColor=color1, create=create, delete=delete, edit=edit, copy=copy, undo=undo,
                     createMode=create_mode, editMode=edit_mode, advancedMode=advanced_mode,
                     shapeLineColor=shape_line_color, shapeFillColor=shape_fill_color,
                     zoom=zoom, zoomIn=zoom_in, zoomOut=zoom_out, zoomOrg=zoom_org,
                     fitWindow=fit_window, fitWidth=fit_width,
                     zoomActions=zoom_actions,
                     lightBrighten=light_brighten, lightDarken=light_darken, lightOrg=light_org,
                     lightActions=light_actions,
                     fileMenuActions=(
                         open, open_dir, save, save_as, close, reset_all, quit),
                     beginner=(), advanced=(),
                     editMenu=(undo, edit, copy, delete,
                               None, color1, draw_squares_option),
                     beginnerContext=(create, edit, copy, delete),
                     advancedContext=(create_mode, edit_mode, edit, copy,
                                      delete, shape_line_color, shape_fill_color),
                     onLoadActive=(
                         close, create, create_mode, edit_mode),
                     onShapesPresent=(save_as, hide_all, show_all))

    menus = Struct(
        file=main_window.menu(get_str('menu_file')),
        edit=main_window.menu(get_str('menu_edit')),
        view=main_window.menu(get_str('menu_view')),
        help=main_window.menu(get_str('menu_help')),
        recentFiles=QMenu(get_str('menu_openRecent')),
        labelList=label_menu)

    # 自动保存：翻页时自动保存标注
    auto_saving = QAction(get_str('autoSaveMode'), main_window)
    auto_saving.setCheckable(True)
    auto_saving.setChecked(settings.get(SETTING_AUTO_SAVE, False))
    # 单类别模式（PR#106）
    single_class_mode = QAction(get_str('singleClsMode'), main_window)
    single_class_mode.setShortcut("Ctrl+Shift+S")
    single_class_mode.setCheckable(True)
    single_class_mode.setChecked(settings.get(SETTING_SINGLE_CLASS, False))
    main_window.lastLabel = None
    # 标签显示在框上方的开关
    display_label_option = QAction(get_str('displayLabel'), main_window)
    display_label_option.setShortcut("Ctrl+Shift+P")
    display_label_option.setCheckable(True)
    display_label_option.setChecked(settings.get(SETTING_PAINT_LABEL, False))
    display_label_option.triggered.connect(main_window.toggle_paint_labels_option)

    add_actions(menus.file,
                (open, open_dir, change_save_dir, open_annotation, copy_prev_bounding, menus.recentFiles, save, save_format, save_as, close, reset_all, delete_image, quit))
    add_actions(menus.help, (help_default, show_info, show_shortcut))

    # 标签统计 — 独立菜单栏项，放在帮助后面
    label_stats_action = action('标签统计', main_window.show_label_stats,
                                'Ctrl+T', None, '统计当前数据集中的标签分布')
    main_window.menuBar().addAction(label_stats_action)

    # 格式转换 — 独立菜单栏项
    convert_action = action('格式转换', main_window.show_convert_dialog,
                            None, None, '批量转换标注文件格式')
    main_window.menuBar().addAction(convert_action)

    # 删除标注文件 — 独立菜单栏项
    clean_action = action('删除标注文件', main_window.show_clean_dialog,
                          None, None, '批量删除标注文件（清理已转换的原文件）')
    main_window.menuBar().addAction(clean_action)

    add_actions(menus.view, (
        auto_saving,
        single_class_mode,
        display_label_option,
        labels, toggle_side_panels, advanced_mode, None,
        hide_all, show_all, None,
        zoom_in, zoom_out, zoom_org, None,
        remember_zoom_action,
        fit_window, fit_width, None,
        light_brighten, light_darken, light_org))
    main_window.auto_saving = auto_saving
    main_window.single_class_mode = single_class_mode
    main_window.display_label_option = display_label_option

    menus.file.aboutToShow.connect(main_window.update_file_menu)

    # 画布自定义右键菜单
    add_actions(main_window.canvas.menus[0], actions.beginnerContext)
    add_actions(main_window.canvas.menus[1], (
        action('&Copy here', main_window.copy_shape),
        action('&Move here', main_window.move_shape)))

    actions.beginner = (
        open, open_dir, change_save_dir, open_next_image, open_prev_image, verify, save, save_format, None, create, copy, delete, None,
        zoom_compound, None,
        remember_zoom_action,
        fit_window, fit_width, None,
        light_compound, light_org)

    actions.advanced = (
        open, open_dir, change_save_dir, open_next_image, open_prev_image, save, save_format, None,
        create_mode, edit_mode, None,
        hide_all, show_all, None,
        remember_zoom_action)

    tools = main_window.toolbar('Tools')
    tools.setOrientation(Qt.Vertical)
    # dock 包装在 init 末尾（restoreState 之后）进行，避免被覆盖

    return actions, menus, tools
