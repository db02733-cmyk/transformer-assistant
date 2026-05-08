import math
import streamlit as st
import os
import json
import datetime
import csv
import io
from openai import OpenAI

# ==============================
# 電纜計算相關類和函數
# ==============================
from dataclasses import dataclass

INSULATION_TEMP_C = {
    "PVC": 70,
    "XLPE": 90,
    "EPR": 90,
}

# 電纜阻抗數據
CABLE_RESISTIVITY = {
    "XRE 3x185+95": {
        "insulation": "XLPE",
        "phases": ["3P+N+E"],
        "R_phase_90": 0.12587682,
        "R_phase_150": 0.14882838,
        "R_neutral_150": 0.28984740,
        "R_earth_150": 0.28984740,
    },
    "VV 4x35": {
        "insulation": "PVC",
        "phases": ["3P", "1P+N"],
        "R_phase_70": 0.6719358,
        "R_phase_90": 0.7944522,
    },
    "LXS 3x150+70": {
        "insulation": "XLPE",
        "phases": ["3P+N"],
        "R_phase_90": 0.2678618,
        "R_neutral_90": 0.571,
    },
    "LXS 4x70": {
        "insulation": "XLPE",
        "phases": ["3P+N"],
        "R_phase_90": 0.5760329,
        "R_neutral_90": 0.571,
    },
}

# 保險絲切斷電流數據
FUSE_CUT_OFF = {
    16: {0.1: 30, 0.2: 45, 0.5: 60, 1: 70, 5: 80},
    32: {0.1: 60, 0.2: 90, 0.5: 120, 1: 140, 5: 160},
    63: {0.1: 100, 0.2: 150, 0.5: 200, 1: 230, 5: 267},
    80: {0.1: 130, 0.2: 190, 0.5: 260, 1: 310, 5: 367},
    100: {0.1: 170, 0.2: 250, 0.5: 350, 1: 420, 5: 491},
    160: {0.1: 300, 0.2: 450, 0.5: 650, 1: 800, 5: 900},
    200: {0.1: 380, 0.2: 550, 0.5: 800, 1: 950, 5: 1100},
    250: {0.1: 450, 0.2: 700, 0.5: 1000, 1: 1200, 5: 1350},
    315: {0.1: 700, 0.2: 1100, 0.5: 1500, 1: 1800, 5: 2000},
    400: {0.1: 900, 0.2: 1400, 0.5: 2000, 1: 2300, 5: 2600},
    500: {0.1: 1100, 0.2: 1700, 0.5: 2300, 1: 2700, 5: 3000},
}


@dataclass
class Cable:
    name: str
    length_m: float
    load_a: float
    r_phase: float
    r_neutral: float = 0.0
    r_earth: float = 0.0


def _pick_r(params: dict, prefix: str, insulation: str) -> float:
    t = INSULATION_TEMP_C.get(insulation, 90)
    k = f"{prefix}_{t}"
    if k in params:
        return params[k]
    # fallback：常見 keys
    for fk in (params.get("R_phase_90"), params.get("R_phase_70"), 0.0):
        if isinstance(fk, (int, float)):
            return fk
    return 0.0

def calc_fault_current_v2(
        cable_model: str,
        length_m: float,
        fuse_rating: int,
        time_s: float,
        sc_type: str = "三相短路",
):
    params = CABLE_RESISTIVITY.get(cable_model)
    if not params:
        raise ValueError(f"未知電纜型號：{cable_model}")

    insulation = params.get("insulation", "XLPE")

    r_phase = _pick_r(params, "R_phase", insulation)
    r_neutral = _pick_r(params, "R_neutral", insulation)
    r_earth = _pick_r(params, "R_earth", insulation)

    if sc_type == "三相短路":
        rho_eq = r_phase
    elif sc_type == "單相短路（L-N）":
        if r_neutral <= 0:
            raise ValueError("該電纜不支援 L-N 短路計算")
        rho_eq = r_phase + r_neutral
    elif sc_type == "單相短路（L-E）":
        if r_earth <= 0:
            raise ValueError("該電纜不支援 L-E 短路計算")
        rho_eq = r_phase + r_earth
    else:
        raise ValueError("不支援的短路類型")

    z_total = (rho_eq / 1000) * length_m

    if z_total <= 0:
        i_fault = float("inf")
    else:
        if sc_type.startswith("三相"):
            i_fault = 400 / (math.sqrt(3) * z_total)
        else:
            i_fault = 230 / z_total

    i_cutoff = FUSE_CUT_OFF.get(fuse_rating, {}).get(time_s)

    if i_cutoff is None:
        raise ValueError(f"保險絲 {fuse_rating}A 在 {time_s}s 無切斷電流資料")

    return {
        "fault_current_a": round(i_fault, 2),
        "cutoff_current_a": i_cutoff,
        "safe": i_fault >= i_cutoff,
        "equivalent_resistivity": round(rho_eq, 6),
        "sc_type": sc_type,
        "temp_used": INSULATION_TEMP_C.get(insulation, 90),
        "time_s": time_s,
    }

