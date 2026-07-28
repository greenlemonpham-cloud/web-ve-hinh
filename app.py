import base64
import io
import re
import urllib.parse
import urllib.request
from PIL import Image
from google import genai
import streamlit as st

# ==========================================
# 1. CẤU HÌNH GIAO DIỆN TRANG WEB
# ==========================================
st.set_page_config(
    page_title="Chuyển Ảnh Bài Toán Sang TikZ",
    page_icon="📐",
    layout="wide",
)

st.title("📐 AI Chuyển Đề Bài Hình Học Sang Hình Vẽ TikZ")
st.markdown(
    "Made by penqwinn"
)

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

st.sidebar.info(
    "💡 **Hướng dẫn:**\n"
    "1. Lấy API Key miễn phí từ Google AI Studio.\n"
    "2. Dán mã vào ô bên trên và bấm Enter để kích hoạt."
)

api_key = st.session_state["user_api_key"]


# ==========================================
# 3. HÀM BỔ TRỢ & RENDER HÌNH TIKZ
# ==========================================
def clean_tikz_code(raw_text: str) -> str:
    """Làm sạch mã TikZ do AI trả về."""
    match_codeblock = re.search(
        r"\x60{3}(?:latex|tikz)?\n(.*?)\x60{3}", raw_text, re.DOTALL
    )
    text = match_codeblock.group(1).strip() if match_codeblock else raw_text.strip()

    match_tikz = re.search(
        r"(\\begin\{tikzpicture\}.*?\\end\{tikzpicture\})", text, re.DOTALL
    )
    if match_tikz:
        return match_tikz.group(1).strip()

    cleaned_lines = []
    for line in text.split("\n"):
        line_str = line.strip()
        if any(
            line_str.startswith(cmd)
            for cmd in [
                "\\documentclass",
                "\\usepackage",
                "\\begin{document}",
                "\\end{document}",
                "\\usetikzlibrary",
            ]
        ):
            continue
        cleaned_lines.append(line)

    clean_body = "\n".join(cleaned_lines).strip()
    if not clean_body.startswith("\\begin{tikzpicture}"):
        clean_body = f"\\begin{{tikzpicture}}\n{clean_body}\n\\end{{tikzpicture}}"

    return clean_body


def render_tikz_kroki(tikz_code: str) -> tuple[bytes | None, str | None]:
    """Render mã TikZ thành dữ liệu ảnh PNG thông qua Kroki API."""
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
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "User-Agent": "Mozilla/5.0",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                return response.read(), None
            return None, f"Kroki Server phản hồi mã trạng thái {response.status}"
    except Exception as e:
        return None, f"Lỗi kết nối Kroki: {e}"


