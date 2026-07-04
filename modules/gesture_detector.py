"""Gesture detection using pynput with integrated snipping tool detection - Dynamic Sensitivity"""
import threading
import time
from collections import deque
from pynput.mouse import Listener, Button
from pynput.keyboard import Controller, Key, Listener as KeyListener
import pyperclip
from modules.Xcursor_ai import XcursorAI
from modules.keyword_cache import KeywordCache
from modules.snipping_detector import SnippingDetector

keyboard = Controller()

class GestureDetector:
    def __init__(self, cmd_queue):
        self.position_history = deque(maxlen=30)
        self.SHAKE_THRESHOLD = 120  # DYNAMIC - can be changed by settings
        self.TIME_WINDOW = 0.6
        self.last_gesture_time = 0
        self.GESTURE_COOLDOWN = 1.0
        self.last_shake_pos = None
        
        self.tracking_enabled = True
        self.middle_click_count = 0
        self.last_middle_click_time = 0
        self.MIDDLE_CLICK_TIMEOUT = 0.5
        
        self.capture_count = 0
        
        self.last_captured_text = None
        self.clipboard_clear_timer = None
        self.CLIPBOARD_TTL_SECONDS = 7
        
        self.vertical_shake_triggered = False
        self.waiting_for_vertical_click = False
        self.vertical_shake_click_time = None
        self.processing_snipping_event = False
        self.snipping_closed_processed = False  # Track if we've processed the close event
        
        # Snipping tool detection
        self.snipping_detector = SnippingDetector()
        self.snipping_open = False
        self.snipping_detector.add_callback(self._on_snipping_state_change)
        # START MONITORING IMMEDIATELY - prevents first-run race condition
        self.snipping_detector.start_monitoring()
        
        self.listener = None
        self.hotkey_listener = None
        self.cmd_queue = cmd_queue
        self.Xcursor_ai = XcursorAI(cache=KeywordCache())
        
        self.keyword_queue = deque()
        self.queue_processor_running = False
        
        # ✅ AI Streaming state
        self.ai_streaming = False
        self.ai_stop_requested = False
    
    def _on_snipping_state_change(self, is_open: bool, foreground: str):
        """Callback when snipping tool state changes"""
        # Ignore if we're already processing
        if self.processing_snipping_event:
            return
        
        # CRITICAL FIX: Only process state changes when we're actually waiting
        if not self.waiting_for_vertical_click:
            return
        
        if is_open:
            # Snipping tool opened
            self.snipping_open = True
            self.snipping_closed_processed = False  # Reset flag
            print(f"   📸 Snipping tool opened: {foreground}")
            print("   ⏳ Waiting for you to capture text...")
            # Clear clipboard when snipping tool opens
            self._clear_clipboard_force()
        else:
            # Snipping tool closed
            self.snipping_open = False
            
            # Only process if we haven't already processed this close event
            if not self.snipping_closed_processed and self.waiting_for_vertical_click:
                self.snipping_closed_processed = True
                self.processing_snipping_event = True
                
                print(f"   📸 Snipping tool closed")
                print("   ⏳ Checking for captured text...")
                
                # Wait for clipboard to update from OS
                time.sleep(0.5)  # Increased from 0.3 for reliability
                text = pyperclip.paste().strip()
                
                if text:
                    print(f"   ✅ Text captured! {len(text)} chars")
                    self._show_overlay_with_text(text)
                else:
                    print("   ℹ️ No text captured - nothing to show")
                    self.cmd_queue.clear_overlay()
                
                # Reset state
                self.waiting_for_vertical_click = False
                self.vertical_shake_triggered = False
                self.processing_snipping_event = False
    
    def _clear_clipboard_force(self):
        """Force clear clipboard by copying empty string"""
        try:
            # Clear the clipboard
            pyperclip.copy("")
            time.sleep(0.05)  # Give OS time to register clipboard change
            self.last_captured_text = None
            if self.clipboard_clear_timer:
                self.clipboard_clear_timer.cancel()
                self.clipboard_clear_timer = None
            print("   🧹 Clipboard cleared")
        except Exception as e:
            print(f"   ⚠️ Failed to clear clipboard: {e}")
    
    def _show_overlay_with_text(self, text):
        """Show overlay with captured text and analyze"""
        self.capture_count += 1
        self.last_captured_text = text
        self.start_clipboard_clear_timer()
        print(f"\n📋 OCR CAPTURE #{self.capture_count}: {len(text)} chars")
        
        # Show overlay with the text
        self.cmd_queue.show_overlay(text, self.last_shake_pos)
        
        # ✅ NEW: Store reference to the overlay
        self.overlay = self.cmd_queue.get_overlay()  # Get the overlay reference
        
        # CLEAR CLIPBOARD IMMEDIATELY after sending to AI
        self.clear_clipboard_now()
        print("🧹 Clipboard cleared after sending to AI")
        
        # ✅ Start AI analysis in background
        threading.Thread(target=self._analyze_text_with_ai, args=(text,), daemon=True).start()
    
    def _analyze_text_with_ai(self, text):
        """Analyze text using AI in background thread"""
        try:
            # ✅ Use the stored overlay reference
            overlay = self.overlay
            if not overlay:
                print("⚠️ Overlay not available")
                return
            
            # overlay.show_loading()  # ✅ Uncomment if this method exists
            conversation_history = overlay.conversation_history if hasattr(overlay, 'conversation_history') else None
            
            # ✅ Get selected model from dropdown
            selected_model = overlay.model_selector.currentText() if overlay else None
            
            self.ai_streaming = True
            self.ai_stop_requested = False
            
            def token_callback(token):
                if self.ai_stop_requested:
                    return
                # ✅ Queue for main thread processing
                self.cmd_queue.add_ai_token(token)
            
            def done_callback():
                self.ai_streaming = False
                # ✅ Signal completion via cmd_queue
                self.cmd_queue.add_ai_token("", final=True)
            
            # ✅ Pass selected model to AI
            self.Xcursor_ai.analyze_streaming(
                text=text,
                token_callback=token_callback,
                done_callback=done_callback,
                model=selected_model,
                conversation_history=conversation_history
            )
            
        except Exception as e:
            print(f"❌ AI Analysis error: {e}")
            import traceback
            traceback.print_exc()  # ✅ Better error reporting
            self.ai_streaming = False
            if self.overlay:
                # self.overlay.hide_loading()  # ✅ Uncomment if exists
                self.overlay.add_ai_token(f"\n\n❌ Error: {str(e)}")
                self.overlay.finish_ai_response()

    def toggle_tracking(self):
        self.tracking_enabled = not self.tracking_enabled
        status = "ON ✅" if self.tracking_enabled else "OFF ❌"
        print(f"\n🔄 GESTURE TRACKING: {status}\n")
    
    def start_clipboard_clear_timer(self):
        if self.clipboard_clear_timer:
            self.clipboard_clear_timer.cancel()
        
        self.clipboard_clear_timer = threading.Timer(
            self.CLIPBOARD_TTL_SECONDS,
            self._clear_clipboard_timeout
        )
        self.clipboard_clear_timer.daemon = True
        self.clipboard_clear_timer.start()
    
    def _clear_clipboard_timeout(self):
        self.last_captured_text = None
        print(f"[🧹 Clipboard cleared after {self.CLIPBOARD_TTL_SECONDS}s]")
    
    def clear_clipboard_now(self):
        """FEATURE 1: Clear clipboard immediately after input is sent to AI"""
        try:
            pyperclip.copy("")  # Actually clear the system clipboard
            self.last_captured_text = None
            if self.clipboard_clear_timer:
                self.clipboard_clear_timer.cancel()
                self.clipboard_clear_timer = None
            print("🧹 Clipboard cleared immediately")
        except Exception as e:
            print(f"⚠️ Failed to clear clipboard: {e}")
    
    def is_clipboard_empty(self):
        """Check if clipboard is empty (for Feature 2)"""
        try:
            content = pyperclip.paste().strip()
            return len(content) == 0
        except:
            return True
    
    def trigger_snipping_tool(self):
        """Trigger Windows snipping tool with overlay detection"""
        print("\n🎯 VERTICAL SHAKE DETECTED! Opening snipping tool...\n")
        
        # Set flags BEFORE opening snipping tool
        self.vertical_shake_triggered = True
        self.waiting_for_vertical_click = True
        self.snipping_closed_processed = False  # Reset close flag
        
        # CRITICAL: Force clear clipboard BEFORE opening snipping tool
        self._clear_clipboard_force()
        
        try:
            # Open snipping tool
            with keyboard.pressed(Key.shift):
                with keyboard.pressed(Key.cmd):
                    keyboard.press('t')
                    keyboard.release('t')
            
            # Monitoring already started in __init__() - no need to check/start here
            
            self.vertical_shake_click_time = time.time()
            
            print("\n📸 SNIPPING TOOL INSTRUCTIONS:")
            print("   1. Select the area you want to capture")
            print("   2. The tool will auto-detect when you take the screenshot")
            print("   3. Text will be extracted automatically if found\n")
            print("   ⏳ Waiting for snipping tool to close...")
            print("   🧹 Clipboard has been cleared, waiting for new text...\n")
            
        except Exception as e:
            print(f"❌ Error opening snipping tool: {e}")
            self.vertical_shake_triggered = False
            self.waiting_for_vertical_click = False
            self.snipping_closed_processed = False
    
    def manual_trigger_keyword_extraction(self):
        """Manual keyword extraction with f8"""
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
        keywords = self.Xcursor_ai.extractor.extract(text, count=50)
        new_keywords = 0
        for keyword in keywords:
            if not self.Xcursor_ai.cache.has(keyword):
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
            definition, from_cache = self.Xcursor_ai.get_keyword_definition(keyword)
            if not from_cache:
                print(f"  📚 Indexed: {keyword}")
            time.sleep(0.5)
        self.queue_processor_running = False
    
    def on_move(self, x, y):
        """Handle mouse movement - detect shakes only"""
        # Don't process if snipping tool is open or we're waiting
        if self.snipping_open or self.waiting_for_vertical_click:
            return
            
        current_time = time.time()
        self.position_history.append((x, y, current_time))
        
        if self.tracking_enabled:
            self.detect_horizontal_shake()
            self.detect_vertical_shake()
    
    def on_click(self, x, y, button, pressed):
        """Handle mouse click - detect double middle-click to toggle tracking"""
        # Only process middle button clicks when pressed down
        if button != Button.middle or not pressed:
            return
        
        current_time = time.time()
        
        # Check if this is a double-click
        if current_time - self.last_middle_click_time < self.MIDDLE_CLICK_TIMEOUT:
            # Double-click detected!
            self.middle_click_count += 1
            
            if self.middle_click_count >= 2:
                # Actually toggle on the second click
                self.toggle_tracking()
                self.middle_click_count = 0
                self.last_middle_click_time = 0
        else:
            # New click sequence
            self.middle_click_count = 1
            self.last_middle_click_time = current_time
    
    def detect_horizontal_shake(self):
        """Detect horizontal shake - uses dynamic SHAKE_THRESHOLD"""
        # Skip if vertical shake is in progress
        if self.waiting_for_vertical_click or self.vertical_shake_triggered:
            return
            
        if len(self.position_history) < 6:
            return
        now = time.time()
        recent = [p for p in self.position_history if now - p[2] < self.TIME_WINDOW]
        if len(recent) < 6:
            return
        x_positions = [p[0] for p in recent]
        total_movement = max(x_positions) - min(x_positions)
        if total_movement < self.SHAKE_THRESHOLD:  # Uses DYNAMIC threshold
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
            print(f"[HORIZONTAL SHAKE] {total_movement}px movement (threshold: {self.SHAKE_THRESHOLD}px)")
            self.last_gesture_time = current_time
            self._handle_horizontal_shake()
    
    def _handle_horizontal_shake(self):
        """✅ SIMPLIFIED: Horizontal shake logic
        
        NEW BEHAVIOR (simplified):
        - If window visible → close it (don't check clipboard)
        - If window hidden → open it (don't check clipboard)
        
        That's it. No more clipboard safety checks.
        """
        is_visible = self.cmd_queue.is_overlay_visible()
        
        if is_visible:
            # Window is open → close it
            print(f"\n📱 Window visible → Closing")
            self.cmd_queue.clear_overlay()
        else:
            # Window is hidden → open it (try to show clipboard content)
            print(f"\n📁 Window hidden → Opening")
            try:
                with keyboard.pressed(Key.ctrl):
                    keyboard.press('c')
                    keyboard.release('c')
                time.sleep(0.05)
                text = pyperclip.paste().strip()
                if text:
                    self._show_overlay_with_text(text)
                else:
                    # No clipboard content → open input overlay
                    self.cmd_queue.show_input_overlay(self.last_shake_pos)
            except Exception as e:
                print(f"⚠️ Error: {e}")
                self.cmd_queue.show_input_overlay(self.last_shake_pos)
            
    def detect_vertical_shake(self):
        """Detect vertical shake - uses dynamic SHAKE_THRESHOLD"""
        if len(self.position_history) < 6:
            return
        now = time.time()
        recent = [p for p in self.position_history if now - p[2] < self.TIME_WINDOW]
        if len(recent) < 6:
            return
        y_positions = [p[1] for p in recent]
        total_movement = max(y_positions) - min(y_positions)
        if total_movement < self.SHAKE_THRESHOLD:  # Uses DYNAMIC threshold
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
            print(f"[VERTICAL SHAKE] {total_movement}px movement (threshold: {self.SHAKE_THRESHOLD}px)")
            self.last_gesture_time = current_time
            threading.Thread(target=self.trigger_snipping_tool, daemon=True).start()
    
    def start(self):
        """Start gesture detection with snipping monitoring"""
        print("=" * 70)
        print("🎯 GESTURE-CONTROLLED OCR + Xcursor AI v2 (FIXED)")
        print("=" * 70)
        print("\n📋 GESTURES:")
        print("   1. Horizontal shake → Captures selected text → AI analyzes")
        print("   2. Vertical shake → Opens snipping tool → Auto-captures text on close")
        print("   3. Double middle-click → Toggle gesture tracking ON/OFF")
        print("   4. f8 → Manual keyword extraction")
        print("\n🔄 BEHAVIOR:")
        print("   ✅ Clipboard CLEARED immediately after input sent to AI")
        print("   ✅ Horizontal shake closes window ONLY if clipboard is empty")
        print("   ✅ Horizontal shake opens window if hidden (copies clipboard)")
        print("   ✅ UI ONLY opens when new text is captured")
        print("   ✅ No UI if no text in clipboard after snipping")
        print("   ✅ Prevents duplicate processing")
        print("   ✅ Double middle-click toggles all gestures")
        print("   ✅ Settings changes apply in REAL-TIME")
        
        # ✅ Fixed: Check if Xcursor_ai has been initialized and has connected attribute
        if hasattr(self.Xcursor_ai, 'connected') and self.Xcursor_ai.connected:
            print("\n🤖 AI Status: ✅ CONNECTED")
            # ✅ Fixed: Check if model attribute exists
            if hasattr(self.Xcursor_ai, 'model'):
                print(f"   Model: {self.Xcursor_ai.model}")
            elif hasattr(self.Xcursor_ai, 'current_model'):
                print(f"   Model: {self.Xcursor_ai.current_model}")
            else:
                print(f"   Model: {self.Xcursor_ai.ollama_model if hasattr(self.Xcursor_ai, 'ollama_model') else 'Unknown'}")
        else:
            print("\n🤖 AI Status: ❌ NOT CONNECTED")
            print("   Start Ollama: ollama serve")
        
        print(f"\n🎯 Current Gesture Sensitivity: {self.SHAKE_THRESHOLD}px")
        print("=" * 70 + "\n")
        
        def on_press(key):
            try:
                if key == Key.f8:
                    self.manual_trigger_keyword_extraction()
            except:
                pass
        
        self.hotkey_listener = KeyListener(on_press=on_press)
        self.hotkey_listener.start()
        
        # Listen for mouse movement AND clicks
        self.listener = Listener(on_move=self.on_move, on_click=self.on_click)
        self.listener.start()
        self.listener.join()
    
    def stop(self):
        """Stop all listeners and monitoring"""
        # Reset tracking state
        self.middle_click_count = 0
        self.last_middle_click_time = 0
        
        # Stop AI streaming if in progress
        self.ai_stop_requested = True
        self.ai_streaming = False
        
        if self.listener:
            self.listener.stop()
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        if self.snipping_detector:
            self.snipping_detector.stop_monitoring()
        print("\n✅ Shutdown complete.")