# ==============================
# 資料庫檔案
# ==============================
DB_FILE = "transformer_db.json"


# ==============================
# 試驗規則引擎
# ==============================
def get_default_tests(trans_type, capacity_kva):
    routine = [
        "同批次所有變壓器均需通過以下測試：", "",
        "\t① 繞組電阻測量",
        "\t② 電壓比測試和聯結組標號檢定",
        "\t③ 短路阻抗和負載損耗測量",
        "\t④ 空載電流和空載損耗測量",
        "\t⑤ 繞組對地絕緣電阻和（或）tanδ 測量（GB 6451）",
        "\t⑥ 絕緣例行試驗（GB 1094.3）",
        "\t⑦ 有載分接開關試驗",
        "\t⑧ 絕緣油試驗：至少進行變壓器油擊穿電壓試驗" if trans_type == "油浸式" else "\t⑧ 絕緣系統電氣強度試驗",
        "\t⑨ 局部放電測量" if capacity_kva >= 10000 else "\t⑨ 建議進行局部放電測量",
        "\t⑩ 密封性試驗（氣壓或油壓法）" if trans_type == "油浸式" else "",
    ]

    type_test = [
        "同型號變壓器至少選一臺通過以下測試：", "",
        "\t① 溫升試驗（GB 1094.2）",
        "\t② 絕緣型式試驗（GB 1094.3）",
        "\t③ 雷擊衝擊電壓試驗（LI）",
        "\t④ 操作衝擊電壓試驗（SI）" if capacity_kva >= 220000 else "\t④ 短路承受能力試驗",
        "\t⑤ 油含有氣量分析" if capacity_kva >= 110000 and trans_type == "油浸式" else "",
    ]

    special = [
        "以下特種試驗需由廠家與澳電協商並選擇性進行：", "",
        "\t① 絕緣特殊試驗（GB 1094.3）",
        "\t② 繞組對地和繞組間的電容測定",
        "\t③ 暫態電壓傳輸特性測定",
        "\t④ 三相變壓器零序阻抗測量",
        "\t⑤ 短路承受能力試驗",
        "\t⑥ 聲級測定（GB 7328）" if capacity_kva >= 240000 else "\t⑥ 建議進行聲級測定（GB 7328）",
        "\t⑦ 空載電流諧波測量",
        "\t⑧ 風扇和油泵電機所吸取功率測量（適用於強迫油循環風冷變壓器）",
        "\t⑨ 局部放電測量（≤10pC）",
        "\t⑩ 頻率響應分析（FRA）" if capacity_kva >= 240000 else "\t⑩ 建議進行頻率響應分析（FRA）",
        "\t⑪ 耐火試驗（特殊場所）",
        "\t⑫ 濕熱試驗（沿海地區）" if trans_type == "乾式" else "\t⑫ 絕緣油試驗：油中溶解氣體分析（DGA）",
    ]
    if trans_type == "油浸式":
        special += ["\t⑬ 油流靜電試驗" if capacity_kva < 220000 else "\t⑬ 熱油循環試驗", ]

    return {
        "常規試驗": "\n".join(routine),
        "型式試驗": "\n".join(type_test),
        "特種試驗": "\n".join(special)
    }


# ==============================
# 資料庫管理
# ==============================
def load_transformer_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_transformer_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


