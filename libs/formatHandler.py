# -*- coding: utf-8 -*-
"""格式处理器策略模式。

将 save_labels / load_file 中的 if format == X 分支消除，
每种标注格式封装为一个独立 Handler。
"""

from abc import ABC, abstractmethod

from libs.constants import (FORMAT_PASCALVOC, FORMAT_YOLO, FORMAT_CREATEML)
from libs.labelFile import LabelFileFormat
from libs.pascal_voc_io import PascalVocReader, XML_EXT
from libs.yolo_io import YoloReader, TXT_EXT
from libs.create_ml_io import CreateMLReader, JSON_EXT


class FormatHandler(ABC):
    """标注格式策略接口。"""

    @property
    @abstractmethod
    def ext(self) -> str:
        """文件扩展名（含点），如 '.xml'。"""

    @property
    @abstractmethod
    def format(self) -> LabelFileFormat:
        """对应的 LabelFileFormat 枚举值。"""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """界面显示名称，如 'PascalVOC'。"""

    @property
    @abstractmethod
    def icon(self) -> str:
        """工具栏图标资源名，如 'format_voc'。"""

    @abstractmethod
    def save(self, label_file, filename, shapes, image_path, image_data,
             label_hist, line_color, fill_color):
        """将 shapes 保存为特定格式的标注文件。

        Args:
            label_file: LabelFile 实例（已设置 verified）
            filename: 目标文件路径（可能不含扩展名）
            ...
        Returns:
            str: 实际写入的文件路径（含正确扩展名）
        """

    @abstractmethod
    def load(self, file_path, image_path=None):
        """读取标注文件，返回 (shapes, verified)。

        shapes: list of (label, points, None, None, difficult)
        points: [(x1,y1), (x2,y2), (x3,y3), (x4,y4)]
        """


class PascalVocFormatHandler(FormatHandler):
    ext = XML_EXT
    format = LabelFileFormat.PASCAL_VOC
    display_name = FORMAT_PASCALVOC
    icon = 'format_voc'

    def save(self, label_file, filename, shapes, image_path, image_data,
             label_hist, line_color, fill_color):
        if not filename.lower().endswith('.xml'):
            filename += XML_EXT
        label_file.save_pascal_voc_format(
            filename, shapes, image_path, image_data,
            line_color, fill_color)
        return filename

    def load(self, file_path, image_path=None):
        reader = PascalVocReader(file_path)
        return reader.get_shapes(), reader.verified


class YoloFormatHandler(FormatHandler):
    ext = TXT_EXT
    format = LabelFileFormat.YOLO
    display_name = FORMAT_YOLO
    icon = 'format_yolo'

    def save(self, label_file, filename, shapes, image_path, image_data,
             label_hist, line_color, fill_color):
        if not filename.lower().endswith('.txt'):
            filename += TXT_EXT
        label_file.save_yolo_format(
            filename, shapes, image_path, image_data, label_hist,
            line_color, fill_color)
        return filename

    def load(self, file_path, image_path=None):
        if image_path is None:
            raise ValueError("YOLO loading requires image_path")
        from PyQt5.QtGui import QImage
        image = QImage()
        image.load(image_path)
        reader = YoloReader(file_path, image)
        return reader.get_shapes(), reader.verified


class CreateMLFormatHandler(FormatHandler):
    ext = JSON_EXT
    format = LabelFileFormat.CREATE_ML
    display_name = FORMAT_CREATEML
    icon = 'format_createml'

    def save(self, label_file, filename, shapes, image_path, image_data,
             label_hist, line_color, fill_color):
        if not filename.lower().endswith('.json'):
            filename += JSON_EXT
        label_file.save_create_ml_format(
            filename, shapes, image_path, image_data, label_hist,
            line_color, fill_color)
        return filename

    def load(self, file_path, image_path=None):
        if image_path is None:
            raise ValueError("CreateML loading requires image_path")
        reader = CreateMLReader(file_path, image_path)
        return reader.get_shapes(), reader.verified


# ── 注册表 ────────────────────────────────────────────────
FORMAT_REGISTRY = {
    LabelFileFormat.PASCAL_VOC: PascalVocFormatHandler,
    LabelFileFormat.YOLO:       YoloFormatHandler,
    LabelFileFormat.CREATE_ML:  CreateMLFormatHandler,
}


def get_handler(label_file_format: LabelFileFormat) -> FormatHandler:
    """从注册表获取格式处理器实例。"""
    cls = FORMAT_REGISTRY.get(label_file_format)
    if cls is None:
        raise ValueError(f"Unknown label file format: {label_file_format}")
    return cls()
