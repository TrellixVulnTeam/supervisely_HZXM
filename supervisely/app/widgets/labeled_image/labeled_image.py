import copy
import uuid

from supervisely.annotation.annotation import Annotation
from supervisely.app import DataJson
from supervisely.app.widgets import Widget
from supervisely.app.widgets import GridGallery


class LabeledImage(GridGallery):
    def __init__(
        self,
        annotations_opacity: float = 0.5,
        show_opacity_slider: bool = True,
        enable_zoom: bool = False,
        resize_on_zoom: bool = False,
        fill_rectangle: bool = True,
        border_width: int = 3,
        widget_id: str = None,
    ):
        self._image_id = None
        super().__init__(
            columns_number=1,
            annotations_opacity=annotations_opacity,
            show_opacity_slider=show_opacity_slider,
            enable_zoom=enable_zoom,
            resize_on_zoom=resize_on_zoom,
            fill_rectangle=fill_rectangle,
            border_width=border_width,
            widget_id=widget_id,
        )

    def set(self, title, image_url, ann: Annotation = None, image_id=None):
        self.clean_up()
        self.append(image_url=image_url, annotation=ann, title=title)
        self._image_id = image_id
        DataJson().send_changes()

    def clean_up(self):
        super().clean_up()
        self._image_id = None

    def is_empty(self):
        return len(self._data) == 0

    @property
    def id(self):
        return self._image_id
