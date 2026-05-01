import re

def clean_text(text):
    """Sanitizes text by removing URLs, HTML, punctuation, and extra noise."""
    if not text:
        return ""
    
    text = text.lower()
    text = re.sub(r'\[.*?\]', '', text)               # Remove text in brackets
    text = re.sub(r'https?://\S+|www\.\S+', '', text) # Remove links
    text = re.sub(r'<.*?>+', '', text)                # Remove HTML tags
    text = re.sub(r'[^a-zA-Z\s]', '', text)           # Keep only letters and spaces
    text = re.sub(r'\n', ' ', text)                   # Remove newlines
    
    return text.strip()

def process_input(user_text="", image_path=None):
    """Lightweight processing engine."""
    final_text = user_text if user_text else ""
    cleaned_data = clean_text(final_text)
    return cleaned_data