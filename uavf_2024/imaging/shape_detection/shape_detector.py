from __future__ import annotations
import warnings
from ultralytics import YOLO
from ultralytics.engine.results import Results, Boxes
import numpy as np
from ..imaging_types import Tile, DetectionResult, img_coord_t, SHAPES
import os
from .. import profiler

CURRENT_FILE_PATH = os.path.dirname(os.path.realpath(__file__))



class ShapeDetector:
    def __init__(self, img_size):
        self.shape_model = YOLO(f"{CURRENT_FILE_PATH}/weights/v8n-best.pt")
        rand_input = np.random.rand(1, img_size, img_size, 3).astype(np.float32)
        self.shape_model.predict(list(rand_input), verbose=False)
        self.num_processed = 0
        self.cnf_matrix = {'circle' : [0.83, 0, 0, 0, 0, .01, 0, 0, 0],
                            'semicircle': [.01, .67, .28, .02, .05, .03, 0, 0, .01],
                            'quartercircle': [0, .18, .43, 0, .41, .17, 0, 0, 0],
                            'triangle': [0, .03, 0, .91, .01, 0, 0, 0, 0],
                            'rectangle': [.01, 0, .19, 0, .46, .08, 0, 0, 0],
                            'pentagon': [.10, .03, .08, 0, .01, .68, 0, 0, 0],
                            'star': [0, .01, 0, .04, 0, 0, .97, .02, 0],
                            'cross': [0, .04, 0, .01, 0, 0, 0, .96, .03],
                            'person': [0, .01, 0, .01, .01, 0, 0, 0, .91]
                                }


    @profiler
    def predict(self, tiles: tuple[Tile]) -> list[DetectionResult]:
        imgs_list = [tile.img.get_array() for tile in tiles if tile is not None]
        predictions: list[Results] = self.shape_model.predict(imgs_list, verbose=False)

        full_results = []
        for img_index, single_pred in enumerate(predictions):
            if not isinstance(single_pred.boxes, Boxes):
                warnings.warn("ShapeInstanceSegmenter.predict() could not extract Boxes from YOLO output")
                continue
        
            boxes: Boxes = single_pred.boxes
            for box, prob, cls in zip(boxes.xywh, boxes.conf, boxes.cls):
                x,y,w,h = box.int()
                x-=int(w/2) # adjust to make x,y the top left
                y-=int(h/2)
                confidences = np.zeros(9)
                confidences[cls.int()] = prob
                full_results.append(
                    DetectionResult(
                        x=img_coord_t(x.item())+tiles[img_index].x,
                        y=img_coord_t(y.item())+tiles[img_index].y,
                        width=img_coord_t(w.item()),
                        height=img_coord_t(h.item()),
                        confidences = np.array(self.cnf_matrix[SHAPES[cls.int()]]),
                        img = tiles[img_index].img.make_sub_image(x, y, w, h),
                        id = self.num_processed
                    )
                )
                self.num_processed += 1
            return full_results
