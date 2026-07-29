import base64
import io
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from PIL import Image
from openai import OpenAI
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
    page_title="Chuyển Ảnh Bài Toán Sang TikZ (Auto AI)",
    page_icon="📐",
    layout="wide",
)

st.title("📐 AI Chuyển Đề Bài Hình Học Sang Hình Vẽ TikZ")
st.markdown("Made by levu | **Tự động thử tất cả AI Vision trên OpenRouter**")

# ==========================================
# 2. CẤU HÌNH API KEY & ĐỊNH DẠNG TẠI SIDEBAR
# ==========================================
st.sidebar.header("⚙️ Cấu hình Hệ thống")

if "user_api_key" not in st.session_state:
    st.session_state["user_api_key"] = ""

input_key = st.sidebar.text_input(
    "Nhập OpenRouter API Key:",
    value=st.session_state["user_api_key"],
    type="password",
    help="Lấy mã API key miễn phí tại: https://openrouter.ai/keys",
)

if input_key:
    st.session_state["user_api_key"] = input_key.strip()

api_key = st.session_state["user_api_key"]

# Tùy chọn định dạng đầu ra (PNG hoặc SVG)
render_format = st.sidebar.selectbox(
    "🖼️ Định dạng ảnh đầu ra:",
    options=["png", "svg"],
    index=0,
    help="Chọn SVG để có chất lượng ảnh vector nét tuyệt đối khi chèn vào đề thi Word/LaTeX"
)

def get_openrouter_client(key: str):
    clean_key = key.strip()
    if not clean_key:
        return None
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=clean_key,
    )

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

def render_tikz(tikz_code: str, output_format: str = "png") -> tuple[bytes | None, str | None]:
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

def generate_fast_auto(client: OpenAI, contents_payload: list):
    """
    Tự động duyệt qua tất cả AI Vision khả dụng trên OpenRouter
    """
    # 1. Chuyển đổi payload sang định dạng OpenAI Vision chuẩn
    user_content = []
    for item in contents_payload:
        if isinstance(item, Image.Image):
            buffered = io.BytesIO()
            item.save(buffered, format="PNG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
            })
        elif isinstance(item, str):
            user_content.append({
                "type": "text",
                "text": item
            })

    # 2. Danh sách TOÀN BỘ các dòng AI Vision mạnh nhất
    base_models = [
        "google/gemini-2.0-flash-001",
        "google/gemini-2.0-flash-lite-001",
        "google/gemini-flash-1.5",
        "google/gemini-flash-1.5-8b",
        "qwen/qwen-2.5-vl-72b-instruct",
        "meta-llama/llama-3.2-11b-vision-instruct",
        "mistralai/pixtral-12b",
        "openai/gpt-4o-mini",
    ]

    # Tự động kết hợp cả bản chuẩn và biến thể :free
    all_candidates = []
    for m in base_models:
        all_candidates.append(m)
        all_candidates.append(f"{m}:free")

    error_logs = []
    
    # 3. Vòng lặp tự động chạy thử từng Model
    for model_name in all_candidates:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": user_content}],
                extra_headers={
                    "HTTP-Referer": "https://streamlit.io",
                    "X-Title": "TikZ Generator",
                },
                timeout=25
            )
            if response and response.choices and response.choices[0].message.content:
                # Thành công -> Trả về kết quả ngay
                return response.choices[0].message.content, None
        except Exception as e:
            err_msg = str(e)
            # Chỉ ghi nhận lỗi rút gọn để tránh ngợp giao diện
            if "404" not in err_msg and "400" not in err_msg:
                error_logs.append(f"• {model_name}: {err_msg[:120]}")
            continue

    detailed_error = "\n".join(error_logs) if error_logs else "Tất cả các Model AI hiện tại đều bận hoặc không phản hồi."
    return None, f"❌ Chưa thể xử lý bài toán. Chi tiết phản hồi:\n{detailed_error}"

# ==========================================
# 4. LUỒNG XỬ LÝ CHÍNH
# ==========================================
if "paste_key" not in st.session_state:
    st.session_state["paste_key"] = 0
if "rendered_image" not in st.session_state:
    st.session_state["rendered_image"] = None
if "tikz_code" not in st.session_state:
    st.session_state["tikz_code"] = ""
if "render_mime" not in st.session_state:
    st.session_state["render_mime"] = "image/png"

