import os
import asyncio
import streamlit as st
from loguru import logger
import tempfile
import base64
import re
import functools
import html
import time
from typing import Any

# --- BACKEND IMPORTS ---
from main import _prepare_cv_data, _initialize_state, _run_graph
from src.config.settings import config
from src.agents.agents import get_agent_factory
from src.db.database import init_db
from src.graph import build_graph

# --- PAGE CONFIG ---
st.set_page_config(layout="wide", page_title="AGENTIC HIRE AI")


# --- DATABASE INITIALIZATION (run once per session) ---
@st.cache_resource
def init_database() -> None:
    """Initialize database engine once per Streamlit session."""
    asyncio.run(init_db(config))


init_database()


# --- STATE ---
if "running" not in st.session_state:
    st.session_state.running = False

if "logs" not in st.session_state:
    st.session_state.logs = []

if "final_state" not in st.session_state:
    st.session_state.final_state = None

if "cancel_requested" not in st.session_state:
    st.session_state.cancel_requested = False


# --- BASE64 IMAGE ---
@functools.lru_cache(maxsize=10)
def get_base64_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


# --- CSS ---
def inject_layout_css(img_base64: str) -> None:
    st.markdown(
        f"""
    <style>

    .bg-img-container {{
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        z-index: -1;
    }}

    .bg-img-container img {{
        width: 100%;
        height: 100%;
        object-fit: cover;
        filter: brightness(0.6);
    }}

    .stApp {{
        background: transparent;
        color: #C0D6E4;
        font-family: monospace;
    }}

    .glass-panel {{
        background: rgba(10, 31, 51, 0.75);
        backdrop-filter: blur(12px);
        padding: 30px;
        border-radius: 15px;
        border: 1px solid rgba(29, 233, 182, 0.3);
        margin-top: 20px;
    }}

    /* ===== TERMINAL ===== */

    .neural-terminal {{
        height: 600px;
        overflow-y: auto;
        background: rgba(8, 24, 40, 0.95);
        border: 1px solid #1de9b6;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 0 20px rgba(29, 233, 182, 0.3);
    }}

    .msg {{
        display: flex;
        align-items: flex-start;
        gap: 10px;
        margin-bottom: 10px;
        opacity: 0;
        animation: fadeIn 0.4s ease forwards;
    }}

    .msg img {{
        width: 28px;
        height: 28px;
    }}

    .msg-text {{
        font-size: 0.8rem;
        line-height: 1.4;
    }}

    .system {{
        color: #9aa7b0;
        font-style: italic;
    }}

    @keyframes fadeIn {{
        to {{
            opacity: 1;
        }}
    }}

    button {{
        border: 1px solid #1de9b6 !important;
        background: transparent !important;
        color: #1de9b6 !important;
    }}

    /* ===== DYNAMIC TERMINAL ROWS ===== */
    .terminal-row {{
        display: flex;
        align-items: flex-start;
        gap: 10px; /* Adjust this to 0px if you want them touching */
        margin-bottom: 15px;
        width: 100%;
    }}

    .terminal-avatar {{
        flex-shrink: 0;
        border: 1px solid rgba(29, 233, 182, 0.3);
        border-radius: 4px;
        width: 100px;
        height: 100px;
        object-fit: cover;
    }}

    .log-entry {{
        background: rgba(29, 233, 182, 0.07);
        border-left: 4px solid #1de9b6;
        padding: 12px;
        border-radius: 0px 8px 8px 0px;
        flex-grow: 1;
        min-height: 100px;
    }}

    .prefix {{
        color: #1de9b6;
        font-weight: bold;
        font-family: 'Courier New', monospace;
        font-size: 0.9rem;
        margin-bottom: 4px;
        display: inline-block;
        width: 160px;
        min-width: 160px;
        height: 24px;
        flex-shrink: 0;
    }}

    .msg-content {{
        color: #C0D6E4;
        font-family: monospace;
        font-size: 0.95rem;
        word-break: break-word;
    }}

    .log-entry.scout, .log-entry.tailor, .log-entry.orchestrator {{
        background: rgba(3, 169, 244, 0.07);
        border-left-color: #03A9F4;
    }}
    .log-entry.scout .prefix, .log-entry.scout .msg-content,
    .log-entry.tailor .prefix, .log-entry.tailor .msg-content,
    .log-entry.orchestrator .prefix, .log-entry.orchestrator .msg-content {{
        color: #03A9F4;
    }}

    .log-entry.system {{
        background: rgba(29, 233, 182, 0.07);
        border-left-color: #1de9b6;
    }}
    .log-entry.system .prefix, .log-entry.system .msg-content {{
        color: #1de9b6;
    }}

    .log-entry.WARNING {{
        background: rgba(255, 193, 7, 0.07) !important;
        border-left-color: #ffc107 !important;
    }}
    .log-entry.WARNING .prefix, .log-entry.WARNING .msg-content {{
        color: #ffc107 !important;
    }}
    .log-entry.ERROR {{
        background: rgba(244, 67, 54, 0.07) !important;
        border-left-color: #f44336 !important;
    }}
    .log-entry.ERROR .prefix, .log-entry.ERROR .msg-content {{
        color: #f44336 !important;
    }}
    </style>

    <div class="bg-img-container">
        <img src="data:image/png;base64,{img_base64}">
    </div>
    """,
        unsafe_allow_html=True,
    )


