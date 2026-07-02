#!/usr/bin/env python3
"""
Gesture-Controlled OCR + Xcursor AI v2 (PyQt6 Modern UI)
FIXES: Text wrapping, clipboard timer, small input box, deselect on move, vertical shake logic
"""

from pynput.mouse import Listener, Button
from pynput.keyboard import Controller, Key, Listener as KeyListener
from collections import deque
import time
import pyperclip
import threading
import requests
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import re
from collections import Counter
import queue

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *

keyboard = Controller()

# =======================
# THREAD-SAFE COMMAND QUEUE
# =======================

class CommandQueue:
    """Thread-safe queue for main thread to process overlay commands"""
    
    def __init__(self):
        self.queue = queue.Queue()
    
    def show_overlay(self, text, pos=None, is_empty=False):
        self.queue.put(('show', text, pos, is_empty))
    
    def show_input_overlay(self, pos=None):
        self.queue.put(('show_input', None, pos))
    
    def add_ai_token(self, token, final=False):
        self.queue.put(('ai_token', token, final))
    
    def clear_overlay(self):
        self.queue.put(('clear', None))
    
    def get_command(self):
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None


# =======================
# PERSISTENT KEYWORD CACHE
# =======================

class KeywordCache:
    def __init__(self, cache_dir="~/.gesture_ocr_cache"):
        self.cache_dir = Path(cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "keywords.json"
        self.ttl_hours = 6
        self.definitions = self._load_cache()
    
    def _load_cache(self):
        if not self.cache_file.exists():
            return {}
        try:
            with open(self.cache_file, 'r') as f:
                data = json.load(f)
            now = datetime.now()
            pruned = {}
            for keyword, entry in data.items():
                expiry = datetime.fromisoformat(entry['expiry'])
                if now < expiry:
                    pruned[keyword] = entry
            if len(pruned) < len(data):
                self._save_cache(pruned)
            return pruned
        except:
            return {}
    
    def _save_cache(self, data):
        try:
            with open(self.cache_file, 'w') as f:
                json.dump(data, f, indent=2)
        except:
            pass
    
    def get(self, keyword):
        keyword = keyword.lower()
        if keyword in self.definitions:
            entry = self.definitions[keyword]
            expiry = datetime.fromisoformat(entry['expiry'])
            if datetime.now() < expiry:
                return entry['definition']
        return None
    
    def set(self, keyword, definition):
        keyword = keyword.lower()
        self.definitions[keyword] = {
            'definition': definition,
            'expiry': (datetime.now() + timedelta(hours=self.ttl_hours)).isoformat(),
            'cached_at': datetime.now().isoformat()
        }
        self._save_cache(self.definitions)
    
    def has(self, keyword):
        return self.get(keyword.lower()) is not None


# =======================
# KEYWORD EXTRACTOR
# =======================

class KeywordExtractor:
    def __init__(self):
        self.stopwords = set([
            'the', 'is', 'i', 'am', 'are', 'was', 'were', 'be', 'been',
            'and', 'or', 'not', 'but', 'in', 'on', 'at', 'to', 'for',
            'of', 'from', 'by', 'with', 'as', 'a', 'an', 'this', 'that',
            'these', 'those', 'it', 'its', 'they', 'them', 'their',
            'what', 'when', 'where', 'why', 'how', 'which', 'who',
            'will', 'would', 'could', 'should', 'can', 'may', 'might',
            'has', 'have', 'do', 'does', 'did', 'doing', 'done',
            'get', 'see', 'go', 'come', 'make', 'give', 'take', 'use',
            'know', 'think', 'say', 'said', 'says', 'if', 'then',
            'so', 'also', 'just', 'only', 'even', 'all', 'each', 'every',
            'both', 'either', 'neither', 'no', 'yes', 'ok', 'like', 'kind',
            'seem', 'back', 'good', 'bad', 'new', 'old', 'way', 'day',
            'time', 'place', 'one', 'two', 'more', 'less', 'most', 'much',
            'etc', 'etc.', 'etc…'
        ])
    
    def extract(self, text, count=50):
        words = re.findall(r'\b[\w-]+\b', text.lower())
        filtered = [w for w in words if w not in self.stopwords and len(w) > 2]
        if not filtered:
            return []
        counter = Counter(filtered)
        return [word for word, _ in counter.most_common(count)]


# =======================
# QWEN AI INTEGRATION
# =======================

class XcursorAI:
    def __init__(self, cache=None):
        self.base_url = "http://localhost:11434"
        self.model = "qwen2.5-coder:3b"
        self.connected = self.check_connection()
        self.cache = cache or KeywordCache()
        self.extractor = KeywordExtractor()
    
    def check_connection(self):
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except:
            return False
    
    def analyze_streaming(self, text, token_callback, done_callback):
        if not self.connected:
            token_callback("⚠️ Xcursor not connected. Start Ollama: ollama serve")
            done_callback()
            return
        
        try:
            prompt = f"""Analyze the following text briefly and provide a concise response:

TEXT:
{text}

RESPONSE:"""
            
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "temperature": 0.7,
                    "keep_alive": -1,
                },
                timeout=120,
                stream=True
            )
            
            if response.status_code == 200:
                for line in response.iter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            token = data.get("response", "")
                            if token:
                                token_callback(token)
                        except:
                            pass
                done_callback()
            else:
                token_callback(f"❌ Xcursor error: {response.status_code}")
                done_callback()
        
        except requests.exceptions.Timeout:
            token_callback("⏱️ Xcursor timeout.")
            done_callback()
        except Exception as e:
            token_callback(f"❌ Error: {str(e)}")
            done_callback()
    
    def get_keyword_definition(self, keyword):
        cached = self.cache.get(keyword)
        if cached:
            return cached, True
        
        try:
            prompt = f"""Define the word '{keyword}' in one sentence, concise and clear."""
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "temperature": 0.5,
                    "keep_alive": -1,
                },
                timeout=30
            )
            if response.status_code == 200:
                definition = response.json().get("response", "").strip()
                self.cache.set(keyword, definition)
                return definition, False
        except:
            pass
        return f"[Definition not available]", True


