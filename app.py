import base64
import io
import re
import time
import urllib.parse
import urllib.request
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
# 1. CẤU HÌNH GIAO DIỆN
# ==========================================
st.set_page_config(
    page_title="Chuyển Ảnh Bài Toán Sang TikZ",
    page_icon="📐",
    layout="wide",
)

st.title("📐 AI Chuyển Đề Bài Hình Học Sang Hình Vẽ TikZ")
st.markdown("Made by levu")

# ==========================================
# 2. CẤU HÌNH API KEY TẠI SIDEBAR
# ==========================================
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

@st.cache_resource
def get_gemini_client(key: str):
    return genai.Client(api_key=key)

# ==========================================
# 3. HÀM RENDER TIKZ & AI
# ==========================================
def clean_tikz_code(raw_text: str) -> str:
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
    if not clean_body.startswith("\\begin{tikzpicture}"):
        clean_body = f"\\begin{{tikzpicture}}\n{clean_body}\n\\end{{tikzpicture}}"
    return clean_body

def render_tikz(tikz_code: str) -> tuple[bytes | None, str | None]:
    full_doc = f"""\\documentclass[tikz,border=5pt]{{standalone}}
\\usepackage{{amsmath,amssymb}}
\\usetikzlibrary{{calc,arrows,arrows.meta,intersections,shapes,patterns,angles,quotes}}
\\begin{{document}}
{tikz_code}
\\end{{document}}"""

    url = "https://kroki.io/tikz/png"
    try:
        req = urllib.request.Request(
            url,
            data=full_doc.encode("utf-8"),
            headers={"Content-Type": "text/plain; charset=utf-8", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return response.read(), None
            return None, f"Lỗi Kroki: {response.status}"
    except Exception as e:
        return None, f"Lỗi kết nối Render: {e}"

def generate_fast(client, image, prompt):
    """
    Hàm gọi AI chuẩn hóa dữ liệu ảnh và sử dụng tên mô hình chuẩn SDK mới
    """
    # 1. Chuẩn hóa dữ liệu ảnh sang định dạng PIL RGB
    try:
        if isinstance(image, bytes):
            image = Image.open(io.BytesIO(image))
        elif not isinstance(image, Image.Image):
            image = Image.open(io.BytesIO(image))
            
        if image.mode != "RGB":
            image = image.convert("RGB")
    except Exception as img_err:
        return None, f"Lỗi xử lý định dạng ảnh: {img_err}"

    # 2. Danh sách mô hình chuẩn SDK google-genai (Ưu tiên 2.5-flash và 2.0-flash-lite)
    # Danh sách tối đa các mô hình Gemini hỗ trợ nhận diện hình ảnh
    fast_models = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]

    error_logs = []
    for model_name in fast_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[image, prompt],
            )
            if response and response.text:
                return response.text, None
        except Exception as e:
            err_msg = str(e)
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                error_logs.append(f"• {model_name}: ⚠️ Đã hết hạn mức Free Quota của Google cho Key này.")
                time.sleep(2)
            else:
                error_logs.append(f"• {model_name}: {err_msg}")
            continue

    # 3. Trả về chi tiết lỗi nếu không mô hình nào chạy được
    detailed_error = "\n".join(error_logs)
    return (
        None,
        f"❌ AI chưa thể xử lý. Chi tiết lỗi từ Google API:\n{detailed_error}"
    )

# ==========================================
# 4. LUỒNG XỬ LÝ CHÍNH
# ==========================================
# Khởi tạo key quản lý làm mới giao diện
if "paste_key" not in st.session_state:
    st.session_state["paste_key"] = 0
if "rendered_image" not in st.session_state:
    st.session_state["rendered_image"] = None
