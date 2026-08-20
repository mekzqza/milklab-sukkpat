"""FrokFix Agent Harness (S2 + S4 pivot).

Usage:
    python agent_harness.py --cmd "จอ iPhone 12 แตก ซ่อมเท่าไหร่"
    python agent_harness.py --cmd "รับงานเปลี่ยนแบต iPhone 12 890 บาท"
    python agent_harness.py --cmd "จอ A54 มีของไหม"

Pivot note (S4): MilkLab มี 3 tool (log_sale / query_sales / send_alert)
FrokFix เพิ่ม quote_repair กับ check_part_stock เพราะร้านซ่อมต้องตอบ
"เท่าไหร่ เสร็จกี่โมง มีอะไหล่ไหม" ก่อนถึงจะได้รับงาน ซึ่งร้านนมไม่มีขั้นตอนนี้
ราคาทั้งหมดอ่านจาก frokfix_kb.md ไฟล์เดียวกับที่ RAG chatbot ใช้ ไม่ hardcode ซ้ำ
"""

import argparse
import json
import os
import re
import sys
from datetime import date

from dotenv import load_dotenv
from google import genai
from sales_logger import (
    STATUS_IN_PROGRESS,
    append_job,
    get_sheet,
    get_stock_sheet,
    send_notification,
)

KB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frokfix_kb.md")

# บรรทัดราคาใน kb: "- บริการ | รุ่น / รุ่น | ราคา | นาที | วันประกัน"
PRICE_LINE = re.compile(
    r"^-\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*$"
)

ANY_MODEL = "ทุกรุ่น"

# อาการที่ลูกค้าพูด → ชื่อบริการใน kb (เช็คตามลำดับ อันที่เจาะจงกว่าต้องมาก่อน)
SYMPTOM_MAP = [
    ("ล้างเครื่องโดนน้ำ", ["ตกน้ำ", "โดนน้ำ", "น้ำเข้า", "เปียก"]),
    ("เปลี่ยนแบต", ["แบต", "บวม", "หมดเร็ว", "เปอร์เซ็นต์", "ดับเอง"]),
    ("ซ่อมพอร์ตชาร์จ", ["พอร์ต", "ชาร์จไม่เข้า", "เสียบไม่ติด", "ตูดชาร์จ", "ชาร์จ"]),
    ("เปลี่ยนกระจกหลัง", ["ฝาหลัง", "กระจกหลัง", "หลังแตก"]),
    ("เปลี่ยนกล้องหลัง", ["กล้อง", "ถ่ายรูป", "เบลอ"]),
    ("ติดฟิล์มกระจก", ["ฟิล์ม"]),
    ("เปลี่ยนจอ", ["จอ", "หน้าจอ", "แตก", "ร้าว", "ทัช", "เส้น", "จุด", "ไม่ติด"]),
]
FALLBACK_SERVICE = "ตรวจเช็คอาการ"

# ponytail: คิวคิดเป็นค่าเฉลี่ยต่อเครื่อง ไม่ได้เก็บเวลาซ่อมจริงลง Sheet
# ถ้าอยากแม่นขึ้นค่อยเพิ่มคอลัมน์ minutes แล้วบวกของจริงแทน
AVG_MINUTES_PER_JOB = 45


def _norm(s: str) -> str:
    return s.replace(" ", "").replace("-", "").lower()


def load_price_table(path: str = KB_PATH) -> list[dict]:
    """อ่านตารางราคาจาก frokfix_kb.md — source of truth เดียวของราคา"""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = PRICE_LINE.match(line.strip())
            if not m:
                continue
            service, models, price, minutes, warranty = m.groups()
            rows.append(
                {
                    "service": service,
                    "models": [x.strip() for x in models.split("/")],
                    "price": int(price),
                    "minutes": int(minutes),
                    "warranty_days": int(warranty),
                }
            )
    if not rows:
        raise RuntimeError(f"ไม่พบตารางราคาใน {path}")
    return rows


PRICE_TABLE = load_price_table()
SERVICE_LIST = sorted({r["service"] for r in PRICE_TABLE})
MODEL_LIST = sorted({m for r in PRICE_TABLE for m in r["models"] if m != ANY_MODEL})


def match_service(symptom: str) -> str:
    """อาการภาษาคน → ชื่อบริการ"""
    for service, keywords in SYMPTOM_MAP:
        if any(k in symptom for k in keywords):
            return service
    return FALLBACK_SERVICE


