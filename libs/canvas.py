

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from libs.shape import Shape
from libs.utils import distance
from libs.keyAccelerator import KeyAccelerator

# ── 按键绑定表 ──────────────────────────────────────────
# (key_code, modifier_mask) → action_name
# 将物理按键与逻辑操作解耦。
# 后续可改为从用户配置加载。
KEY_BINDINGS = {
    (Qt.Key_C, Qt.NoModifier):    'corner_cw',      # C 键 → 顺时针切换角点
    (Qt.Key_Z, Qt.NoModifier):    'corner_ccw',     # Z 键 → 逆时针切换角点
    (Qt.Key_X, Qt.NoModifier):    'shape_next',     # X 键 → 选中下一个标注
    (Qt.Key_X, Qt.ShiftModifier): 'shape_prev',     # Shift+X → 选中上一个标注
}

CURSOR_DEFAULT = Qt.ArrowCursor         # 默认箭头
CURSOR_POINT = Qt.PointingHandCursor     # 指向顶点
CURSOR_DRAW = Qt.CrossCursor             # 绘制中
CURSOR_MOVE = Qt.ClosedHandCursor        # 拖拽移动
CURSOR_GRAB = Qt.OpenHandCursor          # 悬浮可抓取

# class Canvas(QGLWidget):


