import os
import sys

# 1. Ép Python sử dụng UTF-8 trên toàn hệ thống (Khắc phục triệt để lỗi ASCII trên Windows)
os.environ["PYTHONUTF8"] = "1"
os.environ["PYTHONIOENCODING"] = "utf-8"

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import io
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from PIL import Image
from google import genai
import streamlit as st

# Kiểm tra & tự động bắt lỗi nếu chưa cài streamlit-paste-button
try:
    from streamlit_paste_button import paste_image_button
    HAS_PASTE_BUTTON = True
except ImportError:
    HAS_PASTE_BUTTON = False

# ==========================================
# CẤU HÌNH GIAO DIỆN STREAMLIT
# ==========================================
st.set_page_config(
    page_title="Chuyển Ảnh Bài Toán Sang TikZ",
    page_icon="📐",
    layout="wide",
)

st.title("📐 AI Chuyển Đề Bài Hình Học Sang Hình Vẽ TikZ")
st.markdown("Made by levu | **Hiển thị chính xác Model AI xử lý thành công**")

# Khởi tạo Session State
if "paste_key" not in st.session_state:
    st.session_state["paste_key"] = 0
if "rendered_image" not in st.session_state:
    st.session_state["rendered_image"] = None
if "tikz_code" not in st.session_state:
    st.session_state["tikz_code"] = ""
if "render_mime" not in st.session_state:
    st.session_state["render_mime"] = "image/png"
if "cooldown_until" not in st.session_state:
    st.session_state["cooldown_until"] = 0
if "used_model" not in st.session_state:
    st.session_state["used_model"] = ""

# Sidebar
st.sidebar.header("⚙️ Cấu hình Hệ thống")

if "user_api_key" not in st.session_state:
    st.session_state["user_api_key"] = ""

input_key = st.sidebar.text_input(
    "Nhập Gemini API Key của bạn:",
    value=st.session_state["user_api_key"],
    type="password",
    help="Copy mã API key từ Google AI Studio và dán vào đây",
)

if input_key:
    st.session_state["user_api_key"] = input_key.strip()

api_key = st.session_state["user_api_key"]

render_format = st.sidebar.selectbox(
    "🖼️ Định dạng ảnh đầu ra:",
    options=["png", "svg"],
    index=0,
    help="Chọn SVG để có chất lượng ảnh vector nét tuyệt đối khi chèn vào đề thi Word/LaTeX"
)

current_now = time.time()
if st.session_state["cooldown_until"] > current_now:
    remaining_secs = int(st.session_state["cooldown_until"] - current_now)
    st.sidebar.warning(f"⏳ Cần chờ: **{remaining_secs} giây** để gửi yêu cầu tiếp theo.")
else:
    st.sidebar.success("🟢 API Sẵn sàng sử dụng!")

@st.cache_resource
def get_gemini_client(key: str):
    return genai.Client(api_key=key)

# ==========================================
# HÀM XỬ LÝ CHUỖI & API
# ==========================================
def sanitize_text_for_api(text: str) -> str:
    """Loại bỏ các ký tự Emoji gây lỗi encode ASCII/Unicode khi gọi API trên Windows"""
    if not isinstance(text, str):
        return text
    # Xóa các ký tự emoji Unicode thuộc dải biểu tượng
    clean_str = re.sub(r'[\U00010000-\U0010ffff\u2600-\u27bf\u1f300-\u1f9ff]', '', text)
    return clean_str.strip()

def run_cooldown_countdown(seconds: int = 60, message: str = "Đang chờ hồi hạn mức (Quota) từ Google"):
    st.session_state["cooldown_until"] = time.time() + seconds
    progress_bar = st.progress(1.0)
    status_text = st.empty()
    
    for remaining in range(seconds, 0, -1):
        percent = remaining / seconds
        progress_bar.progress(percent)
        status_text.warning(f"⏳ **{message}:** Còn lại **{remaining} giây**...")
        time.sleep(1)
        
    progress_bar.empty()
    status_text.success("✅ Đã hết thời gian chờ! Bạn có thể bấm gửi lại ngay.")

def clean_tikz_code(raw_text: str) -> str:
    if not raw_text:
        return ""
    
    # Bỏ qua nếu chuỗi bị dính thông báo lỗi API
    if any(err_word in raw_text for err_word in ["ascii", "RESOURCE_EXHAUSTED", "Lỗi", "429"]):
        return ""

    match_codeblock = re.search(r"\x60{3}(?:latex|tikz)?\n(.*?)\x60{3}", raw_text, re.DOTALL)
    text = match_codeblock.group(1).strip() if match_codeblock else raw_text.strip()

    match_tikz = re.search(r"(\\begin\{tikzpicture\}.*?\\end\{tikzpicture\})", text, re.DOTALL)
    if match_tikz:
        return match_tikz.group(1).strip()

    cleaned_lines = []
    for line in text.split("\n"):
        line_str = line.strip()
        if any(line_str.startswith(cmd) for cmd in ["\\documentclass", "\\usepackage", "\\begin{document}", "\\end{document}", "\\usetikzlibrary"]):
            continue
        cleaned_lines.append(line)

    clean_body = "\n".join(cleaned_lines).strip()
    if clean_body and not clean_body.startswith("\\begin{tikzpicture}"):
        clean_body = f"\\begin{{tikzpicture}}\n{clean_body}\n\\end{{tikzpicture}}"
    return clean_body

