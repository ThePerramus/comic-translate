import os
import hashlib
import uuid
from PySide6.QtGui import QUndoCommand
from .base import PatchCommandBase, _load_patch_image_rgba
import imkit as imk

class PatchInsertCommand(QUndoCommand, PatchCommandBase):
    """
    A single command that inserts **one patch-group** (the patches created by a
    single inpaint call) and is fully undo/redo-able and serialisable.
    """
    def __init__(self, ct, patches, file_path, display=True):
        super().__init__("Insert patches")
        self.ct = ct
        self.viewer = ct.image_viewer
        self.scene = self.viewer._scene
        self.file_path = file_path     # page the patches belong to
        self.display = display

        # prepare lists of patch properties with composite hashes for deduplication
        self.properties_list = []
        for idx, patch in enumerate(patches):
            # Extract data from patch dictionary
            bbox = patch['bbox']
            patch_img = patch['image']

            # spill every image patch to a temp PNG (if not already on disk)
            sub_dir = os.path.join(ct.temp_dir,
                                   "inpaint_patches",
                                   os.path.basename(file_path))
            os.makedirs(sub_dir, exist_ok=True)
            png_path = os.path.join(sub_dir, f"patch_{uuid.uuid4().hex[:8]}_{idx}.png")
            imk.write_image(png_path, patch_img)

            # compute a composite hash of the image and its bounding box for deduplication
            with open(png_path, 'rb') as f:
                img_bytes = f.read()
            bbox_bytes = str(bbox).encode('utf-8')
            img_hash = hashlib.sha256(img_bytes + bbox_bytes).hexdigest()

            # A brand-new patch gets the next z-value in this page's stacking
            # order, so patches drawn later (e.g. a pencil touch-up on top of
            # Clean's patch) stay on top even if an older one underneath gets
            # replaced later (see PatchEraseCommand, which carries the old
            # patch's own z forward instead of assigning a fresh one).
            z_counters = getattr(ct, '_patch_z_counters', None)
            if z_counters is None:
                z_counters = {}
                ct._patch_z_counters = z_counters
            z_counters[file_path] = z_counters.get(file_path, 0) + 1
            patch_z = 0.5 + z_counters[file_path] * 0.0001

            prop = {
                'bbox': bbox,
                'png_path': png_path,
                'hash': img_hash,
                'z': patch_z
            }
            
            # Add webtoon mode information if present
            if 'scene_pos' in patch:
                prop['scene_pos'] = patch['scene_pos']
            if 'page_index' in patch:
                prop['page_index'] = patch['page_index']
            # Which tool produced this patch (e.g. 'pencil', 'reveal_pencil') -
            # missing/absent means "automatic inpaint" (Clean), the historical
            # default. auto_reveal_pages() uses this to leave manual
            # corrections alone instead of re-processing them.
            if 'kind' in patch:
                prop['kind'] = patch['kind']

            self.properties_list.append(prop)

    def _register_patches(self):
        # Ensure top-level storage exists
        patches_list = self.ct.image_patches.setdefault(self.file_path, [])
        if self.display:
            mem_list = self.ct.in_memory_patches.setdefault(self.file_path, [])

        for prop in self.properties_list:
            # skip duplicates by composite hash
            if any(p['hash'] == prop['hash'] for p in patches_list):
                continue

            # add to persistent store
            patch_entry = {
                'bbox': prop['bbox'],
                'png_path': prop['png_path'],
                'hash': prop['hash']
            }
            # Save scene position and page index for webtoon mode
            if 'scene_pos' in prop:
                patch_entry['scene_pos'] = prop['scene_pos']
            if 'page_index' in prop:
                patch_entry['page_index'] = prop['page_index']
            if 'kind' in prop:
                patch_entry['kind'] = prop['kind']
            if 'z' in prop:
                patch_entry['z'] = prop['z']
            patches_list.append(patch_entry)

            # only load into memory if being displayed
            if self.display:
                img_data = _load_patch_image_rgba(png_path=prop['png_path'])
                mem_list.append({
                    'bbox': prop['bbox'],
                    'image': img_data,
                    'hash': prop['hash']
                })

    def _unregister_patches(self):
        patches_list = self.ct.image_patches.get(self.file_path, [])
        if self.display:
            mem_list = self.ct.in_memory_patches.get(self.file_path, [])

        for prop in self.properties_list:
            patches_list[:] = [p for p in patches_list if p['hash'] != prop['hash']]
            if self.display:
                mem_list[:] = [p for p in mem_list if p['hash'] != prop['hash']]

    def _draw_pixmaps(self):
        # only draw when display=True
        if not self.display:
            return
        
        # add new patch items
        for prop in self.properties_list:
            item = self.find_matching_item(self.scene, prop)
            if item is None:
                item = self.create_patch_item(prop, self.viewer)
            if item is not None:
                self._register_with_webtoon_patch_manager(item, prop)

    def _register_with_webtoon_patch_manager(self, item, prop):
        if not getattr(self.viewer, 'webtoon_mode', False):
            return
        page_idx = prop.get('page_index')
        if page_idx is None:
            return
        manager = getattr(getattr(self.viewer, 'webtoon_manager', None), 'scene_item_manager', None)
        patch_manager = getattr(manager, 'patch_manager', None) if manager is not None else None
        if patch_manager is None:
            return
        page_items = patch_manager.loaded_patch_items.setdefault(page_idx, [])
        if item not in page_items:
            page_items.append(item)

    def _remove_pixmaps(self):
        # only remove when display=True
        if not self.display:
            return
        # remove items matching each prop
        for prop in self.properties_list:
            existing = self.find_matching_item(self.scene, prop)
            if existing:
                self.scene.removeItem(existing)

    def redo(self):
        self._register_patches()
        self._draw_pixmaps()
        self.display = True
        self._refresh_view()

    def undo(self):
        self._remove_pixmaps()
        self._unregister_patches()
        self._refresh_view()

    def _refresh_view(self):
        """See PatchEraseCommand._refresh_view() for why this is here too."""
        self.scene.update()
        views = self.scene.views()
        if views:
            views[0].viewport().update()


