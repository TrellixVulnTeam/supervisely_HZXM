import numpy as np
from typing import Optional, List


class PredictionMask:
    def __init__(
        self, class_name: str, mask: np.ndarray, score: Optional[float] = None
    ):
        self.class_name = class_name
        self.mask = mask
        self.score = score

class PredictionBBox:
    def __init__(self, class_name: str, bbox_tlbr: List[int], score: Optional[float]):
        self.class_name = class_name
        self.bbox_tlbr = bbox_tlbr
        self.score = score