TRANSFORMER_DB = load_transformer_db()


# ==============================
# 匯出功能
# ==============================
def export_test_list_csv(model_key=None):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["型號", "類型", "額定容量(kVA)", "額定電流(A)", "額定頻率(Hz)", "常規試驗", "型式試驗", "特種試驗"])
    models = [model_key] if model_key else TRANSFORMER_DB.keys()
    for model in models:
        if model in TRANSFORMER_DB:
            d = TRANSFORMER_DB[model]
            t = get_default_tests(d.get("類型", ""), int(d.get("額定容量", "")))
            writer.writerow([
                d.get("型號", ""),
                d.get("類型", ""),
                d.get("額定容量", ""),
                d.get("額定電流", ""),
                d.get("額定頻率", ""),
                t.get("常規試驗", "").replace("\n", "； "),
                t.get("型式試驗", "").replace("\n", "； "),
                t.get("特種試驗", "").replace("\n", "； ")
            ])
    return output.getvalue()


def export_test_list_txt(model_key=None):
    output = io.StringIO()
    models = [model_key] if model_key else TRANSFORMER_DB.keys()
    for model in models:
        if model in TRANSFORMER_DB:
            d = TRANSFORMER_DB[model]
            t = get_default_tests(d.get("類型", ""), int(d.get("額定容量", "")))
            output.write("=" * 60 + "\n")
            output.write(f"型號：{d.get('型號', '')}\n")
            output.write(f"類型：{d.get('類型', '')}\n")
            output.write(f"額定容量：{d.get('額定容量', '')} kVA\n")
            output.write(f"額定電流：{d.get('額定電流', '')} A\n")
            output.write(f"額定頻率：{d.get('額定頻率', '')} Hz\n")
            output.write("=" * 60 + "\n\n")
            output.write("【常規試驗】\n" + t.get("常規試驗", "") + "\n\n")
            output.write("【型式試驗】\n" + t.get("型式試驗", "") + "\n\n")
            output.write("【特種試驗】\n" + t.get("特種試驗", "") + "\n\n")
    return output.getvalue()


# ==============================
# Session 函數管理
# ==============================
def save_session():
    if st.session_state.current_session:
        os.makedirs("session_data", exist_ok=True)
        with open(f"session_data/{st.session_state.current_session}.json", "w", encoding="utf-8") as f:
            json.dump({
                "nick_name": st.session_state.nick_name,
                "nature": st.session_state.nature,
                "current_session": st.session_state.current_session,
                "message": st.session_state.message
            }, f, ensure_ascii=False, indent=2)


def generate_session():
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def load_sessions():
    if os.path.exists("session_data"):
        return sorted([f[:-5] for f in os.listdir("session_data") if f.endswith(".json")], reverse=True)
    return []


def load_session(name):
    try:
        with open(f"session_data/{name}.json", "r", encoding="utf-8") as f:
            d = json.load(f)
            st.session_state.nick_name = d["nick_name"]
            st.session_state.nature = d["nature"]
            st.session_state.current_session = d["current_session"]
            st.session_state.message = d["message"]
    except:
        pass


def delete_session(name):
    try:
        os.remove(f"session_data/{name}.json")
        if name == st.session_state.current_session:
            st.session_state.message = []
            st.session_state.current_session = generate_session()
    except:
        pass


# ==============================
# AI 提示詞
# ==============================
def get_system_prompt():
    return (
        f"你叫{st.session_state.nick_name}，性格是{st.session_state.nature}。"
        f"禁止任何場景或情緒描述文字。"
    )


# ==============================
# 頁面設定
# ==============================
st.set_page_config(
    page_title="變壓器驗收查詢助手",
    page_icon="⚡️",
    layout="wide"  # 改為 wide 布局，給側邊欄更多空間
)

