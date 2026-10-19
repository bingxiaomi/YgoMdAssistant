import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..vision.region_manager import Region, RegionProfile


def fit_rect(container_width: int, container_height: int, image_width: int, image_height: int) -> QRectF:
    scale = min(container_width / image_width, container_height / image_height)
    width, height = image_width * scale, image_height * scale
    return QRectF((container_width - width) / 2, (container_height - height) / 2, width, height)


class FrameView(QWidget):
    region_changed = Signal(str, object)

    def __init__(self, parent=None, *, editable=True):
        super().__init__(parent)
        self.editable = editable
        self.setMinimumSize(320, 200) if editable else self.setMinimumSize(180, 100)
        self._image = None
        self.profile: RegionProfile | None = None
        self.selected = "duel_log"
        self.show_regions = True
        self.force_draw = False
        self._drag = None
        self.placeholder = "选择游戏窗口并开始采集，或导入录像"
        self.setMouseTracking(True)

    def set_image(self, image: np.ndarray | None):
        if image is None:
            self._image = None
        else:
            data = np.ascontiguousarray(image)
            if self._image is not None and (self._image.width(), self._image.height()) != (data.shape[1], data.shape[0]):
                self._drag = None
            self._image = QImage(data.data, data.shape[1], data.shape[0], data.strides[0],
                                 QImage.Format.Format_BGR888).copy()
        self.update()

    def image_rect(self) -> QRectF:
        if self._image is None:
            return QRectF()
        return fit_rect(self.width(), self.height(), self._image.width(), self._image.height())

    def _screen_region(self, region: Region) -> QRectF:
        rect = self.image_rect()
        return QRectF(rect.x() + region.x * rect.width(), rect.y() + region.y * rect.height(),
                      region.width * rect.width(), region.height * rect.height())

    def _normalized(self, point: QPointF) -> QPointF:
        rect = self.image_rect()
        return QPointF(max(0., min(1., (point.x() - rect.x()) / rect.width())),
                       max(0., min(1., (point.y() - rect.y()) / rect.height())))

    def paintEvent(self, _):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101722"))
        if self._image is None:
            painter.setPen(QColor("#abb8ca"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
            return
        painter.drawImage(self.image_rect(), self._image)
        if not self.profile or not self.show_regions:
            return
        for name, region in self.profile.regions.items():
            rect = self._screen_region(region)
            color = QColor("#f7cc59") if name == self.selected else QColor("#51d5ec")
            painter.setPen(QPen(color, 2))
            painter.drawRect(rect)
            painter.fillRect(QRectF(rect.x(), max(self.image_rect().top(), rect.y() - 23), 145, 22), QColor(16, 23, 34, 215))
            painter.drawText(QPointF(rect.x() + 5, max(self.image_rect().top() + 16, rect.y() - 6)), region.label)
            if self.editable and name == self.selected:
                painter.fillRect(QRectF(rect.right() - 5, rect.bottom() - 5, 10, 10), color)

    def mousePressEvent(self, event):
        if (not self.editable or not self.show_regions or self.profile is None or self._image is None
                or event.button() != Qt.MouseButton.LeftButton or not self.image_rect().contains(event.position())):
            return
        region = self.profile.regions.get(self.selected)
        if region is None:
            return
        screen = self._screen_region(region)
        point = self._normalized(event.position())
        handle = QRectF(screen.right() - 10, screen.bottom() - 10, 20, 20)
        kind = "draw" if self.force_draw else "resize" if handle.contains(event.position()) else "move" if screen.contains(event.position()) else "draw"
        self._drag = (kind, point, region.model_copy())

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        kind, start, original = self._drag
        current = self._normalized(event.position())
        minimum_x, minimum_y = 2 / self._image.width(), 2 / self._image.height()
        if kind == "move":
            x = max(0, min(1 - original.width, original.x + current.x() - start.x()))
            y = max(0, min(1 - original.height, original.y + current.y() - start.y()))
            values = dict(x=x, y=y, width=original.width, height=original.height)
        elif kind == "resize":
            values = dict(x=original.x, y=original.y,
                          width=min(1 - original.x, max(minimum_x, current.x() - original.x)),
                          height=min(1 - original.y, max(minimum_y, current.y() - original.y)))
        else:
            x, y = min(start.x(), current.x()), min(start.y(), current.y())
            width, height = abs(current.x() - start.x()), abs(current.y() - start.y())
            if width < minimum_x or height < minimum_y:
                return
            values = dict(x=x, y=y, width=width, height=height)
        region = Region(label=original.label, **values)
        self.profile.regions[self.selected] = region
        self.region_changed.emit(self.selected, region)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            self.force_draw = False