class Canvas(QWidget):
    """标注画布：负责图片渲染、标注绘制、鼠标/键盘交互。"""
    zoomRequest = pyqtSignal(int)
    lightRequest = pyqtSignal(int)
    scrollRequest = pyqtSignal(int, int)
    newShape = pyqtSignal()
    selectionChanged = pyqtSignal(bool)
    shapeMoved = pyqtSignal()
    drawingPolygon = pyqtSignal(bool)

    CREATE, EDIT = list(range(2))

    epsilon = 24.0

    def __init__(self, *args, **kwargs):
        super(Canvas, self).__init__(*args, **kwargs)
        # 窗口引用缓存，避免重复调用 self.parent().window()
        self._main_window = None

        # 初始状态
        self.mode = self.EDIT
        self.shapes = []                          # 所有已完成标注
        self.current = None                       # 正在绘制的标注
        self.selected_shape = None                # 当前选中的标注
        self.selected_shape_copy = None            # 右键拖拽时的副本
        self.drawing_line_color = QColor(0, 0, 255)
        self.drawing_rect_color = QColor(0, 0, 255)
        self.line = Shape(line_color=self.drawing_line_color)  # 绘制中的虚拟线
        self.prev_point = QPointF()
        self.offsets = QPointF(), QPointF()
        self.scale = 1.0
        self.overlay_color = None
        self.label_font_size = 8
        self.pixmap = QPixmap()
        self.visible = {}
        self._hide_background = False
        self.hide_background = False
        self.h_shape = None
        self.h_vertex = None
        self._painter = QPainter()
        self._cursor = CURSOR_DEFAULT
        # 右键菜单
        self.menus = (QMenu(), QMenu())
        # 控件选项
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.WheelFocus)
        self.verified = False
        self.draw_square = False

        # 平移用
        self.pan_initial_pos = QPoint()

        # 键盘角点选择模式（-1=整体移动/平移，0-3=对应角点）
        self.corner_idx = -1

        # 方向键组合移动（按下 Left+Down 可斜向移动）
        self._pressed_keys = set()
        self._move_timer = QTimer(self)
        self._move_timer.setInterval(50)  # ~20 fps 持续移动
        self._move_timer.timeout.connect(self._process_held_keys)
        self._key_accel = KeyAccelerator()

        # 背景自动填充（只需设置一次，无需每帧重复）
        self.setAutoFillBackground(True)

    def set_drawing_color(self, qcolor):
        self.drawing_line_color = qcolor
        self.drawing_rect_color = qcolor

    def enterEvent(self, ev):
        """鼠标进入画布时恢复当前光标样式。"""
        self.override_cursor(self._cursor)

    def leaveEvent(self, ev):
        """鼠标离开画布时恢复系统光标。"""
        self.restore_cursor()

    def focusOutEvent(self, ev):
        """焦点移出时恢复系统光标。"""
        self.restore_cursor()

    def isVisible(self, shape):
        return self.visible.get(shape, True)

    def drawing(self):
        """是否处于绘制模式。"""
        return self.mode == self.CREATE

    def editing(self):
        """是否处于编辑模式。"""
        return self.mode == self.EDIT

    def set_editing(self, value=True):
        """切换编辑/绘制模式。"""
        self.mode = self.EDIT if value else self.CREATE
        if not value:  # 进入绘制模式
            self.un_highlight()
            self.de_select_shape()
        self.prev_point = QPointF()
        self.repaint()

    def un_highlight(self, shape=None):
        """清除指定标注（或所有标注）的高亮。"""
        if shape == None or shape == self.h_shape:
            if self.h_shape:
                self.h_shape.highlight_clear()
            self.h_vertex = self.h_shape = None

    def selected_vertex(self):
        """是否选中了某个顶点。"""
        return self.h_vertex is not None

    def mouseMoveEvent(self, ev):
        """鼠标移动：更新绘制辅助线、拖拽标注/顶点、平移背景。"""
        pos = self.transform_pos(ev.pos())

        # 缓存主窗口引用
        if self._main_window is None:
            self._main_window = self.parent().window()
        win = self._main_window

        # 更新状态栏坐标
        if win.file_path is not None:
            win.label_coordinates.setText(
                'X: %d; Y: %d' % (pos.x(), pos.y()))

        # ── 绘制模式 ──
        if self.drawing():
            self.override_cursor(CURSOR_DRAW)
            if self.current:
                # 显示标注宽高
                current_width = abs(self.current[0].x() - pos.x())
                current_height = abs(self.current[0].y() - pos.y())
                win.label_coordinates.setText(
                        'Width: %d, Height: %d / X: %d; Y: %d' % (current_width, current_height, pos.x(), pos.y()))

                color = self.drawing_line_color
                if self.out_of_pixmap(pos):
                    # 不允许画到图片外，将坐标裁剪到边界内
                    size = self.pixmap.size()
                    clipped_x = min(max(0, pos.x()), size.width())
                    clipped_y = min(max(0, pos.y()), size.height())
                    pos = QPointF(clipped_x, clipped_y)
                elif len(self.current) > 1 and self.close_enough(pos, self.current[0]):
                    # 靠近起点时吸附，变色提示用户可闭合
                    pos = self.current[0]
                    color = self.current.line_color
                    self.override_cursor(CURSOR_POINT)
                    self.current.highlight_vertex(0, Shape.NEAR_VERTEX)

                if self.draw_square:
                    init_pos = self.current[0]
                    min_x = init_pos.x()
                    min_y = init_pos.y()
                    min_size = min(abs(pos.x() - min_x), abs(pos.y() - min_y))
                    direction_x = -1 if pos.x() - min_x < 0 else 1
                    direction_y = -1 if pos.y() - min_y < 0 else 1
                    self.line[1] = QPointF(min_x + direction_x * min_size, min_y + direction_y * min_size)
                else:
                    self.line[1] = pos

                self.line.line_color = color
                self.prev_point = QPointF()
                self.current.highlight_clear()
            else:
                self.prev_point = pos
            self.repaint()
            return

        # ── 右键拖拽复制 ──
        if Qt.RightButton & ev.buttons():
            if self.selected_shape_copy and self.prev_point:
                self.override_cursor(CURSOR_MOVE)
                self.bounded_move_shape(self.selected_shape_copy, pos)
                self.repaint()
            elif self.selected_shape:
                self.selected_shape_copy = self.selected_shape.copy()
                self.repaint()
            return

        # ── 左键拖拽移动标注/顶点 ──
        if Qt.LeftButton & ev.buttons():
            if self.selected_vertex():
                self.bounded_move_vertex(pos)
                self.shapeMoved.emit()
                self.repaint()

                # 拖动顶点时显示宽高
                point1 = self.h_shape[1]
                point3 = self.h_shape[3]
                current_width = abs(point1.x() - point3.x())
                current_height = abs(point1.y() - point3.y())
                win.label_coordinates.setText(
                        'Width: %d, Height: %d / X: %d; Y: %d' % (current_width, current_height, pos.x(), pos.y()))
            elif self.selected_shape and self.prev_point:
                self.override_cursor(CURSOR_MOVE)
                self.bounded_move_shape(self.selected_shape, pos)
                self.shapeMoved.emit()
                self.repaint()

                # 移动标注时显示宽高
                point1 = self.selected_shape[1]
                point3 = self.selected_shape[3]
                current_width = abs(point1.x() - point3.x())
                current_height = abs(point1.y() - point3.y())
                win.label_coordinates.setText(
                        'Width: %d, Height: %d / X: %d; Y: %d' % (current_width, current_height, pos.x(), pos.y()))
            else:
                # 左键拖拽空白区域 → 平移
                delta = ev.pos() - self.pan_initial_pos
                self.scrollRequest.emit(delta.x(), Qt.Horizontal)
                self.scrollRequest.emit(delta.y(), Qt.Vertical)
                self.update()
            return

        # ── 纯悬浮（无按键）→ 高亮标注或顶点 ──
        self.setToolTip("Image")
        priority_list = self.shapes + ([self.selected_shape] if self.selected_shape else [])
        for shape in reversed([s for s in priority_list if self.isVisible(s)]):
            # 先看是否靠近某个顶点，再看是否在标注区域内
            index = shape.nearest_vertex(pos, self.epsilon)
            if index is not None:
                if self.selected_vertex():
                    self.h_shape.highlight_clear()
                self.h_vertex, self.h_shape = index, shape
                shape.highlight_vertex(index, shape.MOVE_VERTEX)
                self.override_cursor(CURSOR_POINT)
                self.update()
                break
            elif shape.contains_point(pos):
                if self.selected_vertex():
                    self.h_shape.highlight_clear()
                self.h_vertex, self.h_shape = None, shape
                self.override_cursor(CURSOR_GRAB)
                self.update()

                # 悬浮时在状态栏显示标注宽高
                point1 = self.h_shape[1]
                point3 = self.h_shape[3]
                current_width = abs(point1.x() - point3.x())
                current_height = abs(point1.y() - point3.y())
                win.label_coordinates.setText(
                        'Width: %d, Height: %d / X: %d; Y: %d' % (current_width, current_height, pos.x(), pos.y()))
                break
        else:  # 什么都没碰到 → 清除高亮，重置光标
            if self.h_shape:
                self.h_shape.highlight_clear()
                self.update()
            self.h_vertex, self.h_shape = None, None
            self.override_cursor(CURSOR_DEFAULT)

    def mousePressEvent(self, ev):
        """鼠标按下：左键绘制/选中/平移，右键选中标注。"""
        pos = self.transform_pos(ev.pos())

        if ev.button() == Qt.LeftButton:
            if self.drawing():
                self.handle_drawing(pos)
            else:
                selection = self.select_shape_point(pos)
                self.prev_point = pos

                if selection is None:
                    # 空白区域 → 平移
                    QApplication.setOverrideCursor(QCursor(Qt.OpenHandCursor))
                    self.pan_initial_pos = ev.pos()

        elif ev.button() == Qt.RightButton and self.editing():
            self.select_shape_point(pos)
            self.prev_point = pos
        self.update()

    def mouseReleaseEvent(self, ev):
        """鼠标释放：右键弹出菜单，左键结束拖拽。"""
        if ev.button() == Qt.RightButton:
            menu = self.menus[bool(self.selected_shape_copy)]
            self.restore_cursor()
            if not menu.exec_(self.mapToGlobal(ev.pos()))\
               and self.selected_shape_copy:
                # 取消移动：删掉副本
                self.selected_shape_copy = None
                self.repaint()
        elif ev.button() == Qt.LeftButton and self.selected_shape:
            if self.selected_vertex():
                self.override_cursor(CURSOR_POINT)
            else:
                self.override_cursor(CURSOR_GRAB)
        elif ev.button() == Qt.LeftButton:
            pos = self.transform_pos(ev.pos())
            if self.drawing():
                self.handle_drawing(pos)
            else:
                # 结束平移
                QApplication.restoreOverrideCursor()

    def end_move(self, copy=False):
        """结束右键拖拽移动：确认或取消。"""
        assert self.selected_shape and self.selected_shape_copy
        shape = self.selected_shape_copy
        if copy:
            self.shapes.append(shape)
            self.selected_shape.selected = False
            self.selected_shape = shape
            self.repaint()
        else:
            self.selected_shape.points = [p for p in shape.points]
        self.selected_shape_copy = None

    def hide_background_shapes(self, value):
        """设置是否隐藏非选中标注。"""
        self.hide_background = value
        if self.selected_shape:
            # 有选中标注时才隐藏其他标注，否则用户无法选中
            self.set_hiding(True)
            self.repaint()

    def handle_drawing(self, pos):
        """处理绘制模式下左键点击：添加点或闭合标注。"""
        if self.current and self.current.reach_max_points() is False:
            # 矩形模式下，第二个点确定对角 → 自动补全四个顶点
            init_pos = self.current[0]
            min_x = init_pos.x()
            min_y = init_pos.y()
            target_pos = self.line[1]
            max_x = target_pos.x()
            max_y = target_pos.y()
            self.current.add_point(QPointF(max_x, min_y))
            self.current.add_point(target_pos)
            self.current.add_point(QPointF(min_x, max_y))
            self.finalise()
        elif not self.out_of_pixmap(pos):
            self.current = Shape()
            self.current.add_point(pos)
            self.line.points = [pos, pos]
            self.set_hiding()
            self.drawingPolygon.emit(True)
            self.update()

    def set_hiding(self, enable=True):
        """根据 hide_background 开关设置背景隐藏标志。"""
        self._hide_background = self.hide_background if enable else False

    def can_close_shape(self):
        """是否可以闭合当前标注（绘制模式且至少 3 个点）。"""
        return self.drawing() and self.current and len(self.current) > 2

    def mouseDoubleClickEvent(self, ev):
        """双击闭合标注（至少需要 4 个点，因为 press 事件已加了一个点）。"""
        if self.can_close_shape() and len(self.current) > 3:
            self.current.pop_point()
            self.finalise()

    def select_shape(self, shape):
        """选中指定标注。"""
        self.de_select_shape()
        shape.selected = True
        self.selected_shape = shape
        self.set_hiding()
        self.selectionChanged.emit(True)
        self.update()

    def select_shape_point(self, point):
        """选中包含 point 的第一个标注（按创建顺序逆序）。"""
        self.de_select_shape()
        if self.selected_vertex():  # 先看是否选中了顶点
            index, shape = self.h_vertex, self.h_shape
            shape.highlight_vertex(index, shape.MOVE_VERTEX)
            self.select_shape(shape)
            return self.h_vertex
        for shape in reversed(self.shapes):
            if self.isVisible(shape) and shape.contains_point(point):
                self.select_shape(shape)
                self.calculate_offsets(shape, point)
                return self.selected_shape
        return None

    def calculate_offsets(self, shape, point):
        """计算鼠标在标注内的偏移量，用于后续拖拽。"""
        rect = shape.bounding_rect()
        x1 = rect.x() - point.x()
        y1 = rect.y() - point.y()
        x2 = (rect.x() + rect.width()) - point.x()
        y2 = (rect.y() + rect.height()) - point.y()
        self.offsets = QPointF(x1, y1), QPointF(x2, y2)

    def snap_point_to_canvas(self, x, y):
        """将 (x,y) 约束到图片边界内。
        :return: (x, y, snapped) 其中 snapped 表示是否被修正过。
        """
        if x < 0 or x > self.pixmap.width() or y < 0 or y > self.pixmap.height():
            x = max(x, 0)
            y = max(y, 0)
            x = min(x, self.pixmap.width())
            y = min(y, self.pixmap.height())
            return x, y, True

        return x, y, False

    def bounded_move_vertex(self, pos):
        """鼠标拖拽顶点：保持相邻顶点联动以维持矩形。"""
        index, shape = self.h_vertex, self.h_shape
        point = shape[index]
        if self.out_of_pixmap(pos):
            size = self.pixmap.size()
            clipped_x = min(max(0, pos.x()), size.width())
            clipped_y = min(max(0, pos.y()), size.height())
            pos = QPointF(clipped_x, clipped_y)

        if self.draw_square:
            opposite_point_index = (index + 2) % 4
            opposite_point = shape[opposite_point_index]

            min_size = min(abs(pos.x() - opposite_point.x()), abs(pos.y() - opposite_point.y()))
            direction_x = -1 if pos.x() - opposite_point.x() < 0 else 1
            direction_y = -1 if pos.y() - opposite_point.y() < 0 else 1
            shift_pos = QPointF(opposite_point.x() + direction_x * min_size - point.x(),
                                opposite_point.y() + direction_y * min_size - point.y())
        else:
            shift_pos = pos - point

        shape.move_vertex_by(index, shift_pos)

        left_index = (index + 1) % 4
        right_index = (index + 3) % 4
        left_shift = None
        right_shift = None
        if index % 2 == 0:
            right_shift = QPointF(shift_pos.x(), 0)
            left_shift = QPointF(0, shift_pos.y())
        else:
            left_shift = QPointF(shift_pos.x(), 0)
            right_shift = QPointF(0, shift_pos.y())
        shape.move_vertex_by(right_index, right_shift)
        shape.move_vertex_by(left_index, left_shift)

    def bounded_move_shape(self, shape, pos):
        """鼠标拖拽整个标注：保持其不超出图片边界。"""
        if self.out_of_pixmap(pos):
            return False  # 无需移动
        o1 = pos + self.offsets[0]
        if self.out_of_pixmap(o1):
            pos -= QPointF(min(0, o1.x()), min(0, o1.y()))
        o2 = pos + self.offsets[1]
        if self.out_of_pixmap(o2):
            pos += QPointF(min(0, self.pixmap.width() - o2.x()),
                           min(0, self.pixmap.height() - o2.y()))
        dp = pos - self.prev_point
        if dp:
            shape.move_by(dp)
            self.prev_point = pos
            return True
        return False

    def de_select_shape(self):
        """取消选中当前标注。"""
        if self.selected_shape:
            self.selected_shape.selected = False
            self.selected_shape.clear_vertex_select()
            self.selected_shape = None
            self.corner_idx = -1
            self.set_hiding(False)
            self.selectionChanged.emit(False)
            self.update()

    def delete_selected(self):
        """删除当前选中的标注，返回被删除的 Shape 对象。"""
        if self.selected_shape:
            shape = self.selected_shape
            self.un_highlight(shape)
            if self.selected_shape in self.shapes:
                self.shapes.remove(self.selected_shape)
            self.selected_shape = None
            self.corner_idx = -1
            self.update()
            return shape

    def copy_selected_shape(self):
        """复制当前选中的标注并偏移放置。"""
        if self.selected_shape:
            shape = self.selected_shape.copy()
            self.de_select_shape()
            self.shapes.append(shape)
            shape.selected = True
            self.selected_shape = shape
            self.bounded_shift_shape(shape)
            return shape

    def bounded_shift_shape(self, shape):
        """尝试将标注偏移 (2,2)，失败则向反方向偏移。"""
        point = shape[0]
        offset = QPointF(2.0, 2.0)
        self.calculate_offsets(shape, point)
        self.prev_point = point
        if not self.bounded_move_shape(shape, point - offset):
            self.bounded_move_shape(shape, point + offset)

    def paintEvent(self, event):
        """绘制画布：渲染图片、标注、辅助线。"""
        if not self.pixmap:
            return super(Canvas, self).paintEvent(event)

        p = self._painter
        p.begin(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.HighQualityAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        p.scale(self.scale, self.scale)
        p.translate(self.offset_to_center())

        # 绘制图片（如有 overlay 颜色则先叠加）
        temp = self.pixmap
        if self.overlay_color:
            temp = QPixmap(self.pixmap)
            painter = QPainter(temp)
            painter.setCompositionMode(painter.CompositionMode_Overlay)
            painter.fillRect(temp.rect(), self.overlay_color)
            painter.end()

        p.drawPixmap(0, 0, temp)
        Shape.scale = self.scale
        Shape.label_font_size = self.label_font_size
        for shape in self.shapes:
            if (shape.selected or not self._hide_background) and self.isVisible(shape):
                shape.fill = shape.selected
                # save/restore 隔离 painter state，防止 setBrush 泄漏
                p.save()
                shape.paint(p)
                p.restore()
        if self.current:
            self.current.paint(p)
            self.line.paint(p)
        if self.selected_shape_copy:
            self.selected_shape_copy.paint(p)

        # 绘制矩形辅助框（对角虚线填充）
        if self.current is not None and len(self.line) == 2:
            left_top = self.line[0]
            right_bottom = self.line[1]
            rect_width = right_bottom.x() - left_top.x()
            rect_height = right_bottom.y() - left_top.y()
            p.setPen(self.drawing_rect_color)
            brush = QBrush(Qt.BDiagPattern)
            p.setBrush(brush)
            p.drawRect(int(left_top.x()), int(left_top.y()), int(rect_width), int(rect_height))

        # 绘制十字参考线（绘制模式下，上一个点的位置）
        if self.drawing() and not self.prev_point.isNull() and not self.out_of_pixmap(self.prev_point):
            p.setPen(QColor(0, 0, 0))
            p.drawLine(int(self.prev_point.x()), 0, int(self.prev_point.x()), int(self.pixmap.height()))
            p.drawLine(0, int(self.prev_point.y()), int(self.pixmap.width()), int(self.prev_point.y()))

        # 设置画布背景色（表示验证状态）
        if self.verified:
            pal = self.palette()
            pal.setColor(self.backgroundRole(), QColor(184, 239, 38, 128))
            self.setPalette(pal)
        else:
            pal = self.palette()
            pal.setColor(self.backgroundRole(), QColor(232, 232, 232, 255))
            self.setPalette(pal)

        p.end()

    def transform_pos(self, point):
        """将控件坐标系转换为画布坐标系。"""
        return point / self.scale - self.offset_to_center()

    def offset_to_center(self):
        """计算图片居中显示所需的偏移量。"""
        s = self.scale
        area = super(Canvas, self).size()
        w, h = self.pixmap.width() * s, self.pixmap.height() * s
        aw, ah = area.width(), area.height()
        x = (aw - w) / (2 * s) if aw > w else 0
        y = (ah - h) / (2 * s) if ah > h else 0
        return QPointF(x, y)

    def out_of_pixmap(self, p):
        """判断坐标是否超出图片边界。"""
        w, h = self.pixmap.width(), self.pixmap.height()
        return not (0 <= p.x() <= w and 0 <= p.y() <= h)

    def finalise(self):
        """完成当前标注的绘制：闭合、加入列表、清空当前。"""
        assert self.current
        if self.current.points[0] == self.current.points[-1]:
            self.current = None
            self.drawingPolygon.emit(False)
            self.update()
            return

        self.current.close()
        self.shapes.append(self.current)
        self.current = None
        self.set_hiding(False)
        self.newShape.emit()
        self.update()

    def close_enough(self, p1, p2):
        """判断两点是否足够接近（用于闭合吸附）。"""
        return distance(p1 - p2) < self.epsilon

    # sizeHint / minimumSizeHint 是 QScrollArea 所需
    def sizeHint(self):
        return self.minimumSizeHint()

    def minimumSizeHint(self):
        if self.pixmap:
            return self.scale * self.pixmap.size()
        return super(Canvas, self).minimumSizeHint()

    def wheelEvent(self, ev):
        """滚轮事件：Ctrl+滚轮缩放，Ctrl+Shift+滚轮调亮度，无修饰键滚动。"""
        qt_version = 4 if hasattr(ev, "delta") else 5
        if qt_version == 4:
            if ev.orientation() == Qt.Vertical:
                v_delta = ev.delta()
                h_delta = 0
            else:
                h_delta = ev.delta()
                v_delta = 0
        else:
            delta = ev.angleDelta()
            h_delta = delta.x()
            v_delta = delta.y()

        mods = ev.modifiers()
        if int(Qt.ControlModifier) | int(Qt.ShiftModifier) == int(mods) and v_delta:
            self.lightRequest.emit(v_delta)
        elif Qt.ControlModifier == int(mods) and v_delta:
            self.zoomRequest.emit(v_delta)
        else:
            v_delta and self.scrollRequest.emit(v_delta, Qt.Vertical)
            h_delta and self.scrollRequest.emit(h_delta, Qt.Horizontal)
        ev.accept()

    def execute_action(self, action, event=None):
        """分发命名操作：将 '做什么' 与 '按哪个键' 解耦。
        被 Canvas.keyPressEvent 和 MainWindow.eventFilter 调用。
        """
        if action == 'corner_cw':
            if self.selected_shape:
                self._cycle_corner(1)
        elif action == 'corner_ccw':
            if self.selected_shape:
                self._cycle_corner(-1)
        elif action == 'shape_next':
            self._select_next_shape(1)
        elif action == 'shape_prev':
            self._select_next_shape(-1)

    def _select_next_shape(self, direction):
        """切换选中标注：direction=1 下一个，-1 上一个。"""
        if not self.shapes:
            return
        # 清除鼠标悬浮高亮——键盘切换不应继承悬浮状态
        self.un_highlight()
        if not self.selected_shape:
            self.select_shape(self.shapes[0 if direction == 1 else -1])
            return
        if len(self.shapes) == 1:
            return
        idx = self.shapes.index(self.selected_shape)
        next_idx = (idx + direction) % len(self.shapes)
        self.select_shape(self.shapes[next_idx])

    def _lookup_action(self, ev):
        """将按键事件映射为操作名称（查 KEY_BINDINGS）。"""
        shift = ev.modifiers() & Qt.ShiftModifier
        return KEY_BINDINGS.get((ev.key(), shift))

    def keyPressEvent(self, ev):
        """键盘按键处理：方向键移动标注/顶点，Enter 闭合，Escape 取消。"""
        key = ev.key()
        if key == Qt.Key_Escape and self.current:
            print('ESC press')
            self.current = None
            self.drawingPolygon.emit(False)
            self.update()
        elif key == Qt.Key_Return and self.can_close_shape():
            self.finalise()
        elif key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.selected_shape:
            if not ev.isAutoRepeat():
                was_empty = not self._pressed_keys
                self._pressed_keys.add(key)
                if was_empty:
                    self._key_accel.start()
                if not self._move_timer.isActive():
                    self._move_timer.start()
                self._process_held_keys()  # 立即移动一次，不用等定时器
        elif key == Qt.Key_Escape:
            self._reset_corner_mode()
        else:
            # 按键绑定表分发——将物理键与逻辑解耦
            action = self._lookup_action(ev)
            if action:
                self.execute_action(action)

    def keyReleaseEvent(self, ev):
        """方向键释放：停止加速并清除按键记录。"""
        key = ev.key()
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            if not ev.isAutoRepeat():
                self._pressed_keys.discard(key)
                if not self._pressed_keys:
                    self._move_timer.stop()
                    self._key_accel.stop()

    def _cycle_corner(self, direction):
        """通过数据驱动的转换表轮换角点选择。
        direction=1:  顺时针  -1→0→1→2→3→-1→0…
        direction=-1: 逆时针  -1→0→3→2→1→-1→0…
        两者共享同一逻辑——只有转换表不同。
        """
        shape = self.selected_shape
        if shape is None:
            return
        if self.corner_idx == -1:
            self.corner_idx = 0  # 首次按下始终进入左上角(0)
        else:
            transitions = {
                1: {0: 1, 1: 2, 2: 3, 3: -1},    # 顺时针
                -1: {0: 3, 3: 2, 2: 1, 1: -1},   # 逆时针
            }
            self.corner_idx = transitions[direction].get(self.corner_idx, -1)
        self._apply_corner_visual()
        self.repaint()

    def _apply_corner_visual(self):
        """根据当前 corner_idx 更新标注的视觉指示。"""
        shape = self.selected_shape
        if shape is None:
            return
        if self.corner_idx >= 0:
            shape.set_vertex_select(self.corner_idx)
        else:
            shape.clear_vertex_select()

    def _reset_corner_mode(self):
        """重置为整体平移模式。"""
        if self.corner_idx != -1:
            self.corner_idx = -1
            if self.selected_shape:
                self.selected_shape.clear_vertex_select()
            self.repaint()

    def move_one_pixel(self, direction):
        """单步移动 1 像素（保留以兼容外部 API）。"""
        step = QPointF(0, 0)
        if direction == 'Left':
            step = QPointF(-1.0, 0)
        elif direction == 'Right':
            step = QPointF(1.0, 0)
        elif direction == 'Up':
            step = QPointF(0, -1.0)
        elif direction == 'Down':
            step = QPointF(0, 1.0)
        self._apply_move_step(step)

    def _apply_move_step(self, step):
        """应用 (dx, dy) 步长：如果是角点模式则移动单个顶点，否则移动整个标注。"""
        if self.corner_idx >= 0:
            if self._is_valid_vertex_move(self.corner_idx, step):
                self._move_vertex(self.corner_idx, step)
                self.shapeMoved.emit()
                self.repaint()
        else:
            if not self.move_out_of_bound(step):
                self.selected_shape.points[0] += step
                self.selected_shape.points[1] += step
                self.selected_shape.points[2] += step
                self.selected_shape.points[3] += step
                self.shapeMoved.emit()
                self.repaint()

    def _process_held_keys(self):
        """定时器回调：将当前所有按下的方向键合并为一个斜向步长。"""
        if not self.selected_shape:
            self._pressed_keys.clear()
            self._move_timer.stop()
            return

        step_mag = self._key_accel.step()
        dx = 0
        dy = 0
        if Qt.Key_Left in self._pressed_keys:
            dx -= step_mag
        if Qt.Key_Right in self._pressed_keys:
            dx += step_mag
        if Qt.Key_Up in self._pressed_keys:
            dy -= step_mag
        if Qt.Key_Down in self._pressed_keys:
            dy += step_mag
        if dx == 0 and dy == 0:
            return
        self._apply_move_step(QPointF(dx, dy))

    def _move_vertex(self, index, step):
        """移动单个角点，同时调整相邻两点以保持矩形。
        逻辑与 bounded_move_vertex() 一致。"""
        shape = self.selected_shape
        left_idx = (index + 1) % 4
        right_idx = (index + 3) % 4
        if index % 2 == 0:
            right_shift = QPointF(step.x(), 0)
            left_shift = QPointF(0, step.y())
        else:
            left_shift = QPointF(step.x(), 0)
            right_shift = QPointF(0, step.y())
        shape.move_vertex_by(index, step)
        shape.move_vertex_by(right_idx, right_shift)
        shape.move_vertex_by(left_idx, left_shift)

    def _is_valid_vertex_move(self, index, step):
        """判断移动顶点是否合法（不小于 2px、不超出图片边界）。"""
        shape = self.selected_shape
        new_points = [QPointF(p) for p in shape.points]

        left_idx = (index + 1) % 4
        right_idx = (index + 3) % 4
        if index % 2 == 0:
            right_shift = QPointF(step.x(), 0)
            left_shift = QPointF(0, step.y())
        else:
            left_shift = QPointF(step.x(), 0)
            right_shift = QPointF(0, step.y())

        new_points[index] += step
        new_points[right_idx] += right_shift
        new_points[left_idx] += left_shift

        for p in new_points:
            if self.out_of_pixmap(p):
                return False

        xs = [p.x() for p in new_points]
        ys = [p.y() for p in new_points]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if width < 2.0 or height < 2.0:
            return False

        return True

    def move_out_of_bound(self, step):
        """判断按 step 移动后是否超出图片边界。"""
        points = [p1 + p2 for p1, p2 in zip(self.selected_shape.points, [step] * 4)]
        return True in map(self.out_of_pixmap, points)

    def set_last_label(self, text, line_color=None, fill_color=None):
        """设置最后一个标注的标签文本和颜色。"""
        assert text
        self.shapes[-1].label = text
        if line_color:
            self.shapes[-1].line_color = line_color
        if fill_color:
            self.shapes[-1].fill_color = fill_color
        return self.shapes[-1]

    def undo_last_line(self):
        """撤销上一个标注：把它从已完成的列表中移回正在绘制状态。"""
        assert self.shapes
        self.current = self.shapes.pop()
        self.current.set_open()
        self.line.points = [self.current[-1], self.current[0]]
        self.drawingPolygon.emit(True)

    def reset_all_lines(self):
        """重置所有标注（撤销所有并清除当前）。"""
        assert self.shapes
        self.current = self.shapes.pop()
        self.current.set_open()
        self.line.points = [self.current[-1], self.current[0]]
        self.drawingPolygon.emit(True)
        self.current = None
        self.drawingPolygon.emit(False)
        self.update()

    def load_pixmap(self, pixmap):
        """加载新图片并清空标注。"""
        self.pixmap = pixmap
        self.shapes = []
        self.repaint()

    def load_shapes(self, shapes):
        """加载已有标注列表。"""
        self.shapes = list(shapes)
        self.current = None
        self.repaint()

    def set_shape_visible(self, shape, value):
        """设置某个标注的可见性。"""
        self.visible[shape] = value
        self.repaint()

    def current_cursor(self):
        """获取当前光标形状。"""
        cursor = QApplication.overrideCursor()
        if cursor is not None:
            cursor = cursor.shape()
        return cursor

    def override_cursor(self, cursor):
        """覆盖光标样式（如果未被覆盖则新建，否则变更）。"""
        self._cursor = cursor
        if self.current_cursor() is None:
            QApplication.setOverrideCursor(cursor)
        else:
            QApplication.changeOverrideCursor(cursor)

    def restore_cursor(self):
        """恢复系统光标。"""
        QApplication.restoreOverrideCursor()

    def reset_state(self):
        """重置画布状态（取消选中、清除高亮、卸载图片）。"""
        self.de_select_shape()
        self.un_highlight()
        self.selected_shape_copy = None
        self.restore_cursor()
        self.pixmap = None
        self.update()

    def set_drawing_shape_to_square(self, status):
        """设置绘制模式是否为正方形。"""
        self.draw_square = status
