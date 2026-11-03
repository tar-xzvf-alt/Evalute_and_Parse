import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform == "win32", "Display required")
class CollectionUITests(unittest.TestCase):
    def test_startup_profile_and_year_invalidation(self):
        import customtkinter as ctk
        from tkinter import font
        from collection_ui import CollectionPanel
        from ui_theme import prepare_theme, configure_typography
        from vk_collection import save_profile

        prepare_theme()
        root = ctk.CTk()
        try:
            root.geometry("1100x800")
            family, rasterizer = configure_typography(root)
            self.assertEqual(ctk.DrawEngine.preferred_drawing_method, "polygon_shapes")
            self.assertNotEqual(family.casefold(), "fixed")
            panel = CollectionPanel(root, lambda: "", family)
            panel.pack(fill="both", expand=True)
            root.update()
            self.assertGreater(panel.table.winfo_height(), 200)
            settings = panel.settings()
            self.assertEqual(settings["year"], "2020")
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "profile.json"
                save_profile(path, settings, [{"id": 1, "name": "Новости", "selected": True}])
                with patch("collection_ui.filedialog.askopenfilename", return_value=str(path)):
                    panel.load()
                self.assertEqual(panel.rows[0]["id"], 1)
                self.assertTrue(panel.rows[0]["selected"])
                self.assertEqual(panel.mode.get(), "Вручную")
                panel.rows[0].update(count=50, year="2019", months=[1]*12)
                panel.refresh()
                values = panel.table.item("1", "values")
                self.assertEqual(values[2], "—")
                self.assertEqual(values[3], "—")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
