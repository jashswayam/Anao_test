import streamlit as st
import os
import tempfile
import shutil
from dotenv import load_dotenv
from utils import AIOrchestrator, extract_zip, get_codebase_summary, run_test_command, parse_and_save_test_files

# Load environment variables
load_dotenv()

st.set_page_config(page_title="AI Testing Framework Dashboard", layout="wide")

st.title("🚀 AI-Powered Testing Framework Dashboard")
st.markdown("""
Upload your Functional (FSD) and Technical (TSD) specifications, along with your project repository, 
to automatically generate and execute unit and flow tests.
""")

# Sidebar Configuration
st.sidebar.header("⚙️ Configuration")

with st.sidebar.expander("🌐 API Settings", expanded=True):
    api_key = st.text_input("API Key", type="password", value=os.getenv("API_KEY", ""))
    base_url = st.text_input("Base URL", value=os.getenv("BASE_URL", "https://api.openai.com/v1"))
    http_timeout = st.number_input("Request Timeout (seconds)", min_value=1, max_value=600, value=60)
    st.caption("Common API configuration for both models.")

with st.sidebar.expander("🤖 Model Selection", expanded=True):
    l1_model = st.text_input("Vision Model Name (L1)", value="gpt-4o", help="Model used to convert PDF/Images to Markdown")
    l2_model = st.text_input("Reasoning Model Name (L2)", value="gpt-4o", help="Text-only model used for test planning and code generation")

# Main Dashboard Layout
col1, col2 = st.columns(2)

with col1:
    st.header("📄 Specification Upload")
    fsd_file = st.file_uploader("Upload FSD (PDF/Image)", type=["pdf", "png", "jpg", "jpeg"])
    tsd_file = st.file_uploader("Upload TSD (PDF/Image)", type=["pdf", "png", "jpg", "jpeg"])

with col2:
    st.header("📦 Codebase Upload")
    codebase_zip = st.file_uploader("Upload Project Repository (ZIP)", type=["zip"])

# Session State for generated content
if 'fsd_md' not in st.session_state: st.session_state.fsd_md = ""
if 'tsd_md' not in st.session_state: st.session_state.tsd_md = ""
if 'testing_md' not in st.session_state: st.session_state.testing_md = ""
if 'logs' not in st.session_state: st.session_state.logs = ""
if 'temp_repo_path' not in st.session_state: st.session_state.temp_repo_path = ""

def cleanup_temp():
    if st.session_state.temp_repo_path and os.path.exists(st.session_state.temp_repo_path):
        try:
            shutil.rmtree(st.session_state.temp_repo_path)
        except Exception as e:
            st.error(f"Error cleaning up temp directory: {e}")

if st.button("Generate Test Plan", use_container_width=True):
    if not (fsd_file and tsd_file and codebase_zip):
        st.error("Please upload FSD, TSD, and Codebase ZIP file.")
    elif not api_key:
        st.error("Please provide an API key in the sidebar.")
    else:
        with st.status("Processing Pipeline...", expanded=True) as status:
            orchestrator = AIOrchestrator(
                l1_config={'api_key': api_key, 'base_url': base_url, 'model_name': l1_model},
                l2_config={'api_key': api_key, 'base_url': base_url, 'model_name': l2_model},
                timeout=http_timeout
            )
            
            # Phase 2: Layer 1 - Document Processing
            st.write("Extracting FSD content using Vision Model...")
            st.session_state.fsd_md = orchestrator.process_document(fsd_file, fsd_file.name, fsd_file.type)
            
            st.write("Extracting TSD content using Vision Model...")
            st.session_state.tsd_md = orchestrator.process_document(tsd_file, tsd_file.name, tsd_file.type)
            
            # Phase 3: Layer 2 - Codebase Analysis & Test Plan
            st.write("Analyzing codebase...")
            cleanup_temp() # Clean up old run
            st.session_state.temp_repo_path = tempfile.mkdtemp()
            extract_zip(codebase_zip, st.session_state.temp_repo_path)
            summary = get_codebase_summary(st.session_state.temp_repo_path)
            
            st.write("Generating testing.md using Reasoning Model...")
            st.session_state.testing_md = orchestrator.generate_test_plan(
                st.session_state.fsd_md, 
                st.session_state.tsd_md, 
                summary
            )
            
            status.update(label="Test Plan Generated!", state="complete", expanded=False)

st.divider()
st.subheader("📊 Output Logs & Generated Files")

tabs = st.tabs(["FSD.md", "TSD.md", "testing.md", "Execution Logs"])
with tabs[0]:
    st.markdown(st.session_state.fsd_md if st.session_state.fsd_md else "FSD markdown will appear here.")
with tabs[1]:
    st.markdown(st.session_state.tsd_md if st.session_state.tsd_md else "TSD markdown will appear here.")
with tabs[2]:
    st.markdown(st.session_state.testing_md if st.session_state.testing_md else "Testing plan markdown will appear here.")
    if st.session_state.testing_md:
        if st.button("Execute Tests"):
            if not st.session_state.temp_repo_path:
                st.error("Repo path not found. Please regenerate the test plan.")
            else:
                with st.status("Executing Tests...", expanded=True) as status:
                    orchestrator = AIOrchestrator(
                        l1_config={'api_key': api_key, 'base_url': base_url, 'model_name': l1_model},
                        l2_config={'api_key': api_key, 'base_url': base_url, 'model_name': l2_model},
                        timeout=http_timeout
                    )
                    
                    st.write("Generating test files...")
                    summary = get_codebase_summary(st.session_state.temp_repo_path)
                    test_files_raw = orchestrator.generate_test_files(st.session_state.testing_md, summary)
                    saved_files = parse_and_save_test_files(test_files_raw, st.session_state.temp_repo_path)
                    
                    if not saved_files:
                        st.warning("No test files were generated by the AI.")
                    else:
                        st.write(f"Generated {len(saved_files)} test files: {', '.join(saved_files)}")
                        
                        st.write("Running tests...")
                        st.session_state.logs = ""
                        for test_file in saved_files:
                            st.write(f"Running {test_file}...")
                            if test_file.endswith('.py'):
                                cmd = f"pytest {test_file}"
                            elif test_file.endswith('.robot'):
                                cmd = f"robot {test_file}"
                            else:
                                st.write(f"Skipping {test_file}: No runner configured.")
                                continue
                                
                            output = run_test_command(cmd, st.session_state.temp_repo_path)
                            st.session_state.logs += f"--- Result for {test_file} ---\n" + output + "\n"
                    
                    status.update(label="Tests Executed!", state="complete", expanded=False)
                    st.rerun()

with tabs[3]:
    st.code(st.session_state.logs if st.session_state.logs else "Test execution logs will appear here.")
