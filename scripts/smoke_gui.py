"""Build-time/offscreen GUI smoke test. Does not open any hardware."""
import os
from pathlib import Path
import sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtDBus import QDBusMessage
from barracuda_gui import Window

app = QApplication.instance() or QApplication([])
window = Window(autorefresh=False)
window.show()
for page in window.pages:
    window.navigate(page)
    app.processEvents()
window.mouse_page.preview.setChecked(True)
for panel in range(3):
    window.mouse_page.tab(panel)
    app.processEvents()
assert not window.busy
assert all(not b.isEnabled() for b in window.mouse_page.apply_buttons.values())
window.close()
print("All pages rendered; preview commands disabled; QtDBus imported.")
