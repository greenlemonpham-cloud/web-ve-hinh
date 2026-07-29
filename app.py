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
    page_title="Chuyển Ảnh Bài Toán Sang TikZ (100% Gemini Vision)",
    page_icon="📐",
    layout="wide",
)

st.title("📐 AI Chuyển Đề Bài Hình Học Sang Hình Vẽ TikZ")
st.markdown("Made by levu | **Độc quyền 100% Gemini Vision (Độ chính xác hình học cao nhất)**")

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
    full_doc = f"""\\documentclass[tikz,border=10pt]{{standalone}}
\\usepackage{{amsmath,amssymb}}
\\usetikzlibrary{{calc,arrows,arrows.meta,intersections,shapes,patterns,angles,quotes,positioning,3d}}
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

def generate_gemini_pure(client: OpenAI, contents_payload: list):
    """
    ĐỘC QUYỀN HỌ GEMINI VISION (Loại bỏ hoàn toàn GPT-4o-Mini, Qwen, Llama)
    """
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

    # Chỉ dùng danh sách các phiên bản Gemini Vision mạnh nhất
    gemini_models = [
        "google/gemini-2.0-flash-001",
        "google/gemini-2.0-flash-lite-001",
        "google/gemini-1.5-pro",
        "google/gemini-flash-1.5",
        "google/gemini-2.0-flash-001:free",
        "google/gemini-2.0-flash-lite-001:free",
        "google/gemini-flash-1.5:free"
    ]

    error_logs = []
    for model_name in gemini_models:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": user_content}],
                extra_headers={
                    "HTTP-Referer": "https://streamlit.io",
                    "X-Title": "TikZ Pure Gemini Generator",
                },
                timeout=30
            )
            if response and response.choices and response.choices[0].message.content:
                return response.choices[0].message.content, model_name, None
        except Exception as e:
            err_msg = str(e)
            if "404" not in err_msg and "400" not in err_msg:
                error_logs.append(f"• {model_name}: {err_msg[:100]}")
            continue

    detailed_error = "\n".join(error_logs) if error_logs else "Máy chủ Gemini đang quá tải, hãy thử lại sau vài giây."
    return None, None, f"❌ Chưa thể xử lý. Chi tiết:\n{detailed_error}"

# Prompt Tối ưu Tọa độ & Cấu trúc Hình học
GEMINI_STRICT_PROMPT = """
Đóng vai: Chuyên gia biên soạn Sách Giáo Khoa Toán học.

Mục tiêu: Phân tích hình ảnh đề bài và tạo mã TikZ CHÍNH XÁC 100% VỀ CẤU TRÚC HÌNH HỌC, ĐẸP, TỐI GIẢN.

QUY TẮC DỰNG HÌNH BẮT BUỘC:
1. TỌA ĐỘ VÀ VỊ TRÍ CHÍNH XÁC:
   - Hãy quan sát thật kỹ vị trí tương quan giữa các điểm (A, B, C, D, S, H...) trong ảnh.
   - Định nghĩa tọa độ chuẩn xác trước khi nối các đường.
   - KHÔNG ĐƯỢC làm sai lệch góc, hướng nghiêng hay vị trí đỉnh của hình.

2. NÉT VẼ VÀ NÉT KHUẤT:
   - Đường nhìn thấy: Nét liền `thick`, màu `blue!70!black` hoặc `black!85`.
   - Đường bị che khuất/đường phụ: Nét đứt `dashed, gray!60`.
   - KHÔNG tự ý vẽ thêm các đường khung viền hay đường dóng thừa không có trong ảnh đề bài.

3. NHÃN ĐIỂM (LABELS):
   - Đặt nhãn khéo léo (`node[above left]`, `node[below right]`, `node[above]`) để tên điểm KHÔNG BAO GIỜ đè lên nét vẽ.
   - Nhãn điểm nằm trong dấu `$ $` (Ví dụ: `$A$`, `$B$`).

4. HÌNH CHÓP / HÌNH HỘP 3D:
   - Sử dụng góc nhìn chuẩn [x={(-0.6cm,-0.3cm)}, y={(1cm,0cm)}, z={(0cm,1cm)}] để đáy và đường cao đứng đúng vị trí không gian.

