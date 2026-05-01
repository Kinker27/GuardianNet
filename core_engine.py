import easyocr
import re
import string
import os

# Initialize the OCR reader (uses GPU if available, otherwise CPU)
print("Initializing OCR Engine...")
reader = easyocr.Reader(['en'])

def extract_text_from_image(image_path):
    """Reads an image (like a meme or screenshot) and extracts the text."""
    if not os.path.exists(image_path):
        return ""
        
    try:
        print(f"Scanning image: {image_path}...")
        result = reader.readtext(image_path, detail=0)
        extracted_text = " ".join(result)
        return extracted_text
    except Exception as e:
        print(f"Error reading image: {e}")
        return ""

def clean_text(text):
    """Sanitizes text by removing URLs, HTML, punctuation, and extra noise."""
    if not text:
        return ""
    
    text = text.lower()
    text = re.sub(r'\[.*?\]', '', text)               # Remove text in brackets
    text = re.sub(r'https?://\S+|www\.\S+', '', text) # Remove links
    text = re.sub(r'<.*?>+', '', text)                # Remove HTML tags
    text = re.sub(r'[%s]' % re.escape(string.punctuation), '', text) # Remove punctuation
    text = re.sub(r'\n', ' ', text)                   # Remove newlines
    text = re.sub(r'\w*\d\w*', '', text)              # Remove alphanumeric words
    
    return text.strip()

def process_input(user_text="", image_path=None):
    """Master function to handle both text and image inputs."""
    final_text = user_text
    
    # If an image is provided, extract its text and append it
    if image_path:
        image_text = extract_text_from_image(image_path)
        final_text = f"{final_text} {image_text}".strip()
        
    # Clean the combined text
    cleaned_data = clean_text(final_text)
    return cleaned_data

# --- TEST THE ENGINE ---
if __name__ == "__main__":
    # Test: Raw Text
    sample_post = "OMG check out this totally FAKE news link! http://scam.com/virus"
    print("\n--- Testing Core Engine ---")
    print("Original:", sample_post)
    print("Processed:", process_input(user_text=sample_post))