"""MilkLab Agent Harness (S2).

Usage:
    python agent_harness.py --cmd "บันทึกขายนมหมี 2 ขวด ขวดละ 65"
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv
from google import genai
from sales_logger import append_to_sheet, send_notification, get_sheet

# ชื่อเมนูเต็มในร้าน — ใช้ทั้งใน prompt (ให้ LLM map) ไม่ต้องแก้ 2 ที่
MENU_LIST = ["นมหมีฮอกไกโด", "นมหมีสตรอว์เบอร์รี", "นมหมีช็อกโกแลต"]

TOOL_SCHEMA = [
    {
        "name": "log_sale",
        "description": "บันทึกการขายลง Google Sheets และส่ง notification",
        "parameters": {
            "type": "object",
            "properties": {
                "menu": {"type": "string", "description": "ชื่อเมนู"},
                "qty": {"type": "integer", "description": "จำนวนที่ขาย"},
                "price": {"type": "number", "description": "ราคาต่อหน่วย"},
            },
            "required": ["menu", "qty", "price"],
        },
    },
    {
        "name": "query_sales",
        "description": "ดูยอดขายรวมของวันที่ระบุ",
        "parameters": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "วันที่ format YYYY-MM-DD"},
            },
            "required": ["date"],
        },
    },
    {
        "name": "send_alert",
        "description": "ส่ง message แจ้งเตือนผ่าน Bot",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
]


# ---------- tools จริง ----------

def log_sale(menu: str, qty: int, price: float) -> str:
    row = append_to_sheet(menu, qty, price)
    send_notification(
        f"บันทึกขาย {menu} {qty} ขวด ขวดละ {price} บาท รวม {row['total']} บาท"
    )
    return f"OK: row appended at {row['timestamp']} (ยอด {row['total']} บาท)"


def send_alert(message: str) -> str:
    send_notification(message)
    return f"OK: alert sent — {message}"


def query_sales(date: str) -> str:
    """อ่านทุกแถวจาก Sheet → กรองเฉพาะ timestamp ที่ขึ้นต้นด้วย date → รวม total"""
    rows = get_sheet().get_all_values()

    total = 0.0
    count = 0
    for row in rows:
        # row = [timestamp, menu, qty, price, total]
        if len(row) < 5:
            continue
        if row[0].startswith(date):        # "2026-07-15..." startswith "2026-07-15"
            try:
                total += float(row[4])
                count += 1
            except ValueError:
                continue                    # ข้าม header หรือแถวเสีย

    return f"OK: วันที่ {date} มี {count} รายการ ยอดรวม {total} บาท"


TOOLS = {"log_sale": log_sale,
         "query_sales": query_sales, "send_alert": send_alert}


# ---------- LLM ----------

def parse_command(cmd: str, api_key: str | None = None) -> dict:
    client = genai.Client(
        api_key=api_key or os.environ.get("GOOGLE_API_KEY"))

    prompt = f"""คุณเป็นผู้ช่วยร้านนม หน้าที่คือแปลงคำสั่งภาษาไทยเป็น tool call

Tools ที่ใช้ได้:
{json.dumps(TOOL_SCHEMA, ensure_ascii=False, indent=2)}

เมนูในร้าน: {", ".join(MENU_LIST)}
กฎ:
- ต้อง map ชื่อย่อเป็นชื่อเต็ม เช่น "นมหมี" → "นมหมีฮอกไกโด"
- ถ้าคำสั่งถามยอดขาย "วันนี้" ให้ใช้วันที่ปัจจุบัน (ระบบจะเติมให้)
- ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น: {{"tool": "...", "args": {{...}}}}

คำสั่ง: {cmd}"""

    resp = client.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )

    try:
        result = json.loads(resp.text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini ตอบไม่ใช่ JSON: {resp.text[:200]}") from e

    if "tool" not in result or "args" not in result:
        raise RuntimeError(f"JSON ไม่มี key ที่ต้องการ: {result}")
    return result


def dispatch_tool(tool_call: dict) -> str:
    name = tool_call["tool"]
    if name not in TOOLS:
        raise RuntimeError(f"ไม่รู้จัก tool: {name}")
    try:
        return TOOLS[name](**tool_call["args"])
    except TypeError as e:
        raise RuntimeError(f"args ไม่ตรงกับ {name}: {e}") from e


# ---------- main ----------

def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--cmd", required=True, help="คำสั่งภาษาไทย")
    args = parser.parse_args()

    print(f"[USER] {args.cmd}")

    try:
        tool_call = parse_command(args.cmd)
        print(f"[LLM]  tool={tool_call['tool']} args={tool_call['args']}")

        result = dispatch_tool(tool_call)
        print(f"[TOOL] {tool_call['tool']} {result}")
        print(f"[USER] ← {result}")
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
