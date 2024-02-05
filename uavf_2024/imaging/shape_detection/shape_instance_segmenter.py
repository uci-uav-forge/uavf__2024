from __future__ import annotations
import warnings
from ultralytics import YOLO
from ultralytics.engine.results import Results, Boxes
import numpy as np
from ..imaging_types import Tile, InstanceSegmentationResult, img_coord_t
import os
from .. import profiler

CURRENT_FILE_PATH = os.path.dirname(os.path.realpath(__file__))

class ShapeInstanceSegmenter:
    def __init__(self, img_size):
        self.shape_model = YOLO(f"{CURRENT_FILE_PATH}/weights/seg-v8n-best.pt")
        rand_input = np.random.rand(1, img_size, img_size, 3).astype(np.float32)
        self.shape_model.predict(list(rand_input), verbose=False)
        self.num_processed = 0


    @profiler
    def predict(self, tiles: tuple[Tile]) -> list[InstanceSegmentationResult]:
        imgs_list = [tile.img.get_array() for tile in tiles if tile is not None]
        predictions: list[Results] = self.shape_model.predict(imgs_list, verbose=False)

        full_results = []
        for img_index, single_pred in enumerate(predictions):
            masks = single_pred.masks
            if masks is None:
                warnings.warn("ShapeInstanceSegmenter.predict() could not extract masks from YOLO output")
                continue
        
            if not isinstance(single_pred.boxes, Boxes):
                warnings.warn("ShapeInstanceSegmenter.predict() could not extract Boxes from YOLO output")
                continue
        
            boxes: Boxes = single_pred.boxes
            for box, mask, prob, cls in zip(boxes.xywh, masks.data, boxes.conf, boxes.cls):
                x,y,w,h = box.int()
                x-=int(w/2) # adjust to make x,y the top left
                y-=int(h/2)
                confidences = np.ones(9) * (1-prob.item())/8
                confidences[cls.int()] = prob
                full_results.append(
                    InstanceSegmentationResult(
                        x=img_coord_t(x.item())+tiles[img_index].x,
                        y=img_coord_t(y.item())+tiles[img_index].y,
                        width=img_coord_t(w.item()),
                        height=img_coord_t(h.item()),
                        confidences = confidences,
                        mask = mask[y:y+h, x:x+w].unsqueeze(2).cpu().numpy(),
                        img = tiles[img_index].img.make_sub_image(x, y, w, h),
                        id = self.num_processed
                    )
                )
                self.num_processed += 1
            return full_results
