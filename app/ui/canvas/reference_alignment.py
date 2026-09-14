"""Manual page-to-page alignment for the "reveal from a reference scan" workflow:
overlay a second (often lower-quality) scan of the same page semi-transparently,
let the user drag its 4 corners until it visually lines up with the page's own
artwork, then bake that into a warped copy of the reference in the page's own
coordinate space - later tools sample pixels from that baked copy to "reveal"
it (e.g. its untranslated text) through holes punched in the cleaned page above.
"""

import numpy as np
from PySide6 import QtGui
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QBrush, QPolygonF, QTransform
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPixmapItem

import imkit as imk

HANDLE_RADIUS = 9


class CornerHandle(QGraphicsEllipseItem):
    """A small draggable circle marking one corner of the reference-image quad."""

    def __init__(self, index: int):
        super().__init__(-HANDLE_RADIUS, -HANDLE_RADIUS, HANDLE_RADIUS * 2, HANDLE_RADIUS * 2)
        self.index = index
        self.setZValue(1001)
        self.set_selected(False)

    def set_selected(self, selected: bool):
        """Visually marks whether this is the handle arrow-key nudges apply
        to - there's no separate "click to select without dragging" gesture,
        so this is the only way to see which one is currently targeted."""
        if selected:
            self.setBrush(QBrush(QColor(80, 220, 255, 230)))
            pen = QPen(QColor(0, 0, 0, 230), 3)
        else:
            self.setBrush(QBrush(QColor(255, 200, 0, 220)))
            pen = QPen(QColor(0, 0, 0, 220), 2)
        pen.setCosmetic(True)
        self.setPen(pen)


