"""带标签自动补全的下拉选择器组件。

封装 QComboBox + 编辑过滤，用于标签输入时的历史记录匹配。
"""

from PyQt5.QtWidgets import QWidget, QHBoxLayout, QComboBox


class ComboBox(QWidget):
    def __init__(self, parent=None, items=[]):
        super(ComboBox, self).__init__(parent)

        layout = QHBoxLayout()
        self.cb = QComboBox()
        self.items = items
        self.cb.addItems(self.items)

        self.cb.currentIndexChanged.connect(parent.combo_selection_changed)

        layout.addWidget(self.cb)
        self.setLayout(layout)

    def update_items(self, items):
        self.items = items

        self.cb.clear()
        self.cb.addItems(self.items)
