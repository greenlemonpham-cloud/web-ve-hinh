import io
import re
import urllib.request
import urllib.error
from PIL import Image
import streamlit as st
from google import genai

# Kiểm tra thư viện dán ảnh tuỳ chọn
try:
    from streamlit_paste_button import paste_image_button
    HAS_PASTE_BUTTON = True
except ImportError:
    HAS_PASTE_BUTTON = False

# ==========================================
# 1. CẤU HÌNH GIAO DIỆN STREAMLIT
# ==========================================
st.set_page_config(
    page_title="Chuyển Đề Bài Sang TikZ",
    layout="wide"
)

st.title("AI Chuyển Đề Bài Hình Học Sang TikZ")
st.caption("Phiên bản tối ưu hoá: Chạy mượt mà, tiết kiệm API Key")

# Khởi tạo Session State cơ bản
if "tikz_code" not in st.session_state:
    st.session_state["tikz_code"] = ""
if "rendered_bytes" not in st.session_state:
    st.session_state["rendered_bytes"] = None
if "render_mime" not in st.session_state:
    st.session_state["render_mime"] = "image/png"
if "used_model" not in st.session_state:
    st.session_state["used_model"] = ""

# ==========================================
# 2. THANH CẤU HÌNH SIDEBAR
# ==========================================
st.sidebar.header("Cấu hình")

if "api_key" not in st.session_state:
    st.session_state["api_key"] = ""

input_api_key = st.sidebar.text_input(
    "Nhập Gemini API Key:",
    value=st.session_state["api_key"],
    type="password",
    help="Lấy API Key miễn phí tại Google AI Studio"
)
if input_api_key:
    st.session_state["api_key"] = input_api_key.strip()

output_format = st.sidebar.selectbox(
    "Định dạng ảnh:",
    options=["png", "svg"],
    index=0
)

if st.sidebar.button("Xóa tất cả làm lại (Reset)", use_container_width=True):
    st.session_state["tikz_code"] = ""
    st.session_state["rendered_bytes"] = None
    st.session_state["used_model"] = ""
    st.rerun()

# ==========================================
# 3. CÁC HÀM XỬ LÝ CHÍNH
# ==========================================
def extract_tikz_code(text: str) -> str:
    """Tách mã TikZ nguyên bản từ phản hồi của AI"""
    if not text:
        return ""
    
    # Tìm đoạn mã nằm trong ```latex ... ``` hoặc ```tikz ... ```
    match = re.search(r"
http://googleusercontent.com/immersive_entry_chip/0
