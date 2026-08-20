
---
title: FrokFix RAG
emoji: 🔧
colorFrom: blue
colorTo: purple
sdk: streamlit
sdk_version: 1.35.0
app_file: app.py
pinned: false
---

# FrokFix° — ผู้ช่วยร้านซ่อมมือถือ

pivot จาก MilkLab° Solopreneur Starter (Course 69-1) ดูรายละเอียดใน [PIVOT.md](PIVOT.md)

Template repo สำหรับวิชา 31-407-106-406 : AI for Solopreneurs

## เริ่มต้น

1. clone repo แล้ว `cp .env.example .env` เติมคีย์ให้ครบ
2. เปิด **Codespaces** จาก repo ใหม่
3. ตั้ง user-level Codespaces secret `GOOGLE_API_KEY` (ดู Quickstart)
4. รัน `python scripts/verify_setup.py` ใน terminal

## ไฟล์หลัก

| ไฟล์ | Session | คำอธิบาย |
|---|---|---|
| `caption_generator.py` | S1 | สร้างแคปชั่นโปรโมตบริการซ่อม |
| `sales_logger.py` | S2 | บันทึกงานซ่อมลง Google Sheets + แจ้งเตือน Telegram |
| `agent_harness.py` | S2 | รับคำสั่งภาษาไทย เรียก tool (quote_repair / check_part_stock / log_job) |
| `app.py` | S3 | Streamlit RAG chatbot ตอบจาก `frokfix_kb.md` |
| `frokfix_kb.md` | S3/S4 | ตารางราคา + FAQ — source of truth เดียวของราคา |

## เครื่องมือ

- Python 3.11
- Gemini API (google-genai)
- Streamlit (S3)
- gspread (S2)

## ดูคอร์ส

[course-691-stsw](https://github.com/<owner>/course-691-stsw) (link จะ update ตอนสร้าง public repo)
