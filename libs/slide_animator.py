"""侧边栏自动折叠 + 边缘唤醒，不依赖具体业务逻辑。

行为：
  1. 拖动侧边栏缩窄到 40px 以下 → 自动收起（带动画）
  2. 收起后边缘出现可点击的唤醒标签
  3. 点击标签 → 展开侧边栏（带动画）
"""

from PyQt5.QtCore import (QObject, QPropertyAnimation, QEasingCurve,
                          QAbstractAnimation, QTimer, QEvent,
                          Qt, pyqtSignal)
from PyQt5.QtGui import QPainter, QColor, QCursor
from PyQt5.QtWidgets import QDockWidget, QToolButton


_COLLAPSE_THRESHOLD = 40    # px, 缩窄至此宽度以下时自动折叠
_TAB_W = 14                 # px, 边缘唤醒标签宽度
_TAB_H = 100                # px, 标签高度
_ANIM_MS = 160              # ms, 展开/收起动画时长


class _EdgeTab(QToolButton):
    """边缘唤醒标签。自动识别 dock 所在侧，绘制相应箭头。"""

    expand_requested = pyqtSignal()
    _is_left = True  # True=左边缘, False=右边缘

    def __init__(self, is_left_side, parent=None):
        super().__init__(parent)
        self._is_left = is_left_side
        self.setFixedSize(_TAB_W, _TAB_H)
        cursor = Qt.SizeHorCursor
        self.setCursor(QCursor(cursor))
        self.setMouseTracking(True)
        self._hovered = False

        # 根据左右侧设置不同的圆角
        if is_left_side:
            radii = 'border-top-left-radius: 0px; border-bottom-left-radius: 0px;' \
                    'border-top-right-radius: 4px; border-bottom-right-radius: 4px;'
        else:
            radii = 'border-top-left-radius: 4px; border-bottom-left-radius: 4px;' \
                    'border-top-right-radius: 0px; border-bottom-right-radius: 0px;'
        self.setStyleSheet(f"""
            QToolButton {{
                background: rgba(80, 140, 240, 140);
                border: none;
                {radii}
            }}
            QToolButton:hover {{
                background: rgba(80, 140, 240, 210);
            }}
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        color = QColor('#1565C0') if self._hovered else QColor('#444')
        p.setPen(color)
        p.setBrush(color)
        cx, cy = w // 2, h // 2
        s = 5
        # 左侧面板 → 箭头向右 ▶，右侧面板 → 箭头向左 ◀
        if self._is_left:
            pts = (QPoint(cx - s // 2, cy - s),
                   QPoint(cx - s // 2, cy + s),
                   QPoint(cx + s // 2, cy))
        else:
            pts = (QPoint(cx + s // 2, cy - s),
                   QPoint(cx + s // 2, cy + s),
                   QPoint(cx - s // 2, cy))
        p.drawPolygon(*pts)
        p.end()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.expand_requested.emit()
        super().mousePressEvent(event)


class AutoCollapseDockManager(QObject):
    """自动折叠 + 边缘唤醒管理器。"""

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._mw = main_window
        self._docks = []                  # [QDockWidget, ...]
        self._saved_widths = {}           # id(dock) -> int (最后已知正常宽度，>阈值)
        self._edge_tabs = {}              # id(dock) -> _EdgeTab
        self._dock_sides = {}             # id(dock) -> 'left' or 'right'
        self._auto_collapsed = set()      # 由自动折叠隐藏的 dock id
        # 定时轮询 dock 宽度（Resize 事件在拖拽时不可靠）
        self._watchdog = QTimer(self)
        self._watchdog.setInterval(80)    # ms
        self._watchdog.timeout.connect(self._check_widths)

    def _check_widths(self):
        """轮询检查 dock 宽度，低于阈值则自动折叠。"""
        for dock in self._docks:
            if dock.isVisible() and id(dock) not in self._auto_collapsed:
                saved = self._saved_widths.get(id(dock), 0)
                content = dock.widget()
                w = content.width() if content else dock.width()
                # 如实际布局未更新，回退到 maximumWidth
                if w > _COLLAPSE_THRESHOLD and content and content.maximumWidth() < _COLLAPSE_THRESHOLD:
                    w = content.maximumWidth()
                # 更新最后已知正常宽度（仅当宽度大于阈值时）
                if w >= _COLLAPSE_THRESHOLD:
                    self._saved_widths[id(dock)] = w
                # 低于阈值 → 自动折叠
                if w < _COLLAPSE_THRESHOLD < saved:
                    self._auto_collapsed.add(id(dock))
                    self._collapse(dock)

    def register(self, dock):
        """注册一个 QDockWidget 以启用自动折叠/唤醒。"""
        if dock in self._docks:
            return
        self._docks.append(dock)
        content = dock.widget()
        self._saved_widths[id(dock)] = content.width() if content else 200
        # 判断 dock 在主窗口的哪一侧
        area = self._mw.dockWidgetArea(dock)
        if area in (Qt.LeftDockWidgetArea,):
            self._dock_sides[id(dock)] = 'left'
        else:
            self._dock_sides[id(dock)] = 'right'
        # 注册后启动轮询（首次触发时启动）
        if not self._watchdog.isActive():
            self._watchdog.start()

    def toggle_all(self):
        """一键切换全部注册 dock。"""
        any_visible = any(d.isVisible() for d in self._docks)
        for dock in self._docks:
            if any_visible:
                self._collapse(dock)
            else:
                self._expand(dock)

    # ── 事件拦截 ────────────────────────────────────

    def eventFilter(self, obj, event):
        # 主窗口 resize → 重定位边缘标签
        if obj is self._mw and event.type() == QEvent.Resize:
            self._reposition_all_tabs()
            return False
        return super().eventFilter(obj, event)

    # ── 折叠 ────────────────────────────────────────

    def _collapse(self, dock):
        content = dock.widget()
        if content is None:
            dock.hide()
            self._show_edge_tab(dock)
            return
        anim = QPropertyAnimation(content, b'maximumWidth')
        anim.setDuration(_ANIM_MS)
        anim.setStartValue(content.width())
        anim.setEndValue(0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self._finish_collapse(dock))
        anim.start(QAbstractAnimation.DeleteWhenStopped)

    def _finish_collapse(self, dock):
        dock.hide()
        self._show_edge_tab(dock)

    # ── 展开 ────────────────────────────────────────

    def _expand(self, dock):
        self._hide_edge_tab(dock)
        self._auto_collapsed.discard(id(dock))
        content = dock.widget()
        if content is None:
            dock.show()
            return
        target = self._saved_widths.get(id(dock), 250)
        # 先缩到 0 再 show，避免闪现完整宽度
        content.setMaximumWidth(0)
        content.setMinimumWidth(0)
        dock.show()
        content.updateGeometry()
        QTimer.singleShot(0, lambda: self._animate_expand(content, target))

    def _animate_expand(self, content, target):
        if content is None:
            return
        content.setMinimumWidth(0)
        anim = QPropertyAnimation(content, b'maximumWidth')
        anim.setDuration(_ANIM_MS)
        anim.setStartValue(0)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QAbstractAnimation.DeleteWhenStopped)

    # ── 边缘标签管理 ────────────────────────────────

    def _show_edge_tab(self, dock):
        if id(dock) in self._edge_tabs:
            return
        is_left = self._dock_sides.get(id(dock), 'right') == 'left'
        tab = _EdgeTab(is_left, self._mw)
        tab.expand_requested.connect(lambda: self._expand(dock))
        tab.raise_()
        tab.show()
        self._position_tab(tab)
        self._edge_tabs[id(dock)] = tab
        self._mw.installEventFilter(self)

    def _hide_edge_tab(self, dock):
        tab = self._edge_tabs.pop(id(dock), None)
        if tab is not None:
            tab.hide()
            tab.deleteLater()

    def _position_tab(self, tab):
        parent = tab.parent()
        if parent is None:
            return
        if tab._is_left:
            x = 0
        else:
            x = parent.width() - tab.width()
        y = (parent.height() - tab.height()) // 2
        tab.move(x, y)
        tab.raise_()

    def _reposition_all_tabs(self):
        for tab in self._edge_tabs.values():
            self._position_tab(tab)
