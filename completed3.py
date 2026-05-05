# ==============================
# ⚡ 變壓器驗收查詢助手
# 📌 功能：AI 問答 + 型號管理 + 試驗規則 + 一鍵匯出
# 📌 作者：工程驗收助手
# ==============================

# ---------- 基礎套件導入 ----------
import streamlit as st
import os
import json
import datetime
import csv
import io
from openai import OpenAI

# ==============================
# 📌 強制設定（解決部署錯誤）
# ==============================
os.environ["STREAMLIT_LOG_LEVEL"] = "error"

# ==============================
# 📌 資料庫檔案
# ==============================
DB_FILE = "transformer_db.json"


# ============================================================
# 試驗規則
# 根據變壓器類型與容量，自動產生標準試驗項目
# ============================================================
def get_default_tests(trans_type, capacity_mva):
    """
    根據變壓器類型與容量，返回預設試驗項目
    :param trans_type: "油浸式" / "乾式"
    :param capacity_mva: 額定容量（MVA）
    :return: dict 包含三種試驗的文字
    """

    # ---------- 常規試驗（每台必做） ----------
    routine = [
        "繞組電阻測量",
        "電壓比測試與向量確認",
        "絕緣電阻測量",
        "介質損失角正切值(tanδ)測量",
        "油中溶解氣體分析（僅油浸式）" if trans_type == "油浸式" else "絕緣系統電氣強度試驗（僅乾式）",
        "變壓器油擊穿電壓試驗（僅油浸式）" if trans_type == "油浸式" else "局部放電測量（僅乾式）",
        "密封性試驗"
    ]

    # ---------- 形式試驗（型式試驗） ----------
    type_test = [
        "溫升試驗",
        "雷擊衝擊電壓試驗（LI）",
        "操作衝擊電壓試驗（SI，220kV 及以上）",
        "短路承受能力試驗（≥10MVA 必做）" if capacity_mva >= 10 else "短路承受能力試驗（推薦）"
    ]

    # ---------- 特種試驗（特殊需求） ----------
    special = []

    if trans_type == "油浸式":
        special += [
            "油溫升試驗",
            "熱油循環試驗（≥220kV）" if capacity_mva >= 220 else "油流靜電試驗",
            "油中含氣量分析（≥110kV）" if capacity_mva >= 110 else ""
        ]
    else:
        special += [
            "局部放電測量（≤10pC）",
            "耐火試驗（特殊場所）",
            "濕熱試驗（沿海地區）"
        ]

    # 超大容量變壓器額外試驗
    if capacity_mva >= 240:
        special += ["頻率響應分析（FRA）", "聲級測定（≤65dB）"]

    # 回傳結構化資料（前端直接讀取）
    return {
        "形式試驗": "\n".join(filter(None, type_test)),   # 過濾空值
        "常規試驗": "\n".join(routine),
        "特種試驗": "\n".join(filter(None, special))
    }


# ============================================================
# 📌 型號資料庫管理
# 負責讀取 / 寫入 JSON 檔案
# ============================================================
def load_transformer_db():
    """載入變壓器型號資料庫"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_transformer_db(db):
    """儲存變壓器型號資料庫"""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# 全域變數：型號資料庫（記憶體中）
TRANSFORMER_DB = load_transformer_db()


# ============================================================
# 📌 匯出試驗清單功能
# 支援 CSV（Excel）與 TXT（列印）
# ============================================================
def export_test_list_csv(model_key=None):
    """
    匯出試驗清單為 CSV 格式
    :param model_key: 單一型號（None 表示全部）
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # CSV 表頭
    writer.writerow([
        "型號", "類型", "容量(MVA)",
        "形式試驗", "常規試驗", "特種試驗"
    ])

    # 決定要匯出哪些型號
    models = [model_key] if model_key else TRANSFORMER_DB.keys()

    for model in models:
        if model in TRANSFORMER_DB:
            d = TRANSFORMER_DB[model]
            tests = d.get("試驗資料", {})

            writer.writerow([
                d.get("型號", ""),
                d.get("類型", ""),
                d.get("容量", ""),
                tests.get("形式試驗", "").replace("\n", "； "),
                tests.get("常規試驗", "").replace("\n", "； "),
                tests.get("特種試驗", "").replace("\n", "； ")
            ])

    return output.getvalue()


