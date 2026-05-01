import os
import sqlite3
from datetime import datetime
import joblib
from flask import Flask, request, render_template, jsonify
from flask_cors import CORS # NEW: Import CORS
from werkzeug.utils import secure_filename
import core_engine
import google.generativeai as genai

# --- Initialize Flask App ---
app = Flask(__name__)
CORS(app) # NEW: Unlocks the API for the Chrome Extension
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Initialize Cloud LLM (Gemini) ---
# ⚠️ IMPORTANT: Paste your actual API key here!
GOOGLE_API_KEY = os.environ.get("AIzaSyBb5NOCd4qDaKVSwf-4-GREXsnjvvWWbmE") 
genai.configure(api_key=GOOGLE_API_KEY)
gemini_model = genai.GenerativeModel('models/gemini-2.5-flash')

# --- Database Setup (Memory & Analytics) ---
DB_NAME = "guardian_logs.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS scan_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            scan_type TEXT,
            content_snippet TEXT,
            verdict TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def log_to_db(scan_type, content, verdict):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    snippet = content[:50] + "..." if len(content) > 50 else content
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('INSERT INTO scan_logs (timestamp, scan_type, content_snippet, verdict) VALUES (?, ?, ?, ?)',
              (timestamp, scan_type, snippet, verdict))
    conn.commit()
    conn.close()

# --- Load Local ML Models ---
try:
    logreg_hate = joblib.load("models/logreg_model.joblib")
    tfidf_hate = joblib.load("models/tfidf_vectorizer.joblib")
    print("✅ Local Hate Speech models loaded!")
except Exception as e:
    print(f"❌ Error loading Hate Speech models: {e}")
    logreg_hate, tfidf_hate = None, None

try:
    logreg_fake = joblib.load("models/logreg_fake_welfake.joblib")
    tfidf_fake = joblib.load("models/tfidf_fake_welfake.joblib")
    print("✅ Local WELFake models loaded!")
except Exception as e:
    print(f"❌ Error loading WELFake News models: {e}")
    logreg_fake, tfidf_fake = None, None


# --- ROUTING ARCHITECTURE ---

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/hate')
def hate_page():
    return render_template('hate.html')

@app.route('/fake')
def fake_page():
    return render_template('fake.html')

@app.route('/analytics')
def analytics_page():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('SELECT * FROM scan_logs ORDER BY id DESC LIMIT 10')
    recent_logs = c.fetchall()
    
    c.execute('SELECT COUNT(*) FROM scan_logs WHERE verdict LIKE "%Fake%"')
    total_fakes = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM scan_logs')
    total_scans = c.fetchone()[0]
    conn.close()
    
    return render_template('analytics.html', logs=recent_logs, total_scans=total_scans, total_fakes=total_fakes)


# --- MODULE 1: TOXICITY ENGINE ---
@app.route('/analyze_hate', methods=['POST'])
def analyze_hate():
    user_text = request.form.get('text_input', '')
    image_path = None
    if 'image_input' in request.files:
        file = request.files['image_input']
        if file and file.filename != '':
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
            file.save(filepath)
            image_path = filepath
            
    cleaned_text = core_engine.process_input(user_text=user_text, image_path=image_path)
    if image_path and os.path.exists(image_path): os.remove(image_path)
    
    result = "Model not loaded."
    action_steps = None 
    
    if logreg_hate and tfidf_hate:
        vectorized = tfidf_hate.transform([cleaned_text])
        prediction = logreg_hate.predict(vectorized)
        
        if prediction[0] == 1:
            result = "Toxic/Hate Speech Detected"
            action_steps = ["Quarantine the post immediately.", "Issue a 'Strike 1' warning."]
        else:
            result = "Content is Safe"
            
    log_to_db("Toxicity", cleaned_text, result)
    return render_template('hate.html', result=result, cleaned_text=cleaned_text, action_steps=action_steps)

