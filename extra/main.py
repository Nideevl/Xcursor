#!/usr/bin/env python3
"""
Gesture-Controlled OCR + Qwen AI v2 (PyQt6 Modern UI)
Fixed: Proper error handling, overlay recreation, thread safety
"""

import sys
import threading
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, Qt

from modules.command_queue import CommandQueue
from modules.gesture_detector import GestureDetector
from ui.modern_overlay import ModernOverlay


class MainApplication(QApplication):
    """Main PyQt6 application"""
    
    def __init__(self, argv):
        super().__init__(argv)
        
        # Setup
        self.cmd_queue = CommandQueue()
        self.detector = GestureDetector(self.cmd_queue)
        
        # Create overlay
        self.overlay = None
        self.overlay_lock = threading.Lock()
        
        # Start detector in background
        self.detector_thread = threading.Thread(target=self.detector.start, daemon=False)
        self.detector_thread.start()
        
        # Setup timer for processing commands
        self.process_timer = QTimer()
        self.process_timer.timeout.connect(self.process_commands)
        self.process_timer.start(20)  # 50fps
        
        # Setup timer for processing AI tasks
        self.ai_timer = QTimer()
        self.ai_timer.timeout.connect(self.process_ai_tasks)
        self.ai_timer.start(100)  # Check every 100ms
        
        print("✅ Application started. Waiting for gestures...")
    
    def overlay_is_valid(self):
        """Check if overlay object is truly valid and operational"""
        if self.overlay is None:
            return False
        
        try:
            # Test if the overlay's UI is still accessible
            # This will raise RuntimeError if Qt objects were deleted
            _ = self.overlay.message_layout
            _ = self.overlay.input_field
            _ = self.overlay.scroll_area
            
            # Also check the is_closed flag
            if self.overlay.is_closed:
                print("[VALID] Overlay is marked as closed")
                return False
            
            return True
        except (RuntimeError, AttributeError) as e:
            # UI objects were deleted
            print(f"[VALID] Overlay UI deleted: {e}")
            return False
    
    def ensure_overlay(self):
        """Ensure overlay exists and is valid, recreate if broken"""
        with self.overlay_lock:
            if not self.overlay_is_valid():
                # Cleanup old overlay if it exists
                if self.overlay is not None:
                    print("[OVERLAY] Cleaning up old overlay")
                    try:
                        self.overlay.close()
                    except:
                        pass
                
                # Create fresh overlay
                print("[OVERLAY] Creating new ModernOverlay...")
                self.overlay = ModernOverlay(self.cmd_queue)
                print(f"[OVERLAY] New overlay created: {self.overlay}")
                return True
            else:
                print("[OVERLAY] Existing overlay is valid, reusing")
            return True
    
    def process_commands(self):
        """Process commands from queue in main thread"""
        cmd = self.cmd_queue.get_command()
        if cmd:
            cmd_type = cmd[0]
            
            if cmd_type == 'show':
                text = cmd[1]
                print(f"[CMD] 'show' received, text: {text[:50]}...")
                try:
                    print("[CMD] Calling ensure_overlay()")
                    self.ensure_overlay()
                    print(f"[CMD] Overlay exists: {self.overlay is not None}, Valid: {self.overlay_is_valid() if self.overlay else False}")
                    if self.overlay and self.overlay_is_valid():
                        print("[CMD] Adding user message...")
                        self.overlay.add_user_message(text)
                        print("[CMD] Opening overlay at position...")
                        self.overlay.open_at_position(
                            QApplication.primaryScreen().geometry().width() - 620, 
                            20
                        )
                        print("[CMD] Overlay should be visible now")
                        self.cmd_queue.add_ai_task(text)
                    else:
                        print(f"[CMD] ERROR: Overlay not valid - exists: {self.overlay is not None}, valid: {self.overlay_is_valid() if self.overlay else False}")
                except Exception as e:
                    import traceback
                    print(f"⚠️  Overlay show error: {e}")
                    print(traceback.format_exc())
                    self.overlay = None
                    self.ensure_overlay()
            
            elif cmd_type == 'show_at':
                text = cmd[1]
                x, y = cmd[2], cmd[3]
                try:
                    self.ensure_overlay()
                    if self.overlay and self.overlay_is_valid():
                        self.overlay.add_user_message(text)
                        self.overlay.open_at_position(x, y)
                        self.cmd_queue.add_ai_task(text)
                except Exception as e:
                    print(f"⚠️  Overlay show_at error: {e}. Recreating...")
                    self.overlay = None
                    self.ensure_overlay()
            
            elif cmd_type == 'ai_token':
                try:
                    if self.overlay and self.overlay_is_valid() and not self.overlay.is_closed:
                        token = cmd[1]
                        final = cmd[2] if len(cmd) > 2 else False
                        
                        if final:
                            self.overlay.finish_ai_response()
                        else:
                            self.overlay.add_ai_token(token)
                except RuntimeError:
                    # Overlay was destroyed silently, mark for recreation
                    self.overlay = None
            
            elif cmd_type == 'clear':
                try:
                    if self.overlay and self.overlay_is_valid() and not self.overlay.is_closed:
                        self.overlay.clear_content()
                        self.overlay.hide_with_animation()
                except RuntimeError:
                    self.overlay = None
    
    def process_ai_tasks(self):
        """Process AI tasks from queue"""
        if not self.overlay or not self.overlay_is_valid() or self.overlay.is_closed:
            # Clear pending tasks if overlay is not available
            while self.cmd_queue.get_ai_task():
                pass
            return
            
        task = self.cmd_queue.get_ai_task()
        if task:
            def stream_ai():
                def on_token(token):
                    self.cmd_queue.add_ai_token(token)
                
                def on_done():
                    self.cmd_queue.add_ai_token("", final=True)
                
                try:
                    self.detector.qwen_ai.analyze_streaming(task, on_token, on_done)
                except Exception as e:
                    print(f"❌ AI Streaming error: {e}")
            
            thread = threading.Thread(target=stream_ai, daemon=True)
            thread.start()


def main():
    """Main entry point"""
    app = MainApplication(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()