# =======================
# MODERN PYQT6 OVERLAY
# =======================

class ModernOverlay(QMainWindow):
    """Modern floating overlay with glass-morphism design"""
    
    def __init__(self, cmd_queue, stylesheet_path):
        super().__init__()
        self.cmd_queue = cmd_queue
        self.is_visible = False
        self.ai_started = False
        self.stylesheet_path = stylesheet_path
        self.last_mouse_pos = None
        self.is_small_mode = False  # Track if in small input-only mode
        self.normal_size = (620, 500)
        self.small_size = (400, 140)
        
        # Animation properties
        self.opacity = 1.0
        self.fade_animation = None
        
        self.setup_ui()
        self.load_stylesheet()
        self.setup_animations()
        
        # Position at top-right
        self.move(QApplication.primaryScreen().geometry().width() - 700, 20)
        self.setMinimumSize(300, 100)
    
    def load_stylesheet(self):
        """Load external stylesheet"""
        try:
            with open(self.stylesheet_path, 'r') as f:
                stylesheet = f.read()
            self.setStyleSheet(stylesheet)
            print("✅ Stylesheet loaded successfully")
        except Exception as e:
            print(f"⚠️ Failed to load stylesheet: {e}")
    
    def setup_ui(self):
        """Setup the main UI components"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Main container
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Glass container
        self.glass_widget = QWidget()
        self.glass_widget.setObjectName("glassWidget")
        glass_layout = QVBoxLayout(self.glass_widget)
        glass_layout.setContentsMargins(0, 0, 0, 0)
        glass_layout.setSpacing(0)
        
        # Header
        header_widget = QWidget()
        header_widget.setObjectName("header")
        header_widget.setFixedHeight(50)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(15, 0, 15, 0)
        
        # Title with icon
        title_label = QLabel("⚡ Xcursor AI")
        title_label.setObjectName("titleLabel")
        header_layout.addWidget(title_label)
        
        header_layout.addStretch()
        
        # Action buttons
        self.mini_btn = self.create_header_button("─", self.minimize_window)
        self.close_btn = self.create_header_button("✕", self.close_window)
        header_layout.addWidget(self.mini_btn)
        header_layout.addWidget(self.close_btn)
        
        glass_layout.addWidget(header_widget)
        
        # Separator
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFixedHeight(1)
        glass_layout.addWidget(separator)
        
        # Content area
        content_widget = QWidget()
        content_widget.setObjectName("content")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(15, 15, 15, 15)
        content_layout.setSpacing(10)
        
        # Scroll area for messages
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("scrollArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.message_container = QWidget()
        self.message_container.setObjectName("messageContainer")
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(0, 0, 0, 0)
        self.message_layout.setSpacing(8)
        self.message_layout.addStretch()
        
        self.scroll_area.setWidget(self.message_container)
        content_layout.addWidget(self.scroll_area)
        
        # Input area
        input_container = QWidget()
        input_container.setObjectName("inputContainer")
        input_container.setFixedHeight(50)
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(8, 0, 8, 0)
        input_layout.setSpacing(5)
        
        self.input_field = QLineEdit()
        self.input_field.setObjectName("inputField")
        self.input_field.setPlaceholderText("Type your message...")
        self.input_field.returnPressed.connect(self.send_input_message)
        input_layout.addWidget(self.input_field)
        
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.send_button.setFixedWidth(80)
        self.send_button.clicked.connect(self.send_input_message)
        input_layout.addWidget(self.send_button)
        
        self.input_container_widget = input_container
        content_layout.addWidget(input_container)
        
        glass_layout.addWidget(content_widget)
        
        # Footer with status
        footer_widget = QWidget()
        footer_widget.setObjectName("footer")
        footer_widget.setFixedHeight(35)
        footer_layout = QHBoxLayout(footer_widget)
        footer_layout.setContentsMargins(15, 0, 15, 0)
        
        self.status_label = QLabel("● Connected")
        self.status_label.setObjectName("statusLabel")
        footer_layout.addWidget(self.status_label)
        
        footer_layout.addStretch()
        
        self.copy_btn = QPushButton("📋 Copy")
        self.copy_btn.setObjectName("footerButton")
        self.copy_btn.clicked.connect(self.copy_content)
        self.copy_btn.setVisible(False)
        
        self.clear_btn = QPushButton("🗑️ Clear")
        self.clear_btn.setObjectName("footerButton")
        self.clear_btn.clicked.connect(self.clear_content)
        
        footer_layout.addWidget(self.copy_btn)
        footer_layout.addWidget(self.clear_btn)
        
        glass_layout.addWidget(footer_widget)
        
        main_layout.addWidget(self.glass_widget)
        
        # Set initial size (normal)
        self.resize(*self.normal_size)
        
        # Enable mouse dragging
        self.drag_position = None
        self.glass_widget.mousePressEvent = self.mouse_press_event
        self.glass_widget.mouseMoveEvent = self.mouse_move_event
        
        # Add resize grip
        self.resize_grip = QSizeGrip(self.glass_widget)
        self.resize_grip.setStyleSheet("QSizeGrip { width: 20px; height: 20px; }")
    
    def create_header_button(self, text, callback):
        """Create a header button with hover effect"""
        btn = QPushButton(text)
        btn.setObjectName("headerButton")
        btn.setFixedSize(30, 30)
        btn.clicked.connect(callback)
        return btn
    
    def setup_animations(self):
        """Setup animation framework"""
        self.fade_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fade_effect)
        self.fade_effect.setOpacity(0)
        
        self.fade_animation = QPropertyAnimation(self.fade_effect, b"opacity")
        self.fade_animation.setDuration(300)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
    
    def show_with_animation(self):
        """Show window with fade-in animation"""
        self.show()
        self.raise_()
        self.activateWindow()
        self.is_visible = True
        
        self.fade_animation.setStartValue(0)
        self.fade_animation.setEndValue(1)
        self.fade_animation.start()
    
    def hide_with_animation(self):
        """Hide window with fade-out animation"""
        self.fade_animation.setStartValue(1)
        self.fade_animation.setEndValue(0)
        self.fade_animation.finished.connect(self._hide_complete)
        self.fade_animation.start()
    
    def _hide_complete(self):
        """Complete hide after animation"""
        self.hide()
        self.is_visible = False
        self.fade_animation.finished.disconnect(self._hide_complete)
    
    def minimize_window(self):
        """Minimize/close window"""
        self.hide_with_animation()
    
    def close_window(self):
        """Close window and clear content"""
        self.clear_content()
        self.hide_with_animation()
    
    def set_small_mode(self, enabled=True):
        """Toggle between small input-only mode and normal mode"""
        if enabled and not self.is_small_mode:
            self.is_small_mode = True
            self.scroll_area.hide()
            self.copy_btn.hide()
            self.clear_btn.hide()
            self.status_label.hide()
            # Resize to small
            QTimer.singleShot(50, lambda: self.resize(*self.small_size))
        elif not enabled and self.is_small_mode:
            self.is_small_mode = False
            self.scroll_area.show()
            self.copy_btn.show()
            self.clear_btn.show()
            self.status_label.show()
            # Resize to normal
            QTimer.singleShot(50, lambda: self.resize(*self.normal_size))
    
    def create_message_widget(self, text, is_user=True):
        """Create a styled message widget with proper text wrapping"""
        message_widget = QWidget()
        layout = QVBoxLayout(message_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Header with timestamp and label
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        
        timestamp = QLabel(datetime.now().strftime("%H:%M:%S"))
        timestamp.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: 500;")
        
        label = QLabel("You" if is_user else "🤖 Xcursor")
        label.setStyleSheet(f"""
            color: {'#58a6ff' if is_user else '#00d9ff'};
            font-weight: 600;
            font-size: 12px;
        """)
        
        header.addWidget(timestamp)
        header.addSpacing(8)
        header.addWidget(label)
        header.addStretch()
        layout.addLayout(header)
        
        # Message content - use QTextEdit for better wrapping
        content = QTextEdit()
        content.setPlainText(text)
        content.setReadOnly(True)
        content.setWordWrapMode(QTextOption.WrapMode.WordWrap)
        content.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                border: none;
                color: #e6edf3;
                font-size: 13px;
                padding: 0px;
                margin: 0px;
            }
        """)
        content.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        content.document().setDocumentMargin(0)
        
        # Set minimum height for content
        doc_height = content.document().size().height()
        content.setFixedHeight(max(int(doc_height) + 4, 24))
        
        layout.addWidget(content)
        
        message_widget.setObjectName("userMessage" if is_user else "aiMessage")
        return message_widget, content
    
    def add_user_message(self, text):
        """Add user message to the chat"""
        # Expand to normal size if in small mode
        if self.is_small_mode:
            self.set_small_mode(False)
        
        # Truncate if extremely long
        if len(text) > 500:
            text = text[:500] + "\n[...truncated...]"
        
        message, content = self.create_message_widget(text, is_user=True)
        self.message_layout.insertWidget(self.message_layout.count() - 1, message)
        
        # Scroll to bottom
        QTimer.singleShot(50, self.scroll_to_bottom)
        
        self.copy_btn.setVisible(False)
    
    def add_ai_token(self, token):
        """Add AI token to current message"""
        # Check if we need to create a new AI message
        if not self.ai_started:
            self.ai_message, self.ai_content = self.create_message_widget("", is_user=False)
            self.message_layout.insertWidget(self.message_layout.count() - 1, self.ai_message)
            self.ai_started = True
        
        # Append token to existing content
        if self.ai_content:
            current_text = self.ai_content.toPlainText()
            new_text = current_text + token
            self.ai_content.setPlainText(new_text)
            
            # Auto-update height
            doc_height = self.ai_content.document().size().height()
            self.ai_content.setFixedHeight(max(int(doc_height) + 4, 24))
            
            # Auto-scroll
            QTimer.singleShot(50, self.scroll_to_bottom)
        
        self.copy_btn.setVisible(True)
    
    def finish_ai_response(self):
        """Finish AI response"""
        self.ai_started = False
        self.ai_content = None
        self.ai_message = None
    
    def scroll_to_bottom(self):
        """Scroll the scroll area to the bottom"""
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def send_input_message(self):
        """Send user input as message"""
        text = self.input_field.text().strip()
        if not text:
            return
        
        # If in small mode, expand first
        if self.is_small_mode:
            self.set_small_mode(False)
        
        self.add_user_message(text)
        self.input_field.clear()
        
        # Start AI streaming for this input
        self.cmd_queue.queue.put(('ai_analyze', text, None))
    
    def copy_content(self):
        """Copy AI response to clipboard"""
        if self.ai_started and self.ai_content:
            text = self.ai_content.toPlainText()
            if text:
                clipboard = QApplication.clipboard()
                clipboard.setText(text)
                
                # Visual feedback
                self.copy_btn.setText("✅ Copied!")
                QTimer.singleShot(1500, lambda: self.copy_btn.setText("📋 Copy"))
    
    def clear_content(self):
        """Clear all messages"""
        # Remove all widgets except the stretch
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.ai_started = False
        self.ai_content = None
        self.ai_message = None
        self.copy_btn.setVisible(False)
        self.input_field.clear()
        
        # Back to normal size
        if self.is_small_mode:
            self.set_small_mode(False)
    
    def set_position_from_mouse(self, x, y):
        """Set window position based on mouse coordinates"""
        self.last_mouse_pos = (x, y)
        # Position near cursor but offset to avoid covering cursor
        window_x = max(10, x + 20)
        window_y = max(10, y + 20)
        
        # Ensure window doesn't go off-screen
        screen = QApplication.primaryScreen().geometry()
        if window_x + self.width() > screen.width():
            window_x = screen.width() - self.width() - 10
        if window_y + self.height() > screen.height():
            window_y = screen.height() - self.height() - 10
        
        self.move(window_x, window_y)
    
    def mouse_press_event(self, event):
        """Handle mouse press for window dragging"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint()
    
    def mouse_move_event(self, event):
        """Handle mouse move for window dragging"""
        if self.drag_position is not None:
            delta = event.globalPosition().toPoint() - self.drag_position
            new_pos = self.pos() + delta
            self.move(new_pos)
            self.drag_position = event.globalPosition().toPoint()
    
    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        self.drag_position = None
        event.accept()


# =======================
# GESTURE DETECTOR
# =======================

class GestureDetector:
    def __init__(self, cmd_queue):
        self.position_history = deque(maxlen=30)
        self.SHAKE_THRESHOLD = 120
        self.TIME_WINDOW = 0.6
        self.last_gesture_time = 0
        self.GESTURE_COOLDOWN = 0.4
        self.last_shake_pos = None
        
        self.tracking_enabled = True
        self.middle_click_count = 0
        self.last_middle_click_time = 0
        self.MIDDLE_CLICK_TIMEOUT = 0.5
        
        self.left_button_pressed = False
        self.click_count = 0
        self.waiting_for_clicks = False
        self.capture_count = 0
        
        # Clipboard management - FIX #3 & #5
        self.last_captured_text = None
        self.clipboard_clear_timer = None
        self.CLIPBOARD_TTL_SECONDS = 7
        
        # Vertical shake state - FIX #6
        self.vertical_shake_triggered = False
        self.waiting_for_vertical_click = False
        self.vertical_shake_click_time = None
        
        self.listener = None
        self.hotkey_listener = None
        self.cmd_queue = cmd_queue
        self.qwen_ai = QwenAI(cache=KeywordCache())
        
        self.keyword_queue = deque()
        self.queue_processor_running = False
    
    def toggle_tracking(self):
        self.tracking_enabled = not self.tracking_enabled
        status = "ON ✅" if self.tracking_enabled else "OFF ❌"
        print(f"\n🔄 GESTURE TRACKING: {status}\n")
    
    def start_clipboard_clear_timer(self):
        """Start 7-second timer to auto-clear captured text - FIX #3"""
        if self.clipboard_clear_timer:
            self.clipboard_clear_timer.cancel()
        
        self.clipboard_clear_timer = threading.Timer(
            self.CLIPBOARD_TTL_SECONDS,
            self._clear_clipboard_timeout
        )
        self.clipboard_clear_timer.daemon = True
        self.clipboard_clear_timer.start()
    
    def _clear_clipboard_timeout(self):
        """Called when timer expires"""
        self.last_captured_text = None
        self.waiting_for_clicks = False
        print(f"[🧹 Clipboard cleared after {self.CLIPBOARD_TTL_SECONDS}s]")
    
    def clear_clipboard_now(self):
        """Immediately clear clipboard text on mouse movement - FIX #5"""
        if self.last_captured_text is not None:
            self.last_captured_text = None
            self.waiting_for_clicks = False
            if self.clipboard_clear_timer:
                self.clipboard_clear_timer.cancel()
                self.clipboard_clear_timer = None
            print("[🧹 Clipboard cleared due to mouse movement]")
    
    def trigger_snipping_tool(self):
        print("\n🎯 VERTICAL SHAKE DETECTED! Taking screenshot...\n")
        print("   Waiting for you to capture text... (if nothing copied, input box will open)")
        
        # Clear clipboard immediately on vertical shake
        self.clear_clipboard_now()
        
        try:
            with keyboard.pressed(Key.shift):
                with keyboard.pressed(Key.cmd):
                    keyboard.press('t')
                    keyboard.release('t')
            self.vertical_shake_triggered = True
            self.waiting_for_vertical_click = True
            self.vertical_shake_click_time = time.time()
        except Exception as e:
            print(f"❌ Error: {e}")
    
    def capture_ocr_text(self):
        """Capture OCR text after screenshot"""
        try:
            time.sleep(0.3)
            text = pyperclip.paste().strip()
            if not text:
                print("⚠️ No text in clipboard - opening input box")
                self.cmd_queue.show_input_overlay(self.last_shake_pos)
                return False
            
            self.capture_count += 1
            self.last_captured_text = text
            self.start_clipboard_clear_timer()
            print(f"\n📋 OCR CAPTURE #{self.capture_count}: {len(text)} chars")
            self.cmd_queue.show_overlay(text, self.last_shake_pos)
            
            self.waiting_for_clicks = False
            self.click_count = 0
            self.vertical_shake_triggered = False
            self.waiting_for_vertical_click = False
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def get_and_print_selected_text(self):
        """Get selected text and send to overlay"""
        try:
            with keyboard.pressed(Key.ctrl):
                keyboard.press('c')
                keyboard.release('c')
            time.sleep(0.05)
            text = pyperclip.paste().strip()
            if text:
                self.last_captured_text = text
                self.start_clipboard_clear_timer()
                print(f"\n📝 TEXT SELECTED: {len(text)} chars")
                self.cmd_queue.show_overlay(text, self.last_shake_pos)
            else:
                print("ℹ️ No text selected - opening input box")
                self.cmd_queue.show_input_overlay(self.last_shake_pos)
        except Exception as e:
            print(f"⚠️ Error: {e}")
    
    def manual_trigger_keyword_extraction(self):
        try:
            with keyboard.pressed(Key.ctrl):
                keyboard.press('c')
                keyboard.release('c')
            time.sleep(0.1)
            text = pyperclip.paste()
            if text and len(text) > 20:
                print(f"\n🎯 MANUAL KEYWORD EXTRACTION TRIGGERED")
                print(f"   Text size: {len(text)} chars")
                self._process_keywords_background(text)
            else:
                print("\n⚠️ No text in clipboard or too short (<20 chars)")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    def _process_keywords_background(self, text):
        keywords = self.qwen_ai.extractor.extract(text, count=50)
        new_keywords = 0
        for keyword in keywords:
            if not self.qwen_ai.cache.has(keyword):
                self.keyword_queue.append(keyword)
                new_keywords += 1
        if new_keywords > 0:
            print(f"  📚 Added {new_keywords} new keywords to queue")
        
        if not self.queue_processor_running and self.keyword_queue:
            thread = threading.Thread(target=self._keyword_queue_processor, daemon=True)
            thread.start()
    
    def _keyword_queue_processor(self):
        self.queue_processor_running = True
        while self.keyword_queue:
            keyword = self.keyword_queue.popleft()
            definition, from_cache = self.qwen_ai.get_keyword_definition(keyword)
            if not from_cache:
                print(f"  📚 Indexed: {keyword}")
            time.sleep(0.5)
        self.queue_processor_running = False
    
    def on_move(self, x, y):
        """On mouse movement, clear old clipboard text - FIX #5"""
        current_time = time.time()
        self.position_history.append((x, y, current_time))
        
        # Clear clipboard on movement
        self.clear_clipboard_now()
        
        if self.tracking_enabled:
            # Don't detect horizontal shake if snipping tool is active
            if not self.waiting_for_vertical_click:
                self.detect_horizontal_shake()
            self.detect_vertical_shake()
    
    def on_click(self, x, y, button, pressed):
        """Handle mouse clicks"""
        if button == Button.middle and pressed:
            self.handle_middle_click()
            return
        
        if button != Button.left:
            return
        
        if pressed:
            self.left_button_pressed = True
        else:
            self.left_button_pressed = False
            
            if self.tracking_enabled:
                # Handle vertical shake click - FIX #6
                if self.waiting_for_vertical_click:
                    print(f"   Click detected after vertical shake")
                    time.sleep(0.2)
                    text = pyperclip.paste().strip()
                    if text:
                        print(f"   Text found in clipboard!")
                        self.capture_ocr_text()
                    else:
                        print(f"   No text in clipboard yet, waiting for next click...")
                        # Still waiting for text
                    return
                
                self.detect_text_selection(x, y)
                if self.waiting_for_clicks:
                    self.click_count += 1
                    print(f"👆 Click {self.click_count}/2 detected")
                    if self.click_count >= 2:
                        self.capture_ocr_text()
    
    def handle_middle_click(self):
        current_time = time.time()
        if current_time - self.last_middle_click_time < self.MIDDLE_CLICK_TIMEOUT:
            self.toggle_tracking()
            self.middle_click_count = 0
            self.last_middle_click_time = 0
        else:
            self.middle_click_count = 1
            self.last_middle_click_time = current_time
    
    def detect_text_selection(self, x, y):
        try:
            time.sleep(0.1)
            with keyboard.pressed(Key.ctrl):
                keyboard.press('c')
                keyboard.release('c')
            time.sleep(0.05)
        except:
            pass
    
    def detect_horizontal_shake(self):
        if len(self.position_history) < 6:
            return
        now = time.time()
        recent = [p for p in self.position_history if now - p[2] < self.TIME_WINDOW]
        if len(recent) < 6:
            return
        x_positions = [p[0] for p in recent]
        total_movement = max(x_positions) - min(x_positions)
        if total_movement < self.SHAKE_THRESHOLD:
            return
        directions = []
        for i in range(1, len(x_positions)):
            delta = x_positions[i] - x_positions[i-1]
            if abs(delta) > 8:
                directions.append(1 if delta > 0 else -1)
        if len(directions) < 3:
            return
        reversals = sum(1 for i in range(1, len(directions)) if directions[i] != directions[i-1])
        if reversals < 2:
            return
        y_positions = [p[1] for p in recent]
        y_movement = max(y_positions) - min(y_positions)
        if y_movement > total_movement / 1.7:
            return
        time_span = recent[-1][2] - recent[0][2]
        if time_span > 0.9:
            return
        current_time = time.time()
        if current_time - self.last_gesture_time > self.GESTURE_COOLDOWN:
            self.last_shake_pos = (recent[-1][0], recent[-1][1])
            print(f"[HORIZONTAL SHAKE] {total_movement}px movement")
            self.last_gesture_time = current_time
            self.get_and_print_selected_text()
    
    def detect_vertical_shake(self):
        if len(self.position_history) < 6:
            return
        now = time.time()
        recent = [p for p in self.position_history if now - p[2] < self.TIME_WINDOW]
        if len(recent) < 6:
            return
        y_positions = [p[1] for p in recent]
        total_movement = max(y_positions) - min(y_positions)
        if total_movement < self.SHAKE_THRESHOLD:
            return
        directions = []
        for i in range(1, len(y_positions)):
            delta = y_positions[i] - y_positions[i-1]
            if abs(delta) > 8:
                directions.append(1 if delta > 0 else -1)
        if len(directions) < 3:
            return
        reversals = sum(1 for i in range(1, len(directions)) if directions[i] != directions[i-1])
        if reversals < 2:
            return
        x_positions = [p[0] for p in recent]
        x_movement = max(x_positions) - min(x_positions)
        if x_movement > total_movement / 1.7:
            return
        time_span = recent[-1][2] - recent[0][2]
        if time_span > 0.9:
            return
        current_time = time.time()
        if current_time - self.last_gesture_time > self.GESTURE_COOLDOWN:
            self.last_shake_pos = (recent[-1][0], recent[-1][1])
            print(f"[VERTICAL SHAKE] {total_movement}px movement")
            self.last_gesture_time = current_time
            threading.Thread(target=self.trigger_snipping_tool, daemon=True).start()
    
    def start(self):
        print("=" * 70)
        print("🎯 GESTURE-CONTROLLED OCR + QWEN AI v2 (IMPROVED)")
        print("=" * 70)
        print("\n📋 GESTURES:")
        print("   1. Horizontal shake → AI analyzes selected text")
        print("   2. Vertical shake → Screenshot OCR")
        print("   3. After screenshot, click when you have text copied")
        print("   4. Double middle-click → Toggle tracking")
        print("   5. If no text → Input box opens (small mode)")
        print("\n🔄 IMPROVEMENTS:")
        print("   ✅ Text wraps properly in messages")
        print("   ✅ Better button styling and fonts")
        print("   ✅ Clipboard auto-clears after 7 seconds")
        print("   ✅ Small input box expands on typing")
        print("   ✅ Mouse movement clears old text")
        print("   ✅ Vertical shake waits for copied text")
        
        if self.qwen_ai.connected:
            print("\n🤖 AI Status: ✅ CONNECTED")
            print(f"   Model: {self.qwen_ai.model}")
        else:
            print("\n🤖 AI Status: ❌ NOT CONNECTED")
            print("   Start Ollama: ollama serve")
            sys.exit(1)
        
        print("\n⌨️ Press Ctrl+C to stop")
        print("=" * 70 + "\n")
        
        def on_press(key):
            try:
                if key == Key.f6:
                    self.manual_trigger_keyword_extraction()
            except:
                pass
        
        self.hotkey_listener = KeyListener(on_press=on_press)
        self.hotkey_listener.start()
        
        self.listener = Listener(on_move=self.on_move, on_click=self.on_click)
        self.listener.start()
        self.listener.join()
    
    def stop(self):
        if self.listener:
            self.listener.stop()
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        print("\n✅ Shutdown complete.")


