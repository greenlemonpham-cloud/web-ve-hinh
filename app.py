import os
import sys

# 1. Ep Python su dung UTF-8 tren Windows
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
import urllib.request
import urllib.error
from PIL import Image
from google import genai
import streamlit as st

# Kiem tra thu vien paste button
try:
    from streamlit_paste_button import paste_image_button
    HAS_PASTE_BUTTON = True
except ImportError:
    HAS_PASTE_BUTTON = False

# ==========================================
# CAU HINH GIAO DIEN STREAMLIT
# ==========================================
st.set_page_config(
    page_title="Chuyen Anh Bai Toan Sang TikZ",
    layout="wide",
)

st.title("AI Chuyen De Bai Hinh Hoc Sang Hinh Ve TikZ")
st.markdown("Made by levu | Hien thi chinh xac Model AI xu ly thanh cong")

# Khoi tao Session State
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
st.sidebar.header("Cau hinh He thong")

if "user_api_key" not in st.session_state:
    st.session_state["user_api_key"] = ""

input_key = st.sidebar.text_input(
    "Nhap Gemini API Key cua ban:",
    value=st.session_state["user_api_key"],
    type="password",
    help="Copy ma API key tu Google AI Studio va dan vao day",
)

if input_key:
    st.session_state["user_api_key"] = input_key.strip()

api_key = st.session_state["user_api_key"]

render_format = st.sidebar.selectbox(
    "Dinh dang anh dau ra:",
    options=["png", "svg"],
    index=0,
    help="Chon SVG de co chat luong anh vector net tuyet doi"
)

current_now = time.time()
if st.session_state["cooldown_until"] > current_now:
    remaining_secs = int(st.session_state["cooldown_until"] - current_now)
    st.sidebar.warning(f"Can cho: {remaining_secs} giay de gui yeu cau tiep theo.")
else:
    st.sidebar.success("API San sang su dung!")

@st.cache_resource
def get_gemini_client(key: str):
    return genai.Client(api_key=key)

# ==========================================
# HAM XU LY CHUOI & API
# ==========================================
def clean_ascii_only(text: str) -> str:
    """Loai bo triet de tat ca ky tu unicode / emoji khong phai ASCII"""
    if not isinstance(text, str):
        return text
    return text.encode('ascii', errors='ignore').decode('ascii')

def run_cooldown_countdown(seconds: int = 60, message: str = "Dang cho hoi han muc Quota tu Google"):
    st.session_state["cooldown_until"] = time.time() + seconds
    progress_bar = st.progress(1.0)
    status_text = st.empty()
    
    for remaining in range(seconds, 0, -1):
        percent = remaining / seconds
        progress_bar.progress(percent)
        status_text.warning(f"{message}: Con lai {remaining} giay...")
        time.sleep(1)
        
    progress_bar.empty()
    status_text.success("Da het thoi gian cho! Ban co the bam gui lai ngay.")

def clean_tikz_code(raw_text: str) -> str:
    if not raw_text:
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
        return None, "Loi: Ma TikZ khong hop le hoac rong."

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
            return None, f"Loi Kroki: HTTP {response.status}"
    except urllib.error.HTTPError as e:
        try:
            error_details = e.read().decode('utf-8', errors='ignore')
            clean_err = re.sub(r'<[^>]+>', '', error_details).strip()
            return None, f"Loi cu phap TikZ (HTTP {e.code}): {clean_err[:250]}"
        except Exception:
            return None, f"Loi bien dich Kroki: HTTP {e.code}"
    except Exception as e:
        return None, f"Loi ket noi Render: {e}"

def generate_fast(client, contents_payload):
    # Danh sach Model uu tien theo thu tu
    fast_models = [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]

    error_logs = []
    hit_rate_limit = False

    for model_name in fast_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents_payload,
            )
            if response and hasattr(response, "text") and response.text:
                return response.text, None, False, model_name
            else:
                error_logs.append(f"- {model_name}: Phan hoi rong.")
        except Exception as e:
            # Clean sach chuoi exception thanh ASCII thuan tuy de tranh crash Windows
            safe_err = clean_ascii_only(str(e))
            if "429" in safe_err or "RESOURCE_EXHAUSTED" in safe_err:
                hit_rate_limit = True
                error_logs.append(f"- {model_name}: Qua gioihan luot goi (Free Quota 429).")
            else:
                error_logs.append(f"- {model_name}: {safe_err[:120]}")
            continue

    detailed_error = "\n".join(error_logs)
    return None, f"[Loi API Google]\n{detailed_error}", hit_rate_limit, None

