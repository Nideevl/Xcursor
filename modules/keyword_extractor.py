"""Extract keywords from text"""
import re
from collections import Counter

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