def fmt_minutes(minutes: int) -> str:
    if minutes >= 1440:
        days = round(minutes / 1440)
        return f"{days} ถึง {days + 1} วัน"
    if minutes >= 60:
        h, m = divmod(minutes, 60)
        return f"{h} ชม." + (f" {m} นาที" if m else "")
    return f"{minutes} นาที"


def queue_minutes() -> int:
    """เวลารอจากเครื่องที่ยัง 'กำลังซ่อม' ค้างอยู่ในร้าน"""
    try:
        rows = get_sheet().get_all_values()
    except Exception:
        return 0  # เช็คคิวไม่ได้ก็ยังตอบราคาได้ ดีกว่าพังทั้งคำตอบ
    waiting = sum(1 for r in rows if len(r) >= 6 and r[5].strip() == STATUS_IN_PROGRESS)
    return waiting * AVG_MINUTES_PER_JOB


# ---------- tools จริง ----------


def quote_repair(model: str, symptom: str) -> str:
    """ประเมินราคา + เวลารับเครื่อง จากรุ่นและอาการที่ลูกค้าบอก"""
    service = match_service(symptom)
    matches = [
        r
        for r in PRICE_TABLE
        if r["service"].startswith(service)
        and (
            ANY_MODEL in r["models"]
            or any(_norm(m) == _norm(model) for m in r["models"])
        )
    ]
    if not matches:
        return (
            f"OK: ยังไม่มีราคา {service} ของ {model} ในตาราง "
            f"(รุ่นที่มีราคาแล้ว: {', '.join(MODEL_LIST)}) "
            "แนะนำให้ลูกค้าเข้ามาตรวจเช็คฟรีก่อน"
        )

    queue = queue_minutes()
    # ไม่ใช้ลูกศรยูนิโค้ดใน output เพราะ console ไทยเป็น cp874 แล้วพังตอน print
    lines = [f"OK: {model} อาการ '{symptom}' ตรงกับบริการ {service}"]
    for r in matches:
        eta = r["minutes"] + queue
        warranty = (
            f"ประกัน {r['warranty_days']} วัน" if r["warranty_days"] else "ไม่มีประกัน"
        )
        price = "ฟรี" if r["price"] == 0 else f"{r['price']:,} บาท"
        lines.append(
            f"  - {r['service']}: {price} | ซ่อม {fmt_minutes(r['minutes'])}"
            f" | {warranty} | รับเครื่องได้ในราว {fmt_minutes(eta)}"
        )
    if queue:
        lines.append(f"  (รวมคิวหน้าร้านอีก {fmt_minutes(queue)} แล้ว)")
    return "\n".join(lines)


def check_part_stock(part: str) -> str:
    """เช็คอะไหล่คงเหลือ + ราคาทุน/ราคาขาย จาก Sheet สต็อก"""
    rows = get_stock_sheet().get_all_values()
    hits = [
        r
        for r in rows[1:]
        if len(r) >= 6 and (_norm(part) in _norm(r[0]) or _norm(part) in _norm(r[1]))
    ]
    if not hits:
        return f"OK: ไม่มี '{part}' ในสต็อก ต้องสั่งเข้า แจ้งลูกค้าว่า 1 ถึง 3 วัน"

    lines = [f"OK: อะไหล่ที่ตรงกับ '{part}'"]
    for name, model, qty, cost, price, lead in (r[:6] for r in hits):
        left = int(qty) if qty.strip().isdigit() else 0
        state = f"เหลือ {left} ชิ้น" if left else f"หมด ต้องสั่ง {lead} วัน"
        lines.append(f"  - {name} ({model}): {state} | ทุน {cost} | ขาย {price}")
    return "\n".join(lines)


def log_job(model: str, service: str, price: float, warranty_days: int = 0) -> str:
    job = append_job(model, service, price, warranty_days)
    send_notification(f"รับงาน {model} — {service} {price} บาท ประกัน {warranty_days} วัน")
    return f"OK: บันทึกงานเวลา {job['timestamp']} (สถานะ {job['status']})"


def query_sales(date_str: str) -> str:
    """รวมรายได้ของวันที่ระบุจาก Sheet งานซ่อม"""
    rows = get_sheet().get_all_values()

    total = 0.0
    count = 0
    for row in rows:
        # row = [timestamp, model, service, price, warranty_days, status]
        if len(row) < 4 or not row[0].startswith(date_str):
            continue
        try:
            total += float(row[3])
            count += 1
        except ValueError:
            continue  # ข้าม header หรือแถวเสีย

    return f"OK: วันที่ {date_str} รับงาน {count} เคส รายได้รวม {total:,.0f} บาท"


