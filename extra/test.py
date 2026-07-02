import win32gui
import win32con
import win32process
import psutil
import time

def is_snipping_window_open():
    """Check if ANY snipping tool window is open and visible"""
    def enum_windows_callback(hwnd, windows):
        if win32gui.IsWindowVisible(hwnd):
            window_text = win32gui.GetWindowText(hwnd).lower()
            
            # Check for snipping-related window titles
            snipping_titles = [
                'snipping tool',
                'snip & sketch',
                'screenshot',
                'capture',
                'snipping'
            ]
            
            if any(title in window_text for title in snipping_titles):
                # Also check if it's a child window (which snipping tool often is)
                parent = win32gui.GetParent(hwnd)
                if parent == 0:  # Top-level window
                    windows.append(hwnd)
                    print(f"   Found: '{win32gui.GetWindowText(hwnd)}'")
        return True
    
    windows = []
    win32gui.EnumWindows(enum_windows_callback, windows)
    return len(windows) > 0

def get_foreground_snipping_process():
    """Check if foreground window is snipping tool"""
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

def monitor_snipping():
    """Monitor for snipping tool window state changes"""
    print("\n🔍 MONITORING SNIPPING TOOL WINDOW")
    print("   - Background processes will be ignored")
    print("   - Only visible windows count")
    print("   - Press Ctrl+C to stop\n")
    
    last_state = None
    
    try:
        while True:
            is_open = is_snipping_window_open()
            foreground = get_foreground_snipping_process()
            
            if is_open != last_state:
                if is_open:
                    print(f"✅ Snipping tool WINDOW OPENED! (Foreground: {foreground})")
                else:
                    print("❌ Snipping tool WINDOW CLOSED!")
                last_state = is_open
            
            time.sleep(0.5)
            
    except KeyboardInterrupt:
        print("\n\n⏹️ Monitoring stopped")

if __name__ == "__main__":
    try:
        import win32gui
        import win32process
    except ImportError:
        print("❌ Install pywin32: pip install pywin32")
        sys.exit(1)
    
    print("=" * 60)
    print("SNIPPING TOOL WINDOW DETECTOR")
    print("=" * 60)
    
    # Initial state
    print("\n📊 Current state:")
    if is_snipping_window_open():
        print("   ⚠️ Snipping tool window is OPEN")
    else:
        print("   ✅ Snipping tool window is CLOSED")
    
    print("\n" + "=" * 60)
    print("Now monitoring for window state changes...")
    print("Background processes will be IGNORED.")
    print("Only visible windows count.")
    print("=" * 60 + "\n")
    
    monitor_snipping()