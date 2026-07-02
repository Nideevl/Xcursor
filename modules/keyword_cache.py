"""Persistent cache for keyword definitions"""
import json
from pathlib import Path
from datetime import datetime, timedelta

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