class PatchEraseCommand(QUndoCommand, PatchCommandBase):
    """
    Replaces one or more existing patches with an eroded (partially transparent)
    version of themselves - the "eraser for inpaint patches" tool. Each affected
    patch is swapped out for a new one with a hole punched in it, so whatever was
    underneath (an older patch, or the original image) shows through. Fully
    undo/redo-able: undo restores the untouched original patch.
    """
    def __init__(self, ct, erased, file_path):
        """erased: list of {'old_patch': <existing patch dict from image_patches>,
        'new_image': <RGBA numpy array, same bbox as old_patch>}."""
        super().__init__("Erase inpaint patch")
        self.ct = ct
        self.viewer = ct.image_viewer
        self.scene = self.viewer._scene
        self.file_path = file_path

        self.old_props = []
        self.new_props = []
        for entry in erased:
            old_patch = entry['old_patch']
            self.old_props.append(dict(old_patch))

            bbox = old_patch['bbox']
            new_image = entry['new_image']

            if not (new_image[:, :, 3] > 0).any():
                # Fully erased - nothing left of this patch, don't recreate it.
                self.new_props.append(None)
                continue

            sub_dir = os.path.join(ct.temp_dir, "inpaint_patches", os.path.basename(file_path))
            os.makedirs(sub_dir, exist_ok=True)
            png_path = os.path.join(sub_dir, f"patch_{uuid.uuid4().hex[:8]}_erased.png")
            imk.write_image(png_path, new_image)

            with open(png_path, 'rb') as f:
                img_bytes = f.read()
            img_hash = hashlib.sha256(img_bytes + str(bbox).encode('utf-8')).hexdigest()

            new_prop = {'bbox': bbox, 'png_path': png_path, 'hash': img_hash}
            if 'scene_pos' in old_patch:
                new_prop['scene_pos'] = old_patch['scene_pos']
            if 'page_index' in old_patch:
                new_prop['page_index'] = old_patch['page_index']
            # Keep the replaced patch at its original stacking position -
            # otherwise re-adding it here would make it the most-recently-
            # added same-z item and jump to the top, ahead of anything drawn
            # after it originally (see create_patch_item()'s comment).
            new_prop['z'] = old_patch.get('z', 0.5)
            if 'kind' in old_patch:
                new_prop['kind'] = old_patch['kind']
            self.new_props.append(new_prop)

    def _remove(self, prop):
        patches_list = self.ct.image_patches.get(self.file_path, [])
        mem_list = self.ct.in_memory_patches.get(self.file_path, [])
        existing = self.find_matching_item(self.scene, prop)
        if existing:
            self.scene.removeItem(existing)
        patches_list[:] = [p for p in patches_list if p['hash'] != prop['hash']]
        mem_list[:] = [p for p in mem_list if p['hash'] != prop['hash']]

    def _add(self, prop):
        patches_list = self.ct.image_patches.setdefault(self.file_path, [])
        mem_list = self.ct.in_memory_patches.setdefault(self.file_path, [])
        if not any(p['hash'] == prop['hash'] for p in patches_list):
            patches_list.append(dict(prop))
        img_data = _load_patch_image_rgba(png_path=prop['png_path'])
        mem_list.append({'bbox': prop['bbox'], 'image': img_data, 'hash': prop['hash']})
        if not self.find_matching_item(self.scene, prop):
            self.create_patch_item(prop, self.viewer)

    def redo(self):
        for old_prop, new_prop in zip(self.old_props, self.new_props):
            self._remove(old_prop)
            if new_prop is not None:
                self._add(new_prop)
        self._refresh_view()

    def undo(self):
        for old_prop, new_prop in zip(self.old_props, self.new_props):
            if new_prop is not None:
                self._remove(new_prop)
            self._add(old_prop)
        self._refresh_view()

    def _refresh_view(self):
        """Belt-and-suspenders full repaint after a remove-then-add swap.
        Qt normally tracks the dirty region for removeItem()/addItem() on its
        own, but when several overlapping patches get swapped out in one
        command (e.g. an auto-reveal replacing a Clean patch that a manual
        reveal-pencil stroke already partially overlaps), a stale partial
        repaint of the old item's vacated area is possible - it would look
        exactly like a rendering glitch (stray leftover pixels) even though
        the underlying patch data is already correct, which is consistent
        with get_image_array() (a fresh recomposite, not the paint buffer)
        never reproducing it."""
        self.scene.update()
        views = self.scene.views()
        if views:
            views[0].viewport().update()