if "tikz_code" not in st.session_state:
    st.session_state["tikz_code"] = ""

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

            # Hiển thị nút Dán nếu đã cài thư viện (kèm dynamic key để xoá)
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
            else:
                st.warning("💡 Mẹo: Chạy `pip install streamlit-paste-button` trong Terminal để bật nút dán ảnh 1-click.")

            # Tải file dự phòng (kèm dynamic key để xoá)
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

            # Xem trước ảnh & Chạy AI
            if image_to_process is not None:
                st.image(image_to_process, caption="Ảnh đề bài đã sẵn sàng", use_container_width=True)

                # Nút xóa ảnh input
                if st.button("❌ Xóa ảnh", use_container_width=True):
                    st.session_state["paste_key"] += 1
                    st.session_state["rendered_image"] = None
                    st.session_state["tikz_code"] = ""
                    st.rerun()

                if st.button("🚀 Chuyển đổi & Vẽ hình ngay", type="primary", use_container_width=True):
                    prompt = """
                    Đóng vai (Role):
                    Bạn là một Giáo sư Toán học và Chuyên gia bậc thầy về lập trình LaTeX/TikZ/PGFPlots.
                    
                    Mục tiêu (Objective):
                    Hãy phân tích hình ảnh bài toán/đồ thị được cung cấp và chuyển đổi chính xác thành mã TikZ hoàn chỉnh, có thể biên dịch (compile) thành công ngay lập tức.
                    
                    Yêu cầu kỹ thuật nghiêm ngặt (Strict Guidelines):
                    1. Môi trường: Luôn sử dụng \\documentclass[tikz, border=5mm]{standalone}. Nếu là đồ thị hàm số phức tạp thì dùng thêm gói pgfplots với \\usepackage{pgfplots} và \\pgfplotsset{compat=1.18}.
                    2. Thư viện: Khai báo đầy đủ các thư viện cần thiết như \\usetikzlibrary{calc, angles, quotes, intersections, through, positioning, 3d, arrows.meta}.
                    3. Tọa độ & Điểm: Dùng hệ tọa độ Oxy rõ ràng. Ưu tiên tính toán tọa độ bằng thư viện `calc` hoặc `intersections`. Định nghĩa các điểm \\coordinate trước khi vẽ.
                    4. Tính thẩm mỹ:
                       - Nét vẽ: Nét chính dùng thick/thin, nét đứt/khuất/đường dóng dùng `dashed` màu nhạt (`gray!70`).
                       - Ký hiệu: Góc vuông dùng thư viện `angles`, đoạn thẳng bằng nhau dùng tick mark.
                       - Nhãn: Ký tự toán đặt trong dấu $ $, vị trí (above, below, left, right...) tránh đè nét vẽ.
                       - Hình 3D: Dùng hệ tọa độ góc nhìn chuẩn [x={(-0.6cm,-0.4cm)}, y={(1cm,0cm)}, z={(0cm,1cm)}] để góc nhìn không bị vỡ.
                    5. Cấu trúc code: Có chú thích % rõ ràng cho từng phần (khai báo điểm, vẽ đường, đánh dấu góc...).
                    
                    Định dạng đầu ra (Output Format):
                    Chỉ cung cấp DUY NHẤT một khối mã (code block) bằng ngôn ngữ ```latex ... ```. KHÔNG giải thích, KHÔNG chào hỏi, KHÔNG thêm bất kỳ văn bản nào khác bên ngoài khối mã latex.
                    """

                    with st.spinner("⚡ AI đang phân tích và tạo hình..."):
                        generated_text, err = generate_fast(client, image_to_process, prompt)

                        if generated_text:
                            tikz_code = clean_tikz_code(generated_text)
                            st.session_state["tikz_code"] = tikz_code

                            img_bytes, render_err = render_tikz(tikz_code)
                            if img_bytes:
                                st.session_state["rendered_image"] = img_bytes
                                st.success("⚡ Vẽ hình thành công!")
                            else:
                                st.error(f"❌ Lỗi render TikZ: {render_err}")
                        else:
                            st.error(f"❌ Lỗi AI: {err}")

        with col_right:
            st.subheader("2. Kết quả Hình vẽ Minh họa")

            if st.session_state["rendered_image"] is not None:
                st.image(st.session_state["rendered_image"], caption="Hình vẽ TikZ kết quả", use_container_width=True)
                st.download_button(
                    label="📥 Tải ảnh PNG về máy",
                    data=st.session_state["rendered_image"],
                    file_name="hinh_hoc_tikz.png",
                    mime="image/png",
                    type="primary",
                    use_container_width=True,
                )

                with st.expander("📝 Xem / Copy Mã TikZ & Biên dịch"):
                    st.code(st.session_state["tikz_code"], language="latex")
                    st.markdown("[🌐 Mở trang hotrohoctap.com/1ai/6tikz](https://hotrohoctap.com/1ai/6tikz/)")
            else:
                st.info("👈 Hãy dán hoặc tải ảnh đề bài ở cột bên trái.")
else:
    st.warning("⚠️ Vui lòng nhập Gemini API Key ở thanh sidebar bên trái.")
