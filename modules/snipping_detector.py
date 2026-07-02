"""
Windows Snipping Tool overlay detection
Detects when snipping tool windows are open/closed including overlay windows
"""
import time
import threading
from typing import Optional, Callable

try:
    import win32gui
    import win32process
    import psutil
    WINDOWS_AVAILABLE = True
except ImportError:
    WINDOWS_AVAILABLE = False
    print("⚠️ Windows-specific modules not available. Snipping detection disabled.")

class SnippingDetector:
    """Detects snipping tool window state changes including overlay windows"""
    
    def __init__(self):
        self.is_open = False
        self.last_state = None
        self.callbacks = []
        self.monitoring = False
        self.monitor_thread = None
        self.stop_flag = False
        
        if not WINDOWS_AVAILABLE:
            print("⚠️ Snipping detector: Windows modules not available")
    
    def is_snipping_window_open(self) -> bool:
        """Check if ANY snipping tool window is open and visible"""
        if not WINDOWS_AVAILABLE:
            return False
            
        def enum_windows_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                window_text = win32gui.GetWindowText(hwnd).lower()
                
                # More specific snipping tool detection
                snipping_titles = [
                    'snipping tool',
                    'snip & sketch',
                    'snipping tool overlay',
                    'snippingtool'
                ]
                
                # Check if it's a snipping tool window
                is_snipping = any(title in window_text for title in snipping_titles)
                
                if is_snipping:
                    parent = win32gui.GetParent(hwnd)
                    # Top-level windows or overlays
                    if parent == 0:
                        windows.append(hwnd)
                        # Debug: print(f"   Found snipping window: '{win32gui.GetWindowText(hwnd)}'")
            return True
        
        windows = []
        win32gui.EnumWindows(enum_windows_callback, windows)
        return len(windows) > 0
    
    def get_foreground_snipping_process(self) -> Optional[str]:
        """Check if foreground window is snipping tool"""
        if not WINDOWS_AVAILABLE:
            return None
            
        try:
            hwnd = win32gui.GetForegroundWindow()
            if hwnd:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                for proc in psutil.process_iter(['pid', 'name']):
                    if proc.info['pid'] == pid:
                        proc_name = proc.info['name'].lower()
                        if any(name in proc_name for name in ['snippingtool', 'screensketch']):
                            return proc_name
        except:
            pass
        return None
    
    def add_callback(self, callback: Callable[[bool, Optional[str]], None]):
        """Add callback for state changes: callback(is_open, foreground_process)"""
        self.callbacks.append(callback)
    
    def remove_callback(self, callback: Callable):
        """Remove a callback"""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def _notify_callbacks(self, is_open: bool, foreground: Optional[str]):
        """Notify all callbacks of state change"""
        for callback in self.callbacks:
            try:
                callback(is_open, foreground)
            except Exception as e:
                print(f"⚠️ Error in callback: {e}")
    
    def start_monitoring(self, interval: float = 0.5):
        """Start monitoring snipping tool windows"""
        if self.monitoring:
            return
        
        if not WINDOWS_AVAILABLE:
            print("⚠️ Cannot monitor snipping tool: Windows modules not available")
            return
        
        self.monitoring = True
        self.stop_flag = False
        
        def monitor_loop():
            print("\n🔍 SNIPPING TOOL MONITORING STARTED")
            print("   - Detects open/closed states")
            print("   - Includes overlay windows")
            print("   - Press Ctrl+C to stop\n")
            
            while not self.stop_flag:
                try:
                    is_open = self.is_snipping_window_open()
                    foreground = self.get_foreground_snipping_process()
                    
                    if is_open != self.last_state:
                        if is_open:
                            print(f"✅ Snipping tool OPENED! (Foreground: {foreground})")
                        else:
                            print("❌ Snipping tool CLOSED!")
                        
                        self.is_open = is_open
                        self.last_state = is_open
                        self._notify_callbacks(is_open, foreground)
                    
                    time.sleep(interval)
                    
                except Exception as e:
                    print(f"⚠️ Monitoring error: {e}")
                    time.sleep(interval)
            
            print("\n⏹️ Snipping monitoring stopped")
        
        self.monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop monitoring"""
        self.stop_flag = True
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
    
    def get_current_state(self) -> tuple[bool, Optional[str]]:
        """Get current snipping tool state"""
        if not WINDOWS_AVAILABLE:
            return False, None
        return self.is_snipping_window_open(), self.get_foreground_snipping_process()