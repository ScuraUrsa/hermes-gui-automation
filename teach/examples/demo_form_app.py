"""Tiny desktop app used to test record -> generalize -> replay on Windows and Linux.

    python demo_form_app.py OUT.json [+X+Y] [LAYOUT.json]

Window "Hermes Demo Form" with: Name, Login, Password (masked), two checkboxes
(Newsletter, Invoice) and Save. Save writes the form to OUT.json and closes.
Tk exposes no accessibility tree, so this exercises the coordinate fallback
(offsets inside the window), which is the hardest case for replay.
If LAYOUT.json is given, the screen centre of every widget is written there
once the window is shown, so tests can play the user without hardcoding
title bar sizes.
"""

import json
import sys
import tkinter as tk


def main() -> None:
    if sys.platform.startswith("win"):
        try:  # report real pixels on scaled displays, like the recorder does
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    out = sys.argv[1]
    pos = sys.argv[2] if len(sys.argv) > 2 else "+100+100"
    root = tk.Tk()
    root.title("Hermes Demo Form")
    root.geometry("360x260" + pos)
    root.resizable(False, False)

    widgets = {}
    fields = {}
    for row, (label, show) in enumerate((("Name", ""), ("Login", ""), ("Password", "*"))):
        tk.Label(root, text=label, width=10, anchor="w").place(x=10, y=15 + row * 40)
        e = tk.Entry(root, show=show, width=24)
        e.place(x=110, y=15 + row * 40)
        fields[label.lower()] = e
        widgets[label.lower()] = e

    newsletter = tk.BooleanVar(value=False)
    invoice = tk.BooleanVar(value=False)
    widgets["newsletter"] = tk.Checkbutton(root, text="Newsletter", variable=newsletter)
    widgets["newsletter"].place(x=10, y=135)
    widgets["invoice"] = tk.Checkbutton(root, text="Invoice", variable=invoice)
    widgets["invoice"].place(x=150, y=135)

    def save() -> None:
        data = {k: e.get() for k, e in fields.items()}
        data.update(newsletter=newsletter.get(), invoice=invoice.get())
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f)
        root.destroy()

    widgets["save"] = tk.Button(root, text="Save", width=10, command=save)
    widgets["save"].place(x=130, y=190)

    def write_layout() -> None:
        if len(sys.argv) > 3:
            layout = {k: [w.winfo_rootx() + w.winfo_width() // 2, w.winfo_rooty() + w.winfo_height() // 2]
                      for k, w in widgets.items()}
            with open(sys.argv[3], "w", encoding="utf-8") as f:
                json.dump(layout, f)

    root.after(100, lambda: (root.lift(), root.focus_force()))
    root.after(700, write_layout)
    root.mainloop()


if __name__ == "__main__":
    main()
