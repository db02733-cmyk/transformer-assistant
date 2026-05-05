# ==============================
# ⚡ 變壓器驗收查詢助手
# ==============================

import streamlit as st
import os
import json
import datetime
import csv
import io
from openai import OpenAI

# ==============================
# 📌 資料庫
# ==============================
DB_FILE = "transformer_db.json"

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
# 📌 試驗規則
# ==============================
def get_default_tests(trans_type, capacity_mva):
    routine = [
        "繞組電阻測量",
        "電壓比測試與向量確認",
        "絕緣電阻測量",
        "介質損失角正切值(tanδ)測量",
        "油中溶解氣體分析（僅油浸式）" if trans_type == "油浸式" else "絕緣系統電氣強度試驗（僅乾式）",
        "變壓器油擊穿電壓試驗（僅油浸式）" if trans_type == "油浸式" else "局部放電測量（僅乾式）",
        "密封性試驗"
    ]

    type_test = [
        "溫升試驗",
        "雷擊衝擊電壓試驗（LI）",
        "操作衝擊電壓試驗（SI，220kV 及以上）",
        "短路承受能力試驗（≥10MVA 必做）" if capacity_mva >= 10 else "短路承受能力試驗（推薦）"
    ]

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

    if capacity_mva >= 240:
        special += ["頻率響應分析（FRA）", "聲級測定（≤65dB）"]

    return {
        "形式試驗": "\n".join(filter(None, type_test)),
        "常規試驗": "\n".join(routine),
        "特種試驗": "\n".join(filter(None, special))
    }

# ==============================
# 📌 匯出
# ==============================
def export_test_list_csv(model_key=None):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["型號", "類型", "容量(MVA)", "形式試驗", "常規試驗", "特種試驗"])
    models = [model_key] if model_key else TRANSFORMER_DB.keys()
    for model in models:
        if model in TRANSFORMER_DB:
            d = TRANSFORMER_DB[model]
            t = d.get("試驗資料", {})
            writer.writerow([
                d.get("型號", ""),
                d.get("類型", ""),
                d.get("容量", ""),
                t.get("形式試驗", "").replace("\n", "； "),
                t.get("常規試驗", "").replace("\n", "； "),
                t.get("特種試驗", "").replace("\n", "； ")
            ])
    return output.getvalue()

def export_test_list_txt(model_key=None):
    output = io.StringIO()
    models = [model_key] if model_key else TRANSFORMER_DB.keys()
    for model in models:
        if model in TRANSFORMER_DB:
            d = TRANSFORMER_DB[model]
            t = d.get("試驗資料", {})
            output.write("=" * 60 + "\n")
            output.write(f"型號：{d.get('型號', '')}\n")
            output.write(f"類型：{d.get('類型', '')}\n")
            output.write(f"容量：{d.get('容量', '')} MVA\n")
            output.write("=" * 60 + "\n\n")
            output.write("【形式試驗】\n" + t.get("形式試驗", "") + "\n\n")
            output.write("【常規試驗】\n" + t.get("常規試驗", "") + "\n\n")
            output.write("【特種試驗】\n" + t.get("特種試驗", "") + "\n\n")
    return output.getvalue()

# ==============================
# 📌 Session
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
# 📌 AI
# ==============================
def get_system_prompt():
    return f"你叫{st.session_state.nick_name}，性格是{st.session_state.nature}。請給出專業驗收建議。"

# ==============================
# 📌 頁面
# ==============================
st.set_page_config(page_title="變壓器驗收助手", page_icon="⚡", layout="centered")
st.title("⚡ 變壓器驗收查詢助手")

# ==============================
# 📌 State
# ==============================
if "message" not in st.session_state:
    st.session_state.message = []
if "nick_name" not in st.session_state:
    st.session_state.nick_name = "小甜甜"
if "nature" not in st.session_state:
    st.session_state.nature = "御姐風格的成熟台灣姑娘"
if "current_session" not in st.session_state:
    st.session_state.current_session = generate_session()

