"""Thread-safe command queue for communication between threads"""
import queue

class CommandQueue:
    """Thread-safe queue for main thread to process overlay commands"""
    
    def __init__(self):
        self.queue = queue.Queue()
        self.app = None  # Reference to main app for visibility checks
    
    def set_app(self, app):
        """Set reference to main app"""
        self.app = app
    
    def show_overlay(self, text, pos=None, is_empty=False):
        self.queue.put(('show', text, pos, is_empty))
    
    def show_input_overlay(self, pos=None):
        self.queue.put(('show_input', None, pos))
    
    def add_ai_token(self, token, final=False):
        self.queue.put(('ai_token', token, final))
    
    def clear_overlay(self):
        self.queue.put(('clear', None))
    
    def get_overlay(self):
        """Return reference to the current overlay window"""
        if self.app and hasattr(self.app, 'overlay'):
            return self.app.overlay
        return None
    
    def get_command(self):
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None
    
    def is_overlay_visible(self):
        """Check if overlay is currently visible"""
        if self.app:
            return self.app.is_overlay_visible()
        return False
    def show_existing_overlay(self):
        """Show existing overlay without clearing content"""
        self.queue.put(('show_existing', None))

    def minimize_overlay(self):
        """Minimize overlay (preserve content)"""
        self.queue.put(('minimize', None))