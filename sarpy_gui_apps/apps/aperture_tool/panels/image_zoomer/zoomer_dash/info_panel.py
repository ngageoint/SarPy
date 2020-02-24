from tkinter_gui_builder.panel_templates.widget_panel.widget_panel import AbstractWidgetPanel
from tkinter_gui_builder.widgets import basic_widgets


class InfoPanel(AbstractWidgetPanel):
    def __init__(self, parent):
        AbstractWidgetPanel.__init__(self, parent)
        self.decimation_label = basic_widgets.Label
        self.decimation_val = basic_widgets.Entry

        widget_list = ["decimation_label", "decimation_val"]

        self.init_w_box_layout(widget_list, n_columns=2, column_widths=[20, 10])
        self.set_label_text("info panel")

        self.decimation_label.config(text="decimation")
        self.decimation_val.config(state='disabled')