# --- 注入 CSS 樣式 (讓介面變深色，更像截圖) ---
st.markdown("""
<style>
    /* 全局背景 */
    .main {
        background-color: #0E1117;
        color: #FAFAFA;
    }
    /* 側邊欄背景 */
    .stSidebar {
        background-color: #262730;
        border-right: 1px solid #444;
    }
    /* 標題顏色 */
    h1, h2, h3, h4, h5, h6 {
        color: #00D2FF;
    }
    /* 按鈕樣式 */
    .stButton>button {
        background-color: #FF4B4B;
        color: white;
        border-radius: 5px;
        border: none;
    }
    .stButton>button:hover {
        background-color: #FF6B6B;
    }
    /* 輸入框背景 */
    .stTextInput>div>div>input, .stSelectbox>div>div>select, .stTextArea>div>div>textarea {
        background-color: #333;
        color: white;
    }
    /* Markdown 代碼塊 */
    .stCodeBlock pre {
        background-color: #1E1E1E;
        color: #D4D4D4;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚡️ 變壓器驗收查詢助手")

# ==============================
# Session State
# ==============================
if "message" not in st.session_state:
    st.session_state.message = []
if "nick_name" not in st.session_state:
    st.session_state.nick_name = "拉克絲"
if "nature" not in st.session_state:
    st.session_state.nature = "不苟言笑較真的性格"
if "current_session" not in st.session_state:
    st.session_state.current_session = generate_session()

# ==============================
# API Key
# ==============================
api_key = os.environ.get("DEEPSEEK_API_KEY")
if not api_key:
    st.error("⚠️ 尚未設定 DEEPSEEK_API_KEY，請在 Streamlit Cloud 的 Secrets 中設定")
    st.stop()

client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com/v1"
)

# ==============================
# 聊天紀錄
# ==============================
# 使用一個容器來限制聊天紀錄的高度，防止頁面過長
chat_container = st.container(height=600)
with chat_container:
    for msg in st.session_state.message:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

# ==============================
# 側邊欄
# ==============================
with st.sidebar:
    st.subheader("🛠 控制面板")
    mode = st.radio("模式", ["電纜安全長度計算", "型號查詢"], horizontal=True)

    # 這裡加入一個分隔線，把模式選擇和下面的內容稍微隔開
    st.divider()

    # ---------- 型號查詢 ----------
    if mode == "型號查詢":
        model = st.selectbox("選擇型號", ["請選擇"] + list(TRANSFORMER_DB.keys()))
        if model != "請選擇":
            col1, col2 = st.columns(2)
            with col1:
                if st.button("查看資料", use_container_width=True):
                    d = TRANSFORMER_DB[model]
                    md = f"## 🪪 {d['型號']}\n\n"
                    md += f"**類型**：{d.get('類型', '')}\n"
                    md += f"**額定容量**：{d.get('額定容量', '')} KVA\n\n"
                    md += f"**額定電流**：{d.get('額定電流', '')} A\n"
                    md += f"**額定頻率**：{d.get('額定頻率', '')} Hz\n\n"
                    t = get_default_tests(d.get("類型"), d.get("額定容量", 0))
                    md += "### 🛠️ 常規試驗\n" + t.get("常規試驗", "") + "\n\n"
                    md += "### 🖥️ 型式試驗\n" + t.get("型式試驗", "") + "\n\n"
                    md += "### 🔬 特種試驗\n" + t.get("特種試驗", "") + "\n\n"
                    st.session_state.message.append({"role": "assistant", "content": md})
                    st.rerun()
            with col2:
                st.download_button("📃 CSV", export_test_list_csv(model), f"{model}.csv", "text/csv",
                                   use_container_width=True)
                st.download_button("📄 TXT", export_test_list_txt(model), f"{model}.txt", "text/plain",
                                   use_container_width=True)

    # 注意：這裡的 st.divider() 原本是在 if 裡面的，把它移到外面，確保不管哪個模式都有分隔
    st.divider()

    # ---------- 電纜安全長度計算 ----------
    if mode == "電纜安全長度計算":
        st.subheader("📏 電纜安全長度計算")

        # 初始化 session state
        if "cable_result" not in st.session_state:
            st.session_state.cable_result = None

        # 創建兩個選項卡
        tab1, tab2 = st.tabs(["📐 基本計算", "⚡ 短路保護驗證"])

        with tab1:
            with st.form("cable_calc_form"):
                st.markdown("### 基本參數")

                col1, col2 = st.columns(2)
                with col1:
                    cable_voltage = st.number_input(
                        "系統電壓 (V)",
                        min_value=1,
                        max_value=1000,
                        value=400,
                        step=10,
                        help="三相系統線電壓"
                    )
                    fuse_current = st.number_input(
                        "保險絲額定電流 (A)",
                        min_value=1,
                        max_value=1000,
                        value=200,
                        step=10
                    )
                    cable_area = st.number_input(
                        "電纜截面積 (mm²)",
                        min_value=1.0,
                        max_value=1000.0,
                        value=185.0,
                        step=5.0
                    )

                with col2:
                    material = st.selectbox(
                        "電纜材質",
                        ["銅", "鋁"],
                        index=0
                    )
                    drop_percent = st.slider(
                        "允許電壓降 (%)",
                        min_value=1.0,
                        max_value=10.0,
                        value=5.0,
                        step=0.5
                    )
                    cable_type = st.selectbox(
                        "電纜類型",
                        ["普通電纜", "鋼帶鎧裝電纜", "XLPE 電纜"],
                        index=0
                    )

                # 高級選項
                with st.expander("🔧 高級選項"):
                    temp_coeff = st.slider(
                        "溫度係數 (°C)",
                        min_value=20,
                        max_value=150,
                        value=90,
                        step=5,
                        help="電纜工作溫度"
                    )
                    power_factor = st.slider(
                        "功率因數",
                        min_value=0.8,
                        max_value=1.0,
                        value=0.85,
                        step=0.01
                    )
                    three_phase = st.checkbox("三相系統", value=True)

                submitted = st.form_submit_button("🧮 開始計算", use_container_width=True)

                if submitted:
                    # 電阻率 (Ω·mm²/m) 20°C
                    resistivity_20 = 0.0175 if material == "銅" else 0.0283

                    # 溫度修正係數
                    temp_correction = 1 + 0.00393 * (temp_coeff - 20)
                    resistivity = resistivity_20 * temp_correction

                    # 允許電壓降 (V)
                    max_drop = cable_voltage * (drop_percent / 100)

                    # 計算最大長度
                    if three_phase:
                        # 三相公式: L = (ΔV × A) / (√3 × ρ × I × cosφ)
                        max_length = (max_drop * cable_area) / (
                                math.sqrt(3) * resistivity * fuse_current * power_factor)
                    else:
                        # 單相公式: L = (ΔV × A) / (2 × ρ × I)
                        max_length = (max_drop * cable_area) / (2 * resistivity * fuse_current)

                    # 存儲結果
                    st.session_state.cable_result = {
                        "cable_voltage": cable_voltage,
                        "fuse_current": fuse_current,
                        "cable_area": cable_area,
                        "material": material,
                        "drop_percent": drop_percent,
                        "max_length": max_length,
                        "resistivity": resistivity,
                        "max_drop": max_drop,
                        "three_phase": three_phase,
                        "temp_coeff": temp_coeff
                    }
        with tab2:
            st.markdown("### 短路保護驗證")

            if st.session_state.cable_result:
                result = st.session_state.cable_result

                with st.form("short_circuit_check"):
                    st.info(f"當前電壓降計算長度：{result['max_length']:.2f} m")

                    col1, col2 = st.columns(2)

                    with col1:
                        fuse_rating = st.selectbox(
                            "保險絲額定值 A",
                            [16, 32, 63, 80, 100, 160, 200, 250, 315, 400, 500],
                            key="fuse_rating_tab2"
                        )

                        time_s = st.selectbox(
                            "保險絲跳開時間 s",
                            [0.1, 0.2, 0.5, 1.0, 5.0],
                            index=4,
                            key="time_s_tab2"
                        )

                        sc_type = st.selectbox(
                            "短路類型",
                            ["三相短路", "單相短路（L-N）", "單相短路（L-E）"],
                            key="sc_type_tab2"
                        )

                    with col2:
                        cable_model = st.selectbox(
                            "電纜型號",
                            list(CABLE_RESISTIVITY.keys()),
                            key="cable_model_tab2"
                        )

                        actual_length = st.number_input(
                            "實際電纜長度 m",
                            min_value=1.0,
                            max_value=2000.0,
                            value=float(result["max_length"]),
                            key="actual_length_tab2"
                        )

                    if st.form_submit_button("🔍 驗證短路保護"):
                        try:
                            sc_result = calc_fault_current_v2(
                                cable_model=cable_model,
                                length_m=actual_length,
                                fuse_rating=fuse_rating,
                                time_s=time_s,
                                sc_type=sc_type
                            )

                            st.success(f"✅ 使用電纜：{cable_model}｜短路類型：{sc_type}")

                            col1, col2, col3 = st.columns(3)
                            col1.metric("最小故障電流 A", f"{sc_result['fault_current_a']:.1f} ")
                            col2.metric("保險絲切斷電流 A", f"{sc_result['cutoff_current_a']} ")
                            col3.metric("保護結果","✅" if sc_result["safe"] else "❌")

                            if not sc_result["safe"]:
                                st.error("⚠️ 故障電流不足，保險絲可能無法及時跳脫")

                        except ValueError as e:
                            st.error(str(e))


        # 顯示計算結果
        if st.session_state.cable_result:
            result = st.session_state.cable_result

            st.markdown("---")
            st.markdown("### 📋 計算結果")

            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric(
                    "最大電纜長度 m",
                    f"{result['max_length']:.2f} ",
                    delta=f"{result['max_length'] * 1.1:.1f} m (安全裕度10%)"
                )

            with col2:
                st.metric(
                    "允許電壓降 V",
                    f"{result['max_drop']:.2f} ",
                    delta=f"{result['drop_percent']}%"
                )

            with col3:
                st.metric(
                    "等效電阻率 Ω·mm²/m",
                    f"{result['resistivity']:.5f} ",
                    delta=f"{result['temp_coeff']}°C"
                )

            # 詳細計算過程
            with st.expander("📐 詳細計算過程"):
                # 重新計算需要的值
                resistivity_20 = 0.0175 if result['material'] == "銅" else 0.0283
                power_factor = 0.85  # 使用默認值

                # 構建公式字符串
                if result['three_phase']:
                    formula = f""" 
                        計算公式：三相系統

                        1. 溫度修正後電阻率：
                           ρ = {resistivity_20} × (1 + 0.00393 × ({result['temp_coeff']} - 20))
                             = {result['resistivity']:.6f} Ω·mm²/m

                        2. 允許電壓降：
                           ΔV = {result['cable_voltage']} V × {result['drop_percent']}%
                              = {result['max_drop']:.2f} V

                        3. 三相最大長度：
                           L = {result['max_drop']:.2f} × {result['cable_voltage']}
                               / (√3 × {result['resistivity']:.6f} × {result['fuse_current']} × {power_factor})
                             = {result['max_length']:.2f} m
                            """
                else:
                    formula = f""" 
                        計算公式：單相系統

                        1. 溫度修正後電阻率：
                           ρ = {resistivity_20} × (1 + 0.00393 × ({result['temp_coeff']} - 20))
                             = {result['resistivity']:.6f} Ω·mm²/m

                        2. 允許電壓降：
                           ΔV = {result['cable_voltage']} V × {result['drop_percent']}%
                              = {result['max_drop']:.2f} V

                        3. 單相最大長度：
                           L = {result['max_drop']:.2f} × {result['cable_area']}
                               / (2 × {result['resistivity']:.6f} × {result['fuse_current']})
                             = {result['max_length']:.2f} m
                            """
                st.code(formula)

    # 在這裡統一放置「型號管理」、「助手資料」、「會話管理」
    # 這樣不管你選擇哪個模式，這些功能都會顯示在側邊欄的底部
    st.divider()

    # ---------- 型號管理（含新增 + 刪除） ----------
    st.subheader("📦 型號管理")

    # ➕ 新增型號
    with st.expander("➕ 新增變壓器型號"):
        with st.form("add"):
            model_id = st.text_input("型號（唯一）*")
            col1, col2, col3 = st.columns(3)
            with col1:
                trans_type = st.selectbox("類型", ["油浸式", "乾式"])
                capacity = st.number_input("額定容量(kVA)", 0, step=1)
            with col2:
                voltage = st.text_input("電壓比(kV)")
                maker = st.text_input("製造商")
            with col3:
                current = st.number_input("額定電流(A)", 0, step=10)
                friquency = st.number_input("頻率(Hz)", 0, step=1)

            if st.form_submit_button("新增", use_container_width=True):
                if model_id and model_id not in TRANSFORMER_DB:
                    TRANSFORMER_DB[model_id] = {
                        "型號": model_id,
                        "類型": trans_type,
                        "額定容量": capacity,
                        "電壓比": voltage,
                        "製造商": maker,
                        "額定電流": current,
                        "額定頻率": friquency,
                    }
                    save_transformer_db(TRANSFORMER_DB)
                    st.success("👌 型號新增成功")
                    st.rerun()
                else:
                    st.error("型號已存在或為空")

    # 🗑️ 刪除型號
    st.divider()
    st.subheader("🗑️ 刪除型號")

    del_model = st.selectbox(
        "選擇要刪除的型號",
        ["請選擇"] + list(TRANSFORMER_DB.keys()),
        key="delete_model_select"
    )

    if del_model != "請選擇":
        col1, col2 = st.columns([3, 1])
        with col1:
            st.warning(f"⚠️ 確定要刪除型號 **{del_model}** 嗎？此操作無法復原。")
        with col2:
            if st.button("確認刪除", type="secondary", use_container_width=True):
                if del_model in TRANSFORMER_DB:
                    del TRANSFORMER_DB[del_model]
                    save_transformer_db(TRANSFORMER_DB)
                    st.success(f"✅ 型號 {del_model} 已刪除")
                    st.rerun()
                else:
                    st.error("型號不存在")

    st.divider()

    # ---------- 助手資料 ----------
    st.subheader("💃🏻 助手資料")
    nick = st.text_input("暱稱", value=st.session_state.nick_name, key="nick_input")
    if nick:
        st.session_state.nick_name = nick

    nature = st.text_area("性格", value=st.session_state.nature, key="nature_input")
    if nature:
        st.session_state.nature = nature

    st.caption("💡 修改後立即生效")

    st.divider()

    # ---------- 會話管理 ----------
    if st.button("✏️ 新建會話", use_container_width=True):
        save_session()
        st.session_state.message = []
        st.session_state.current_session = generate_session()
        save_session()
        st.rerun()

    st.caption("📂 會話歷史")
    for s in load_sessions():
        c1, c2 = st.columns([4, 1])
        with c1:
            if st.button(
                    s,
                    width="stretch",
                    type="primary" if s == st.session_state.current_session else "secondary"
            ):
                load_session(s)
                st.rerun()
        with c2:
            if st.button("🗑️", width="stretch", key=f"del_{s}"):
                delete_session(s)
                st.rerun()

# ==============================
# 聊天輸入 (放在側邊欄外面)
# ==============================
prompt = st.chat_input("輸入問題或變壓器型號：")

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state.message.append({"role": "user", "content": prompt})

    if prompt.upper() in TRANSFORMER_DB:
        d = TRANSFORMER_DB[prompt.upper()]
        md = f"## 🪪 {d['型號']}\n\n"
        md += f"**類型**：{d.get('類型', '')}\n"
        md += f"**額定容量**：{d.get('額定容量', '')} KVA\n\n"
        t = get_default_tests(d.get("類型", ""), d.get("額定容量", ""))
        md += "### 🛠️ 常規試驗\n" + t.get("常規試驗", "") + "\n\n"
        md += "### 🖥️ 型式試驗\n" + t.get("型式試驗", "") + "\n\n"
        md += "### 🔬 特種試驗\n" + t.get("特種試驗", "") + "\n\n"
        st.session_state.message.append({"role": "assistant", "content": md})
    else:
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "system", "content": get_system_prompt()}, *st.session_state.message],
                stream=True
            )
            with st.chat_message("assistant"):
                placeholder = st.empty()
                reply = ""
                for chunk in resp:
                    if chunk.choices[0].delta.content:
                        reply += chunk.choices[0].delta.content
                        placeholder.write(reply)
                st.session_state.message.append({"role": "assistant", "content": reply})
        except Exception as e:
            st.error(f"AI 呼叫失敗：{e}")

    save_session()