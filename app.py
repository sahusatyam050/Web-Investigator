import asyncio
import uuid
import streamlit as st
from database.db_manager import DatabaseManager
from core.validator import TargetValidator
from core.browser_engine import PlaywrightInvestigationEngine
from ui.components import inject_custom_css
from ui.dashboard import render_dashboard
from config import DEFAULT_MAX_PAGES
import threading
from streamlit.runtime.scriptrunner import add_script_run_ctx

# Page Configuration
st.set_page_config(
    page_title="Gaming Website Investigation Prototype",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inject modern dark theme styles
inject_custom_css()

# Initialize Database Manager
db_manager = DatabaseManager()

# Session State Initialization
if "engine" not in st.session_state:
    st.session_state.engine = None
if "current_inv_id" not in st.session_state:
    st.session_state.current_inv_id = None
if "status" not in st.session_state:
    st.session_state.status = "idle" # idle, running, paused_auth, completed, stopped
if "logs" not in st.session_state:
    st.session_state.logs = []

def add_log(action: str, status: str):
    st.session_state.logs.append(f"[{status}] {action}")

def trigger_auth_pause():
    st.session_state.status = "paused_auth"

# Main Header
st.markdown('<div class="main-header">Gaming Website Investigation Prototype</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Automated Evidence Collection Engine (Version 1)</div>', unsafe_allow_html=True)

# Sidebar for Past Investigations
with st.sidebar:
    st.markdown("### 📜 Past Investigations")
    all_invs = db_manager.get_all_investigations()
    if all_invs:
        inv_options = {f"{inv['website_url']} ({inv['start_time']})": inv['id'] for inv in all_invs}
        selected_past = st.selectbox("Select Previous Case:", ["-- Select Current / New Run --"] + list(inv_options.keys()))
        if selected_past != "-- Select Current / New Run --":
            st.session_state.current_inv_id = inv_options[selected_past]
            st.session_state.status = "completed"
    else:
        st.info("No past investigations recorded.")

# Step 1: Homepage Controls
st.markdown("### 🎯 Investigation Controls")
url_input = st.text_input("Website URL", placeholder="https://parimatch.com", key="url_input")

# Optional Auto-Login Credentials Section
with st.expander("🔑 Auto-Login Credentials (Optional — Automated Authentication)", expanded=False):
    c_auth_col1, c_auth_col2, c_auth_col3 = st.columns([2, 3, 3])
    with c_auth_col1:
        auth_mode = st.selectbox("Login Mode", ["Auto-Detect", "Phone / Mobile Number", "User ID / Username", "Email"], key="auth_mode")
    with c_auth_col2:
        auth_user = st.text_input("Username / Mobile / Email", placeholder="e.g. 9876543210 or Shinchan2001", key="auth_user")
    with c_auth_col3:
        auth_pass = st.text_input("Password", type="password", placeholder="Enter account password", key="auth_pass")

col_start, col_stop, col_limit = st.columns([2, 2, 3])

with col_limit:
    max_pages = st.slider("Max Crawl Pages (Priority First)", min_value=1, max_value=50, value=DEFAULT_MAX_PAGES)

with col_start:
    start_clicked = st.button("🔍 Start Investigation", use_container_width=True, type="primary", disabled=(st.session_state.status == "running"))

with col_stop:
    stop_clicked = st.button("🛑 Stop Investigation", use_container_width=True, disabled=(st.session_state.status != "running"))

# Handle Stop Button Click
if stop_clicked and st.session_state.get("engine"):
    st.session_state.engine.request_stop()
    st.warning("Stop request sent to crawler. Finalizing evidence collected so far...")

# Step 6: Authentication Banner (if login required)
if st.session_state.status == "paused_auth":
    st.markdown("""
        <div class="auth-banner">
            ⚠️ Login Required — Please log in manually in the open browser window on your screen.<br>
            After logging in, click the button below to resume evidence collection.
        </div>
    """, unsafe_allow_html=True)
    if st.button("▶️ Resume Investigation", type="primary"):
        if st.session_state.engine:
            st.session_state.engine.resume_investigation()
            st.session_state.status = "running"
            st.rerun()

# Execute Start Investigation Workflow
if start_clicked and url_input.strip():
    target_url = url_input.strip()
    st.session_state.logs = []
    
    # Step 2: Validate Target URL
    st.info(f"Validating target URL: `{target_url}`...")
    val_result = TargetValidator.validate_url(target_url)
    
    if not val_result["valid"]:
        st.error(f"❌ Target Validation Failed: {val_result.get('error', 'Unreachable website')}")
        st.session_state.status = "idle"
    else:
        st.success(f"✅ Target Validated: Reachable ({val_result['status_code']}), HTTPS: {val_result['is_https']}")
        
        investigation_id = f"INV_{uuid.uuid4().hex[:8].upper()}"
        st.session_state.current_inv_id = investigation_id
        st.session_state.status = "running"

        # Instantiate Browser Engine
        engine = PlaywrightInvestigationEngine(db_manager, max_pages=max_pages)
        st.session_state.engine = engine
        st.session_state.progress_text = "🚀 Launching Playwright Engine..."

        # Use thread-safe queues to pass data from background thread to Streamlit UI
        import queue
        if "prog_q" not in st.session_state: st.session_state.prog_q = queue.Queue()
        if "log_q" not in st.session_state: st.session_state.log_q = queue.Queue()

        # Run Async Playwright Workflow in Background Thread to Keep UI Unblocked
        def run_crawler_thread():
            try:
                def safe_update_progress(msg):
                    st.session_state.prog_q.put(msg)
                
                def safe_log(msg, level="INFO"):
                    import time
                    st.session_state.log_q.put(f"{time.strftime('%H:%M:%S')} | {level} | {msg}")

                asyncio.run(engine.run_investigation(
                    target_url=val_result["final_url"],
                    investigation_id=investigation_id,
                    log_callback=safe_log,
                    auth_callback=trigger_auth_pause,
                    progress_callback=safe_update_progress,
                    auth_user=auth_user.strip() if auth_user else "",
                    auth_pass=auth_pass.strip() if auth_pass else "",
                    auth_mode=auth_mode
                ))
            except Exception as e:
                import traceback
                print(f"🔥 BACKGROUND THREAD ERROR: {e}")
                traceback.print_exc()
            finally:
                st.session_state.status = "completed"
                st.session_state.engine = None
        
        t = threading.Thread(target=run_crawler_thread, daemon=True)
        add_script_run_ctx(t)
        t.start()
        st.rerun()

# Dynamic Progress Tracker using st.fragment
@st.fragment(run_every="1s")
def render_live_progress():
    if st.session_state.status == "running":
        # Pull latest progress & logs from thread-safe queues
        if "prog_q" in st.session_state:
            while not st.session_state.prog_q.empty():
                st.session_state.progress_text = st.session_state.prog_q.get()
        
        if "log_q" in st.session_state:
            while not st.session_state.log_q.empty():
                st.session_state.logs.append(st.session_state.log_q.get())

        st.info(f"⏳ {st.session_state.get('progress_text', 'Investigating...')}")
        
        if st.session_state.get("logs"):
            st.markdown("### 📋 Live Investigation Logs")
            with st.container():
                for log in st.session_state.logs[-10:]:
                    st.code(log)
    elif st.session_state.status == "completed" and "engine" not in st.session_state:
        # If thread marked as completed, force full page reload to show dashboard
        st.session_state.engine = "CLEARED" # Prevent infinite rerun loop
        st.rerun()

# Call the dynamic fragment
if st.session_state.status in ["running", "completed"]:
    render_live_progress()

# Step 12: Render Evidence Dashboard if Investigation is Selected / Completed
if st.session_state.current_inv_id and st.session_state.status in ["completed", "stopped"]:
    st.markdown("---")
    render_dashboard(db_manager, st.session_state.current_inv_id)
