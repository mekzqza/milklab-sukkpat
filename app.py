"""FrokFix RAG Chatbot (S3).

Run locally: streamlit run app.py
Deploy: push to GitHub then Actions deploys to HuggingFace Space

นักศึกษาต้องเติม TODO 5 จุด ใน Session 3 Lab 2.2
"""

import os

import faiss
import streamlit as st
from dotenv import load_dotenv
from google import genai
from sentence_transformers import SentenceTransformer

load_dotenv()


@st.cache_resource
def load_index():
    # TODO 1: โหลด + หั่น chunk
    with open("frokfix_kb.md", encoding="utf-8") as f:
        text = f.read()
    chunks = [c.strip() for c in text.split("\n## ") if c.strip()]

    # TODO 2: encode chunk เป็นเวกเตอร์
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    embeddings = model.encode(chunks, convert_to_numpy=True)

    # TODO 3: สร้าง faiss index
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)

    return model, index, chunks


def retrieve_top_k(query, model, index, chunks, k=3):
    query_vec = model.encode(
        [query], convert_to_numpy=True
    )  # ← model ตัวเดียวกับตอน encode chunk!
    distances, indices = index.search(query_vec, k)
    return [chunks[i] for i in indices[0]]


def generate_answer(query, context_chunks):
    context = "\n\n".join(context_chunks)
    prompt = f"""ตอบจากข้อมูลต่อไปนี้เท่านั้น ถ้าไม่มีใน context ให้บอกว่าไม่ทราบ ห้ามเดา

ข้อมูล:
{context}

คำถาม: {query}"""

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY ไม่ถูกตั้งค่า")
    client = genai.Client(api_key=api_key)
    resp = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return resp.text


def main():
    st.set_page_config(page_title="FrokFix° RAG", page_icon="🔧")
    st.title("FrokFix° เช็คราคาซ่อมมือถือ")
    st.caption("ถามราคา อาการเสีย หรือเงื่อนไขประกัน ตอบจากตารางราคาจริงของร้าน")

    try:
        model, index, chunks = load_index()
    except NotImplementedError as exc:
        st.error(f"TODO not implemented: {exc}")
        st.stop()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    if prompt := st.chat_input("เช่น จอ iPhone 12 เท่าไหร่ ซ่อมกี่วัน"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)

        with st.chat_message("assistant"):
            with st.spinner("กำลังค้นข้อมูล..."):
                context = retrieve_top_k(prompt, model, index, chunks)
                answer = generate_answer(prompt, context)
            st.write(answer)
            with st.expander("Source chunks"):
                for i, c in enumerate(context, 1):
                    st.markdown(f"**[{i}]** {c}")
        st.session_state.messages.append({"role": "assistant", "content": answer})


if __name__ == "__main__":
    main()
