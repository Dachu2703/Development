import streamlit as st
from pathlib import Path
from .search import search_code
from .patcher import make_patch, apply_patch_local
from .llm import call_llm


st.set_page_config(page_title="Code Assistant", layout="wide")

st.title("Local Code Assistant")

col1, col2 = st.columns([1, 3])

with col1:
    q = st.text_input("Search query or question")
    if st.button("Search") and q:
        results = search_code(q, root='..')
        st.session_state['results'] = results
    if st.button("Ask LLM") and q:
        ans = call_llm(q)
        if ans:
            st.session_state['llm_answer'] = ans
        else:
            st.warning("No LLM configured (set OPENAI_API_KEY) or provider failed.")
    st.write("---")
    st.write("Results")
    for r in st.session_state.get('results', [])[:50]:
        st.markdown(f"- {r['file']}:{r['line_no']} — {r['line']}")

with col2:
    st.header("File Viewer / Patch")
    file_path = st.text_input("File path to open", value="")
    if file_path and st.button("Open"):
        p = Path(file_path)
        if p.exists():
            st.session_state['file_content'] = p.read_text(encoding='utf-8')
        else:
            st.session_state['file_content'] = ""
    content = st.text_area("Content", value=st.session_state.get('file_content', ''), height=400)
    if st.button("Preview Patch"):
        patch = make_patch(file_path, content)
        st.code(patch)
        st.session_state['last_patch'] = patch
    if st.checkbox("Confirm apply patch") and st.button("Apply Patch"):
        try:
            apply_patch_local(file_path, content, overwrite=True)
            st.success(f"Wrote {file_path}")
        except Exception as e:
            st.error(str(e))

    if st.session_state.get('llm_answer'):
        st.subheader("LLM Answer")
        st.write(st.session_state['llm_answer'])