# --- TERMINAL RENDERER ---
def render_terminal(placeholder: Any, logs: list[Any]) -> None:
    """Zero-gap terminal using pure HTML/CSS for log rows."""
    with placeholder.container():
        with st.container(height=600, border=True):
            if not logs:
                st.write("SYSTEM_IDLE: Awaiting Uplink...")
                return

            for log_item in reversed(logs[-50:]):
                agent = log_item[0]
                text = log_item[1]
                img = log_item[2]
                level = log_item[3] if len(log_item) > 3 else "INFO"

                # Convert image to base64 to use inside raw HTML
                img_html = ""
                if img and os.path.exists(img):
                    data = get_base64_image(img)
                    img_html = f'<img src="data:image/png;base64,{data}" width="100" class="terminal-avatar">'
                else:
                    img_html = '<div class="terminal-avatar" style="display:flex; align-items:center; justify-content:center; font-size:40px;">⚙️</div>'

                prefix = {
                    "scout": "[SCOUT]",
                    "tailor": "[TAILOR]",
                    "orchestrator": "[ORCHESTRATOR]",
                    "system": "[SYS_MSG]",
                }.get(agent, "LOG")

                # Single markdown call for the whole row ensures no Streamlit column padding
                st.markdown(
                    f"""
                    <div class="terminal-row">
                        {img_html}
                        <div class="log-entry {level} {agent}">
                            <div class="prefix">{prefix}</div>
                            <div class="msg-content">{text}</div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# --- LOG SINK ---
class StreamlitLogSink:
    def __init__(self, placeholder: Any, log_buffer: list[Any]) -> None:
        self.placeholder = placeholder
        self.log_buffer = log_buffer
        self.handler_id: Any = None
        self.last_update: float = 0.0

    def write(self, message: Any) -> None:
        clean = str(message).strip()

        level = "INFO"
        if hasattr(message, "record"):
            level = message.record["level"].name
        elif "[ERROR]" in clean.upper() or "EXCEPTION" in clean.upper():
            level = "ERROR"
        elif "[WARNING]" in clean.upper() or "[WARN]" in clean.upper():
            level = "WARNING"

        if level == "CRITICAL":
            level = "ERROR"

        if "[SCOUT]" in clean:
            agent = "scout"
            img = "ui/images/scout_avatar.jpg"
        elif "[TAILOR]" in clean:
            agent = "tailor"
            img = "ui/images/tailor_avatar.jpg"
        elif "[ORCHESTRATOR]" in clean:
            agent = "orchestrator"
            img = "ui/images/orch_avatar.jpg"
        else:
            agent = "system"
            img = "ui/images/cpu_avatar.jpg"

        self.log_buffer.append((agent, clean, img, level))

        # Throttle UI updates to roughly 2 FPS (every 0.5 seconds)
        current_time = time.time()
        if current_time - self.last_update > 0.5:
            render_terminal(self.placeholder, self.log_buffer)
            self.last_update = current_time

    def __enter__(self) -> "StreamlitLogSink":
        self.handler_id = logger.add(
            self, format="{time:HH:mm:ss} | {message}", level="INFO"
        )
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        if self.handler_id:
            logger.remove(self.handler_id)


# --- MAIN APP ---
def streamlit_app() -> None:

    img_path = "ui/images/bg.jpg"
    if os.path.exists(img_path):
        inject_layout_css(get_base64_image(img_path))

    col_left, col_right = st.columns([1, 1.5])

    with col_left:
        st.title("AGENTIC HIRE AI")
        st.caption("HEADHUNTER PROTOCOL v1.0")
        st.write("---")

        uploaded_file = st.file_uploader("Upload CV (PDF)", type=["pdf"])

        st.text_area(
            "Search Parameters:",
            height=120,
            value=f"{config.initial_prompt}",
            key="criteria",
        )

        c1, c2 = st.columns(2)
        start = c1.button("INITIALIZE", use_container_width=True)
        stop = c2.button("ABORT", use_container_width=True)

    with col_right:
        status_placeholder = st.empty()
        terminal_placeholder = st.empty()

        if stop:
            st.session_state.cancel_requested = True
            st.session_state.running = False
            st.session_state.logs.append(
                ("system", "[SYSTEM] Aborted by user.", None, "WARNING")
            )
            status_placeholder.warning("Process stopped.")
            st.stop()

        if start:
            if not uploaded_file:
                status_placeholder.error("Upload CV first.")
                return

            st.session_state.running = True
            st.session_state.logs = []
            st.session_state.final_state = None
            st.session_state.cancel_requested = False

            st.rerun()

        if st.session_state.running:
            cv_path = None

            try:
                if not uploaded_file:
                    status_placeholder.error("Upload CV first.")
                    return
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    cv_path = tmp.name

                with StreamlitLogSink(terminal_placeholder, st.session_state.logs):
                    status_placeholder.info("Agents are running...")

                    cv_manager = _prepare_cv_data(cv_path, get_agent_factory())

                    state = _initialize_state(
                        cv_manager, config, user_prompt=st.session_state.criteria
                    )

                    # Inject the user's search criteria into the graph state
                    # (Note: Update "search_parameters" to match your actual LangGraph state schema)
                    state["search_parameters"] = st.session_state.criteria

                    final_state = _run_graph(state, build_graph())

                    st.session_state.final_state = final_state
                    status_placeholder.success("✅ Done")

            except Exception as e:
                logger.error(f"[ERROR] {e}")
                status_placeholder.error(str(e))

            finally:
                if cv_path and os.path.exists(cv_path):
                    os.remove(cv_path)

                # Guarantee final render of logs even if the last ones were throttled
                render_terminal(terminal_placeholder, st.session_state.logs)

                st.session_state.running = False

        # This ensures the terminal stays populated with the last logs after a run
        # or shows the idle message on first load.
        else:
            render_terminal(terminal_placeholder, st.session_state.logs)

        if st.session_state.final_state:
            st.markdown("## 🎯 Results")
            apps = st.session_state.final_state.get("applications", {})

            for _, content in apps.items():
                st.markdown(
                    f"""
                <div class="glass-panel">
                    <h4>{content.get('job_title')} / {content.get('company')}</h4>
                    <p>{content.get('founded_job_offer')}</p>
                </div>
                """,
                    unsafe_allow_html=True,
                )


if __name__ == "__main__":
    streamlit_app()
