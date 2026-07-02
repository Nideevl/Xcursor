"""Modern PyQt6 overlay with enhanced syntax highlighting and semantic coloring"""
import sys
from datetime import datetime
from pathlib import Path
import re
from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import QWIDGETSIZE_MAX  


class CodeBlockWidget(QWidget):

    def __init__(self, code_html, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.code_display = QTextBrowser()

        self.code_display.setObjectName("codeBlockContent")
        self.code_display.setReadOnly(True)

        # preserve long lines
        self.code_display.setLineWrapMode(
            QTextEdit.LineWrapMode.NoWrap
        )

        # horizontal only
        self.code_display.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.code_display.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.code_display.document().setDocumentMargin(0)

        self.code_display.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed
        )

        self.code_display.setStyleSheet("""
        QTextBrowser {
            background: transparent;
            border: none;
            padding: 0px;
            margin: 0px;

            font-family:
                Menlo,
                Monaco,
                Consolas,
                "Liberation Mono",
                monospace;

            font-size: 14px;
        }
        """)

        layout.addWidget(self.code_display)

        # Track last-set html so callers/ourselves can skip no-op updates
        self._last_html = None

        self.set_html(code_html)

    def set_html(self, html):
        """Update the code content. Avoids redundant work if html is unchanged,
        and avoids forcing a synchronous repaint (which caused UI flicker)."""
        if html == self._last_html:
            return
        self._last_html = html

        self.code_display.setHtml(html)

        # Defer the height recalculation to the next event-loop iteration
        # instead of forcing QApplication.processEvents() synchronously.
        # That synchronous call was the main source of the flicker: it forced
        # an immediate repaint mid-construction/update every time this was called.
        QTimer.singleShot(0, self._adjust_height)

    def _adjust_height(self):
        doc = self.code_display.document()

        width = self.code_display.viewport().width()
        if width <= 0:
            # Viewport may not have a valid width yet (e.g. widget not yet
            # laid out). Fall back to our own width, then a sane default.
            width = self.width() if self.width() > 0 else 400

        doc.setTextWidth(width)
        doc.adjustSize()

        h = int(doc.size().height())
        self.code_display.setFixedHeight(h + 8)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        doc = self.code_display.document()

        doc.setTextWidth(
            self.code_display.viewport().width()
        )

        doc.adjustSize()

        self.code_display.setFixedHeight(
            int(doc.size().height()) + 8
        )