def render_tikz(tikz_code: str, output_format: str = "png") -> tuple[bytes | None, str | None]:
    if not tikz_code.strip():
        return None, "Mã TikZ không hợp lệ hoặc rỗng."

    full_doc = f"""\\documentclass[tikz,border=5pt]{{standalone}}
\\usepackage{{amsmath,amssymb}}
\\usetikzlibrary{{calc,arrows,arrows.meta,intersections,shapes,patterns,angles,quotes}}
\\begin{{document}}
{tikz_code}
\\end{{document}}"""

    url = f"https://kroki.io/tikz/{output_format}"
    try:
        req = urllib.request.Request(
            url,
            data=full_doc.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                return response.read(), None
            return None, f"Lỗi Kroki: HTTP {response.status}"
    except urllib.error.HTTPError as e:
        try:
            error_details = e.read().decode('utf-8', errors='ignore')
            clean_err = re.sub(r'<[^>]+>', '', error_details).strip()
            return None, f"Lỗi cú pháp TikZ (HTTP {e.code}): {clean_err[:250]}"
        except Exception:
            return None, f"Lỗi biên dịch Kroki: HTTP {e.code}"
    except Exception as e:
        return None, f"Lỗi kết nối Render: {e}"

def generate_fast(client, contents_payload):
    fast_models = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
    ]

    error_logs = []
    hit_rate_limit = False

    # Lọc sạch emoji khỏi toàn bộ nội dung gửi đến Google API
    clean_payload = []
    for item in contents_payload:
        if isinstance(item, str):
            clean_payload.append(sanitize_text_for_api(item))
        else:
            clean_payload.append(item)

    for model_name in fast_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=clean_payload,
            )
            if response and response.text:
                return response.text, None, False, model_name
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                hit_rate_limit = True
                error_logs.append(f"- {model_name}: Vượt quá hạn mức lượt gọi Free Quota.")
            else:
                # Làm sạch thông báo lỗi trước khi hiển thị
                safe_msg = sanitize_text_for_api(err_msg)
                error_logs.append(f"- {model_name}: {safe_msg[:120]}")
            continue

    detailed_error = "\n".join(error_logs)
    return None, f"AI chưa thể xử lý. Chi tiết lỗi từ Google API:\n{detailed_error}", hit_rate_limit, None