Định dạng đầu ra:
Chỉ trả về DUY NHẤT 1 khối mã ```latex ... ```. KHÔNG giải thích.
"""

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
if "used_model" not in st.session_state:
    st.session_state["used_model"] = ""

if api_key:
    client = get_openrouter_client(api_key.strip())

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
            else:
                st.warning("💡 Mẹo: Chạy `pip install streamlit-paste-button` trong Terminal để bật nút dán ảnh 1-click.")

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

                if st.button("🚀 Gemini Vẽ hình (Độ chính xác cao)", type="primary", use_container_width=True):
                    with st.spinner("⚡ Gemini Vision đang phân tích không gian & dựng hình..."):
                        generated_text, model_used, err = generate_gemini_pure(client, [image_to_process, GEMINI_STRICT_PROMPT])

                        if generated_text:
                            tikz_code = clean_tikz_code(generated_text)
                            st.session_state["tikz_code"] = tikz_code
                            st.session_state["used_model"] = model_used

                            img_bytes, render_err = render_tikz(tikz_code, output_format=render_format)
                            if img_bytes:
                                st.session_state["rendered_image"] = img_bytes
                                st.session_state["render_mime"] = "image/png" if render_format == "png" else "image/svg+xml"
                                st.success(f"⚡ Vẽ thành công bằng: **{model_used}**")
                            else:
                                st.error(f"❌ {render_err}")
                        else:
                            st.error(f"❌ {err}")

        with col_right:
            st.subheader("2. Kết quả Hình vẽ Minh họa")

            if st.session_state["rendered_image"] is not None:
                st.caption(f"🤖 AI thực hiện: `{st.session_state['used_model']}`")
                st.image(
                    st.session_state["rendered_image"], 
                    caption=f"Hình vẽ TikZ kết quả ({render_format.upper()})", 
                    use_container_width=True
                )
                
                st.download_button(
                    label=f"📥 Tải ảnh {render_format.upper()} sắc nét",
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
                st.markdown("### ✏️ Yêu cầu Gemini sửa hình vẽ")
                refine_input = st.text_input(
                    "Nhập yêu cầu sửa (VD: Đổi vị trí điểm A, thêm nét đứt SH):",
                    key="refine_input_text"
                )
                
                if st.button("✨ Cập nhật hình vẽ theo yêu cầu", type="secondary", use_container_width=True):
                    if not refine_input.strip():
                        st.warning("⚠️ Vui lòng nhập yêu cầu cần chỉnh sửa.")
                    else:
                        refine_prompt = f"""
                        Role: Chuyên gia TikZ.
                        Nhiệm vụ: Cập nhật mã TikZ hiện tại theo đúng yêu cầu người dùng, đảm bảo chuẩn hình học.

                        MÃ TIKZ HIỆN TẠI:
                        ```latex
                        {st.session_state["tikz_code"]}
                        ```

                        YÊU CẦU CHỈNH SỬA:
                        {refine_input}

                        Chỉ trả về DUY NHẤT một khối mã ```latex ... ```. KHÔNG giải thích.
                        """

                        payload = [image_to_process, refine_prompt] if image_to_process is not None else [refine_prompt]

                        with st.spinner("⚡ Gemini đang chỉnh sửa nét vẽ..."):
                            generated_text, model_used, err = generate_gemini_pure(client, payload)
                            if generated_text:
                                new_tikz_code = clean_tikz_code(generated_text)
                                st.session_state["tikz_code"] = new_tikz_code
                                st.session_state["used_model"] = model_used

                                img_bytes, render_err = render_tikz(new_tikz_code, output_format=render_format)
                                if img_bytes:
                                    st.session_state["rendered_image"] = img_bytes
                                    st.session_state["render_mime"] = "image/png" if render_format == "png" else "image/svg+xml"
                                    st.success(f"✨ Cập nhật thành công bằng **{model_used}**!")
                                    st.rerun()
                                else:
                                    st.error(f"❌ {render_err}")
                            else:
                                st.error(f"❌ {err}")
            else:
                st.info("👈 Hãy dán hoặc tải ảnh đề bài ở cột bên trái.")
else:
    st.warning("⚠️ Vui lòng nhập OpenRouter API Key ở thanh sidebar bên trái.")