if api_key:
    client = get_openrouter_client(api_key.strip())

    if client:
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("1. Đề bài Hình học")

            image_to_process = None

            # Dán ảnh từ clipboard
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

            # Tải file dự phòng
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
                    5. Cấu trúc code: Có chú thích % rõ ràng cho từng phần.
                    
                    Định dạng đầu ra (Output Format):
                    Chỉ cung cấp DUY NHẤT một khối mã (code block) bằng ngôn ngữ ```latex ... ```. KHÔNG giải thích, KHÔNG chào hỏi, KHÔNG thêm bất kỳ văn bản nào khác bên ngoài khối mã latex.
                    """

                    with st.spinner("⚡ AI đang tự động tìm mô hình khả dụng và vẽ hình..."):
                        generated_text, err = generate_fast_auto(client, [image_to_process, prompt])

                        if generated_text:
                            tikz_code = clean_tikz_code(generated_text)
                            st.session_state["tikz_code"] = tikz_code

                            img_bytes, render_err = render_tikz(tikz_code, output_format=render_format)
                            if img_bytes:
                                st.session_state["rendered_image"] = img_bytes
                                st.session_state["render_mime"] = "image/png" if render_format == "png" else "image/svg+xml"
                                st.success("⚡ Vẽ hình thành công!")
                            else:
                                st.error(f"❌ {render_err}")
                        else:
                            st.error(f"❌ {err}")

        with col_right:
            st.subheader("2. Kết quả Hình vẽ Minh họa")

            if st.session_state["rendered_image"] is not None:
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
                    st.markdown("[🌐 Mở trang hotrohoctap.com/1ai/6tikz](https://hotrohoctap.com/1ai/6tikz/)")

                st.markdown("---")
                st.markdown("### ✏️ Yêu cầu AI sửa hình vẽ này")
                refine_input = st.text_input(
                    "Nhập yêu cầu sửa (VD: Thêm đường cao AH nét đứt, Đổi điểm C thành C'):",
                    key="refine_input_text"
                )
                
                if st.button("✨ Cập nhật hình vẽ theo yêu cầu", type="secondary", use_container_width=True):
                    if not refine_input.strip():
                        st.warning("⚠️ Vui lòng nhập yêu cầu cần chỉnh sửa.")
                    else:
                        refine_prompt = f"""
                        Role: Giáo sư Toán học & Chuyên gia bậc thầy về TikZ.
                        Nhiệm vụ: Chỉnh sửa mã TikZ hiện tại theo yêu cầu người dùng.

                        MÃ TIKZ HIỆN TẠI:
                        ```latex
                        {st.session_state["tikz_code"]}
                        ```

                        YÊU CẦU CHỈNH SỬA TỪ NGUỜI DÙNG:
                        {refine_input}

                        Yêu cầu kỹ thuật:
                        - Cập nhật chính xác mã TikZ dựa trên mã hiện tại và yêu cầu chỉnh sửa.
                        - Giữ nguyên tính chính xác của hình học và thẩm mỹ nét vẽ.
                        - Chỉ trả về DUY NHẤT một khối mã ```latex ... ```. KHÔNG giải thích, KHÔNG chào hỏi.
                        """

                        payload = [image_to_process, refine_prompt] if image_to_process is not None else [refine_prompt]

                        with st.spinner("⚡ AI đang tự động xử lý cập nhật..."):
                            generated_text, err = generate_fast_auto(client, payload)
                            if generated_text:
                                new_tikz_code = clean_tikz_code(generated_text)
                                st.session_state["tikz_code"] = new_tikz_code

                                img_bytes, render_err = render_tikz(new_tikz_code, output_format=render_format)
                                if img_bytes:
                                    st.session_state["rendered_image"] = img_bytes
                                    st.session_state["render_mime"] = "image/png" if render_format == "png" else "image/svg+xml"
                                    st.success("✨ Cập nhật hình vẽ thành công!")
                                    st.rerun()
                                else:
                                    st.error(f"❌ {render_err}")
                            else:
                                st.error(f"❌ {err}")
            else:
                st.info("👈 Hãy dán hoặc tải ảnh đề bài ở cột bên trái.")
else:
    st.warning("⚠️ Vui lòng nhập OpenRouter API Key ở thanh sidebar bên trái.")