def send_alert(message: str) -> str:
    send_notification(message)
    return f"OK: alert sent — {message}"


TOOL_SCHEMA = [
    {
        "name": "quote_repair",
        "description": (
            "ประเมินราคาและเวลารับเครื่อง จากรุ่นและอาการที่ลูกค้าบอก "
            "ใช้ตอบคำถาม 'ซ่อมเท่าไหร่ เสร็จเมื่อไหร่'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "รุ่นเครื่อง เช่น iPhone 12"},
                "symptom": {
                    "type": "string",
                    "description": "อาการที่ลูกค้าบอก เช่น จอแตก แบตบวม",
                },
            },
            "required": ["model", "symptom"],
        },
    },
    {
        "name": "check_part_stock",
        "description": "เช็คว่าอะไหล่ชิ้นนั้นมีในสต็อกกี่ชิ้น ราคาทุนเท่าไหร่ ถ้าหมดต้องสั่งกี่วัน",
        "parameters": {
            "type": "object",
            "properties": {
                "part": {"type": "string", "description": "ชื่ออะไหล่หรือรุ่น เช่น จอ A54"},
            },
            "required": ["part"],
        },
    },
    {
        "name": "log_job",
        "description": "บันทึกงานซ่อมที่รับแล้วลง Google Sheets และส่ง notification",
        "parameters": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "รุ่นเครื่อง"},
                "service": {"type": "string", "description": "รายการซ่อม"},
                "price": {"type": "number", "description": "ราคาที่ตกลง"},
                "warranty_days": {"type": "integer", "description": "ประกันกี่วัน"},
            },
            "required": ["model", "service", "price"],
        },
    },
    {
        "name": "query_sales",
        "description": "ดูรายได้รวมของวันที่ระบุ",
        "parameters": {
            "type": "object",
            "properties": {
                "date_str": {"type": "string", "description": "วันที่ format YYYY-MM-DD"},
            },
            "required": ["date_str"],
        },
    },
    {
        "name": "send_alert",
        "description": "ส่ง message แจ้งเตือนผ่าน Bot เช่น เตือนว่าอะไหล่ใกล้หมด",
        "parameters": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
]

TOOLS = {
    "quote_repair": quote_repair,
    "check_part_stock": check_part_stock,
    "log_job": log_job,
    "query_sales": query_sales,
    "send_alert": send_alert,
}


# ---------- LLM ----------


def parse_command(cmd: str, api_key: str | None = None) -> dict:
    client = genai.Client(api_key=api_key or os.environ.get("GOOGLE_API_KEY"))

    prompt = f"""คุณเป็นผู้ช่วยหน้าร้านซ่อมมือถือ FrokFix° หน้าที่คือแปลงคำสั่งภาษาไทยเป็น tool call

Tools ที่ใช้ได้:
{json.dumps(TOOL_SCHEMA, ensure_ascii=False, indent=2)}

รุ่นที่ร้านมีราคาแล้ว: {", ".join(MODEL_LIST)}
บริการที่ร้านรับ: {", ".join(SERVICE_LIST)}
กฎ:
- map ชื่อรุ่นย่อเป็นชื่อเต็ม เช่น "ไอโฟน 12" หรือ "ip12" ให้เป็น "iPhone 12", "A54" ให้เป็น "Samsung A54"
- ถ้าลูกค้าถามราคาหรือถามว่าเสร็จเมื่อไหร่ ให้ใช้ quote_repair โดยส่งอาการดิบที่ลูกค้าพูดไปใน symptom
- ถ้าถามว่ามีอะไหล่ไหม ให้ใช้ check_part_stock
- ใช้ log_job เฉพาะตอนที่รับงานแล้วจริง ไม่ใช่ตอนถามราคา
- ถ้าถามยอด "วันนี้" ให้ใช้ {date.today().isoformat()}
- ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น: {{"tool": "...", "args": {{...}}}}

คำสั่ง: {cmd}"""

    try:
        resp = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
    except Exception as e:  # 429/503 จาก Gemini เจอบ่อย ไม่ต้องโยน traceback ใส่หน้าคนใช้
        raise RuntimeError(f"เรียก Gemini ไม่สำเร็จ ลองใหม่อีกครั้ง: {e}") from e

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
        print(f"[TOOL] {tool_call['tool']}\n{result}")
    except RuntimeError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
