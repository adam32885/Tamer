"""A scrolling page that fits on screen must not slide down (leaving a gap at the top) on wheel, arrows or resize."""
import sys
sys.path.insert(0, sys.argv[1]); import tamer as am; import tkinter as tk
from tkinter import ttk
root = tk.Tk(); root.geometry("500x600+0+0")
sf = am.ScrollFrame(root); sf.pack(fill="both", expand=True)
rows = [ttk.Label(sf.inner, text=f"Row {i}") for i in range(5)]
for r in rows:
    r.pack(anchor="w")
root.update()
cv = sf.canvas


def wheel(delta, times=10):
    x, y = cv.winfo_rootx() + 50, cv.winfo_rooty() + 50
    for _ in range(times):
        am.ScrollFrame._on_wheel(type("E", (), {"widget": rows[0], "x_root": x, "y_root": y, "delta": delta}))
    root.update()


assert sf.inner.winfo_reqheight() < cv.winfo_height(), "short page fits"
wheel(120)
assert cv.canvasy(0) == 0, f"wheel up on a short page left a gap of {-cv.canvasy(0)}"
vsb = next(w for w in sf.winfo_children() if isinstance(w, ttk.Scrollbar))
for _ in range(10):                                       # what clicking the scrollbar's up arrow does
    root.tk.eval(f"{vsb.cget('command')} scroll -1 units")
root.update()
assert cv.canvasy(0) == 0, f"scrollbar arrow on a short page left a gap of {-cv.canvasy(0)}"

for i in range(5, 80):                                    # now a long page: scrolling works as before
    ttk.Label(sf.inner, text=f"Row {i}").pack(anchor="w")
root.update()
assert sf.inner.winfo_reqheight() > cv.winfo_height(), "long page needs scrolling"
wheel(-120)
assert cv.canvasy(0) > 0, "wheel down scrolls a long page"
wheel(120, 100)
assert cv.canvasy(0) == 0, "wheel up stops at the top"
wheel(-120, 100)
root.geometry("500x6000"); root.update()                  # window grows taller than the page
if sf.inner.winfo_reqheight() <= cv.winfo_height():
    assert cv.canvasy(0) == 0, f"after growing the window the page sits {-cv.canvasy(0)} px down"
root.destroy(); print("GUI OK")
