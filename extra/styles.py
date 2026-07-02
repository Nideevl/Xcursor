# styles.py
"""Modern UI Styles for Gesture OCR"""

# Main glass-morphism style with fixed properties (no unsupported backdrop-filter)
GLASS_STYLE = """
/* Glass container */
#glassWidget {
    background: rgba(20, 25, 35, 0.92);
    border-radius: 16px;
    border: 1px solid rgba(255, 255, 255, 0.08);
}

/* Header */
#header {
    background: rgba(255, 255, 255, 0.03);
    border-radius: 16px 16px 0 0;
}

#titleLabel {
    color: #00d9ff;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.5px;
    padding: 5px 0;
    font-family: 'Segoe UI', 'Arial', sans-serif;
}

#headerButton {
    background: transparent;
    color: #8b949e;
    border: none;
    border-radius: 6px;
    font-size: 16px;
    font-weight: 400;
    padding: 0;
    font-family: 'Segoe UI', 'Arial', sans-serif;
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

/* Messages - with word wrap */
.userMessage {
    background: rgba(88, 166, 255, 0.12);
    border: 1px solid rgba(88, 166, 255, 0.08);
    border-radius: 10px;
    padding: 10px 14px;
    color: #e6edf3;
    font-size: 13px;
    line-height: 1.6;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    word-wrap: break-word;
    white-space: pre-wrap;
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
    font-size: 13px;
    line-height: 1.6;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    word-wrap: break-word;
    white-space: pre-wrap;
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

/* Input area */
#inputArea {
    background: rgba(255, 255, 255, 0.05);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    padding: 10px 15px;
}

#inputField {
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    color: #e6edf3;
    font-size: 13px;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    padding: 8px 12px;
}

#inputField:focus {
    border: 1px solid rgba(0, 217, 255, 0.4);
    background: rgba(255, 255, 255, 0.08);
}

#sendButton {
    background: rgba(0, 217, 255, 0.15);
    border: 1px solid rgba(0, 217, 255, 0.2);
    border-radius: 8px;
    color: #00d9ff;
    font-size: 13px;
    font-weight: 500;
    font-family: 'Segoe UI', 'Arial', sans-serif;
    padding: 8px 16px;
}

#sendButton:hover {
    background: rgba(0, 217, 255, 0.25);
}

#sendButton:pressed {
    background: rgba(0, 217, 255, 0.35);
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
    font-family: 'Segoe UI', 'Arial', sans-serif;
}

#footerButton {
    background: transparent;
    color: #8b949e;
    border: none;
    border-radius: 6px;
    font-size: 12px;
    padding: 4px 10px;
    font-family: 'Segoe UI', 'Arial', sans-serif;
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
"""