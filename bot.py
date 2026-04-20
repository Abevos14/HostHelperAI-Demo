from dotenv import load_dotenv
load_dotenv()

# --- Core Logic Functions (The Brain) ---
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import os
from datetime import datetime

# --- Configuration ---
SPREADSHEET_NAME = "HostHelperAI"
LOG_SPREADSHEET_NAME = "Host Helper AI Log"
CREDS_FILE = 'credentials.json'

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("[CRITICAL WARNING] GEMINI_API_KEY not found.")

MODEL = 'gemini-2.5-flash'

FALLBACK_RESPONSE = (
    "I'm sorry, I don't have that specific information. I will notify the host to help you with that."
)

def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    try:
        import streamlit as st
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            return gspread.authorize(creds)
    except Exception:
        pass
    if os.path.exists(CREDS_FILE):
        creds = ServiceAccountCredentials.from_json_keyfile_name(CREDS_FILE, scope)
        return gspread.authorize(creds)
    return None

def send_sms_alert(question):
    """Sends an SMS to the host when a guest asks an unanswered question."""
    print("[SMS DEBUG] send_sms_alert called")
    try:
        import streamlit as st
        sid = st.secrets["TWILIO_ACCOUNT_SID"]
        token = st.secrets["TWILIO_AUTH_TOKEN"]
        from_number = st.secrets["TWILIO_FROM"]
        to_number = st.secrets["HOST_PHONE"]
        print(f"[SMS DEBUG] Got secrets. SID starts with: {str(sid)[:6]}")

        from twilio.rest import Client
        client = Client(sid, token)
        message = client.messages.create(
            body=f"Host Helper Alert: A guest asked:\n\"{question.strip()}\"\n\nUpdate your knowledge base.",
            from_=from_number,
            to=to_number
        )
        print(f"[SMS SENT] SID: {message.sid}")
        return True
    except Exception as e:
        import traceback
        print(f"[SMS ERROR] {e}")
        print(traceback.format_exc())
        # Log error to Google Sheet
        try:
            client = get_gspread_client()
            if client:
                sheet = client.open(LOG_SPREADSHEET_NAME).sheet1
                sheet.append_row(["SMS_ERROR", str(e)])
        except Exception as e2:
            print(f"[SHEET ERROR] {e2}")
        return False

def log_unanswered_question(question):
    """Logs questions to the Google Sheet and sends SMS alert."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = [timestamp, question.strip()]
    print(f"\n[HOST LOG] UNANSWERED: {question.strip()}")
    try:
        client = get_gspread_client()
        if client:
            sheet = client.open(LOG_SPREADSHEET_NAME).sheet1
            sheet.append_row(log_entry)
    except Exception as e:
        print(f"[LOG ERROR] {e}")
    result = send_sms_alert(question)
    print(f"[SMS RESULT] Success: {result}")

def get_knowledge_base():
    """Pulls all data from Google Sheets knowledge base."""
    try:
        client = get_gspread_client()
        if not client:
            return "ERROR: Credentials file not found."
        sheet = client.open(SPREADSHEET_NAME).sheet1
        data = sheet.get_all_records()
        kb_string = ""
        for item in data:
            kb_string += f"{item.get('Topic', 'N/A')}: {item.get('Data', 'N/A')}\n"
        return kb_string.strip()
    except Exception as e:
        return f"ERROR: Failed to load knowledge base. Details: {e}"

def ask_host_helper(question, kb_data, chat_history=None):
    """Generates an AI response based on the Knowledge Base and conversation history."""
    if kb_data.startswith("ERROR"):
        return f"System Error: {kb_data}"

    if chat_history is None:
        chat_history = []

    history_text = ""
    for msg in chat_history:
        role = "Guest" if msg["role"] == "user" else "Assistant"
        history_text += f"{role}: {msg['content']}\n"

    system_prompt = (
        "You are a friendly, concise, and helpful AI assistant for a short-term rental guest. "
        "Your responses should be encouraging and direct. "
        "You must answer the guest's question *only* using the information provided in the 'KNOWLEDGE BASE' below. "
        "Do not make up any information or use outside knowledge. "
        "\n\n**EXCEPTION:** If the guest says 'Hi', 'Hello', 'Thanks', or 'Goodbye', respond politely and naturally WITHOUT using the knowledge base. "
        f"\n\nIf the user asks a specific question and the answer is not in the knowledge base, respond exactly with: '{FALLBACK_RESPONSE}'"
    )

    full_prompt = (
        f"{system_prompt}\n\n"
        f"KNOWLEDGE BASE:\n{kb_data}\n\n"
        f"CONVERSATION HISTORY:\n{history_text}\n"
        f"GUEST QUESTION: {question}"
    )

    try:
        response = genai.GenerativeModel(MODEL).generate_content(full_prompt)
        ai_response = response.text
        if FALLBACK_RESPONSE in ai_response:
            log_unanswered_question(question)
        return ai_response
    except Exception as e:
        if "API_KEY" in str(e) or "invalid API key" in str(e):
            return "AI Error: Your GEMINI_API_KEY is incorrect or not set."
        return f"AI Error: Could not generate response. Details: {e}"
