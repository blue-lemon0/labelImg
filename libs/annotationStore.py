# -*- coding: utf-8 -*-
"""标注数据模型，与 UI 无关。变更通过信号通知。"""

from PyQt5.QtCore import QObject, pyqtSignal


class AnnotationStore(QObject):
    """标注数据模型，集中管理所有标注相关状态。"""

    data_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.label_hist: list[str] = []
        self.label_to_indices: dict[str, list[int]] = {}
        self.img_label_map: dict[str, dict[str, int]] = {}
        self.stats_cache: dict | None = None
        self.items_to_shapes: dict = {}
        self.shapes_to_items: dict = {}
        self.last_label: str = ""
        self.prev_label_text: str = ""
        self.default_label: str = ""

    def add_label_to_history(self, text: str):
        """将标签加入历史记录（大小写去重，保留最近 100 条）。"""
        self.label_hist = [l for l in self.label_hist if l.lower() != text.lower()]
        self.label_hist.append(text)
        if len(self.label_hist) > 100:
            self.label_hist = self.label_hist[-100:]

    def remove_from_history(self, text: str):
        """从历史记录移除（大小写不敏感）。"""
        self.label_hist = [l for l in self.label_hist if l.lower() != text.lower()]

    def get_all_labels(self) -> list[str]:
        """返回去重排序的所有候选标签（来自 label_to_indices + label_hist）。"""
        labels = set(self.label_to_indices.keys())
        labels.update(self.label_hist)
        labels.discard("")
        return sorted(labels)