def export_test_list_txt(model_key=None):
    """
    匯出試驗清單為 TXT 格式（適合現場列印）
    """
    output = io.StringIO()
    models = [model_key] if model_key else TRANSFORMER_DB.keys()

    for model in models:
        if model in TRANSFORMER_DB:
            d = TRANSFORMER_DB[model]
            tests = d.get("試驗資料", {})

            output.write("=" * 60 + "\n")
            output.write(f"變壓器型號：{d.get('型號', '')}\n")
            output.write(f"類型：{d.get('類型', '')}\n")
            output.write(f"容量：{d.get('容量', '')} MVA\n")
            output.write("=" * 60 + "\n\n")

            output.write("【形式試驗】\n")
            output.write(tests.get("形式試驗", "") + "\n\n")

            output.write("【常規試驗】\n")
            output.write(tests.get("常規試驗", "") + "\n\n")

            output.write("【特種試驗】\n")
            output.write(tests.get("特種試驗", "") + "\n\n")

            output.write("\n" + "=" * 60 + "\n\n")

    return output.getvalue()


# ============================================================
# 📌 Session 管理（聊天紀錄）
# 負責儲存 / 載入 / 刪除聊天會話
# ============================================================
def save_session():
    """儲存當前聊天會話"""
    if st.session_state.current_session:
        session_data = {
            "nick_name": st.session_state.nick_name,
            "nature": st.session_state.nature,
            "current_session": st.session_state.current_session,
            "message": st.session_state.message
        }
        os.makedirs("session_data", exist_ok=True)
        with open(f"session_data/{st.session_state.current_session}.json", "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)


def generate_session():
    """產生新的會話 ID（時間戳）"""
    return datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def load_sessions():
    """載入所有歷史會話"""
    if os.path.exists("session_data"):
        files = [f[:-5] for f in os.listdir("session_data") if f.endswith(".json")]
        return sorted(files, reverse=True)
    return []


def load_session(name):
    """載入指定會話"""
    try:
        with open(f"session_data/{name}.json", "r", encoding="utf-8") as f:
            d = json.load(f)
            st.session_state.nick_name = d["nick_name"]
            st.session_state.nature = d["nature"]
            st.session_state.current_session = d["current_session"]
            st.session_state.message = d["message"]
    except Exception as e:
        st.error(e)


def delete_session(name):
    """刪除指定會話"""
    try:
        os.remove(f"session_data/{name}.json")
        if name == st.session_state.current_session:
            st.session_state.message = []
            st.session_state.current_session = generate_session()
    except Exception as e:
        st.error(e)


# ============================================================
# 📌 AI 提示詞生成
# ============================================================
def get_system_prompt():
    """生成 AI 系統提示詞"""
    return (
        f"你叫{st.session_state.nick_name}，性格是{st.session_state.nature}。"
        f"請根據變壓器類型、容量及試驗標準，給出專業驗收建議。"
        f"禁止任何場景或情緒描述文字。"
    )


# ============================================================
# 📌 Streamlit 頁面設定
# ============================================================
st.set_page_config(
    page_title="變壓器驗收查詢助手",
    page_icon="⚡",
    layout="wide"   # 寬版佈局（適合桌面）
)

st.title("⚡ 變壓器驗收查詢助手")

# ============================================================
# 📌 Session State 初始化
# 確保所有狀態都存在，避免 KeyError
# ============================================================
if "message" not in st.session_state:
    st.session_state.message = []
if "nick_name" not in st.session_state:
    st.session_state.nick_name = "小甜甜"
if "nature" not in st.session_state:
    st.session_state.nature = "御姐風格的成熟台灣姑娘"
if "current_session" not in st.session_state:
    st.session_state.current_session = generate_session()

# ============================================================
# 📌 聊天紀錄顯示
# ============================================================
for msg in st.session_state.message:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# ============================================================
# 📌 OpenAI / DeepSeek API Client
# ============================================================
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

# ============================================================
# 📌 側邊欄（主要操作介面）
# ============================================================
with st.sidebar:
    st.subheader("🛠 控制面板")

    # ---------- 模式切換 ----------
    mode = st.radio(
        "模式選擇",
        ["AI 問答模式", "型號直接查詢"],
        horizontal=True
    )

    # ---------- 型號查詢模式 ----------
    if mode == "型號直接查詢":
        model = st.selectbox(
            "選擇變壓器型號",
            ["請選擇"] + list(TRANSFORMER_DB.keys())
        )

        if model != "請選擇":
            col1, col2 = st.columns(2)
            with col1:
                if st.button("查看型號資料", type="primary"):
                    d = TRANSFORMER_DB[model]
                    md = f"## 🔌 {d['型號']} 技術參數\n\n"
                    md += "| 項目 | 內容 |\n|------|------|\n"
                    for k, v in d.items():
                        if k not in ["型號", "試驗資料", "類型", "容量"]:
                            md += f"| {k} | {v} |\n"

                    md += f"\n| 類型 | {d.get('類型', '未填寫')} |\n"
                    md += f"| 容量 | {d.get('容量', '未填寫')} MVA |\n"

                    if "試驗資料" in d:
                        md += "\n---\n"
                        md += "## 🧪 試驗資料\n\n"
                        for test_key, test_title in {
                            "形式試驗": "📋 形式試驗",
                            "常規試驗": "🔧 常規試驗",
                            "特種試驗": "⚡ 特種試驗"
                        }.items():
                            md += f"### {test_title}\n"
                            md += f"{d['試驗資料'].get(test_key, '無資料')}\n\n"

                    st.session_state.message.append({
                        "role": "assistant",
                        "content": md
                    })
                    st.rerun()

            with col2:
                # ---------- 匯出單一型號試驗清單 ----------
                st.download_button(
                    label="📄 匯出試驗清單（CSV）",
                    data=export_test_list_csv(model),
                    file_name=f"{model}_試驗清單.csv",
                    mime="text/csv",
                    type="secondary"
                )

                st.download_button(
                    label="📝 匯出試驗清單（TXT）",
                    data=export_test_list_txt(model),
                    file_name=f"{model}_試驗清單.txt",
                    mime="text/plain",
                    type="secondary"
                )

    st.divider()

    # ---------- 型號管理 ----------
    st.subheader("📦 型號管理")

    with st.expander("➕ 新增變壓器型號"):
        with st.form("add_model_form"):
            st.markdown("### 📌 基本參數")
            col1, col2 = st.columns(2)
            with col1:
                model_id = st.text_input("型號（唯一）*")
                trans_type = st.selectbox("變壓器類型", ["油浸式", "乾式"])
                capacity = st.number_input("額定容量（MVA）", min_value=0.1, step=0.1)
                voltage = st.text_input("電壓比")
                cooling = st.text_input("冷卻方式")
                maker = st.text_input("製造商")
            with col2:
                date = st.date_input("出廠日期")
                standard = st.text_input("驗收標準", value="GB/T 1094")
                insulation = st.text_input("絕緣水平")
                impedance = st.text_input("阻抗電壓")
                no_load = st.text_input("空載損耗")
                load_loss = st.text_input("負載損耗")

            st.markdown("---")
            st.markdown("### 🧪 試驗資料（根據類型與容量自動匹配）")

            # 根據類型與容量自動產生試驗
            default_tests = get_default_tests(trans_type, capacity)

            # 只讀顯示（不可編輯）
            st.text_area(
                "📋 形式試驗（Type Test）",
                value=default_tests["形式試驗"],
                height=120,
                disabled=True
            )

            st.text_area(
                "🔧 常規試驗（Routine Test）",
                value=default_tests["常規試驗"],
                height=120,
                disabled=True
            )

            st.text_area(
                "⚡ 特種試驗（Special Test）",
                value=default_tests["特種試驗"],
                height=120,
                disabled=True
            )

            submitted = st.form_submit_button("新增型號")
            if submitted:
                if not model_id:
                    st.warning("型號不能為空")
                elif model_id in TRANSFORMER_DB:
                    st.error("此型號已存在")
                else:
                    TRANSFORMER_DB[model_id] = {
                        "型號": model_id,
                        "類型": trans_type,
                        "容量": capacity,
                        "額定容量": f"{capacity} MVA",
                        "電壓比": voltage,
                        "冷卻方式": cooling,
                        "製造商": maker,
                        "出廠日期": str(date),
                        "驗收標準": standard,
                        "絕緣水平": insulation,
                        "阻抗電壓": impedance,
                        "空載損耗": no_load,
                        "負載損耗": load_loss,
                        "試驗資料": default_tests
                    }
                    save_transformer_db(TRANSFORMER_DB)
                    st.success(f"✅ 型號 {model_id} 已新增")
                    st.rerun()

    st.caption("🗑️ 刪除型號")
    del_model = st.selectbox(
        "選擇要刪除的型號",
        ["請選擇"] + list(TRANSFORMER_DB.keys()),
        key="delete_select"
    )
    if del_model != "請選擇" and st.button("確認刪除", type="secondary"):
        del TRANSFORMER_DB[del_model]
        save_transformer_db(TRANSFORMER_DB)
        st.success(f"✅ 型號 {del_model} 已刪除")
        st.rerun()

    # ---------- 批量匯出 ----------
    st.divider()
    st.subheader("📤 批量匯出")

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📊 匯出全部型號（CSV）",
            data=export_test_list_csv(),
            file_name="全部變壓器試驗清單.csv",
            mime="text/csv",
            type="primary"
        )

    with col2:
        st.download_button(
            label="📄 匯出全部型號（TXT）",
            data=export_test_list_txt(),
            file_name="全部變壓器試驗清單.txt",
            mime="text/plain",
            type="primary"
        )

    st.divider()

    # ---------- 會話管理 ----------
    if st.button("✏️ 新建會話", width="stretch"):
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
            if st.button("❌", width="stretch", key=f"del_{s}"):
                delete_session(s)
                st.rerun()

    st.divider()
    st.subheader("🤖 助手資料")

    nick = st.text_input("暱稱", value=st.session_state.nick_name)
    if nick:
        st.session_state.nick_name = nick

    nature = st.text_area("性格", value=st.session_state.nature)
    if nature:
        st.session_state.nature = nature

