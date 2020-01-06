from tkinter_gui_builder.panel_templates.basic_widgets_panel import BasicWidgetsPanel
from sarpy_apps.aperture_tool.panels.image_zoomer.zoomer_dash.button_panel import ButtonPanel
from sarpy_apps.aperture_tool.panels.image_zoomer.zoomer_dash.info_panel import InfoPanel
from tkinter_gui_builder.panel_templates.file_selector import FileSelector


class ZoomerDash(BasicWidgetsPanel):
    buttons = ButtonPanel
    file_selector = FileSelector
    info_panel = InfoPanel

    def __init__(self, parent):
        BasicWidgetsPanel.__init__(self, parent)
        widget_list = ["file_selector", "buttons", "info_panel"]
        self.init_w_basic_widget_list(widget_list, 2, [1, 2])
        self.set_label_text("wake tool controls")