# =======================
# MAIN APPLICATION
# =======================

class MainApplication(QApplication):
    """Main PyQt6 application"""
    
    def __init__(self, argv, stylesheet_path):
        super().__init__(argv)
        
        # Setup
        self.cmd_queue = CommandQueue()
        self.detector = GestureDetector(self.cmd_queue)
        
        # Create overlay with stylesheet path
        self.overlay = ModernOverlay(self.cmd_queue, stylesheet_path)
        
        # Start detector in background
        self.detector_thread = threading.Thread(target=self.detector.start, daemon=False)
        self.detector_thread.start()
        
        # Setup timer for processing commands
        self.process_timer = QTimer()
        self.process_timer.timeout.connect(self.process_commands)
        self.process_timer.start(20)  # 50fps
        
        print("✅ Application started. Waiting for gestures...")
    
    def process_commands(self):
        """Process commands from queue in main thread"""
        cmd = self.cmd_queue.get_command()
        if cmd:
            cmd_type = cmd[0]
            
            if cmd_type == 'show':
                text = cmd[1]
                pos = cmd[2] if len(cmd) > 2 else None
                is_empty = cmd[3] if len(cmd) > 3 else False
                
                if pos:
                    self.overlay.set_position_from_mouse(pos[0], pos[1])
                
                # Exit small mode
                if self.overlay.is_small_mode:
                    self.overlay.set_small_mode(False)
                
                self.overlay.clear_content()
                self.overlay.add_user_message(text)
                self.overlay.show_with_animation()
                self.overlay.input_field.setFocus()
                
                # Start AI streaming
                self._stream_ai(text)
            
            elif cmd_type == 'show_input':
                pos = cmd[2] if len(cmd) > 2 else None
                
                if pos:
                    self.overlay.set_position_from_mouse(pos[0], pos[1])
                
                # Enter small mode
                self.overlay.clear_content()
                self.overlay.set_small_mode(True)
                self.overlay.show_with_animation()
                self.overlay.input_field.setFocus()
                self.overlay.input_field.setPlaceholderText("No text detected. Type here...")
            
            elif cmd_type == 'ai_analyze':
                text = cmd[1]
                self._stream_ai(text)
            
            elif cmd_type == 'ai_token':
                token = cmd[1]
                final = cmd[2] if len(cmd) > 2 else False
                if final:
                    self.overlay.finish_ai_response()
                else:
                    self.overlay.add_ai_token(token)
            
            elif cmd_type == 'clear':
                self.overlay.clear_content()
                self.overlay.hide_with_animation()
    
    def _stream_ai(self, text):
        """Stream AI response for text"""
        def stream_ai():
            def on_token(token):
                self.cmd_queue.add_ai_token(token)
            
            def on_done():
                self.cmd_queue.add_ai_token("", final=True)
            
            self.detector.qwen_ai.analyze_streaming(text, on_token, on_done)
        
        thread = threading.Thread(target=stream_ai, daemon=True)
        thread.start()


def main():
    """Main entry point"""
    # Find stylesheet path
    stylesheet_path = Path(__file__).parent / "gesture_ocr_modern.qss"
    if not stylesheet_path.exists():
        stylesheet_path = Path.cwd() / "gesture_ocr_modern.qss"
    
    if not stylesheet_path.exists():
        print(f"⚠️ Warning: Stylesheet not found at {stylesheet_path}")
        print("Make sure gesture_ocr_modern.qss is in the same directory as this script")
    
    app = MainApplication(sys.argv, str(stylesheet_path))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()