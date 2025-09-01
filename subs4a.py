# Adding subtitles in a transparent background as an overlay. The background can be any streaming service.
# Copyright: Svetlin Tassev.
# Released under GPLv3.

import sys
import re
import time
from PyQt5 import QtCore, QtGui, QtWidgets

# Subtitle entry data structure
class Subtitle:
    def __init__(self, start, end, text):
        self.start = start  # in seconds
        self.end = end      # in seconds
        self.text = text

# Parse SRT file and return list of Subtitle objects
def parse_srt(filename):
    subtitles = []
    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\Z)')
    
    def time_to_seconds(t):
        h, m, s_ms = t.split(':')
        s, ms = s_ms.split(',')
        return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
    
    for match in pattern.finditer(content):
        start = time_to_seconds(match.group(2))
        end = time_to_seconds(match.group(3))
        text = match.group(4).strip().replace('\n', '<br>')  # preserve line breaks using html
        subtitles.append(Subtitle(start, end, text))
    return subtitles

class SubtitleOverlay(QtWidgets.QWidget):
    def __init__(self, subtitles, start_offset=0, time_multiplier=24.0, font_size_pt=24):
        super().__init__()
        self.subtitles = subtitles
        self.start_offset = start_offset  # seconds offset for syncing
        self.time_multiplier = time_multiplier  # multiplier to speed/slow time
        self.current_subtitle = ""

        self.paused = False
        self.pause_time = 0
        self.elapsed_paused = 0  # accumulated paused duration
        self.show_timer = False  # whether to show timer display
        
        self.font_size_pt = font_size_pt  # set from arg or default 24
        
        self.drag_position = None  # For mouse drag start position

        self.init_ui()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_subtitle)
        self.timer.start(100)  # update every 100ms
        
        self.playback_start = time.time()  # timestamp when playback started

        # Timer for hiding coefficient overlay
        self.coeff_hide_timer = QtCore.QTimer(self)
        self.coeff_hide_timer.setSingleShot(True)
        self.coeff_hide_timer.timeout.connect(self.hide_coefficient_label)

        # Show initial coeff info at start
        self.show_coeff_info()

    def init_ui(self):
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint | 
                            QtCore.Qt.WindowStaysOnTopHint | 
                            QtCore.Qt.Tool)  # No taskbar entry
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)  # to receive keyboard events

        # Subtitle label
        self.label = QtWidgets.QLabel('', self)
        self.label.setStyleSheet(self.get_label_style())
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setWordWrap(True)  # Enable wrapping for multi-line subtitles

        # Make label transparent to mouse events so dragging works on the entire widget
        self.label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        # Timer label - initially hidden
        self.timer_label = QtWidgets.QLabel('', self)
        self.timer_label.setStyleSheet("""
            QLabel {
                color: yellow;
                font-size: 18pt;
                background-color: rgba(0, 0, 0, 150);
                border: 1px solid yellow;
                padding: 5px 10px;
            }
        """)
        self.timer_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignTop)
        self.timer_label.hide()
        self.timer_label.setFixedWidth(200)

        # Coefficient overlay label (shows fps & font size)
        self.coeff_label = QtWidgets.QLabel('', self)
        self.coeff_label.setStyleSheet("""
            QLabel {
                color: cyan;
                font-size: 20pt;
                font-weight: bold;
                background-color: rgba(0, 0, 0, 180);
                border: 2px solid cyan;
                padding: 5px 15px;
                border-radius: 10px;
            }
        """)
        self.coeff_label.setAlignment(QtCore.Qt.AlignCenter)
        self.coeff_label.hide()
        #self.coeff_label.setFixedWidth(350)  # wider to fit both values
        self.coeff_label.setFixedHeight(50)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.timer_label)
        layout.addStretch()
        layout.addWidget(self.label)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(5)

        # Initial sizing and positioning, the label text is empty so fallback sizing
        self.adjust_size_and_position()

    def get_label_style(self):
        return f"""
            QLabel {{
                color: white;
                font-size: {self.font_size_pt}pt;
                font-style: italic;
                background-color: rgba(0, 0, 0, 80);
            }}
        """

    def keyPressEvent(self, event):
        key = event.key()
        mod = event.modifiers()
        time_offset=0.5
        ctrl_pressed = mod & QtCore.Qt.ControlModifier

        if key == QtCore.Qt.Key_Space:
            # Pause/unpause toggle
            if self.paused:
                # Resume
                self.paused = False
                resumed_time = time.time()
                self.elapsed_paused += resumed_time - self.pause_time
            else:
                # Pause
                self.paused = True
                self.pause_time = time.time()

        elif key == QtCore.Qt.Key_Left:
            # Rewind 1 second offset
            self.start_offset -= time_offset

        elif key == QtCore.Qt.Key_Right:
            # Fast forward 1 second offset
            self.start_offset += time_offset

        elif key == QtCore.Qt.Key_A:
            # Toggle subtitle timer display on/off
            self.show_timer = not self.show_timer
            if self.show_timer:
                self.timer_label.show()
            else:
                self.timer_label.hide()

        elif ctrl_pressed and (key == QtCore.Qt.Key_Plus or key == QtCore.Qt.Key_Equal):
            # Increase time multiplier
            self.adjust_time_multiplier(increase=True)

        elif ctrl_pressed and key == QtCore.Qt.Key_Minus:
            # Decrease time multiplier
            self.adjust_time_multiplier(increase=False)

        elif key == QtCore.Qt.Key_X:
            # Increase font size
            self.change_font_size(increase=True)

        elif key == QtCore.Qt.Key_C:
            # Decrease font size
            self.change_font_size(increase=False)

    def adjust_time_multiplier(self, increase=True):
        """Adjust the time_multiplier by ~1%, keeping anchor subtitle time fixed."""
        old_coeff = self.time_multiplier
        step = 0.001
        
        min_coeff = 0.1
        max_coeff = 122.0

        elapsed_real = self.get_elapsed_real()
        elapsed_subtitle = self.elapsed_subtitle(elapsed_real)

        if increase:
            new_coeff = min(max_coeff, self.time_multiplier + step)
        else:
            new_coeff = max(min_coeff, self.time_multiplier - step)

        self.start_offset = elapsed_subtitle - elapsed_real * new_coeff/24.0
        self.time_multiplier = new_coeff

        self.show_coeff_info()

    def show_coeff_info(self):
        # Set text
        self.coeff_label.setText(f"FPS: {self.time_multiplier:.3f}   Font size: {self.font_size_pt}pt")
        # Resize to fit content exactly
        self.coeff_label.adjustSize()
        self.coeff_label.show()
        # Center horizontally
        self.coeff_label.move((self.width() - self.coeff_label.width()) // 2, 5)
        self.coeff_hide_timer.start(3000)

    def hide_coefficient_label(self):
        self.coeff_label.hide()

    def get_elapsed_real(self):
        if self.paused:
            elapsed_real = self.pause_time - self.playback_start - self.elapsed_paused
        else:
            elapsed_real = time.time() - self.playback_start - self.elapsed_paused
        return elapsed_real

    def elapsed_subtitle(self, elapsed_real):
        return elapsed_real * self.time_multiplier / 24. + self.start_offset

    def change_font_size(self, increase=True):
        step = 2
        min_size = 8
        max_size = 172
        if increase:
            self.font_size_pt = min(max_size, self.font_size_pt + step)
        else:
            self.font_size_pt = max(min_size, self.font_size_pt - step)

        self.label.setStyleSheet(self.get_label_style())
        self.adjust_size_and_position()
        self.show_coeff_info()

    def adjust_size_and_position(self):
        # Keep current top-left position to preserve window position after resize
        current_pos = self.pos()

        # Calculate width dynamically (base logic)
        screen = QtWidgets.QApplication.primaryScreen().geometry()
        max_width = int(screen.width() * 0.8)
        base_font = 24
        base_width = 800
        width = int(base_width * (self.font_size_pt / base_font))
        width = min(width, max_width)
        width = max(400, width)  # minimum width

        # Set label fixed width for proper wrapping calculation
        self.label.setFixedWidth(width)

        # Use QTextDocument for accurate height measurement of HTML with wrapping
        doc = QtGui.QTextDocument()
        doc.setDefaultFont(self.label.font())
        doc.setTextWidth(width)
        # use current subtitle or a placeholder (spaces) so height isn't zero if empty
        doc.setHtml(self.current_subtitle if self.current_subtitle else " " * 10)

        needed_height = int(doc.size().height()) + 40  # add padding

        min_height = int(self.font_size_pt * 3.5) + 40
        needed_height = max(needed_height, min_height)

        self.resize(width, needed_height)
        self.label.setFixedHeight(needed_height - 20)

        # Restore original position to keep window where user moved it
        self.move(current_pos)

        # Position coeff label top-center
        self.coeff_label.move((self.width() - self.coeff_label.width()) // 2, 5)

    def update_subtitle(self):
        elapsed_real = self.get_elapsed_real()
        elapsed = self.elapsed_subtitle(elapsed_real)
        
        subtitle_text = ""
        for s in self.subtitles:
            if s.start <= elapsed <= s.end:
                subtitle_text = s.text
                break
        
        if subtitle_text != self.current_subtitle:
            self.current_subtitle = subtitle_text
            self.label.setText(subtitle_text)
            self.adjust_size_and_position()

        if self.show_timer:
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            milliseconds = int((elapsed - int(elapsed)) * 1000)
            timer_text = f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"
            self.timer_label.setText(timer_text)

    # --- Dragging Methods ---
    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.LeftButton and self.drag_position is not None:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.drag_position = None
            event.accept()

def main():
    if len(sys.argv) < 2:
        print("Usage: python subtitle_overlay.py subtitle_file.srt [start_offset_seconds] [time_multiplier] [font_size_pt]")
        sys.exit(1)
    
    srt_path = sys.argv[1]
    start_offset = float(sys.argv[2]) if len(sys.argv) > 2 else 0
    time_multiplier = float(sys.argv[3]) if len(sys.argv) > 3 else 24.0
    font_size_pt = int(sys.argv[4]) if len(sys.argv) > 4 else 24
    
    subtitles = parse_srt(srt_path)
        
    app = QtWidgets.QApplication([])
    overlay = SubtitleOverlay(subtitles, start_offset, time_multiplier, font_size_pt)
    overlay.show()
    app.exec_()

if __name__ == '__main__':
    main()

