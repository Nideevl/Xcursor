#!/usr/bin/env python3
"""
Gesture-Controlled OCR + Xcursor AI v2 (Modular Version)
Modern PyQt6 UI with snipping tool detection
"""
import sys
import json
import threading
from dotenv import load_dotenv
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from modules.command_queue import CommandQueue
from modules.overlay import ModernOverlay
from modules.gesture_detector import GestureDetector

load_dotenv()
class MainApplication(QApplication):
    """Main PyQt6 application"""
    
    def __init__(self, argv, stylesheet_path):
        super().__init__(argv)
        
        # Setup
        self.cmd_queue = CommandQueue()
        self.detector = GestureDetector(self.cmd_queue)
        # Create overlay with stylesheet path and detector reference
        self.overlay = ModernOverlay(self.cmd_queue, stylesheet_path)
        self.overlay.set_detector(self.detector)  # Pass detector for clipboard clearing

        self.cmd_queue.set_app(self)
        
        # Load saved window size (normal mode only, not small mode)
        self.load_window_size()
        
        # Connect overlay's resize event to save config
        self.overlay.resized.connect(self.save_window_size)
        
        # Start detector in background
        self.detector_thread = threading.Thread(target=self.detector.start, daemon=False)
        self.detector_thread.start()
        
        # Setup timer for processing commands
        self.process_timer = QTimer()
        self.process_timer.timeout.connect(self.process_commands)
        self.process_timer.start(20)  # 50fps
        
        print("✅ Application started. Waiting for gestures...")
    
    def load_window_size(self):
        """Load saved window size from config.json"""
        try:
            config_path = Path(__file__).parent / "config.json"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    saved_width = config.get('window_width')
                    saved_height = config.get('window_height')
                    
                    if saved_width and saved_height:
                        # UPDATE normal_size so set_small_mode(False) uses the saved size!
                        self.overlay.normal_size = (saved_width, saved_height)
                        self.overlay.resize(saved_width, saved_height)
                        print(f"✅ Window size restored: {saved_width}x{saved_height}")
        except Exception as e:
            print(f"⚠️ Could not load window size: {e}")
    
    def save_window_size(self):
        """Save current window size to config.json"""
        try:
            # Only save if NOT in small mode (small mode size is fixed)
            if not self.overlay.is_small_mode:
                config_path = Path(__file__).parent / "config.json"
                width = self.overlay.width()
                height = self.overlay.height()
                
                # Update in-memory normal_size so it persists until next app restart
                self.overlay.normal_size = (width, height)
                
                # Load existing config or create new
                config = {}
                if config_path.exists():
                    with open(config_path, 'r') as f:
                        config = json.load(f)
                
                # Update size (keep other settings)
                config['window_width'] = width
                config['window_height'] = height
                
                # Save config
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=2)
                
                print(f"💾 Window size saved: {width}x{height}")
        except Exception as e:
            print(f"⚠️ Could not save window size: {e}")
    
    def process_commands(self):
        """Process commands from queue in main thread"""
        cmd = self.cmd_queue.get_command()
        if cmd:
            cmd_type = cmd[0]
            print(f"🔍 DEBUG: Processing command: {cmd_type}")
            
            if cmd_type == 'show':
                text = cmd[1]
                pos = cmd[2] if len(cmd) > 2 else None
                is_empty = cmd[3] if len(cmd) > 3 else False
                
                if pos:
                    self.overlay.set_position_from_mouse(pos[0], pos[1])
                
                if self.overlay.is_small_mode:
                    self.overlay.set_small_mode(False)
                
                self.overlay.clear_content()
                self.overlay.add_user_message(text)
                self.overlay.show_with_animation()
                self.overlay.input_field.setFocus()
                # AI is triggered inside add_user_message
            
            elif cmd_type == 'show_input':
                pos = cmd[2] if len(cmd) > 2 else None
                
                if pos:
                    self.overlay.set_position_from_mouse(pos[0], pos[1])
                
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
                
                # Handle the token
                if final:
                    self.overlay.finish_ai_response()
                else:
                    # Only add token if it's meaningful content
                    if token and token.strip():
                        self.overlay.add_ai_token(token)
                    elif token == '\n':
                        # Allow newlines for formatting
                        self.overlay.add_ai_token(token)
            
            elif cmd_type == 'clear':
                self.overlay.clear_content()
                self.overlay.hide_with_animation()
            
            elif cmd_type == 'minimize':
                print(f"🔍 DEBUG: minimize command received")
                # ✅ STOP AI BEFORE MINIMIZING (for horizontal gesture)
                if self.overlay.ai_started:
                    print("🛑 Stopping AI due to gesture minimize")
                    self.detector.Xcursor_ai.stop_streaming()
                    self.overlay.finish_ai_response()
                self.overlay.minimize_window() 

            elif cmd_type == 'show_existing':
                print(f"🔍 DEBUG: show_existing - showing overlay without clearing")
                self.overlay.show_with_animation()  # Just show, don't clear
                self.overlay.input_field.setFocus()
    
    def _stream_ai(self, text):
        """Stream AI response for text with selected model"""
        def stream_ai():
            def on_token(token):
                self.cmd_queue.add_ai_token(token)
            
            def on_done():
                self.cmd_queue.add_ai_token("", final=True)
            
            # Get selected model from overlay dropdown
            selected_model = self.overlay.get_selected_model()
            print(f"🤖 Using model: {selected_model}")
            
            # Pass the selected model to analyze_streaming
            self.detector.Xcursor_ai.analyze_streaming(
                text, 
                on_token, 
                on_done, 
                model=selected_model,
                conversation_history=self.overlay.conversation_history  # ADD THIS
            )
        
        thread = threading.Thread(target=stream_ai, daemon=True)
        thread.start()

    def is_overlay_visible(self):
        """Check if overlay is visible"""
        visible = self.overlay.is_visible
        print(f"🔍 DEBUG: is_overlay_visible() returning {visible}")
        return visible