# ==============================
# 📌 API Key（✅ 修正）
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
# 📌 聊天紀錄
# ==============================
for msg in st.session_state.message:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# ==============================
# 📌 側邊欄
# ==============================
with st.sidebar:
    st.subheader("🛠 控制面板")
    mode = st.radio("模式", ["AI 問答", "型號查詢"], horizontal=True)

    if mode == "型號查詢":
        model = st.selectbox("選擇型號", ["請選擇"] + list(TRANSFORMER_DB.keys()))
        if model != "請選擇":
            col1, col2 = st.columns(2)
            with col1:
                if st.button("查看資料", use_container_width=True):
                    d = TRANSFORMER_DB[model]
                    md = f"## 🔌 {d['型號']}\n\n"
                    md += f"**類型**：{d.get('類型', '')}\n"
                    md += f"**容量**：{d.get('容量', '')} MVA\n\n"
                    t = d.get("試驗資料", {})
                    md += "### 🧪 形式試驗\n" + t.get("形式試驗", "") + "\n\n"
                    md += "### 🔧 常規試驗\n" + t.get("常規試驗", "") + "\n\n"
                    md += "### ⚡ 特種試驗\n" + t.get("特種試驗", "") + "\n\n"
                    st.session_state.message.append({"role": "assistant", "content": md})
                    st.rerun()
            with col2:
                st.download_button("📄 CSV", export_test_list_csv(model), f"{model}.csv", "text/csv", use_container_width=True)
                st.download_button("📝 TXT", export_test_list_txt(model), f"{model}.txt", "text/plain", use_container_width=True)

    st.divider()

    with st.expander("➕ 新增型號"):
        with st.form("add"):
            model_id = st.text_input("型號*")
            col1, col2 = st.columns(2)
            with col1:
                trans_type = st.selectbox("類型", ["油浸式", "乾式"])
                capacity = st.number_input("容量(MVA)", 0.1, step=0.1)
            with col2:
                voltage = st.text_input("電壓比")
                maker = st.text_input("製造商")

            tests = get_default_tests(trans_type, capacity)
            st.text_area("形式試驗", tests["形式試驗"], height=100, disabled=True)
            st.text_area("常規試驗", tests["常規試驗"], height=100, disabled=True)
            st.text_area("特種試驗", tests["特種試驗"], height=100, disabled=True)

            if st.form_submit_button("新增", use_container_width=True):
                if model_id and model_id not in TRANSFORMER_DB:
                    TRANSFORMER_DB[model_id] = {
                        "型號": model_id,
                        "類型": trans_type,
                        "容量": capacity,
                        "電壓比": voltage,
                        "製造商": maker,
                        "試驗資料": tests
                    }
                    save_transformer_db(TRANSFORMER_DB)
                    st.success("✅ 新增成功")
                    st.rerun()
                else:
                    st.error("型號已存在或為空")

    st.divider()
    if st.button("✏️ 新建會話", use_container_width=True):
        save_session()
        st.session_state.message = []
        st.session_state.current_session = generate_session()
        save_session()
        st.rerun()

# ==============================
# 📌 聊天
# ==============================
prompt = st.chat_input("輸入問題或型號：")

if prompt:
    st.chat_message("user").write(prompt)
    st.session_state.message.append({"role": "user", "content": prompt})

    if prompt.upper() in TRANSFORMER_DB:
        d = TRANSFORMER_DB[prompt.upper()]
        md = f"## 🔌 {d['型號']}\n\n"
        md += f"**類型**：{d.get('類型', '')}\n"
        md += f"**容量**：{d.get('容量', '')} MVA\n\n"
        t = d.get("試驗資料", {})
        md += "### 🧪 形式試驗\n" + t.get("形式試驗", "") + "\n\n"
        md += "### 🔧 常規試驗\n" + t.get("常規試驗", "") + "\n\n"
        md += "### ⚡ 特種試驗\n" + t.get("特種試驗", "") + "\n\n"
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