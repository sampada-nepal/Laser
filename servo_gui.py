"""Two-servo desktop controller for the companion Arduino sketch."""

import tkinter as tk
from tkinter import messagebox, ttk

import serial
from serial.tools import list_ports


class ServoController(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Two Servo Controller")
        self.resizable(False, False)
        self.port = None
        self.pending = {}
        self.port_name = tk.StringVar()
        self.status = tk.StringVar(value="Disconnected")
        self.angles = [tk.IntVar(value=90), tk.IntVar(value=90)]
        self.sliders = []

        frame = ttk.Frame(self, padding=20)
        frame.grid()
        ttk.Label(frame, text="Serial port").grid(row=0, column=0, sticky="w")
        self.ports = ttk.Combobox(frame, textvariable=self.port_name, width=26, state="readonly")
        self.ports.grid(row=0, column=1, padx=(10, 6))
        ttk.Button(frame, text="Refresh", command=self.refresh_ports).grid(row=0, column=2)
        self.connect_button = ttk.Button(frame, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=1, column=1, pady=(10, 20))

        for index, label in enumerate(("Servo 1", "Servo 2")):
            row = index + 2
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w")
            slider = ttk.Scale(
                frame, from_=0, to=180, length=260,
                command=lambda value, i=index: self.set_angle(i, value),
            )
            slider.set(90)
            slider.grid(row=row, column=1, padx=10, pady=8)
            self.sliders.append(slider)
            ttk.Label(frame, textvariable=self.angles[index], width=4).grid(row=row, column=2)

        ttk.Button(frame, text="Center both (90°)", command=self.center).grid(
            row=4, column=1, pady=(14, 8)
        )
        ttk.Label(frame, textvariable=self.status).grid(row=5, column=0, columnspan=3)
        self.refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self.close)

    def refresh_ports(self):
        names = [port.device for port in list_ports.comports()]
        self.ports["values"] = names
        if self.port_name.get() not in names:
            self.port_name.set(next((name for name in names if "usb" in name.lower()), names[0] if names else ""))

    def toggle_connection(self):
        if self.port:
            self.port.close()
            self.port = None
            self.connect_button.configure(text="Connect")
            self.status.set("Disconnected")
            return
        if not self.port_name.get():
            messagebox.showerror("No port", "Connect the Arduino and click Refresh.")
            return
        try:
            self.port = serial.Serial(self.port_name.get(), 115200, timeout=0, write_timeout=1)
            self.connect_button.configure(text="Disconnect")
            self.status.set(f"Connected to {self.port_name.get()}")
            for index, angle in enumerate(self.angles):
                self.send(index, angle.get())
        except serial.SerialException as exc:
            self.port = None
            messagebox.showerror("Connection failed", str(exc))

    def set_angle(self, index, value):
        angle = round(float(value))
        self.angles[index].set(angle)
        if index in self.pending:
            self.after_cancel(self.pending[index])
        self.pending[index] = self.after(40, lambda: self.send(index, angle))

    def send(self, index, angle):
        self.pending.pop(index, None)
        if not self.port:
            return
        try:
            self.port.write(f"{index + 1},{angle}\n".encode("ascii"))
        except serial.SerialException as exc:
            self.port.close()
            self.port = None
            self.connect_button.configure(text="Connect")
            self.status.set(f"Disconnected: {exc}")

    def center(self):
        for slider in self.sliders:
            slider.set(90)

    def close(self):
        if self.port:
            self.port.close()
        self.destroy()


if __name__ == "__main__":
    ServoController().mainloop()