class ReferenceAlignmentManager:
    """Owns the live drag-to-align session: the semi-transparent overlay pixmap
    and its 4 corner handles. Nothing here is persisted - callers read the
    result out of confirm() and decide what to do with it."""

    def __init__(self, viewer):
        self.viewer = viewer
        self._scene = viewer._scene

        self.active_file_path: str | None = None
        self.ref_path: str | None = None
        self.ref_image: np.ndarray | None = None  # RGB, untouched reference pixels
        self.overlay_item: QGraphicsPixmapItem | None = None
        self.handles: list[CornerHandle] = []
        self.corners: list[QPointF] = []
        self.opacity: float = 0.5
        self.dragging_index: int | None = None
        # The handle arrow-key nudges apply to - set the moment a corner is
        # dragged, and stays targeted (even after releasing) until a
        # different one is dragged, so a rough mouse drag can be followed by
        # fine keyboard adjustment without needing a separate "select" click.
        self.selected_corner_index: int | None = None
        self._original_scene_rect: QRectF | None = None

    @property
    def active(self) -> bool:
        return self.overlay_item is not None

    def start(self, file_path: str, ref_path: str, saved_corners=None) -> bool:
        """Begin (or resume) alignment for `file_path` using the image at `ref_path`."""
        self.cancel()

        ref_image = imk.read_image(ref_path)
        if ref_image is None or not self.viewer.hasPhoto():
            return False

        self.active_file_path = file_path
        self.ref_path = ref_path
        self.ref_image = ref_image
        rh, rw = ref_image.shape[:2]

        page_rect = self.viewer.photo.boundingRect()
        page_w, page_h = page_rect.width(), page_rect.height()

        if saved_corners:
            corners = [QPointF(x, y) for x, y in saved_corners]
        else:
            # Default: stretch the reference to cover the whole page; the user
            # drags corners inward/outward from there to match the real art.
            corners = [QPointF(0, 0), QPointF(page_w, 0), QPointF(page_w, page_h), QPointF(0, page_h)]
        self.corners = corners
        self._original_scene_rect = self.viewer.sceneRect()

        qimage = QtGui.QImage(ref_image.data, rw, rh, ref_image.strides[0],
                               QtGui.QImage.Format.Format_RGB888).copy()
        pixmap = QtGui.QPixmap.fromImage(qimage)
        self.overlay_item = QGraphicsPixmapItem(pixmap)
        self.overlay_item.setZValue(999)  # above patches/art, below the drag handles
        self.overlay_item.setOpacity(self.opacity)
        self.overlay_item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self.overlay_item)

        self.handles = []
        for i, pt in enumerate(corners):
            handle = CornerHandle(i)
            handle.setPos(pt)
            self._scene.addItem(handle)
            self.handles.append(handle)
        self.selected_corner_index = 0
        self.handles[0].set_selected(True)

        self._apply_transform()
        self._update_scene_rect()
        return True

    def cancel(self):
        """Discard the in-progress overlay/handles without saving anything."""
        if self.overlay_item is not None:
            self._scene.removeItem(self.overlay_item)
            self.overlay_item = None
        for handle in self.handles:
            self._scene.removeItem(handle)
        self.handles = []
        self.corners = []
        self.active_file_path = None
        self.ref_path = None
        self.ref_image = None
        self.dragging_index = None
        self.selected_corner_index = None
        # Restore the normal page-only scrollable area (see _update_scene_rect).
        if self._original_scene_rect is not None:
            self.viewer.setSceneRect(self._original_scene_rect)
            self._original_scene_rect = None

    def set_opacity(self, value: float):
        self.opacity = value
        if self.overlay_item is not None:
            self.overlay_item.setOpacity(value)

    def hit_test(self, scene_pos: QPointF) -> int | None:
        for handle in self.handles:
            if handle.contains(handle.mapFromScene(scene_pos)):
                return handle.index
        return None

    def begin_drag(self, index: int):
        self.dragging_index = index
        if self.selected_corner_index != index:
            if self.selected_corner_index is not None:
                self.handles[self.selected_corner_index].set_selected(False)
            self.selected_corner_index = index
            self.handles[index].set_selected(True)

    def drag_to(self, scene_pos: QPointF):
        if self.dragging_index is None:
            return
        self.corners[self.dragging_index] = scene_pos
        self.handles[self.dragging_index].setPos(scene_pos)
        self._apply_transform()
        self._update_scene_rect()

    def end_drag(self):
        self.dragging_index = None

    def nudge_selected_corner(self, dx: float, dy: float) -> bool:
        """Moves the currently selected corner handle by (dx, dy) - for fine
        keyboard adjustment where a mouse drag is too coarse. A corner becomes
        selected the moment you start dragging it and stays selected (even
        after releasing) until a different one is dragged."""
        if self.selected_corner_index is None or not self.active:
            return False
        idx = self.selected_corner_index
        pt = self.corners[idx]
        new_pt = QPointF(pt.x() + dx, pt.y() + dy)
        self.corners[idx] = new_pt
        self.handles[idx].setPos(new_pt)
        self._apply_transform()
        self._update_scene_rect()
        return True

    def _update_scene_rect(self):
        """A corner dragged outside the page is otherwise unreachable: QGraphicsView
        clamps scrolling to sceneRect, so content past its edges can't be scrolled
        into view no matter how far you drag. Grow the scene rect to always cover
        wherever the handles currently are (plus margin), so panning/zooming can
        still reach them; restored to the page-only rect in cancel()."""
        if self._original_scene_rect is None:
            return
        bounds = QRectF(self._original_scene_rect)
        margin = max(self._original_scene_rect.width(), self._original_scene_rect.height()) * 0.5
        for pt in self.corners:
            bounds = bounds.united(QRectF(pt.x() - margin, pt.y() - margin, margin * 2, margin * 2))
        self.viewer.setSceneRect(bounds)

    def _apply_transform(self):
        """Live preview only: map the reference pixmap's own rectangle onto the
        dragged quad using a cheap Qt-native projective transform, so dragging
        feels instant without re-warping the actual pixel array each move."""
        if self.overlay_item is None:
            return
        rect = self.overlay_item.pixmap().rect()
        src = QPolygonF([QPointF(0, 0), QPointF(rect.width(), 0),
                          QPointF(rect.width(), rect.height()), QPointF(0, rect.height())])
        dst = QPolygonF(self.corners)
        transform = QTransform()
        if QTransform.quadToQuad(src, dst, transform):
            self.overlay_item.setTransform(transform)

    def confirm(self):
        """Bake the final warp. Returns (file_path, ref_path, corners, warped_rgb_array)
        or None on failure; the caller owns persisting/caching the result."""
        if self.overlay_item is None or self.ref_image is None:
            return None

        rh, rw = self.ref_image.shape[:2]
        src = np.array([[0, 0], [rw, 0], [rw, rh], [0, rh]], dtype=np.float64)
        dst = np.array([[p.x(), p.y()] for p in self.corners], dtype=np.float64)

        page_rect = self.viewer.photo.boundingRect()
        out_w, out_h = int(round(page_rect.width())), int(round(page_rect.height()))

        try:
            matrix = imk.get_perspective_transform(src, dst)
            warped = imk.warp_perspective(self.ref_image, matrix, (out_w, out_h))
        except Exception:
            return None

        file_path = self.active_file_path
        ref_path = self.ref_path
        corners = [[p.x(), p.y()] for p in self.corners]
        self.cancel()
        return file_path, ref_path, corners, warped