# --- MODULE 2: CREDIBILITY ENGINE ---
@app.route('/analyze_fake', methods=['POST'])
def analyze_fake():
    user_text = request.form.get('text_input', '')
    if not user_text:
        return render_template('fake.html', fake_result="Please enter some text.", cleaned_text="")

    result = "Analysis Failed."
    action_steps = None 
    final_reasoning = ""
    source_url = None
    
    if logreg_fake and tfidf_fake:
        vectorized = tfidf_fake.transform([user_text])
        probabilities = logreg_fake.predict_proba(vectorized)[0]
        fake_confidence = probabilities[1] 
        
        if fake_confidence >= 0.85:
            result = "Fake/Unreliable News Detected"
            final_reasoning = f"Blocked by Local ML (Confidence: {fake_confidence*100:.1f}%)."
            action_steps = ["Apply a 'Misinformation' warning label."]
        else:
            escalation_note = f"Local ML Score: {fake_confidence*100:.1f}%. Escalated to Cloud AI."
            prompt = f"""
            You are an expert fact-checking AI. Analyze this text for misinformation.
            You MUST respond in EXACTLY this 3-line format:
            VERDICT: [FAKE or REAL]
            SOURCE: [If REAL, provide a direct, valid https:// URL. If FAKE, write NONE]
            REASON: [1-2 sentences explaining your verdict]
            
            Text: "{user_text}"
            """
            try:
                response = gemini_model.generate_content(prompt)
                lines = response.text.strip().split('\n')
                gemini_verdict = ""
                gemini_reason = ""
                
                for line in lines:
                    line_upper = line.strip().upper()
                    if line_upper.startswith("VERDICT:"):
                        gemini_verdict = line_upper.replace("VERDICT:", "").strip()
                    elif line_upper.startswith("SOURCE:"):
                        extracted_url = line.replace("SOURCE:", "").replace("Source:", "").strip()
                        if extracted_url.startswith("http"):
                            source_url = extracted_url
                    elif line_upper.startswith("REASON:"):
                        gemini_reason = line.replace("REASON:", "").replace("Reason:", "").strip()

                if "FAKE" in gemini_verdict:
                    result = "Fake/Unreliable News Detected (AI Verified)"
                    action_steps = ["Apply 'Misinformation' label.", "Attach fact-checker link."]
                    final_reasoning = f"{escalation_note} | Analysis: {gemini_reason}"
                else:
                    result = "News snippet appears Verified/Real (AI Verified)"
                    final_reasoning = f"{escalation_note} | Analysis: {gemini_reason}"
                    
            except Exception as e:
                 print(f"Gemini API Error: {e}")
                 result = "API Error"
                 final_reasoning = "API connection failed."
                 
    log_to_db("Credibility", user_text, result)
    return render_template('fake.html', fake_result=result, cleaned_text=user_text, action_steps=action_steps, reasoning=final_reasoning, source_url=source_url)


# --- API ENDPOINTS (FOR CHROME EXTENSION) ---
@app.route('/api/v1/analyze_fake', methods=['POST'])
def api_analyze_fake():
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({"error": "No text provided."}), 400
        
    user_text = data['text']
    
    vectorized = tfidf_fake.transform([user_text])
    probabilities = logreg_fake.predict_proba(vectorized)[0]
    fake_confidence = probabilities[1]
    
    if fake_confidence >= 0.85:
        log_to_db("API_Credibility", user_text, "Fake")
        return jsonify({
            "verdict": "FAKE",
            "confidence": round(fake_confidence * 100, 2),
            "engine_used": "Local ML",
            "reasoning": f"Blocked by Local ML. Pattern matches known misinformation datasets."
        })
        
    # Cascade to Gemini for the API response
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
        reason = ""
        for line in lines:
            if line.upper().startswith("VERDICT:"):
                verdict = "FAKE" if "FAKE" in line.upper() else "REAL"
            elif line.upper().startswith("REASON:"):
                reason = line.replace("REASON:", "").replace("Reason:", "").strip()
                
        log_to_db("API_Credibility", user_text, verdict)
        return jsonify({
            "verdict": verdict,
            "confidence": round(fake_confidence * 100, 2),
            "engine_used": "Cloud API (Gemini)",
            "reasoning": reason
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)