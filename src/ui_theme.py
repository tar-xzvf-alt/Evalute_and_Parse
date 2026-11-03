"""Readable, BaseALT-inspired palette; no logos or brand affiliation implied."""

import sys
from tkinter import font, ttk

import customtkinter as ctk

BG = "#F4F5F7"
SURFACE = "#FFFFFF"
TEXT = "#20242B"
MUTED = "#59616D"
BORDER = "#D5DAE0"
ORANGE = "#F58220"
ORANGE_HOVER = "#E8720E"
PALE_ORANGE = "#FFF0E2"


def prepare_theme():
    """Run before creating widgets. Polygons do not depend on a shape font."""
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    ctk.DrawEngine.preferred_drawing_method = "polygon_shapes"
    theme = ctk.ThemeManager.theme
    changes = {
        "CTk": {"fg_color": BG},
        "CTkToplevel": {"fg_color": BG},
        "CTkFrame": {"fg_color": SURFACE, "top_fg_color": SURFACE,
                     "border_color": BORDER, "corner_radius": 8},
        "CTkLabel": {"text_color": TEXT},
        "CTkButton": {"fg_color": ORANGE, "hover_color": ORANGE_HOVER,
                      "text_color": TEXT, "text_color_disabled": "#79818D",
                      "border_color": BORDER, "corner_radius": 6, "border_width": 0},
        "CTkEntry": {"fg_color": SURFACE, "border_color": BORDER,
                     "text_color": TEXT, "placeholder_text_color": MUTED,
                     "border_width": 1, "corner_radius": 5},
        "CTkSegmentedButton": {"fg_color": "#E8EBEF", "selected_color": ORANGE,
                               "selected_hover_color": ORANGE_HOVER,
                               "unselected_color": "#E8EBEF", "unselected_hover_color": "#DDE2E8",
                               "text_color": TEXT, "corner_radius": 5},
        "CTkProgressBar": {"fg_color": "#E1E5EA", "progress_color": ORANGE,
                           "border_color": BORDER, "corner_radius": 3},
        "CTkCheckBox": {"fg_color": ORANGE, "hover_color": ORANGE_HOVER,
                        "checkmark_color": TEXT, "text_color": TEXT, "border_color": MUTED},
        "CTkScrollbar": {"button_color": "#BCC3CC", "button_hover_color": "#8D97A4"},
    }
    for widget, values in changes.items():
        theme[widget].update(values)


def configure_typography(root):
    available = {name.casefold(): name for name in font.families(root)}
    preferred = (["Segoe UI", "DejaVu Sans"] if sys.platform == "win32" else
                 ["Helvetica", "DejaVu Sans"] if sys.platform == "darwin" else
                 ["Noto Sans", "DejaVu Sans", "Liberation Sans"])
    family = next((available[name.casefold()] for name in preferred if name.casefold() in available),
                  font.nametofont("TkDefaultFont", root=root).actual("family"))
    ctk.ThemeManager.theme["CTkFont"].update(family=family, size=18)
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        font.nametofont(name, root=root).configure(family=family, size=-18)
    root.option_add("*Font", (family, -18))
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    style.configure("VK.Treeview", font=(family, -18), rowheight=36,
                    background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                    borderwidth=0, relief="flat")
    style.configure("VK.Treeview.Heading", font=(family, -17, "bold"),
                    background="#EAEDF1", foreground=TEXT, padding=(10, 10),
                    relief="flat", borderwidth=0)
    style.map("VK.Treeview", background=[("selected", PALE_ORANGE)],
              foreground=[("selected", TEXT)])
    style.map("VK.Treeview.Heading", background=[("active", "#E0E5EB")])
    for orientation in ("Vertical", "Horizontal"):
        style.configure(f"{orientation}.TScrollbar", background="#C6CDD6", troughcolor=BG,
                        bordercolor=BG, arrowcolor=MUTED, lightcolor=BG, darkcolor=BG)
    try:
        rasterizer = root.tk.call("::tk::pkgconfig", "get", "fontsystem")
    except Exception:
        rasterizer = "unknown"
    return family, rasterizer


def secondary(button):
    button.configure(fg_color=SURFACE, hover_color="#EDF0F4", text_color=TEXT,
                     border_color=BORDER, border_width=1)
