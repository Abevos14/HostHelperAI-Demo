import streamlit as st
import bot as core
import qrcode
from io import BytesIO

st.set_page_config(page_title="Host Helper AI", page_icon="🏠", layout="centered", initial_sidebar_state="expanded")

APP_URL = "https://hostai-demo.streamlit.app"

@st.cache_data(ttl=3600)
def load_knowledge_base():
    kb_data = core.get_knowledge_base()
    if kb_data.startswith("ERROR"):
        st.error(f"Failed to load KB: {kb_data}")
    return kb_data

@st.cache_data
def generate_qr_code(url):
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "pin_error" not in st.session_state:
    st.session_state.pin_error = False
if "total_count" not in st.session_state:
    st.session_state.total_count = 0
if "unanswered_count" not in st.session_state:
    st.session_state.unanswered_count = 0
if "messages" not in st.session_state:
    st.session_state.messages = []

knowledge_base = load_knowledge_base()
kb_is_ready = not knowledge_base.startswith("ERROR")

if not st.session_state.authenticated:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🏠 Host Helper AI")
        st.markdown("**Welcome to your property assistant.**")
        st.markdown("Please enter the guest PIN provided by your host to continue.")
        st.markdown("<br>", unsafe_allow_html=True)
        pin_input = st.text_input("Guest PIN", type="password", placeholder="Enter your PIN", label_visibility="collapsed")
        if st.button("🔓 Unlock", use_container_width=True):
            correct_pin = core.get_pin(knowledge_base)
            if correct_pin and pin_input.strip() == correct_pin.strip():
                st.session_state.authenticated = True
                st.session_state.pin_error = False
                st.rerun()
            else:
                st.session_state.pin_error = True
        if st.session_state.pin_error:
            st.error("Incorrect PIN. Please check with your host.")
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.caption("Powered by Host Helper AI")
else:
    st.title("🏠 Host Helper AI")
    st.caption("Your instant, property-specific guest assistant.")
    with st.sidebar:
        st.header("Host Dashboard")
        col1, col2 = st.columns(2)
        with col1:
            st.metric(label="Total Chats", value=st.session_state.total_count)
        with col2:
            st.metric(label="Unanswered", value=st.session_state.unanswered_count)
        st.markdown("---")
        st.subheader("Controls")
        if st.button("🔄 Refresh Data"):
            load_knowledge_base.clear()
            st.cache_data.clear()
            st.toast("Data refreshed!", icon="✅")
            st.rerun()
        if st.button("🗑️ Clear Chat History"):
            st.session_state.messages = []
            st.session_state.total_count = 0
            st.session_state.unanswered_count = 0
            st.rerun()
        if st.button("🔒 Lock App"):
            st.session_state.authenticated = False
            st.session_state.messages = []
            st.rerun()
        st.markdown("---")
        st.markdown("**System Status:**")
        st.success("Online" if kb_is_ready else "Offline")
        st.caption(f"Source: `{core.SPREADSHEET_NAME}`")
        st.caption(f"Log: `{core.LOG_SPREADSHEET_NAME}`")
        st.markdown("---")
        st.subheader("Guest QR Code")
        st.caption("Print and display this in your property.")
        st.image(generate_qr_code(APP_URL), use_container_width=True)
        st.download_button(label="Download QR Code", data=generate_qr_code(APP_URL), file_name="host_helper_qr.png", mime="image/png")
    if not st.session_state.messages:
        st.session_state.messages.append({"role": "assistant", "content": "Welcome! I am your host assistant. How can I help you check in or enjoy your stay?"})
    for message in st.session_state.messages:
        avatar_icon = "🏠" if message["role"] == "assistant" else "👤"
        with st.chat_message(message["role"], avatar=avatar_icon):
            st.markdown(message["content"])
    if prompt := st.chat_input("Ask about Wi-Fi, check-in, parking..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar="🏠"):
            with st.spinner("Checking property guide..."):
                if kb_is_ready:
                    response = core.ask_host_helper(prompt, knowledge_base, chat_history=st.session_state.messages)
                    st.session_state.total_count += 1
                    if core.FALLBACK_RESPONSE in response:
                        st.session_state.unanswered_count += 1
                else:
                    response = "System Error: KB not ready."
                st.markdown(response)
        st.session_state.messages.append({"role": "assistant", "content": response})