def render_tikz_quicklatex(tikz_code: str) -> tuple[bytes | None, str | None]:
    """Render mã TikZ thông qua QuickLaTeX API làm phương án dự phòng."""
    url = "https://www.quicklatex.com/cgi-bin/quicklatex.exe"
    preamble = r"""
\usepackage{amsmath}
\usepackage{amsfonts}
\usepackage{amssymb}
\usepackage{tikz}
\usetikzlibrary{calc,arrows,arrows.meta,intersections,shapes,patterns,angles,quotes}
"""
    post_data = urllib.parse.urlencode({
        "formula": tikz_code,
        "fsize": "18px",
        "fcolor": "000000",
        "mode": "0",
        "out": "1",
        "rem_ont": "1",
        "preamble": preamble,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url, data=post_data, headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            result = response.read().decode("utf-8", errors="ignore")

        lines = result.strip().split("\n")
        if len(lines) >= 1 and lines[0].strip() == "0":
            if len(lines) >= 3:
                img_url = lines[2].split()[0]
                if img_url.startswith("http://"):
                    img_url = "https://" + img_url[7:]
                img_req = urllib.request.Request(
                    img_url, headers={"User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(img_req, timeout=10) as img_resp:
                    img_bytes = img_resp.read()
                return img_bytes, None

        error_msg = (
            "\n".join(lines[1:])
            if len(lines) > 1
            else "QuickLaTeX không thể biên dịch mã TikZ này."
        )
        return None, error_msg
    except Exception as e:
        return None, f"Lỗi kết nối máy chủ QuickLaTeX: {e}"


def render_tikz(tikz_code: str) -> tuple[bytes | None, str | None]:
    """Kết hợp đa máy chủ render để đảm bảo tỉ lệ thành công cao nhất."""
    # Thử máy chủ Kroki trước
    img_bytes, kroki_err = render_tikz_kroki(tikz_code)
    if img_bytes:
        return img_bytes, None

    # Nếu Kroki không khả dụng, chuyển sang QuickLaTeX
    img_bytes, ql_err = render_tikz_quicklatex(tikz_code)
    if img_bytes:
        return img_bytes, None

    return None, f"Tất cả máy chủ render đều báo lỗi:\n- Kroki: {kroki_err}\n- QuickLaTeX: {ql_err}"


def generate_with_retry(client, image, prompt):
    """Tự động tìm và sử dụng mô hình Gemini tương thích với API key của bạn."""
    candidate_models = []

    # 1. Tự động lấy danh sách mô hình khả dụng từ tài khoản API
    try:
        listed_models = list(client.models.list())
        for m in listed_models:
            m_name = getattr(m, "name", "") or str(m)
            clean_name = m_name.replace("models/", "")
            if "gemini" in clean_name.lower() and "embed" not in clean_name.lower():
                if clean_name not in candidate_models:
                    candidate_models.append(clean_name)
                if m_name not in candidate_models:
                    candidate_models.append(m_name)
    except Exception as e:
        print("Lỗi khi lấy danh sách mô hình:", e)

    # 2. Thêm các tên mô hình dự phòng tiêu chuẩn
    fallback_models = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-2.5-pro",
    ]
    for fb in fallback_models:
        if fb not in candidate_models:
            candidate_models.append(fb)

    last_err = None

    for model_name in candidate_models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[image, prompt],
            )
            if response and response.text:
                return response.text, None
        except Exception as e:
            last_err = e
            continue

    return None, last_err


# ==========================================
# 4. LUỒNG XỬ LÝ CHÍNH
# ==========================================
if api_key:
    api_key_clean = api_key.strip()

    try:
        client = genai.Client(api_key=api_key_clean)
    except Exception as e:
        st.error(f"Lỗi khởi tạo Gemini Client: {e}")
        client = None

    if client:
        col_left, col_right = st.columns(2)

        if "rendered_image" not in st.session_state:
            st.session_state["rendered_image"] = None
        if "tikz_code" not in st.session_state:
            st.session_state["tikz_code"] = ""

        # --------------------------------------
        # CỘT TRÁI: ĐỀ BÀI (TẢI / DÁN ẢNH)
        # --------------------------------------
        with col_left:
            st.subheader("1. Đề bài Hình học")

            tab_upload, tab_paste = st.tabs(["📁 Tải / Dán ảnh (Ctrl + V)", "🔗 Mã ảnh Base64"])

            image_to_process = None

            with tab_upload:
                st.caption(
                    "📌 **Hướng dẫn dán nhanh:** Chụp ảnh màn hình (`Win + Shift + S`), sau đó nhấp vào ô bên dưới và bấm **Ctrl + V**."
                )
                uploaded_file = st.file_uploader(
                    "Chọn file hoặc dán ảnh vào đây...",
                    type=["jpg", "jpeg", "png"],
                )
                if uploaded_file is not None:
                    try:
                        image_to_process = Image.open(uploaded_file)
                    except Exception:
                        st.error("Không thể đọc định dạng ảnh này.")

            with tab_paste:
                paste_b64 = st.text_area(
                    "Dán chuỗi Base64 của ảnh vào đây (dạng data:image/png;base64,...):",
                    height=100,
                    placeholder="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
                )
                if paste_b64 and paste_b64.strip():
                    try:
                        clean_b64 = paste_b64.strip()
                        if "," in clean_b64:
                            clean_b64 = clean_b64.split(",")[1]
                        image_bytes = base64.b64decode(clean_b64)
                        image_to_process = Image.open(io.BytesIO(image_bytes))
                    except Exception:
                        st.error("Mã Base64 không hợp lệ. Vui lòng kiểm tra lại.")

            # Hiển thị xem trước ảnh và nút Bắt đầu chuyển đổi
            if image_to_process is not None:
                st.image(
                    image_to_process,
                    caption="Ảnh đề bài đã sẵn sàng",
                    use_container_width=True,
                )

                if st.button("🚀 Chuyển đổi & Vẽ hình ngay", type="primary", use_container_width=True):
                    prompt = """
                    Bạn là một chuyên gia toán học và ngôn ngữ vẽ hình TikZ trong LaTeX.
                    Hãy phân tích kỹ ảnh bài toán hình học này:
                    1. Xác định vị trí các điểm, đường thẳng, góc vuông, ký hiệu bằng nhau, đường tròn.
                    2. Viết mã TikZ hoàn chỉnh đặt trong khối \\begin{tikzpicture} ... \\end{tikzpicture}.
                    3. Đảm bảo tên các điểm, độ dài và góc khớp chính xác với ảnh bài toán.
                    4. CHỈ xuất duy nhất khối mã trong ```latex \\begin{tikzpicture} ... \\end{tikzpicture} ```. KHÔNG thêm bất kỳ câu giải thích nào.
                    """

                    with st.spinner("AI đang phân tích ảnh và tự động dựng hình..."):
                        generated_text, err = generate_with_retry(client, image_to_process, prompt)

                        if generated_text:
                            tikz_code = clean_tikz_code(generated_text)
                            st.session_state["tikz_code"] = tikz_code
                            
                            # Render trực tiếp ra hình ảnh
                            img_bytes, render_err = render_tikz(tikz_code)
                            if img_bytes:
                                st.session_state["rendered_image"] = img_bytes
                                st.success("Đã phân tích và vẽ hình thành công!")
                            else:
                                st.error(f"❌ Lỗi khi render hình vẽ TikZ:\n{render_err}")
                        else:
                            st.error(f"❌ Lỗi kết nối AI: {err}")

        # --------------------------------------
        # CỘT PHẢI: HÌNH VẼ KẾT QUẢ & CÔNG CỤ DỰ PHÒNG
        # --------------------------------------
        with col_right:
            st.subheader("2. Kết quả Hình vẽ Minh họa")

            if st.session_state["rendered_image"] is not None:
                st.image(
                    st.session_state["rendered_image"],
                    caption="Hình vẽ được tự động tạo từ đề bài",
                    use_container_width=True,
                )
                st.download_button(
                    label="📥 Tải ảnh PNG sắc nét về máy",
                    data=st.session_state["rendered_image"],
                    file_name="hinh_hoc_ve_tu_de.png",
                    mime="image/png",
                    type="primary",
                    use_container_width=True,
                )

                # Mở rộng: Hiển thị mã TikZ & Link biên dịch hotrohoctap.com
                with st.expander("📝 Xem / Copy Mã TikZ & Biên dịch trên hotrohoctap.com"):
                    st.code(st.session_state["tikz_code"], language="latex")
                    st.markdown(
                        "[🌐 Bấm vào đây để mở trang web hotrohoctap.com/1ai/6tikz](https://hotrohoctap.com/1ai/6tikz/)"
                    )
            else:
                st.info(
                    "👈 Hãy dán hoặc tải ảnh đề bài ở cột bên trái, sau đó bấm nút **Chuyển đổi & Vẽ hình ngay** để nhận kết quả tại đây."
                )

else:
    st.warning(
        "⚠️ Vui lòng nhập **Gemini API Key** ở thanh menu bên trái và nhấn Enter để mở khóa ứng dụng."
    )