def main():
    """Main entry point"""
    # Find stylesheet path
    stylesheet_path = Path(__file__).parent / "styles" / "gesture_ocr_modern.qss"
    if not stylesheet_path.exists():
        stylesheet_path = Path.cwd() / "gesture_ocr_modern.qss"
    
    if not stylesheet_path.exists():
        print(f"⚠️ Warning: Stylesheet not found at {stylesheet_path}")
        print("Make sure gesture_ocr_modern.qss is in the styles directory")
        # Create a default stylesheet if it doesn't exist
        create_default_stylesheet(stylesheet_path)
    
    app = MainApplication(sys.argv, str(stylesheet_path))
    sys.exit(app.exec())

def create_default_stylesheet(path):
    """Create a default stylesheet if one doesn't exist"""
    default_stylesheet = """
/* Modern Glass-morphism Stylesheet for Gesture OCR Overlay */

#glassWidget {
    background: rgba(20, 22, 27, 0.85);
    border-radius: 12px;
    border: 1px solid rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
}

#header {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 12px 12px 0 0;
}

#titleLabel {
    color: #e6edf3;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

#headerButton {
    background: rgba(255, 255, 255, 0.05);
    border: none;
    border-radius: 6px;
    color: #8b949e;
    font-size: 14px;
    font-weight: 600;
    padding: 0px;
}

#headerButton:hover {
    background: rgba(255, 255, 255, 0.1);
    color: #e6edf3;
}

#headerButton:pressed {
    background: rgba(255, 255, 255, 0.15);
}

#separator {
    background: rgba(255, 255, 255, 0.05);
}

#content {
    background: transparent;
}

#scrollArea {
    background: transparent;
    border: none;
}

#scrollArea QScrollBar:vertical {
    background: rgba(255, 255, 255, 0.02);
    border: none;
    width: 8px;
    border-radius: 4px;
    margin: 2px;
}

#scrollArea QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 0.15);
    border-radius: 4px;
    min-height: 20px;
}

#scrollArea QScrollBar::handle:vertical:hover {
    background: rgba(255, 255, 255, 0.25);
}

#scrollArea QScrollBar::add-line:vertical, 
#scrollArea QScrollBar::sub-line:vertical {
    border: none;
    background: none;
}

#messageContainer {
    background: transparent;
}

#userMessage, #aiMessage {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
    padding: 8px 12px;
    margin: 0px;
}

#userMessage {
    border-left: 3px solid #58a6ff;
}

#aiMessage {
    border-left: 3px solid #00d9ff;
}

#inputContainer {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 0.06);
}

#inputField {
    background: transparent;
    border: none;
    color: #e6edf3;
    font-size: 14px;
    padding: 6px 0px;
    selection-background-color: rgba(88, 166, 255, 0.3);
}

#inputField:focus {
    outline: none;
}

#inputField::placeholder {
    color: #484f58;
}

#modelSelector {
    background: rgba(88, 166, 255, 0.1);
    border: 1px solid rgba(88, 166, 255, 0.2);
    border-radius: 4px;
    color: #e6edf3;
    font-size: 12px;
    padding: 2px 8px;
    selection-background-color: rgba(88, 166, 255, 0.3);
}

#modelSelector:hover {
    background: rgba(88, 166, 255, 0.15);
}

#modelSelector:focus {
    outline: none;
    border: 1px solid rgba(88, 166, 255, 0.4);
}

#modelSelector QAbstractItemView {
    background: rgba(20, 22, 27, 0.95);
    color: #e6edf3;
    border: 1px solid rgba(88, 166, 255, 0.2);
    border-radius: 4px;
    selection-background-color: rgba(88, 166, 255, 0.3);
}

#sendButton {
    background: rgba(88, 166, 255, 0.15);
    border: 1px solid rgba(88, 166, 255, 0.2);
    border-radius: 6px;
    color: #58a6ff;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px;
}

#sendButton:hover {
    background: rgba(88, 166, 255, 0.25);
    border-color: rgba(88, 166, 255, 0.3);
}

#sendButton:pressed {
    background: rgba(88, 166, 255, 0.35);
}

#stopButton {
    background: rgba(255, 127, 114, 0.15);
    border: 1px solid rgba(255, 127, 114, 0.2);
    border-radius: 6px;
    color: #ff7f72;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 12px;
}

#stopButton:hover {
    background: rgba(255, 127, 114, 0.25);
    border-color: rgba(255, 127, 114, 0.3);
}

#stopButton:pressed {
    background: rgba(255, 127, 114, 0.35);
}

#footer {
    background: rgba(255, 255, 255, 0.02);
    border-radius: 0 0 12px 12px;
}

#statusLabel {
    color: #4ade80;
    font-size: 12px;
    font-weight: 500;
}

#statusLabel[status="disconnected"] {
    color: #f87171;
}

#footerButton {
    background: transparent;
    border: none;
    color: #8b949e;
    font-size: 12px;
    font-weight: 500;
    padding: 4px 10px;
    border-radius: 4px;
}

#footerButton:hover {
    background: rgba(255, 255, 255, 0.05);
    color: #e6edf3;
}

#footerButton:pressed {
    background: rgba(255, 255, 255, 0.08);
}
"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            f.write(default_stylesheet)
        print(f"✅ Created default stylesheet at {path}")
    except Exception as e:
        print(f"⚠️ Could not create stylesheet: {e}")

if __name__ == "__main__":
    main()