# ============================================================
# 📌 使用者輸入（聊天框）
# ============================================================
prompt = st.chat_input("輸入問題或變壓器型號：")

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state.message.append({"role": "user", "content": prompt})

    # ---- 如果是型號，直接顯示資料 ----
    if prompt.strip().upper() in TRANSFORMER_DB:
        d = TRANSFORMER_DB[prompt.strip().upper()]
        md = f"## 🔌 {d['型號']} 技術參數\n\n"
        md += "| 項目 | 內容 |\n|------|------|\n"
        for k, v in d.items():
            if k not in ["型號", "試驗資料", "類型", "容量"]:
                md += f"| {k} | {v} |\n"

        md += f"\n| 類型 | {d.get('類型', '未填寫')} |\n"
        md += f"| 容量 | {d.get('容量', '未填寫')} MVA |\n"

        if "試驗資料" in d:
            md += "\n---\n"
            md += "## 🧪 試驗資料\n\n"
            for test_key, test_title in {
                "形式試驗": "📋 形式試驗",
                "常規試驗": "🔧 常規試驗",
                "特種試驗": "⚡ 特種試驗"
            }.items():
                md += f"### {test_title}\n"
                md += f"{d['試驗資料'].get(test_key, '無資料')}\n\n"

        st.session_state.message.append({
            "role": "assistant",
            "content": md
        })

    # ---- 否則交給 AI 回答 ----
    else:
        try:
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": get_system_prompt()},
                    *st.session_state.message
                ],
                stream=True
            )

            with st.chat_message("assistant"):
                placeholder = st.empty()
                reply = ""

                for chunk in resp:
                    if chunk.choices[0].delta.content:
                        reply += chunk.choices[0].delta.content
                        placeholder.write(reply)

                st.session_state.message.append({
                    "role": "assistant",
                    "content": reply
                })

        except Exception as e:
            st.error(f"AI 呼叫失敗：{e}")

    # 儲存會話
    save_session()