# ==========================================
# LUONG XU LY GIAO DIEN CHINH
# ==========================================
if api_key:
    try:
        client = get_gemini_client(api_key.strip())
    except Exception as e:
        st.error(f"Loi khoi tao Gemini Client: {e}")
        client = None

    if client:
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("1. De bai Hinh hoc")
            image_to_process = None

            if HAS_PASTE_BUTTON:
                st.markdown("**Dan nhanh tu bo nho tam:**")
                paste_result = paste_image_button(
                    label="Bam vao day de Dan anh da chup",
                    background_color="#2563EB",
                    text_color="#FFFFFF",
                    key=f"paste_btn_{st.session_state['paste_key']}",
                )
                if paste_result is not None and paste_result.image_data is not None:
                    image_to_process = paste_result.image_data
                st.markdown("---")

            uploaded_file = st.file_uploader(
                "Chon tep anh tu may tinh / Keo tha vao day:",
                type=["jpg", "jpeg", "png"],
                key=f"uploader_{st.session_state['paste_key']}",
            )
            if uploaded_file is not None and image_to_process is None:
                try:
                    image_to_process = Image.open(uploaded_file)
                except Exception:
                    st.error("Khong the doc dinh dang anh nay.")

            if image_to_process is not None:
                try:
                    if isinstance(image_to_process, bytes):
                        image_to_process = Image.open(io.BytesIO(image_to_process))
                    if image_to_process.mode != "RGB":
                        image_to_process = image_to_process.convert("RGB")
                except Exception:
                    pass

                st.image(image_to_process, caption="Anh de bai da san sang", use_container_width=True)

                if st.button("Xoa anh", use_container_width=True):
                    st.session_state["paste_key"] += 1
                    st.session_state["rendered_image"] = None
                    st.session_state["tikz_code"] = ""
                    st.session_state["used_model"] = ""
                    st.rerun()

                if st.button("Chuyen doi & Ve hinh ngay", type="primary", use_container_width=True):
                    now = time.time()
                    if st.session_state["cooldown_until"] > now:
                        wait_sec = int(st.session_state["cooldown_until"] - now)
                        st.warning(f"Vui long cho het thoi gian dem nguoc ({wait_sec}s nua).")
                    else:
                        prompt = (
                            "Convert the geometry figure in this image into valid TikZ code.\n"
                            "Use \\documentclass[tikz, border=5mm]{standalone}.\n"
                            "Include required tikz libraries (calc, angles, quotes, intersections).\n"
                            "Return ONLY the code block ```latex ... ``` without extra text."
                        )

                        with st.spinner("AI dang phan tich va tao hinh..."):
                            generated_text, err, hit_limit, used_model = generate_fast(client, [image_to_process, prompt])

                            if generated_text:
                                tikz_code = clean_tikz_code(generated_text)
                                st.session_state["tikz_code"] = tikz_code
                                st.session_state["used_model"] = used_model

                                img_bytes, render_err = render_tikz(tikz_code, output_format=render_format)
                                if img_bytes:
                                    st.session_state["rendered_image"] = img_bytes
                                    st.session_state["render_mime"] = "image/png" if render_format == "png" else "image/svg+xml"
                                    st.success(f"Ve hinh thanh cong! (Model xu ly: {used_model})")
                                else:
                                    st.error(f"{render_err}")
                            else:
                                st.error(f"{err}")
                                if hit_limit:
                                    run_cooldown_countdown(60, "Tu dong dem nguoc khoi phuc Quota Google API")

        with col_right:
            st.subheader("2. Ket qua Hinh ve Minh hoa")

            if st.session_state["rendered_image"] is not None:
                st.info(f"Model AI da xu ly: `{st.session_state['used_model']}`")

                st.image(
                    st.session_state["rendered_image"], 
                    caption=f"Hinh ve TikZ ket qua ({render_format.upper()})", 
                    use_container_width=True
                )
                
                st.download_button(
                    label=f"Tai anh {render_format.upper()} ve may",
                    data=st.session_state["rendered_image"],
                    file_name=f"hinh_hoc_tikz.{render_format}",
                    mime=st.session_state["render_mime"],
                    type="primary",
                    use_container_width=True,
                )

                with st.expander("Xem / Copy Ma TikZ"):
                    st.code(st.session_state["tikz_code"], language="latex")

                st.markdown("---")
                st.markdown("### Yeu cau AI sua hinh ve nay")
                refine_input = st.text_input(
                    "Nhap yeu cau sua (VD: Them duong cao AH net dut, Doi diem C thanh C'):",
                    key="refine_input_text"
                )
                
                if st.button("Cap nhat hinh ve theo yeu cau", type="secondary", use_container_width=True):
                    now = time.time()
                    if st.session_state["cooldown_until"] > now:
                        wait_sec = int(st.session_state["cooldown_until"] - now)
                        st.warning(f"Vui long cho het thoi gian dem nguoc ({wait_sec}s nua).")
                    elif not refine_input.strip():
                        st.warning("Vui long nhap yeu cau can chinh sua.")
                    else:
                        refine_prompt = (
                            f"Modify the following TikZ code according to user request.\n"
                            f"CURRENT CODE:\n```latex\n{st.session_state['tikz_code']}\n```\n"
                            f"REQUEST: {refine_input}\n"
                            f"Return ONLY the updated code block ```latex ... ```."
                        )

                        payload = [image_to_process, refine_prompt] if image_to_process is not None else [refine_prompt]

                        with st.spinner("AI dang cap nhat lai hinh ve..."):
                            generated_text, err, hit_limit, used_model = generate_fast(client, payload)
                            if generated_text:
                                new_tikz_code = clean_tikz_code(generated_text)
                                st.session_state["tikz_code"] = new_tikz_code
                                st.session_state["used_model"] = used_model

                                img_bytes, render_err = render_tikz(new_tikz_code, output_format=render_format)
                                if img_bytes:
                                    st.session_state["rendered_image"] = img_bytes
                                    st.session_state["render_mime"] = "image/png" if render_format == "png" else "image/svg+xml"
                                    st.success(f"Cap nhat hinh ve thanh cong! (Model xu ly: {used_model})")
                                    st.rerun()
                                else:
                                    st.error(f"{render_err}")
                            else:
                                st.error(f"{err}")
                                if hit_limit:
                                    run_cooldown_countdown(60, "Tu dong dem nguoc khoi phuc Quota Google API")
            else:
                st.info("Hay dan hoac tai anh de bai o cot ben trai.")
else:
    st.warning("Vui long nhap Gemini API Key o thanh sidebar ben trai.")
