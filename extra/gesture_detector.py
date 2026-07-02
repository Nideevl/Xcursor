#!/usr/bin/env python3
"""
Gesture-Controlled OCR + Qwen AI v2 (PyQt6 Modern UI)
FIXED: Windows snipping tool integration, clipboard clearing on vertical shake
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
import subprocess
import win32gui
import win32con
import win32api
from win32con import SW_SHOW, SW_HIDE

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
    
    def show_overlay(self, text):
        self.queue.put(('show', text))
    
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

class QwenAI:
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
            token_callback("⚠️ Qwen not connected. Start Ollama: ollama serve")
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
                token_callback(f"❌ Qwen error: {response.status_code}")
                done_callback()
        
        except requests.exceptions.Timeout:
            token_callback("⏱️ Qwen timeout.")
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
    
    def __init__(self, cmd_queue):
        super().__init__()
        self.cmd_queue = cmd_queue
        self.is_visible = False
        self.ai_started = False
        
        # Animation properties
        self.opacity = 1.0
        self.fade_animation = None
        
        self.setup_ui()
        self.setup_style()
        self.setup_animations()
        
        # Position at top-right
        self.move(QApplication.primaryScreen().geometry().width() - 620, 20)
    
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
        title_label = QLabel("⚡ QWEN AI")
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
        
        glass_layout.addWidget(content_widget)
        glass_layout.addWidget(footer_widget)
        
        main_layout.addWidget(self.glass_widget)
        
        # Set initial size
        self.setFixedSize(600, 450)
        
        # Enable mouse dragging
        self.drag_position = None
        self.glass_widget.mousePressEvent = self.mouse_press_event
        self.glass_widget.mouseMoveEvent = self.mouse_move_event
    
    def create_header_button(self, text, callback):
        """Create a header button with hover effect"""
        btn = QPushButton(text)
        btn.setObjectName("headerButton")
        btn.setFixedSize(30, 30)
        btn.clicked.connect(callback)
        return btn
    
    def setup_style(self):
        """Setup modern stylesheet with glass-morphism"""
        self.setStyleSheet("""
            /* Glass container */
            #glassWidget {
                background: rgba(20, 25, 35, 0.85);
                border-radius: 16px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
            
            /* Blur effect - works on supported platforms */
            #glassWidget {
                backdrop-filter: blur(20px);
                -webkit-backdrop-filter: blur(20px);
            }
            
            /* Header */
            #header {
                background: rgba(255, 255, 255, 0.03);
                border-radius: 16px 16px 0 0;
            }
            
            #titleLabel {
                color: #00d9ff;
                font-size: 14px;
                font-weight: 600;
                letter-spacing: 0.5px;
                padding: 5px 0;
            }
            
            #headerButton {
                background: transparent;
                color: #8b949e;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 400;
                padding: 0;
            }
            
            #headerButton:hover {
                background: rgba(255, 255, 255, 0.08);
                color: #e6edf3;
            }
            
            #headerButton:pressed {
                background: rgba(255, 255, 255, 0.15);
            }
            
            #separator {
                background: rgba(255, 255, 255, 0.06);
            }
            
            /* Content */
            #content {
                background: transparent;
            }
            
            #scrollArea {
                background: transparent;
                border: none;
            }
            
            #scrollArea QScrollBar:vertical {
                background: transparent;
                width: 4px;
                border-radius: 2px;
            }
            
            #scrollArea QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 2px;
                min-height: 20px;
            }
            
            #scrollArea QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            
            #scrollArea QScrollBar::add-line:vertical,
            #scrollArea QScrollBar::sub-line:vertical {
                height: 0;
            }
            
            #messageContainer {
                background: transparent;
            }
            
            /* Messages */
            .userMessage {
                background: rgba(88, 166, 255, 0.15);
                border: 1px solid rgba(88, 166, 255, 0.1);
                border-radius: 10px;
                padding: 10px 14px;
                color: #e6edf3;
                font-size: 12px;
                line-height: 1.6;
            }
            
            .userMessage .timestamp {
                color: #8b949e;
                font-size: 10px;
                font-weight: 500;
                margin-bottom: 4px;
            }
            
            .userMessage .label {
                color: #58a6ff;
                font-weight: 600;
            }
            
            .aiMessage {
                background: rgba(0, 217, 255, 0.08);
                border: 1px solid rgba(0, 217, 255, 0.06);
                border-radius: 10px;
                padding: 10px 14px;
                color: #e6edf3;
                font-size: 12px;
                line-height: 1.6;
            }
            
            .aiMessage .timestamp {
                color: #8b949e;
                font-size: 10px;
                font-weight: 500;
                margin-bottom: 4px;
            }
            
            .aiMessage .label {
                color: #00d9ff;
                font-weight: 600;
            }
            
            .aiMessage .cursor {
                color: #00d9ff;
                animation: blink 1s infinite;
            }
            
            @keyframes blink {
                0%, 50% { opacity: 1; }
                51%, 100% { opacity: 0; }
            }
            
            /* Footer */
            #footer {
                background: rgba(255, 255, 255, 0.02);
                border-radius: 0 0 16px 16px;
                border-top: 1px solid rgba(255, 255, 255, 0.04);
            }
            
            #statusLabel {
                color: #3fb950;
                font-size: 11px;
                font-weight: 500;
            }
            
            #footerButton {
                background: transparent;
                color: #8b949e;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                padding: 4px 10px;
            }
            
            #footerButton:hover {
                background: rgba(255, 255, 255, 0.08);
                color: #e6edf3;
            }
            
            #footerButton:pressed {
                background: rgba(255, 255, 255, 0.15);
            }
            
            /* Scrollbar for messages */
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
                border-radius: 2px;
            }
            
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 2px;
                min-height: 20px;
            }
            
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.3);
            }
            
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)
    
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
        print(f"🔍 DEBUG: show_with_animation() called - is_visible={self.is_visible}")
        self.show()
        self.raise_()
        self.activateWindow()
        self.is_visible = True
        
        self.fade_animation.setStartValue(0)
        self.fade_animation.setEndValue(1)
        self.fade_animation.start()
    
    def hide_with_animation(self):
        """Hide window with fade-out animation"""
        print(f"🔍 DEBUG: hide_with_animation() called - is_visible={self.is_visible}")
        self.fade_animation.setStartValue(1)
        self.fade_animation.setEndValue(0)
        self.fade_animation.finished.connect(self._hide_complete)
        self.fade_animation.start()
    
    def _hide_complete(self):
        """Complete hide after animation"""
        print(f"🔍 DEBUG: _hide_complete() called - setting is_visible=False")
        self.hide()
        self.is_visible = False
        self.fade_animation.finished.disconnect(self._hide_complete)
    
    def minimize_window(self):
        print(f"🔍 DEBUG: minimize_window() called - is_visible={self.is_visible}")
        """Minimize window - hides without clearing content"""
        # Clear clipboard to prevent re-capturing same text
        if self.gesture_detector:
            self.gesture_detector.clear_clipboard_now()
            print("🧹 Clipboard cleared on minimize")
        self.hide_with_animation()
    
    def close_window(self):
        """Close window and clear content"""
        self.clear_content()
        self.hide_with_animation()
    
    def create_message_widget(self, text, is_user=True):
        """Create a styled message widget"""
        message_widget = QWidget()
        layout = QVBoxLayout(message_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Header with timestamp and label
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        
        timestamp = QLabel(datetime.now().strftime("%H:%M:%S"))
        timestamp.setStyleSheet("color: #8b949e; font-size: 10px; font-weight: 500;")
        
        label = QLabel("You" if is_user else "🤖 Qwen")
        label.setStyleSheet(f"""
            color: {'#58a6ff' if is_user else '#00d9ff'};
            font-weight: 600;
            font-size: 11px;
        """)
        
        header.addWidget(timestamp)
        header.addSpacing(8)
        header.addWidget(label)
        header.addStretch()
        layout.addLayout(header)
        
        # Message content
        content = QLabel(text)
        content.setWordWrap(True)
        content.setStyleSheet("color: #e6edf3; font-size: 12px; line-height: 1.6;")
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(content)
        
        message_widget.setObjectName("userMessage" if is_user else "aiMessage")
        return message_widget
    
    def add_user_message(self, text):
        """Add user message to the chat"""
        # Truncate if too long
        if len(text) > 150:
            text = text[:150] + "..."
        
        message = self.create_message_widget(text, is_user=True)
        self.message_layout.insertWidget(self.message_layout.count() - 1, message)
        
        # Scroll to bottom
        QTimer.singleShot(50, self.scroll_to_bottom)
        
        self.copy_btn.setVisible(False)
    
    def add_ai_token(self, token):
        """Add AI token to current message"""
        # Check if we need to create a new AI message
        if not self.ai_started:
            self.ai_message = self.create_message_widget("", is_user=False)
            self.message_layout.insertWidget(self.message_layout.count() - 1, self.ai_message)
            self.ai_started = True
            
            # Find the content label in the message
            self.ai_content = self.ai_message.findChild(QLabel)
        
        # Append token to existing content
        if self.ai_content:
            current_text = self.ai_content.text()
            self.ai_content.setText(current_text + token)
            
            # Auto-scroll
            QTimer.singleShot(50, self.scroll_to_bottom)
        
        self.copy_btn.setVisible(True)
    
    def finish_ai_response(self):
        """Finish AI response"""
        self.ai_started = False
        self.ai_content = None
        self.ai_message = None
        
        # Add a small indicator that response is complete
        if self.message_layout.count() > 0:
            last_widget = self.message_layout.itemAt(self.message_layout.count() - 2)
            if last_widget and last_widget.widget():
                # Add a tiny completion marker
                pass
    
    def scroll_to_bottom(self):
        """Scroll the scroll area to the bottom"""
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def copy_content(self):
        """Copy AI response to clipboard"""
        if self.ai_started and self.ai_content:
            text = self.ai_content.text()
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
# WINDOWS SNIPPING TOOL MONITOR
# =======================

class SnippingToolMonitor:
    """Monitor for Windows Snipping Tool state"""
    
    SNIPPING_TOOL_WINDOWS = [
        "Snipping Tool",
        "Snip & Sketch",
        "Snipping Tool Overlay",
        "Screen Sketch"
    ]
    
    @staticmethod
    def is_snipping_tool_open():
        """Check if any snipping tool window is open"""
        try:
            def enum_windows_callback(hwnd, windows):
                if win32gui.IsWindowVisible(hwnd):
                    window_text = win32gui.GetWindowText(hwnd)
                    for tool_name in SnippingToolMonitor.SNIPPING_TOOL_WINDOWS:
                        if tool_name.lower() in window_text.lower():
                            windows.append(hwnd)
                return True
            
            windows = []
            win32gui.EnumWindows(enum_windows_callback, windows)
            return len(windows) > 0
        except:
            return False
    
    @staticmethod
    def wait_for_snipping_tool_to_close(timeout=30):
        """Wait for snipping tool to close"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not SnippingToolMonitor.is_snipping_tool_open():
                return True
            time.sleep(0.2)
        return False


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
        
        # Track if snipping tool is open
        self.snipping_tool_open = False
        self.snipping_tool_monitor = SnippingToolMonitor()
        
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
    
    def trigger_snipping_tool(self):
        print("\n🎯 VERTICAL SHAKE DETECTED! Opening Snipping Tool...")
        
        # Clear clipboard immediately on vertical shake
        try:
            pyperclip.copy("")
            print("   🧹 Clipboard cleared for fresh capture")
        except Exception as e:
            print(f"   ⚠️ Failed to clear clipboard: {e}")
        
        try:
            # Open Snipping Tool (Windows)
            with keyboard.pressed(Key.cmd):
                with keyboard.pressed(Key.shift):
                    keyboard.press('s')
                    keyboard.release('s')
            
            self.snipping_tool_open = True
            self.click_count = 0
            self.waiting_for_clicks = True
            
            print("   📸 Snipping tool opened - select your area")
            print("   🔄 Horizontal shake detection PAUSED until tool closes")
            
            # Start monitoring thread to detect when snipping tool closes
            threading.Thread(target=self._monitor_snipping_tool, daemon=True).start()
            
        except Exception as e:
            print(f"❌ Error opening snipping tool: {e}")
            self.snipping_tool_open = False
            self.waiting_for_clicks = False
    
    def _monitor_snipping_tool(self):
        """Monitor for snipping tool closure"""
        print("   👁️ Monitoring snipping tool...")
        
        # Wait for snipping tool to close
        if self.snipping_tool_monitor.wait_for_snipping_tool_to_close(timeout=60):
            print("   ✅ Snipping tool closed - horizontal detection RESUMED")
        else:
            print("   ⏱️ Snipping tool monitor timeout - forcing resume")
        
        self.snipping_tool_open = False
        self.waiting_for_clicks = False
        
        # Check if text was captured
        time.sleep(0.2)
        text = pyperclip.paste().strip()
        if text:
            print(f"   ✅ Text captured: {len(text)} chars")
            self.cmd_queue.show_overlay(text)
        else:
            print("   ℹ️ No text captured from snipping tool")
    
    def capture_ocr_text(self):
        try:
            time.sleep(0.3)
            text = pyperclip.paste().strip()
            if not text:
                print("⚠️ No text in clipboard.")
                return False
            
            self.capture_count += 1
            print(f"\n📋 OCR CAPTURE #{self.capture_count}: {len(text)} chars")
            self.cmd_queue.show_overlay(text)
            
            self.waiting_for_clicks = False
            self.click_count = 0
            return True
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def get_and_print_selected_text(self):
        try:
            with keyboard.pressed(Key.ctrl):
                keyboard.press('c')
                keyboard.release('c')
            time.sleep(0.05)
            text = pyperclip.paste().strip()
            if text:
                print(f"\n📝 TEXT SELECTED: {len(text)} chars")
                self.cmd_queue.show_overlay(text)
            else:
                print("ℹ️ No text selected")
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
                print("   Make sure you pressed Ctrl+A first to select text")
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
        current_time = time.time()
        self.position_history.append((x, y, current_time))
        if self.tracking_enabled:
            self.detect_horizontal_shake()
            self.detect_vertical_shake()
    
    def on_click(self, x, y, button, pressed):
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
        # Skip horizontal detection if snipping tool is open
        if self.snipping_tool_open:
            return
        
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
        """Start the gesture detector"""
        print("=" * 70)
        print("🎯 GESTURE-CONTROLLED OCR + QWEN AI v2 (PyQt6 Modern UI)")
        print("=" * 70)
        print("\n📋 GESTURES:")
        print("   1. Select text → Horizontal shake → AI analyzes → OVERLAY opens")
        print("   2. Vertical shake → Opens Snipping Tool (clipboard cleared)")
        print("   3. After Snipping, click twice → OCR sent to AI")
        print("   4. Double-click middle mouse → Toggle tracking")
        print("\n🔄 IMPROVEMENTS:")
        print("   ✅ Clipboard cleared on vertical shake")
        print("   ✅ Horizontal detection paused during snipping tool")
        print("   ✅ Windows snipping tool detection")
        
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
    
    def __init__(self, argv):
        super().__init__(argv)
        
        # Setup
        self.cmd_queue = CommandQueue()
        self.detector = GestureDetector(self.cmd_queue)
        
        # Create overlay
        self.overlay = ModernOverlay(self.cmd_queue)
        
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
                self.overlay.add_user_message(text)
                self.overlay.show_with_animation()
                
                # Start AI streaming
                def stream_ai():
                    def on_token(token):
                        self.cmd_queue.add_ai_token(token)
                    
                    def on_done():
                        self.cmd_queue.add_ai_token("", final=True)
                    
                    self.detector.qwen_ai.analyze_streaming(text, on_token, on_done)
                
                thread = threading.Thread(target=stream_ai, daemon=True)
                thread.start()
            
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


def main():
    """Main entry point"""
    app = MainApplication(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
    