import os

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QFontDatabase
import imkit as imk

from .constants import user_font_path
from app.path_materialization import ensure_path_materialized


class ToolStateMixin:
    def toggle_pan_tool(self):
        if self.pan_button.isChecked():
            self.set_tool("pan")
        else:
            self.set_tool(None)

    def toggle_box_tool(self):
        if self.box_button.isChecked():
            self.set_tool("box")
        else:
            self.set_tool(None)

    def toggle_brush_tool(self):
        if self.brush_button.isChecked():
            self.set_tool("brush")
            size = self.image_viewer.brush_size
            self.set_slider_size(size)
        else:
            self.set_tool(None)

    def toggle_eraser_tool(self):
        if self.eraser_button.isChecked():
            self.set_tool("eraser")
            size = self.image_viewer.eraser_size
            self.set_slider_size(size)
        else:
            self.set_tool(None)

    def toggle_eyedropper_tool(self):
        if self.eyedropper_button.isChecked():
            self.set_tool("eyedropper")
        else:
            self.set_tool(None)

    def toggle_pencil_tool(self):
        if self.pencil_button.isChecked():
            self.set_tool("pencil")
            size = self.image_viewer.drawing_manager.pencil_size
            self.set_slider_size(size)
        else:
            self.set_tool(None)

    def toggle_patch_eraser_tool(self):
        if self.patch_eraser_button.isChecked():
            self.set_tool("patch_eraser")
            size = self.image_viewer.drawing_manager.patch_eraser_size
            self.set_slider_size(size)
        else:
            self.set_tool(None)

    def on_color_picked(self):
        """Called after the eyedropper samples a color: switch straight to the pencil."""
        self.set_tool("pencil")
        size = self.image_viewer.drawing_manager.pencil_size
        self.set_slider_size(size)

    def load_reference_book(self):
        """Load a whole second edition (cbz/cbr/pdf/...) of the same comic, so its
        pages can be auto-paired with this book's pages by index + an offset,
        instead of picking a reference image one page at a time."""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, self.tr("Select Reference Book"), os.path.expanduser("~"),
            self.tr("Comic Archives") + " (*.cbr *.cbz *.cbt *.cb7 *.zip *.rar *.7z *.tar *.pdf *.epub)"
        )
        if not path:
            return
        self.reference_book_handler.prepare_files([path])
        # Any alignment confirmed so far paired pages using the *previous*
        # book/offsets, which is now meaningless - drop it so the next "load
        # reference" click re-resolves fresh instead of silently reusing a
        # stale (likely wrong) reference image.
        self.reference_images.clear()
        self.reference_page_offsets = []
        self._update_reference_offset_label()

    def _effective_reference_offset(self, hq_index: int) -> int:
        """Offsets are set per-breakpoint ("from this page onward"), not a
        single global number, so a divider/insert page partway through the
        reference book can be corrected without breaking pairing for every
        page before it. Returns the value of the last breakpoint at or before
        hq_index, or 0 if none has been set yet."""
        offset = 0
        for start_index, value in self.reference_page_offsets:
            if start_index <= hq_index:
                offset = value
            else:
                break
        return offset

    def set_reference_page_offset(self, value: int):
        """Sets the offset starting at the current page and onward, until the
        next breakpoint (if any). Pages before the current one are untouched."""
        index = self.curr_img_idx
        if self._effective_reference_offset(index) == value and not any(
                start == index for start, _ in self.reference_page_offsets):
            return  # no-op: matches what would already apply here, not a real edit

        self.reference_page_offsets = [
            (start, v) for start, v in self.reference_page_offsets if start != index
        ]
        self.reference_page_offsets.append((index, value))
        self.reference_page_offsets.sort(key=lambda pair: pair[0])

        # Only pages from here onward could have had their effective offset
        # change because of this edit.
        for path in self.image_files[index:]:
            self.reference_images.pop(path, None)

        self._update_reference_offset_label()

    def _update_reference_offset_label(self):
        paths = self.reference_book_handler.file_paths
        offset = self._effective_reference_offset(self.curr_img_idx)
        self.reference_offset_spin.blockSignals(True)
        self.reference_offset_spin.setValue(offset)
        self.reference_offset_spin.blockSignals(False)

        if not paths:
            self.reference_offset_label.setText(self.tr("No reference book loaded"))
            self._set_reference_preview(None)
            return
        index = self.curr_img_idx + offset
        if 0 <= index < len(paths):
            ref_path = paths[index]
            name = os.path.basename(ref_path)
            self.reference_offset_label.setText(
                self.tr("Reference page {0}/{1}: {2} (offset {3})").format(
                    index + 1, len(paths), name, offset))
            self._set_reference_preview(ref_path)
        else:
            self.reference_offset_label.setText(self.tr("Reference page out of range for this offset"))
            self._set_reference_preview(None)

    def _set_reference_preview(self, ref_path: str | None):
        """Small thumbnail of the reference page currently paired with the page
        you're on, so tuning the offset doesn't require opening the reference
        book separately to count pages."""
        if not ref_path:
            self.reference_preview_label.clear()
            self.reference_preview_label.setText(self.tr("(no preview)"))
            return
        try:
            ensure_path_materialized(ref_path)
            img = imk.read_image(ref_path)
            if img is None:
                raise ValueError("could not read reference image")
            h, w = img.shape[:2]
            qimage = QtGui.QImage(img.data, w, h, img.strides[0],
                                   QtGui.QImage.Format.Format_RGB888).copy()
            pixmap = QtGui.QPixmap.fromImage(qimage).scaledToWidth(
                140, QtCore.Qt.TransformationMode.SmoothTransformation)
            self.reference_preview_label.setPixmap(pixmap)
        except Exception:
            self.reference_preview_label.clear()
            self.reference_preview_label.setText(self.tr("(preview unavailable)"))

    def _resolve_reference_book_page(self) -> str | None:
        """The reference-book page paired with the currently displayed page,
        per the configured offset, or None if no book is loaded / out of range."""
        paths = self.reference_book_handler.file_paths
        if not paths or not self.image_files:
            return None
        index = self.curr_img_idx + self._effective_reference_offset(self.curr_img_idx)
        if index < 0 or index >= len(paths):
            return None
        ref_path = paths[index]
        ensure_path_materialized(ref_path)
        return ref_path

    def _sync_reference_alignment_buttons(self):
        """Navigating pages silently cancels any in-progress alignment (see
        ImageViewer.clear_scene), but that left the toggle button showing
        "checked" with nothing actually on screen - so the next click just
        turned the (already-gone) overlay off instead of loading anything,
        and it took a second click to get it to reappear. Keep the button's
        checked state (and the confirm button's enabled state) truthful."""
        active = self.image_viewer.reference_manager.active
        self.load_reference_button.blockSignals(True)
        self.load_reference_button.setChecked(active)
        self.load_reference_button.blockSignals(False)
        self.confirm_reference_button.setEnabled(active)

    def toggle_reference_alignment(self):
        """Overlay a second scan of the current page (semi-transparent, 4 draggable
        corners) so its art can be dragged into alignment with this page's own."""
        if self.load_reference_button.isChecked():
            if not self.image_viewer.hasPhoto() or not self.image_files:
                self.load_reference_button.setChecked(False)
                return

            file_path = self.image_files[self.curr_img_idx]
            existing = self.reference_images.get(file_path)
            saved_corners = existing.get('corners') if existing else None
            ref_path = existing.get('ref_path') if existing else None

            if not ref_path:
                ref_path = self._resolve_reference_book_page()

            if not ref_path:
                ref_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                    self, self.tr("Select Reference Page Image"), os.path.expanduser("~"),
                    self.tr("Images") + " (*.png *.jpg *.jpeg *.bmp *.webp)"
                )
                if not ref_path:
                    self.load_reference_button.setChecked(False)
                    return
                saved_corners = None

            started = self.image_viewer.reference_manager.start(file_path, ref_path, saved_corners)
            if not started:
                self.load_reference_button.setChecked(False)
                return

            self.image_viewer.reference_manager.set_opacity(self.reference_opacity_slider.value() / 100.0)
            self.set_tool("align_reference")
            self.confirm_reference_button.setEnabled(True)
        else:
            self.image_viewer.reference_manager.cancel()
            self.set_tool(None)
            self.confirm_reference_button.setEnabled(False)

    def confirm_reference_alignment(self):
        result = self.image_viewer.reference_manager.confirm()
        if result is None:
            return
        file_path, ref_path, corners, warped = result
        self.reference_images[file_path] = {
            'ref_path': ref_path,
            'corners': corners,
            'warped': warped,
        }
        self.load_reference_button.setChecked(False)
        self.confirm_reference_button.setEnabled(False)
        self.set_tool(None)

    def set_reference_opacity(self, value: int):
        self.image_viewer.reference_manager.set_opacity(value / 100.0)

    def set_slider_size(self, size: int):
        self.brush_eraser_slider.blockSignals(True)
        self.brush_eraser_slider.setValue(size)
        self.brush_eraser_slider.blockSignals(False)

    def set_tool(self, tool_name: str):
        self.image_viewer.unsetCursor()
        self.image_viewer.set_tool(tool_name)

        for name, button in self.tool_buttons.items():
            if name != tool_name:
                button.setChecked(False)
            elif tool_name is not None:
                button.setChecked(True)

        if not tool_name:
            for button in self.tool_buttons.values():
                button.setChecked(False)
            self.image_viewer.setDragMode(QtWidgets.QGraphicsView.DragMode.NoDrag)

    def set_brush_eraser_size(self, size: int):
        try:
            current_tool = self.image_viewer.current_tool
        except Exception:
            current_tool = None

        if current_tool == "brush":
            self.image_viewer.brush_size = size
        elif current_tool == "eraser":
            self.image_viewer.eraser_size = size
        elif current_tool == "pencil":
            self.image_viewer.drawing_manager.set_pencil_size(size, size)
        elif current_tool == "patch_eraser":
            self.image_viewer.drawing_manager.set_patch_eraser_size(size, size)
        else:
            self.image_viewer.brush_size = size
            self.image_viewer.eraser_size = size
            self.image_viewer.drawing_manager.set_pencil_size(size, size)
            self.image_viewer.drawing_manager.set_patch_eraser_size(size, size)

        if self.image_viewer.hasPhoto():
            image = self.image_viewer.get_image_array()
            if image is not None:
                h, w = image.shape[:2]
                scaled_size = self.scale_size(size, w, h)

                if current_tool in {"brush", "eraser", "pencil", "patch_eraser"}:
                    self.image_viewer.set_br_er_size(size, scaled_size)
                else:
                    self.image_viewer.drawing_manager.set_brush_size(size, scaled_size)
                    self.image_viewer.drawing_manager.set_eraser_size(size, scaled_size)
                    self.image_viewer.drawing_manager.set_pencil_size(size, scaled_size)
                    self.image_viewer.drawing_manager.set_patch_eraser_size(size, scaled_size)

    def scale_size(self, base_size, image_width, image_height):
        image_diagonal = (image_width**2 + image_height**2) ** 0.5
        reference_diagonal = 1000
        scaling_factor = image_diagonal / reference_diagonal
        scaled_size = base_size * scaling_factor
        return scaled_size

    def _ensure_custom_font_caches(self) -> None:
        if not hasattr(self, "_custom_font_path_to_family"):
            self._custom_font_path_to_family = {}
        if not hasattr(self, "_custom_font_family_cache"):
            self._custom_font_family_cache = {}
        if not hasattr(self, "_custom_font_miss_cache"):
            self._custom_font_miss_cache = set()

    def _load_custom_font_file(self, font_path: str) -> str | None:
        self._ensure_custom_font_caches()
        if not font_path or not os.path.isfile(font_path):
            return None

        font_path = os.path.normpath(font_path)
        if font_path in self._custom_font_path_to_family:
            return self._custom_font_path_to_family[font_path]

        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id == -1:
            return None

        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            return None

        primary = families[0]
        self._custom_font_path_to_family[font_path] = primary
        for family in families:
            self._custom_font_family_cache[family.casefold()] = family
        return primary

    def ensure_custom_font_loaded(self, font_input: str) -> str:
        if not isinstance(font_input, str):
            return font_input

        requested = font_input.strip()
        if not requested:
            return requested

        self._ensure_custom_font_caches()
        lower = requested.casefold()
        if lower in self._custom_font_family_cache:
            return self._custom_font_family_cache[lower]
        if lower in self._custom_font_miss_cache:
            return requested

        ext = os.path.splitext(requested)[1].lower()
        if ext in [".ttf", ".ttc", ".otf", ".woff", ".woff2"]:
            loaded = self._load_custom_font_file(requested)
            return loaded or requested

        for family in QFontDatabase().families():
            if family.casefold() == lower:
                self._custom_font_family_cache[lower] = family
                return family

        if os.path.isdir(user_font_path):
            for name in os.listdir(user_font_path):
                if os.path.splitext(name)[1].lower() not in [".ttf", ".ttc", ".otf", ".woff", ".woff2"]:
                    continue
                path = os.path.join(user_font_path, name)
                loaded = self._load_custom_font_file(path)
                if loaded and loaded.casefold() == lower:
                    return loaded

        self._custom_font_miss_cache.add(lower)
        return requested

    def get_font_family(self, font_input: str) -> str:
        return self.ensure_custom_font_loaded(font_input)

    def add_custom_font(self, font_input: str):
        if os.path.splitext(font_input)[1].lower() in [".ttf", ".ttc", ".otf", ".woff", ".woff2"]:
            self._load_custom_font_file(font_input)

    def get_color(self):
        default_color = QtGui.QColor("#000000")
        color_dialog = QtWidgets.QColorDialog()
        color_dialog.setCurrentColor(default_color)
        if color_dialog.exec() == QtWidgets.QDialog.Accepted:
            return color_dialog.selectedColor()

    def set_font(self, font_family: str):
        resolved_family = self.ensure_custom_font_loaded(font_family)
        self.font_dropdown.setCurrentFont(QtGui.QFont(resolved_family))
        if self.font_dropdown.currentText() != resolved_family:
            self.font_dropdown.setCurrentText(resolved_family)
