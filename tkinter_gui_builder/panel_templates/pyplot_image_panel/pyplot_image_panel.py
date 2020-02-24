import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
import numpy as np


class PyplotImagePanel(tk.LabelFrame):
    def __init__(self, parent, canvas_width=600, canvas_height=400):
        tk.LabelFrame.__init__(self, parent)
        self.config(highlightbackground="black")
        self.config(highlightthickness=1)
        self.config(borderwidth=5)

        # this is a dummy placeholder for now
        self.image_data = np.zeros((200, 200))

        # default dpi is 100, so npix will be 100 times the numbers passed to figsize
        fig = plt.figure(figsize=(canvas_width/100, canvas_height/100))
        plt.imshow(self.image_data)
        self.canvas = FigureCanvasTkAgg(fig, master=self)
        self.canvas.get_tk_widget().pack()

        self.update_image(self.image_data)

        # self.canvas.get_tk_widget().pack(fill='both', expand=1)

    def update_image(self, image_data):
        self.image_data = image_data
        plt.imshow(self.image_data)
        self.canvas.draw()

