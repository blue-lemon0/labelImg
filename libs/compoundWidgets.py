"""复合控件集合。

提供 ZoomWidget + SpinBox 组合、亮度滚动条等界面小组件。
"""

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import *

_ICON_W = 24
_SPIN_W = 75


def _make_icon_btn(action):
    btn = QToolButton()
    btn.setDefaultAction(action)
    btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
    btn.setIconSize(QSize(_ICON_W, _ICON_W))
    btn.setFixedSize(_ICON_W, _ICON_W)
    btn.setStyleSheet("QToolButton { border: none; padding: 0px; margin: 0px; }")
    return btn


class ZoomWidgetPanel(QWidget):
    """[zoom_out] [spinbox] [zoom_in] in one toolbar row."""

    def __init__(self, zoom_widget, zoom_in_action, zoom_out_action, parent=None):
        super(ZoomWidgetPanel, self).__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(_make_icon_btn(zoom_out_action))
        zoom_widget.setFixedWidth(_SPIN_W)
        layout.addWidget(zoom_widget)
        layout.addWidget(_make_icon_btn(zoom_in_action))
        self.setFixedWidth(4 + _ICON_W + _SPIN_W + _ICON_W)


class LightWidgetPanel(QWidget):
    """[light_darken] [spinbox] [light_brighten] in one toolbar row."""

    def __init__(self, light_widget, light_brighten_action, light_darken_action, parent=None):
        super(LightWidgetPanel, self).__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(_make_icon_btn(light_darken_action))
        light_widget.setFixedWidth(_SPIN_W)
        layout.addWidget(light_widget)
        layout.addWidget(_make_icon_btn(light_brighten_action))
        self.setFixedWidth(4 + _ICON_W + _SPIN_W + _ICON_W)