class ModernOverlay(QMainWindow):
    """Modern floating overlay with glass-morphism design and intelligent highlighting"""
    
    # Signal emitted when window is manually resized
    resized = pyqtSignal()
    
    def __init__(self, cmd_queue, stylesheet_path):
        super().__init__()
        self.cmd_queue = cmd_queue
        self.is_visible = False
        self.ai_started = False
        self.stylesheet_path = stylesheet_path
        self.last_mouse_pos = None
        self.is_small_mode = False
        self.normal_size = (580, 400)
        self.small_size = (400, 140)
        self.current_theme = "dark"  # dark, green, blue
        self.window_opacity = 1.0
        
        self.opacity = 1.0
        self.fade_animation = None
        self.ai_message = None
        self.ai_content = None
        self.ai_plain_text = ""  # TRACK PLAIN TEXT SEPARATELY
        self.ai_segments = []    # TRACK RENDERED SEGMENTS FOR DIFFING (fixes flicker)
        
        # Reference to gesture detector (set later by main.py)
        self.gesture_detector = None
        
        # Get the directory where this script is located
        self.script_dir = Path(__file__).parent.absolute()
        
        # Get bundle path for PyInstaller
        self.bundle_path = self.get_bundle_path()

        self.conversation_history = []  # List of (role, text) tuples: ("user", "...") or ("ai", "...")
        
        # Icon cache
        self.icon_cache = {}
        
        self.setup_ui()
        self.load_stylesheet()
        self.setup_animations()
        self.apply_theme("dark")
        
        self.move(QApplication.primaryScreen().geometry().width() - 700, 20)
        self.setMinimumSize(300, 100)
    
    def get_bundle_path(self):
        """Get the correct path for bundled resources"""
        if getattr(sys, 'frozen', False):
            # Running as compiled executable
            return Path(sys._MEIPASS)
        else:
            # Running as script
            return Path(__file__).parent.parent
    
    def load_stylesheet(self):
        """Load external stylesheet"""
        try:
            paths_to_try = [
                self.stylesheet_path,
                Path(__file__).parent.parent / "styles" / "gesture_ocr_modern.qss",
                Path.cwd() / "styles" / "gesture_ocr_modern.qss",
                Path.cwd() / "gesture_ocr_modern.qss",
            ]
            
            for path in paths_to_try:
                if path and Path(path).exists():
                    with open(path, 'r') as f:
                        stylesheet = f.read()
                    self.setStyleSheet(stylesheet)
                    print(f"✅ Stylesheet loaded from: {path}")
                    return
            
            print(f"⚠️ Stylesheet not found. Using default styling.")
        except Exception as e:
            print(f"⚠️ Failed to load stylesheet: {e}")
    
    def get_icon_path(self, icon_name, theme=None):
        """Get the icon path for a given icon name and theme"""
        if theme is None:
            theme = self.current_theme
        
        # Map theme names to folder names
        theme_folder = {
            "dark": "black",
            "green": "green",
            "blue": "blue"
        }.get(theme, "black")
        
        # Try multiple possible paths
        possible_paths = [
            # Path relative to script directory (modules folder)
            self.script_dir / "icons" / theme_folder / f"{icon_name}.svg",
            # Path relative to script parent (project root)
            self.script_dir.parent / "icons" / theme_folder / f"{icon_name}.svg",
            # Path relative to current working directory
            Path.cwd() / "icons" / theme_folder / f"{icon_name}.svg",
        ]
        
        # Also try PNG as fallback
        for ext in [".svg", ".png"]:
            for path in possible_paths:
                path_with_ext = path.with_suffix(ext)
                if path_with_ext.exists():
                    print(f"✅ Found icon: {path_with_ext}")
                    return path_with_ext
        
        print(f"⚠️ Icon not found: {icon_name} for theme {theme}")
        print(f"   Searched in: {[str(p) for p in possible_paths]}")
        return None
    
    def load_icon(self, icon_name, theme=None):
        """Load an SVG/PNG icon for the given theme"""
        if theme is None:
            theme = self.current_theme
        
        cache_key = f"{theme}_{icon_name}"
        if cache_key in self.icon_cache:
            return self.icon_cache[cache_key]
        
        icon_path = self.get_icon_path(icon_name, theme)
        
        if icon_path and icon_path.exists():
            try:
                # Load as QIcon
                icon = QIcon(str(icon_path))
                if not icon.isNull():
                    self.icon_cache[cache_key] = icon
                    print(f"✅ Loaded icon: {icon_path}")
                    return icon
                else:
                    print(f"⚠️ Icon is null: {icon_path}")
            except Exception as e:
                print(f"⚠️ Failed to load icon {icon_name}: {e}")
        
        # Icon not found or failed to load
        self.icon_cache[cache_key] = None
        return None
    
    def update_button_icons(self):
        """Update send and stop button icons based on current theme"""
        # Load send icon
        send_icon = self.load_icon("send", self.current_theme)
        if send_icon:
            self.send_button.setIcon(send_icon)
            self.send_button.setText("")
            self.send_button.setIconSize(QSize(24, 24))
        else:
            self.send_button.setText("Send")
            self.send_button.setIcon(QIcon())
        
        # Load stop icon
        stop_icon = self.load_icon("stop", self.current_theme)
        if stop_icon:
            self.stop_button.setIcon(stop_icon)
            self.stop_button.setText("")
            self.stop_button.setIconSize(QSize(24, 24))
        else:
            self.stop_button.setText("Stop")
            self.stop_button.setIcon(QIcon())
    
    def apply_theme(self, theme):
        """Apply theme by setting object property and forcing stylesheet re-evaluation"""
        self.current_theme = theme
        self.setProperty("theme", theme)
        
        # Force stylesheet re-evaluation on entire widget tree
        self.style().unpolish(self)
        self.style().polish(self)
        
        # Re-apply stylesheet to force selector re-matching with new property
        current_sheet = self.styleSheet()
        self.setStyleSheet("")
        self.setStyleSheet(current_sheet)
        
        # Update button icons for the new theme
        self.update_button_icons()
    
    def setup_ui(self):
        """Setup the main UI components - IMPROVED VERSION with circular theme buttons & better opacity slider"""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.glass_widget = QWidget()
        self.glass_widget.setObjectName("glassWidget")
        glass_layout = QVBoxLayout(self.glass_widget)
        glass_layout.setContentsMargins(0, 0, 0, 0)
        glass_layout.setSpacing(0)
        
        # ============================================================================
        # HEADER WITH IMPROVED OPACITY SLIDER & CIRCULAR THEME BUTTONS
        # ============================================================================
        header_widget = QWidget()
        header_widget.setObjectName("header")
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(15, 10, 15, 10)
        header_layout.setSpacing(8)
        
        # Use bundle path for logo
        logo_path = str(self.bundle_path / "icons" / "fullLogo.svg")
        title_label = QSvgWidget(logo_path)
        title_label.setObjectName("titleLabel")
        title_label.setFixedSize(135, 34)

        header_layout.addWidget(title_label)
        header_layout.addStretch()
        
        # ✅ IMPROVED: Brightness/Opacity Control Container
        brightness_container = QWidget()
        brightness_container.setObjectName("brightnessContainer")
        brightness_layout = QHBoxLayout(brightness_container)
        brightness_layout.setContentsMargins(0, 0, 0, 0)
        brightness_layout.setSpacing(6)
        
        # Brightness icon
        sun_icon_path = str(self.bundle_path / "icons" / "sun.svg")
        brightness_icon = QSvgWidget(sun_icon_path)
        brightness_icon.setObjectName("brightnessIcon")
        brightness_icon.setFixedSize(16, 16)

        brightness_layout.addWidget(brightness_icon)
        
        # ✅ IMPROVED: Opacity slider - LARGER and more visible
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setObjectName("opacitySlider")
        self.opacity_slider.setMinimum(20)
        self.opacity_slider.setMaximum(100) 
        self.opacity_slider.setValue(100)
        self.opacity_slider.setMaximumWidth(70)  # ✅ Increased from 60px
        self.opacity_slider.setToolTip("Adjust Window Opacity (20-100%)")
        self.opacity_slider.valueChanged.connect(self.update_window_opacity)
        brightness_layout.addWidget(self.opacity_slider)
        
        # ✅ NEW: Percentage display
        self.opacity_label = QLabel("100%")
        self.opacity_label.setObjectName("opacityPercentage")
        self.opacity_label.setToolTip("Current Opacity")
        self.opacity_label.setMinimumWidth(30)
        self.opacity_slider.valueChanged.connect(
            lambda v: self.opacity_label.setText(f"{v}%")
        )
        brightness_layout.addWidget(self.opacity_label)
        
        header_layout.addWidget(brightness_container)
        
        # ✅ IMPROVED: Circular Theme Buttons (Dark, Green, Blue)
        self.theme_buttons = []
        themes = [
            ("dark", "🌙 Dark Mode"),
            ("green", "🌿 Alien Green"),
            ("blue", "💙 Futuristic Blue")
        ]
        
        for theme_name, tooltip in themes:
            btn = QPushButton("●")
            btn.setObjectName(f"themeBtn-{theme_name}")
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda checked, t=theme_name: self.apply_theme(t))
            self.theme_buttons.append(btn)
            header_layout.addWidget(btn)
        
        # Minimize button
        self.minimize_btn = QPushButton("−")  # Minus sign
        self.minimize_btn.setObjectName("minimizeButton")
        self.minimize_btn.setToolTip("Minimize (Shift+click to close)")
        self.minimize_btn.clicked.connect(self.minimize_window)
        header_layout.addWidget(self.minimize_btn)
        
        glass_layout.addWidget(header_widget)
        
        # Separator line
        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        glass_layout.addWidget(separator)
        
        # ============================================================================
        # CONTENT AREA (Messages)
        # ============================================================================
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
        
        # Message container
        self.message_container = QWidget()
        self.message_container.setObjectName("messageContainer")
        self.message_layout = QVBoxLayout(self.message_container)
        self.message_layout.setContentsMargins(0, 0, 0, 0)
        self.message_layout.setSpacing(12)
        self.message_layout.addStretch()
        
        self.scroll_area.setWidget(self.message_container)
        content_layout.addWidget(self.scroll_area)
        
        # ============================================================================
        # INPUT AREA (Text field + Model selector + Buttons)
        # ============================================================================
        input_container = QWidget()
        input_container.setObjectName("inputContainer")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(8, 0, 8, 0)
        input_layout.setSpacing(5)
        # Text input field
        self.input_field = QLineEdit()
        self.input_field.setObjectName("inputField")
        self.input_field.setPlaceholderText("Ask a question...")
        self.input_field.returnPressed.connect(self.send_input_message)
        input_layout.addWidget(self.input_field, stretch=1)
        # Model selector dropdown
        self.model_selector = QComboBox()
        self.model_selector.setObjectName("modelSelector")

        # ✅ Add models with clear labels showing which is which
        self.model_selector.addItems([
            "qwen3.6-27b",
            "Qwen3:4b-instruct",
            "Qwen2.5-coder:3b"
        ])

        self.model_selector.setCurrentIndex(0)  # Default to Groq 27B
        self.model_selector.setMaximumWidth(200)  # Wider to fit text
        self.model_selector.setToolTip("Select AI Model (Groq primary, Ollama fallback)")

        # Add the change handler
        self.model_selector.currentTextChanged.connect(self.on_model_changed)
        input_layout.addWidget(self.model_selector, stretch=0)
        
        # Stop button
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        self.stop_button.clicked.connect(self.stop_ai_generation)
        self.stop_button.setVisible(False)
        input_layout.addWidget(self.stop_button, stretch=0)
        
        # Send button
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(self.send_input_message)
        input_layout.addWidget(self.send_button, stretch=0)
        
        self.input_container_widget = input_container
        content_layout.addWidget(input_container)
        
        glass_layout.addWidget(content_widget)
        
        # Footer hidden (not used)
        self.status_label = None
        self.copy_btn = None
        self.clear_btn = None
        
        main_layout.addWidget(self.glass_widget)
        
        # Set default window size
        self.resize(*self.normal_size)
        
        # Setup dragging
        self.drag_position = None
        self.glass_widget.mousePressEvent = self.mouse_press_event
        self.glass_widget.mouseMoveEvent = self.mouse_move_event
        
        # Resize grip
        self.resize_grip_tl = QSizeGrip(self.glass_widget)  # Top-Left
        self.resize_grip_tr = QSizeGrip(self.glass_widget)  # Top-Right
        self.resize_grip_bl = QSizeGrip(self.glass_widget)  # Bottom-Left
        self.resize_grip_br = QSizeGrip(self.glass_widget) 

        self.resize_grip_tl.move(0, 0)
        self.resize_grip_tr.move(self.width() - 20, 0)  # 20px is default size
        self.resize_grip_bl.move(0, self.height() - 20)
        self.resize_grip_br.move(self.width() - 20, self.height() - 20)

    def update_window_opacity(self, value):
        """Update window opacity based on slider value"""
        self.window_opacity = value / 100.0
        self.setWindowOpacity(self.window_opacity)
    
    def set_detector(self, detector):
        """Set reference to gesture detector for clipboard clearing"""
        self.gesture_detector = detector
    
    def get_selected_model(self):
        """Get the currently selected model from the dropdown"""
        return self.model_selector.currentText()
    
    def setup_animations(self):
        self.fade_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fade_effect)
        self.fade_effect.setOpacity(0)
        
        self.fade_animation = QPropertyAnimation(self.fade_effect, b"opacity")
        self.fade_animation.setDuration(300)
        self.fade_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
    
    def show_with_animation(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.is_visible = True
        self.fade_animation.setStartValue(0)
        self.fade_animation.setEndValue(1)
        self.fade_animation.start()
    
    def hide_with_animation(self):
        self.fade_animation.setStartValue(1)
        self.fade_animation.setEndValue(0)
        self.fade_animation.finished.connect(self._hide_complete)
        self.fade_animation.start()
    
    def _hide_complete(self):
        self.hide()
        self.is_visible = False
        self.fade_animation.finished.disconnect(self._hide_complete)
    
    def minimize_window(self):
        """Minimize window - hides without clearing content"""
        print(f"🔍 DEBUG: minimize_window() called")
        # Just hide - DON'T clear clipboard here, let gesture_detector handle it
        self.hide_with_animation()
    
    def close_window(self):
        """Close window - clears content and hides"""
        self.ai_started = False
        self.ai_content = None
        self.ai_message = None
        self.ai_plain_text = ""
        self.ai_segments = []
        self.input_field.clear()
        self.stop_button.setVisible(False)
        self.send_button.setVisible(True)
        
        # Just fade out and close
        self.hide_with_animation()
    
    def set_small_mode(self, enabled=True): 
        """Toggle between small input-only mode and normal mode - IMMEDIATE resize"""
        if enabled:
            self.is_small_mode = True
            self.scroll_area.hide()
            self.input_field.setPlaceholderText("No text detected. Type here...")
            
            # IMMEDIATE resize
            self.resize(*self.small_size)
            
            # Enforce size constraints
            self.setMinimumSize(*self.small_size)
            self.setMaximumSize(self.small_size[0], self.small_size[1])
            
        else:
            self.is_small_mode = False
            self.scroll_area.show()
            self.input_field.setPlaceholderText("Ask a question...")
            
            # IMMEDIATE resize
            self.resize(*self.normal_size)
            
            # Reset size constraints
            self.setMinimumSize(300, 100)
            self.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX) 
            self.resize(*self.normal_size)
            
            # Force layout recalc
            self.layout().activate()
            self.update() 

    def format_text_with_highlighting(self, text):
        """Format text with semantic highlighting (code blocks handled separately)."""
        # Escape any raw < > in text
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Inline backtick code
        text = re.sub(
            r'`([^`]+)`',
            r'<code style="color: #58a6ff; background: rgba(88,166,255,0.1); '
            r'padding: 1px 5px; border-radius: 3px; font-family: monospace; font-size: 13px;">\1</code>',
            text
        )
        
        # Bold **text**
        text = re.sub(
            r'\*\*([^*]+)\*\*',
            r'<b style="color: #e6edf3;">\1</b>',
            text
        )
        
        # Italic *text*
        text = re.sub(
            r'\*([^*]+)\*',
            r'<i style="color: #a0aec0;">\1</i>',
            text
        )
        
        # Newlines → <br/>
        text = text.replace('\n', '<br/>')
        
        return text
    
    def _highlight_code_block(self, code, lang):
        """Highlight code block with syntax awareness"""
        if lang.lower() == 'python' or not lang:
            return self._highlight_python(code)
        elif lang.lower() in ['java', 'c', 'cpp', 'c++', 'javascript', 'js']:
            return self._highlight_java_like(code)
        elif lang.lower() in ['sql']:
            return self._highlight_sql(code)
        else:
            return code
    
    def _apply_spans(self, code, patterns):
        """Safe span applicator."""
        segments = [('text', code)]
        
        for pattern, span_fn in patterns:
            new_segments = []
            for kind, content in segments:
                if kind == 'html':
                    new_segments.append(('html', content))
                    continue
                last = 0
                for m in pattern.finditer(content):
                    if m.start() > last:
                        new_segments.append(('text', content[last:m.start()]))
                    new_segments.append(('html', span_fn(m)))
                    last = m.end()
                if last < len(content):
                    new_segments.append(('text', content[last:]))
            segments = new_segments
        
        parts = []
        for kind, content in segments:
            if kind == 'text':
                parts.append(content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
            else:
                parts.append(content)
        return ''.join(parts)

    def _highlight_python(self, code):
        """Highlight Python code"""
        keywords = [
            'def', 'class', 'import', 'from', 'return', 'if', 'else', 'elif',
            'for', 'while', 'try', 'except', 'finally', 'with', 'as', 'in',
            'is', 'not', 'and', 'or', 'True', 'False', 'None', 'lambda',
            'yield', 'pass', 'break', 'continue', 'raise', 'assert', 'del',
            'global', 'nonlocal', 'async', 'await', 'self'
        ]
        
        patterns = []
        patterns.append((
            re.compile(r'(#[^\n]*)'),
            lambda m: f'<span style="color:#8B949E; font-style:italic;">{m.group(1).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</span>'
        ))
        patterns.append((
            re.compile(r'"([^"\n]*)"'),
            lambda m: f'<span style="color:#A5D6FF;">&quot;{m.group(1).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}&quot;</span>'
        ))
        patterns.append((
            re.compile(r"'([^'\n]*)'"),
            lambda m: f"<span style=\"color:#A5D6FF;\">'{m.group(1).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')}'</span>"
        ))
        patterns.append((
            re.compile(r'\b(\d+)\b'),
            lambda m: f'<span style="color:#79C0FF;">{m.group(1)}</span>'
        ))
        kw_pattern = re.compile(r'\b(' + '|'.join(re.escape(k) for k in keywords) + r')\b')
        patterns.append((
            kw_pattern,
            lambda m: f'<span style="color:#FF7B72; font-weight:600;">{m.group(1)}</span>'
        ))
        
        result = self._apply_spans(code, patterns)
        return result
    
    def _highlight_java_like(self, code):
        """Highlight Java/C/C++/JS"""
        keywords = [
            'public', 'private', 'protected', 'static', 'final', 'class', 'interface',
            'extends', 'implements', 'new', 'return', 'if', 'else', 'for', 'while',
            'try', 'catch', 'finally', 'throw', 'throws', 'void', 'int', 'String',
            'boolean', 'double', 'float', 'long', 'byte', 'char', 'function', 'const',
            'let', 'var', 'async', 'await', 'import', 'package', 'null', 'true', 'false',
            'this', 'super', 'instanceof', 'switch', 'case', 'break', 'continue', 'default'
        ]
        
        patterns = []
        patterns.append((
            re.compile(r'(//[^\n]*)'),
            lambda m: f'<span style="color:#8B949E; font-style:italic;">{m.group(1).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}</span>'
        ))
        patterns.append((
            re.compile(r'"([^"\n]*)"'),
            lambda m: f'<span style="color:#A5D6FF;">&quot;{m.group(1).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")}&quot;</span>'
        ))
        patterns.append((
            re.compile(r'\b(\d+)\b'),
            lambda m: f'<span style="color:#79C0FF;">{m.group(1)}</span>'
        ))
        kw_pattern = re.compile(r'\b(' + '|'.join(re.escape(k) for k in keywords) + r')\b')
        patterns.append((
            kw_pattern,
            lambda m: f'<span style="color:#FF7B72; font-weight:600;">{m.group(1)}</span>'
        ))
        
        result = self._apply_spans(code, patterns)
        return result
    
    def _highlight_sql(self, code):
        """Highlight SQL"""
        keywords = [
            'SELECT', 'FROM', 'WHERE', 'INSERT', 'INTO', 'UPDATE', 'SET', 'DELETE',
            'CREATE', 'DROP', 'ALTER', 'TABLE', 'JOIN', 'INNER', 'LEFT', 'RIGHT',
            'OUTER', 'ON', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'ORDER', 'BY',
            'GROUP', 'HAVING', 'LIMIT', 'OFFSET', 'AS', 'DISTINCT', 'COUNT',
            'SUM', 'AVG', 'MAX', 'MIN', 'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES',
            'INDEX', 'VALUES', 'NULL', 'IS', 'BETWEEN', 'EXISTS', 'UNION', 'ALL'
        ]
        
        patterns = []
        patterns.append((
            re.compile(r"'([^']*)'"),
            lambda m: f"<span style=\"color:#A5D6FF;\">'{m.group(1).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')}'</span>"
        ))
        kw_pattern = re.compile(r'\b(' + '|'.join(re.escape(k) for k in keywords) + r')\b', re.IGNORECASE)
        patterns.append((
            kw_pattern,
            lambda m: f'<span style="color:#FF7B72; font-weight:600;">{m.group(1).upper()}</span>'
        ))
        
        result = self._apply_spans(code, patterns)
        return result
    
    def create_user_message_widget(self, text, is_truncated=False, full_text=None):
        """Create a user message widget"""
        message_widget = QWidget()
        message_widget.setObjectName("userMessageWrapper")
        
        main_layout = QHBoxLayout(message_widget)
        main_layout.setContentsMargins(0, 2, 0, 2)
        main_layout.setSpacing(0)
        
        main_layout.addStretch()
        
        bubble_widget = QWidget()
        bubble_widget.setObjectName("userBubble")
        bubble_widget.setMaximumWidth(int(self.scroll_area.width() * 0.85))
        bubble_layout = QVBoxLayout(bubble_widget)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(2)
        
        content = QLabel(text)
        content.setWordWrap(True)
        content.setTextFormat(Qt.TextFormat.PlainText)
        content.setObjectName("userMessageContent")
        bubble_layout.addWidget(content)
        
        if is_truncated and full_text:
            show_more_btn = QPushButton("Show more...")
            show_more_btn.setObjectName("showMoreButton")
            show_more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            
            def toggle_expand():
                if show_more_btn.text() == "Show more...":
                    content.setText(full_text)
                    show_more_btn.setText("Show less")
                else:
                    content.setText(full_text[:500] + "...")
                    show_more_btn.setText("Show more...")
            
            show_more_btn.clicked.connect(toggle_expand)
            bubble_layout.addWidget(show_more_btn)
        
        main_layout.addWidget(bubble_widget)
        
        return message_widget, content
    
    def create_ai_message_widget(self, text=""):
        """Create an AI message widget with support for separate code block widgets"""
        self.ai_plain_text = text
        self.ai_segments = []  # reset diff-tracking state
        
        message_widget = QWidget()
        message_widget.setObjectName("aiMessageWrapper")
        message_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        main_layout = QVBoxLayout(message_widget)
        main_layout.setContentsMargins(0, 2, 0, 2)
        main_layout.setSpacing(4)
        
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        
        # AI icon
        ai_icon_path = str(self.bundle_path / "icons" / "Xcursor.svg")
        star_label = QSvgWidget(ai_icon_path)
        star_label.setObjectName("aiStarIcon")
        star_label.setFixedSize(16, 16)
        
        header_layout.addWidget(star_label)
        header_layout.addStretch()
        
        main_layout.addLayout(header_layout)
        
        # Content layout - will hold both text and code blocks as separate widgets
        self.ai_content_layout = QVBoxLayout()
        self.ai_content_layout.setContentsMargins(0, 0, 0, 0)
        self.ai_content_layout.setSpacing(2)
        main_layout.addLayout(self.ai_content_layout)
        main_layout.addStretch()
        
        # ❌ REMOVE the initial QLabel creation ❌
        # Don't add any widget - let _render_ai_content() handle it
        self.ai_content = None  # Mark as empty
        
        # Immediately render the initial text (which will create the proper widget)
        if text:
            self._render_ai_content(text)
        
        return message_widget, None
    
    def add_user_message(self, text):
        """Add user message to the chat"""
        self.conversation_history.append(("user", text))
        if self.is_small_mode:
            self.set_small_mode(False)
        
        full_text = text
        
        display_text = text
        is_truncated = False
        if len(text) > 500:
            display_text = text[:500] + "..."
            is_truncated = True
        
        message, content = self.create_user_message_widget(display_text, is_truncated=is_truncated, full_text=full_text)
        self.message_layout.insertWidget(self.message_layout.count() - 1, message)
        QTimer.singleShot(50, self.scroll_to_bottom)
        
        self.ai_message, self.ai_content = self.create_ai_message_widget("Thinking...")
        self.message_layout.insertWidget(self.message_layout.count() - 1, self.ai_message)
        self.ai_started = True
        
        # Show stop button, hide send button
        self.stop_button.setVisible(True)
        self.send_button.setVisible(False)
        
        self.cmd_queue.queue.put(('ai_analyze', text, None))
    
    def add_ai_token(self, token):
        """Add AI token to current message with smart auto-scroll"""
        if not self.ai_started:
            return
        
        if self.ai_plain_text == "Thinking...":
            self.ai_plain_text = token
        else:
            self.ai_plain_text += token
        
        # Render the updated content - will diff against existing segments
        self._render_ai_content(self.ai_plain_text)  # ✅ No duplicate widgets
        
        # Smart scroll...
        scrollbar = self.scroll_area.verticalScrollBar()
        is_at_bottom = scrollbar.value() >= (scrollbar.maximum() - 5)
        
        if is_at_bottom:
            QTimer.singleShot(50, self.scroll_to_bottom)

    # ------------------------------------------------------------------
    # Segment parsing / widget helpers used by the diff-based renderer
    # ------------------------------------------------------------------

    def _parse_segments(self, text):
        """Parse text into an ordered list of {'type': 'text'|'code', ...} dicts.
        Pure parsing - no widget creation here, so it's cheap to call on
        every token and safe to diff against the previous result."""
        code_blocks = []
        code_pattern = r'```(\w*)\n?(.*?)```'

        def code_replacer(match):
            lang = match.group(1) or ''
            code = match.group(2)
            code_blocks.append((lang, code))
            return f"__CODE_BLOCK_{len(code_blocks)-1}__"

        text_with_placeholders = re.sub(code_pattern, code_replacer, text, flags=re.DOTALL)
        parts = re.split(r'(__CODE_BLOCK_\d+__)', text_with_placeholders)

        segments = []
        for part in parts:
            if part.startswith('__CODE_BLOCK_'):
                idx = int(part.replace('__CODE_BLOCK_', '').replace('__', ''))
                lang, code = code_blocks[idx]
                segments.append({'type': 'code', 'lang': lang, 'content': code})
            elif part.strip():
                segments.append({'type': 'text', 'content': part})
        return segments

    def _wrap_code_html(self, highlighted_code):
        return (
            f'<pre style="'
            f'margin:14px 0;'
            f'padding:18px 20px;'
            f'background:#0D1117;'
            f'border:1px solid #30363D;'
            f'border-radius:12px;'
            f'font-family:Menlo, Monaco, Consolas, "Liberation Mono", monospace;'
            f'font-size:14px;'
            f'line-height:1.75;'
            f'letter-spacing:0;'
            f'color:#E6EDF3;'
            f'white-space:pre;'
            f'overflow:auto;'
            f'">{highlighted_code}</pre>'
        )

    def _create_segment_widget(self, seg):
        """Create a brand-new widget for a segment that has no prior widget."""
        if seg['type'] == 'code':
            highlighted = self._highlight_code_block(seg['content'], seg['lang'])
            return CodeBlockWidget(self._wrap_code_html(highlighted))
        else:
            label = QLabel()
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setOpenExternalLinks(False)
            label.setObjectName("aiMessageContent")
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(0)
            label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            label.setText(self.format_text_with_highlighting(seg['content']))
            return label

    def _update_segment_widget(self, widget, seg):
        """Update an existing widget in place instead of recreating it."""
        if seg['type'] == 'code':
            highlighted = self._highlight_code_block(seg['content'], seg['lang'])
            widget.set_html(self._wrap_code_html(highlighted))
        else:
            widget.setText(self.format_text_with_highlighting(seg['content']))

    def _render_ai_content(self, text):
        """Diff-based render of the streaming AI reply.

        The old implementation deleted every widget in ai_content_layout and
        rebuilt all of them from scratch on every single token - including
        code blocks that had already finished rendering. That caused the
        finished code block to be destroyed/recreated (with a forced
        synchronous repaint) each time trailing text after it changed,
        which is what produced the up/down flicker.

        This version parses the text into segments, and only touches the
        widgets whose underlying segment actually changed:
          - identical segment  -> widget left completely alone
          - same type, changed content -> update the existing widget in place
          - different type at that index -> delete old widget, create new one
          - new segment beyond old length -> create and append
        """
        new_segments = self._parse_segments(text)
        old_segments = self.ai_segments

        self.message_container.setUpdatesEnabled(False)
        try:
            rebuilt = []
            for i, new_seg in enumerate(new_segments):
                if i < len(old_segments):
                    old_seg = old_segments[i]
                    if old_seg['type'] == new_seg['type'] and old_seg['content'] == new_seg['content']:
                        # No change at all - reuse old dict (has the widget ref), skip touching UI
                        rebuilt.append(old_seg)
                        continue
                    if old_seg['type'] == new_seg['type']:
                        # Same kind of segment, content grew/changed -> update in place
                        self._update_segment_widget(old_seg['widget'], new_seg)
                        new_seg['widget'] = old_seg['widget']
                        rebuilt.append(new_seg)
                        continue
                    # Segment type changed at this index (rare) -> replace widget
                    self.ai_content_layout.removeWidget(old_seg['widget'])
                    old_seg['widget'].deleteLater()

                # No prior widget for this index -> create new one
                widget = self._create_segment_widget(new_seg)
                new_seg['widget'] = widget
                self.ai_content_layout.addWidget(widget)
                rebuilt.append(new_seg)

            # If segment count somehow shrank, clean up leftovers
            for old_seg in old_segments[len(new_segments):]:
                self.ai_content_layout.removeWidget(old_seg['widget'])
                old_seg['widget'].deleteLater()

            self.ai_segments = rebuilt
            self.ai_content = None
        finally:
            self.message_container.setUpdatesEnabled(True)
    
    def finish_ai_response(self):
        """Finish AI response and clean up"""
        # Check if we have empty response
        if self.ai_plain_text == "Thinking..." or not self.ai_plain_text:
            if self.ai_message:
                self.message_layout.removeWidget(self.ai_message)
                self.ai_message.deleteLater()
                self.ai_message = None
                self.ai_content = None
                self.ai_plain_text = ""
                self.ai_segments = []
                self.ai_started = False
                self.stop_button.setVisible(False)
                self.send_button.setVisible(True)
                return
        
        # Store AI response in conversation history
        self.conversation_history.append(("ai", self.ai_plain_text))
        
        # Content already rendered by _render_ai_content, nothing more to do
        self.ai_started = False
        self.ai_message = None
        self.ai_content = None
        self.ai_plain_text = ""
        self.ai_segments = []
        
        self.message_layout.invalidate()
        self.scroll_area.widget().layout().invalidate()
        
        # Hide stop button, show send button
        self.stop_button.setVisible(False)
        self.send_button.setVisible(True)
        
        QTimer.singleShot(50, self.scroll_to_bottom)
    
    def scroll_to_bottom(self):
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def send_input_message(self):
        text = self.input_field.text().strip()
        print(f"DEBUG: is_small_mode={self.is_small_mode}, text='{text}'")
        if not text:
            return
        
        if self.is_small_mode:
            print("DEBUG: Calling set_small_mode(False)")
            self.set_small_mode(False)
            print(f"DEBUG: After set_small_mode(False): is_small_mode={self.is_small_mode}")
            QTimer.singleShot(100, lambda: self._send_message_after_expand(text))
        else:
            self._send_message_after_expand(text)
    
    def _send_message_after_expand(self, text):
        self.add_user_message(text)
        self.input_field.clear()
        # Clear clipboard immediately after input is sent
        if self.gesture_detector:
            self.gesture_detector.clear_clipboard_now()
            print("🧹 Clipboard cleared immediately after input")
    
    def copy_content(self):
        """Placeholder - footer removed"""
        pass
    
    def stop_ai_generation(self):
        """Stop AI generation mid-reply"""
        self.cmd_queue.queue.put(('ai_stop', None, None))
        self.finish_ai_response()
    
    def clear_content(self):
        """Clear all messages and reset to default state"""
        while self.message_layout.count() > 1:
            item = self.message_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            
        self.conversation_history = [] 
        
        self.ai_started = False
        self.ai_content = None
        self.ai_message = None
        self.ai_plain_text = ""
        self.ai_segments = []
        self.input_field.clear()
        self.stop_button.setVisible(False)
        self.send_button.setVisible(True)
    
    def set_position_from_mouse(self, x, y):
        self.last_mouse_pos = (x, y)
        window_x = max(10, x + 20)
        window_y = max(10, y + 20)
        
        screen = QApplication.primaryScreen().geometry()
        if window_x + self.width() > screen.width():
            window_x = screen.width() - self.width() - 10
        if window_y + self.height() > screen.height():
            window_y = screen.height() - self.height() - 10
        
        self.move(window_x, window_y)
    
    def mouse_press_event(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint()
    
    def mouse_move_event(self, event):
        if self.drag_position is not None:
            delta = event.globalPosition().toPoint() - self.drag_position
            new_pos = self.pos() + delta
            self.move(new_pos)
            self.drag_position = event.globalPosition().toPoint()
    
    def mouseReleaseEvent(self, event):
        self.drag_position = None
        event.accept()
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        grip_size = 20  # Default QSizeGrip size
        
        self.resize_grip_tl.move(0, 0)
        self.resize_grip_tr.move(self.width() - grip_size, 0)
        self.resize_grip_bl.move(0, self.height() - grip_size)
        self.resize_grip_br.move(self.width() - grip_size, self.height() - grip_size)
        
        # Your existing resize logic
        if not self.is_small_mode:
            self.resized.emit()

    def on_model_changed(self, model_text):
        """Handle model selection change"""
        if self.gesture_detector and hasattr(self.gesture_detector, 'Xcursor_ai'):
            ai = self.gesture_detector.Xcursor_ai
            if model_text == "qwen3.6-27b":
                ai.groq_model = "qwen/qwen3.6-27b"
                print(f"✅ Using Groq: {ai.groq_model}")
            else:
                ai.set_ollama_model(model_text)
                print(f"✅ Using Ollama: {model_text}")