# ==========================================
# LUỒNG XỬ LÝ GIAO DIỆN CHÍNH
# ==========================================
if api_key:
    try:
        client = get_gemini_client(api_key.strip())
    except Exception as e:
        st.error(f"Lỗi khởi tạo Gemini Client: {e}")
        client = None

    if client:
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("1. Đề bài Hình học")
            image_to_process = None

            if HAS_PASTE_BUTTON:
                st.markdown("📋 **Dán nhanh từ bộ nhớ tạm:**")
                paste_result = paste_image_button(
                    label="📋 Bấm vào đây để Dán ảnh đã chụp",
                    background_color="#2563EB",
                    text_color="#FFFFFF",
                    key=f"paste_btn_{st.session_state['paste_key']}",
                )
                if paste_result is not None and paste_result.image_data is not None:
                    image_to_process = paste_result.image_data
                st.markdown("---")

            uploaded_file = st.file_uploader(
                "Chọn tệp ảnh từ máy tính / Kéo thả vào đây:",
                type=["jpg", "jpeg", "png"],
                key=f"uploader_{st.session_state['paste_key']}",
            )
            if uploaded_file is not None and image_to_process is None:
                try:
                    image_to_process = Image.open(uploaded_file)
                except Exception:
                    st.error("Không thể đọc định dạng ảnh này.")

            if image_to_process is not None:
                try:
                    if isinstance(image_to_process, bytes):
                        image_to_process = Image.open(io.BytesIO(image_to_process))
                    if image_to_process.mode != "RGB":
                        image_to_process = image_to_process.convert("RGB")
                except Exception:
                    pass

                st.image(image_to_process, caption="Ảnh đề bài đã sẵn sàng", use_container_width=True)

                if st.button("❌ Xóa ảnh", use_container_width=True):
                    st.session_state["paste_key"] += 1
                    st.session_state["rendered_image"] = None
                    st.session_state["tikz_code"] = ""
                    st.session_state["used_model"] = ""
                    st.rerun()

                if st.button("🚀 Chuyển đổi & Vẽ hình ngay", type="primary", use_container_width=True):
                    now = time.time()
                    if st.session_state["cooldown_until"] > now:
                        wait_sec = int(st.session_state["cooldown_until"] - now)
                        st.warning(f"⚠️ Vui lòng chờ hết thời gian đếm ngược ({wait_sec}s nữa).")
                    else:
                        prompt = """
                        Role: Professor of Mathematics & Expert in TikZ/LaTeX.
                        Objective: Analyze the geometric figure/diagram in the provided image and generate valid, compilable TikZ code.
                        Guidelines:
                        1. Use \\documentclass[tikz, border=5mm]{standalone}.
                        2. Include libraries like calc, angles, quotes, intersections, 3d, arrows.meta.
                        3. Define explicit coordinates before drawing paths.
                        Output format: Return ONLY a code block ```latex ... ```.
                        """

                        with st.spinner("⚡ AI đang phân tích và tạo hình..."):
                            generated_text, err, hit_limit, used_model = generate_fast(client, [image_to_process, prompt])

                            if generated_text:
                                tikz_code = clean_tikz_code(generated_text)
                                st.session_state["tikz_code"] = tikz_code
                                st.session_state["used_model"] = used_model

                                img_bytes, render_err = render_tikz(tikz_code, output_format=render_format)
                                if img_bytes:
                                    st.session_state["rendered_image"] = img_bytes
                                    st.session_state["render_mime"] = "image/png" if render_format == "png" else "image/svg+xml"
                                    st.success(f"⚡ Vẽ hình thành công! *(Model xử lý: **{used_model}**)*")
                                else:
                                    st.error(f"❌ {render_err}")
                            else:
                                st.error(f"❌ {err}")
                                if hit_limit:
                                    run_cooldown_countdown(60, "Tự động đếm ngược khôi phục Quota Google API")

        with col_right:
            st.subheader("2. Kết quả Hình vẽ Minh họa")

            if st.session_state["rendered_image"] is not None:
                st.info(f"🤖 **Model AI đã xử lý:** `{st.session_state['used_model']}`")

                st.image(
                    st.session_state["rendered_image"], 
                    caption=f"Hình vẽ TikZ kết quả ({render_format.upper()})", 
                    use_container_width=True
                )
                
                st.download_button(
                    label=f"📥 Tải ảnh {render_format.upper()} về máy",
                    data=st.session_state["rendered_image"],
                    file_name=f"hinh_hoc_tikz.{render_format}",
                    mime=st.session_state["render_mime"],
                    type="primary",
                    use_container_width=True,
                )

                with st.expander("📝 Xem / Copy Mã TikZ"):
                    st.code(st.session_state["tikz_code"], language="latex")

                st.markdown("---")
                st.markdown("### ✏️ Yêu cầu AI sửa hình vẽ này")
                refine_input = st.text_input(
                    "Nhập yêu cầu sửa (VD: Thêm đường cao AH nét đứt, Đổi điểm C thành C'):",
                    key="refine_input_text"
                )
                
                if st.button("✨ Cập nhật hình vẽ theo yêu cầu", type="secondary", use_container_width=True):
                    now = time.time()
                    if st.session_state["cooldown_until"] > now:
                        wait_sec = int(st.session_state["cooldown_until"] - now)
                        st.warning(f"⚠️ Vui lòng chờ hết thời gian đếm ngược ({wait_sec}s nữa).")
                    elif not refine_input.strip():
                        st.warning("⚠️ Vui lòng nhập yêu cầu cần chỉnh sửa.")
                    else:
                        refine_prompt = f"""
                        Role: Professor of Mathematics & Expert in TikZ.
                        Task: Modify the existing TikZ code according to the user request.

                        CURRENT TIKZ CODE:
                        ```latex
                        {st.session_state["tikz_code"]}
                        ```

                        USER REQUEST:
                        {refine_input}

                        Output format: Return ONLY a code block ```latex ... ```.
                        """

                        payload = [image_to_process, refine_prompt] if image_to_process is not None else [refine_prompt]

                        with st.spinner("⚡ AI đang cập nhật lại hình vẽ..."):
                            generated_text, err, hit_limit, used_model = generate_fast(client, payload)
                            if generated_text:
                                new_tikz_code = clean_tikz_code(generated_text)
                                st.session_state["tikz_code"] = new_tikz_code
                                st.session_state["used_model"] = used_model

                                img_bytes, render_err = render_tikz(new_tikz_code, output_format=render_format)
                                if img_bytes:
                                    st.session_state["rendered_image"] = img_bytes
                                    st.session_state["render_mime"] = "image/png" if render_format == "png" else "image/svg+xml"
                                    st.success(f"✨ Cập nhật hình vẽ thành công! *(Model xử lý: **{used_model}**)*")
                                    st.rerun()
                                else:
                                    st.error(f"❌ {render_err}")
                            else:
                                st.error(f"❌ {err}")
                                if hit_limit:
                                    run_cooldown_countdown(60, "Tự động đếm ngược khôi phục Quota Google API")
            else:
                st.info("👈 Hãy dán hoặc tải ảnh đề bài ở cột bên trái.")
else:
    st.warning("⚠️ Vui lòng nhập Gemini API Key ở thanh sidebar bên trái.")
