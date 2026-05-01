try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import os
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from datetime import datetime

SPREADSHEET_NAME = "HostHelperAI"
LOG_SPREADSHEET_NAME = "Host Helper AI Log"
CREDS_FILE = "credentials.json"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("[CRITICAL WARNING] GEMINI_API_KEY not found.")

MODEL = "gemini-2.5-flash"

FALLBACK_RESPONSE = "I'm sorry, I don't have that specific information. I will notify the host to help you with that."

def get_gspread_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
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

def get_pin(kb_data):
    for line in kb_data.splitlines():
        if line.lower().startswith("pin:"):
            return line.split(":", 1)[1].strip()
    return None

def send_email_alert(question):
    try:
        import streamlit as st
        gmail_user = st.secrets["GMAIL_USER"]
        gmail_password = st.secrets["GMAIL_APP_PASSWORD"]
        host_email = st.secrets["HOST_EMAIL"]
        subject = "Host Helper AI - Unanswered Guest Question"
        body = f"A guest just asked your property bot a question it could not answer.\n\nQuestion: \"{question.strip()}\"\n\nTime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\nConsider adding this topic to your knowledge base so the bot can answer it next time.\n\n- Host Helper AI"
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = formataddr(("Host Helper AI", gmail_user))
        msg["To"] = host_email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

def send_sms_alert(question):
    try:
        import streamlit as st
        sid = st.secrets["TWILIO_ACCOUNT_SID"]
        token = st.secrets["TWILIO_AUTH_TOKEN"]
        from_number = st.secrets["TWILIO_FROM"]
        to_number = st.secrets["HOST_PHONE"]
        from twilio.rest import Client
        client = Client(sid, token)
        message = client.messages.create(
            body=f"Host Helper Alert: A guest asked:\n\"{question.strip()}\"\n\nUpdate your knowledge base.",
            from_=from_number,
            to=to_number
        )
        return True
    except Exception as e:
        print(f"[SMS ERROR] {e}")
        return False

def log_unanswered_question(question):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = [timestamp, question.strip()]
    try:
        client = get_gspread_client()
        if client:
            sheet = client.open(LOG_SPREADSHEET_NAME).sheet1
            sheet.append_row(log_entry)
    except Exception as e:
        print(f"[LOG ERROR] {e}")
    send_email_alert(question)
    send_sms_alert(question)

def get_knowledge_base():
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

def build_prompt(question, kb_data, chat_history=None):
    if chat_history is None:
        chat_history = []
    history_text = ""
    for msg in chat_history:
        role = "Guest" if msg["role"] == "user" else "Assistant"
        history_text += f"{role}: {msg['content']}\n"
    system_prompt = (
        "You are a friendly, concise, and helpful AI assistant for a short-term rental guest. "
        "Your responses should be encouraging and direct. "
        "You must answer the guest question only using the information provided in the KNOWLEDGE BASE below. "
        "Do not make up any information or use outside knowledge. "
        "\n\n**EXCEPTION:** If the guest says Hi, Hello, Thanks, or Goodbye, respond politely and naturally WITHOUT using the knowledge base. "
        f"\n\nIf the user asks a specific question and the answer is not in the knowledge base, respond exactly with: '{FALLBACK_RESPONSE}'"
    )
    return f"{system_prompt}\n\nKNOWLEDGE BASE:\n{kb_data}\n\nCONVERSATION HISTORY:\n{history_text}\nGUEST QUESTION: {question}"

def ask_host_helper(question, kb_data, chat_history=None):
    """Non-streaming version - returns full response as string."""
    if kb_data.startswith("ERROR"):
        return f"System Error: {kb_data}"
    full_prompt = build_prompt(question, kb_data, chat_history)
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

def ask_host_helper_stream(question, kb_data, chat_history=None):
    """Streaming version - yields chunks as they arrive. Returns full text via generator."""
    if kb_data.startswith("ERROR"):
        yield f"System Error: {kb_data}"
        return
    full_prompt = build_prompt(question, kb_data, chat_history)
    try:
        response = genai.GenerativeModel(MODEL).generate_content(full_prompt, stream=True)
        full_text = ""
        for chunk in response:
            if chunk.text:
                full_text += chunk.text
                yield chunk.text
        # After streaming completes, check for fallback and log if needed
        if FALLBACK_RESPONSE in full_text:
            log_unanswered_question(question)
    except Exception as e:
        if "API_KEY" in str(e) or "invalid API key" in str(e):
            yield "AI Error: Your GEMINI_API_KEY is incorrect or not set."
        else:
            yield f"AI Error: Could not generate response. Details: {e}"
