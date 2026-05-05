# ==============================
# 變壓器驗收查詢助手
# 功能包括：AI 問答 + 型號管理 + 試驗規則 + 一鍵匯出 + 助手設定 + 刪除型號
# ==============================

import streamlit as st
import os
import json
import datetime
import csv
import io
from openai import OpenAI
from streamlit.elements.lib.form_utils import current_form_id

# ==============================
# 資料庫檔案
# ==============================
DB_FILE = "transformer_db.json"

# ==============================
# 試驗規則引擎
# ==============================
def get_default_tests(trans_type, capacity_kva):
    routine = [
        "1.繞組電阻測量\n",
        "2.電壓比測試和聯結組標號檢定\n",
        "3.短路阻抗和負載損耗測量\n",
        "4.空載電流和空載損耗測量\n",
        "5.繞組對地絕緣電阻和(或)絕緣系統電容的介質損耗因數(tanδ)的測量(GB 6451)\n",
        "6.絕緣例行試驗(GB 1094.3)\n",
        "7.有載分接開關試驗\n",
        "8.絕緣油試驗（僅油浸式）：變壓器油擊穿電壓試驗必做\n" if trans_type == "油浸式" else "絕緣系統電氣強度試驗（僅乾式）\n",
        "9.局部放電測量\n"if capacity_kva >= 10000 else "建議進行局部放電測量\n",
        "10.密封性試驗:應采用氣壓或油壓法"
    ]

    type_test = [
        "溫升試驗(GB 1094.2)\n",
        "絕緣形式試驗(GB 1094.3)\n",
        "雷擊衝擊電壓試驗（LI）\n",
        "操作衝擊電壓試驗（SI，220kV 及以上）\n",
        "短路承受能力試驗（≥10MVA 必做）\n" if capacity_kva >= 10000 else "短路承受能力試驗（推薦）\n"
    ]

    special = []
    if trans_type == "油浸式":
        special += [
            "熱油循環試驗（≥220kV）\n" if capacity_kva >= 220000 else "油流靜電試驗\n",
            "油中含氣量分析（≥110kV）\n" if capacity_kva >= 110000 else "\n",
            "絕緣特殊試驗(GB 1094.3)\n",
            "繞組對地和繞組間的電容測定\n",
            "暫態電壓傳輸特性測定\n",
            "三相變壓器零序阻抗測量\n",
            "短路承受能力試驗\n",
            "聲級測定(GB 7328)\n",
            "空載電流諧波測量\n",
            "風扇和油泵電機所吸取功率測量:適用於強迫油循環風冷變壓器\n",
            "絕緣油試驗（僅油浸式）:油中溶解氣體分析(DGA)"

        ]
    else:
        special += [
            "局部放電測量（≤10pC）\n",
            "耐火試驗（特殊場所）\n",
            "濕熱試驗（沿海地區）\n"
            "絕緣特殊試驗(GB 1094.3)\n",
            "繞組對地和繞組間的電容測定\n",
            "暫態電壓傳輸特性測定\n",
            "三相變壓器零序阻抗測量\n",
            "短路承受能力試驗\n",
            "聲級測定(GB 7328)\n",
            "空載電流諧波測量\n",
            "風扇和油泵電機所吸取功率測量\n"
        ]

    if capacity_kva >= 240000:
        special += ["頻率響應分析（FRA）\n", "聲級測定（≤65dB）\n"]

    return {
        "常規試驗": "\n".join(routine),
        "形式試驗": "\n".join(filter(None, type_test)),
        "特種試驗": "\n".join(filter(None, special))
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
    writer.writerow(["型號", "類型", "額定容量(kVA)","常規試驗", "形式試驗","特種試驗"])
    models = [model_key] if model_key else TRANSFORMER_DB.keys()
    for model in models:
        if model in TRANSFORMER_DB:
            d = TRANSFORMER_DB[model]
            t = d.get("試驗資料", {})
            writer.writerow([
                d.get("型號", ""),
                d.get("類型", ""),
                d.get("額定容量", ""),
                d.get("額定電流",""),
                d.get("額定頻率", ""),
                t.get("常規試驗", "").replace("\n", "； "),
                t.get("形式試驗", "").replace("\n", "； "),
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
            output.write(f"額定容量：{d.get('額定容量', '')} kVA\n")
            output.write(f"額定電流：{d.get('額定電流', '')} A\n")
            output.write(f"額定頻率：{d.get('額定頻率', '')} Hz\n")
            output.write("=" * 60 + "\n\n")
            output.write("【常規試驗】\n" + t.get("常規試驗", "") + "\n\n")
            output.write("【形式試驗】\n" + t.get("形式試驗", "") + "\n\n")
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
        # f"請根據變壓器類型、額定容量及試驗標準，給出專業驗收建議。"

    )

# ==============================
# 頁面設定
# ==============================
st.set_page_config(
    page_title="變壓器驗收查詢助手",
    page_icon="⚡️",
    layout="centered"
)

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
for msg in st.session_state.message:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# ==============================
# 側邊欄
# ==============================
with st.sidebar:
    st.subheader("🛠 控制面板")
    mode = st.radio("模式", ["AI 問答", "型號查詢"], horizontal=True)

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
                    t = d.get("試驗資料", {})
                    md += "### 🛠️ 常規試驗\n" + t.get("常規試驗", "") + "\n\n"
                    md += "### 🖥️ 形式試驗\n" + t.get("形式試驗", "") + "\n\n"
                    md += "### 🔬 特種試驗\n" + t.get("特種試驗", "") + "\n\n"
                    st.session_state.message.append({"role": "assistant", "content": md})
                    st.rerun()
            with col2:
                st.download_button("📃 CSV", export_test_list_csv(model), f"{model}.csv", "text/csv", use_container_width=True)
                st.download_button("📄 TXT", export_test_list_txt(model), f"{model}.txt", "text/plain", use_container_width=True)

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


            tests = get_default_tests(trans_type, capacity)
            st.text_area("常規試驗", tests["常規試驗"], height=100, disabled=True)
            st.text_area("形式試驗", tests["形式試驗"], height=100, disabled=True)
            st.text_area("特種試驗", tests["特種試驗"], height=100, disabled=True)

            if st.form_submit_button("新增", use_container_width=True):
                if model_id and model_id not in TRANSFORMER_DB:
                    TRANSFORMER_DB[model_id] = {
                        "型號": model_id,
                        "類型": trans_type,
                        "額定容量": capacity,
                        "電壓比": voltage,
                        "製造商": maker,
                        "額定電流":current,
                        "額定頻率":friquency,
                        "試驗資料": tests
                    }
                    save_transformer_db(TRANSFORMER_DB)
                    st.success("👌 型號新增成功")
                    st.rerun()
                else:
                    st.error("型號已存在或為空")

    # 🗑️ 刪除型號（✅ 重點回歸）
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
            if st.button("❌", width="stretch", key=f"del_{s}"):
                delete_session(s)
                st.rerun()

# ==============================
# 聊天輸入
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
        t = d.get("試驗資料", {})
        md += "### 🛠️ 常規試驗\n" + t.get("常規試驗", "") + "\n\n"
        md += "### 🖥️ 形式試驗\n" + t.get("形式試驗", "") + "\n\n"
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