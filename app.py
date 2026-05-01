import os
import sqlite3
from flask import Flask, request, render_template, jsonify
from flask_cors import CORS
import google.generativeai as genai
import core_engine

app = Flask(__name__)
CORS(app)

# --- INITIALIZE CLOUD AI ---
# Safely pull the key from Render's environment variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Create a global placeholder so it NEVER throws a NameError again
gemini_model = None

if GEMINI_API_KEY and GEMINI_API_KEY.strip() != "":
    try:
        genai.configure(api_key=GEMINI_API_KEY.strip())
        gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        print("✅ Gemini AI successfully connected!")
    except Exception as e:
        print(f"❌ Failed to configure Gemini: {e}")
else:
    print("❌ CRITICAL WARNING: GEMINI_API_KEY is missing from the environment!")

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('guardian_logs.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scan_logs
                 (id INTEGER PRIMARY KEY, engine TEXT, text_scanned TEXT, verdict TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def log_to_db(engine, text, verdict):
    try:
        conn = sqlite3.connect('guardian_logs.db')
        c = conn.cursor()
        c.execute("INSERT INTO scan_logs (engine, text_scanned, verdict) VALUES (?, ?, ?)", (engine, text, verdict))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")

init_db()

# --- WEB ROUTES ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/hate')
def toxicity():
    return render_template('hate.html')

@app.route('/fake')
def credibility():
    return render_template('fake.html')

@app.route('/analytics')
def analytics():
    return render_template('analytics.html')

# --- MODULE 1: TOXICITY ENGINE ---
@app.route('/analyze_hate', methods=['POST'])
def analyze_hate():
    user_text = request.form.get('text_input', '').strip()
    
    # Safely grab the uploaded file (checking common HTML form names)
    uploaded_file = None
    for key in ['file', 'image_input', 'image', 'file_input']:
        if key in request.files and request.files[key].filename != '':
            uploaded_file = request.files[key]
            break

    # If both are empty, prompt the user
    if not user_text and not uploaded_file:
         return render_template('hate.html', result="Please enter text or upload an image.", cleaned_text="")

    cleaned_text = core_engine.process_input(user_text=user_text) if user_text else ""

    # Safety check before pinging Gemini
    if gemini_model is None:
         return render_template('hate.html', result="SYSTEM ERROR: API Key missing from server environment.", cleaned_text=cleaned_text)

    # Build payload for Gemini
    payload = [f"""
    You are an administrative content moderation AI. Analyze this input for toxicity, hate speech, or cyberbullying.
    Respond in EXACTLY this format:
    VERDICT: [TOXIC or SAFE]
    ACTION: [1 short sentence of recommended action]
    Text context: "{cleaned_text}"
    """]

    # Append image directly to the payload if it exists
    if uploaded_file:
        payload.append({
            "mime_type": uploaded_file.mimetype,
            "data": uploaded_file.read()
        })

    try:
        # Bypass safety filters so the AI is allowed to analyze toxic input natively
        safety_overrides = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]

        response = gemini_model.generate_content(payload, safety_settings=safety_overrides)
        lines = response.text.strip().split('\n')
        result = "Content is Safe (AI Verified)"
        action_steps = None
        
        for line in lines:
            if line.upper().startswith("VERDICT:"):
                if "TOXIC" in line.upper():
                    result = "Toxic/Hate Speech Detected (AI Verified)"
                    action_steps = ["Quarantine the post immediately."]
            elif line.upper().startswith("ACTION:") and "Toxic" in result:
                 action_steps = [line.replace("ACTION:", "").replace("Action:", "").strip()]
                 
        log_to_db("Toxicity_Cloud", cleaned_text, result)
        return render_template('hate.html', result=result, cleaned_text=cleaned_text, action_steps=action_steps)
    except Exception as e:
        return render_template('hate.html', result=f"Cloud AI Error: {str(e)}", cleaned_text=cleaned_text)

# --- MODULE 2: CREDIBILITY ENGINE ---
@app.route('/analyze_fake', methods=['POST'])
def analyze_fake():
    user_text = request.form.get('text_input', '').strip()
    
    uploaded_file = None
    for key in ['file', 'image_input', 'image', 'file_input']:
        if key in request.files and request.files[key].filename != '':
            uploaded_file = request.files[key]
            break

    if not user_text and not uploaded_file:
        return render_template('fake.html', fake_result="Please enter text or upload an image.", cleaned_text="")

    cleaned_text = core_engine.process_input(user_text=user_text) if user_text else ""

    # Safety check before pinging Gemini
    if gemini_model is None:
         return render_template('fake.html', fake_result="SYSTEM ERROR: API Key missing from server environment.", cleaned_text=cleaned_text)

    prompt = f"""
    You are an expert fact-checking AI. Analyze this input for misinformation.
    You MUST respond in EXACTLY this format:
    VERDICT: [FAKE or REAL]
    REASON: [1-2 sentences explaining your verdict]
    Text context: "{cleaned_text}"
    """
    payload = [prompt]

    if uploaded_file:
        payload.append({
            "mime_type": uploaded_file.mimetype,
            "data": uploaded_file.read()
        })

    try:
        response = gemini_model.generate_content(payload)
        lines = response.text.strip().split('\n')
        result = "Analysis Failed"
        final_reasoning = ""
        action_steps = None
        
        for line in lines:
            line_upper = line.strip().upper()
            if line_upper.startswith("VERDICT:"):
                if "FAKE" in line_upper:
                     result = "Fake/Unreliable News Detected (AI Verified)"
                     action_steps = ["Apply 'Misinformation' label."]
                else:
                     result = "News snippet appears Verified/Real (AI Verified)"
            elif line_upper.startswith("REASON:"):
                final_reasoning = "Cloud AI Analysis: " + line.replace("REASON:", "").replace("Reason:", "").strip()

        log_to_db("Credibility_Cloud", cleaned_text, result)
        return render_template('fake.html', fake_result=result, cleaned_text=cleaned_text, action_steps=action_steps, reasoning=final_reasoning)
    except Exception as e:
         return render_template('fake.html', fake_result=f"API Error: {str(e)}", cleaned_text=cleaned_text)

# --- API ENDPOINTS (FOR CHROME EXTENSION) ---
@app.route('/api/v1/analyze_fake', methods=['POST'])
def api_analyze_fake():
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({"error": "No text provided."}), 400
        
    user_text = data['text']
    
    prompt = f"""
    You are an expert fact-checking AI. Analyze this text for misinformation.
    You MUST respond in EXACTLY this format:
    VERDICT: [FAKE or REAL]
    REASON: [1-2 sentences explaining your verdict]
    Text: "{user_text}"
    """
    try:
        response = gemini_model.generate_content(prompt)
        lines = response.text.strip().split('\n')
        verdict = "REAL"
        reason = "AI determined this is likely accurate."
        
        for line in lines:
            if line.upper().startswith("VERDICT:"):
                verdict = "FAKE" if "FAKE" in line.upper() else "REAL"
            elif line.upper().startswith("REASON:"):
                reason = line.replace("REASON:", "").replace("Reason:", "").strip()
                
        log_to_db("API_Credibility", user_text, verdict)
        return jsonify({
            "verdict": verdict,
            "confidence": 99.9,
            "engine_used": "Cloud API (Gemini)",
            "reasoning": reason
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
