"""FrokFix Caption Generator (S1).

Usage:
    python caption_generator.py

Reads GOOGLE_API_KEY from env. Generates a Thai caption for a phone repair service.
"""

import os
import sys

from dotenv import load_dotenv
from google import genai


PROMPT_TEMPLATE = """คุณคือคนดูแลเพจของร้าน FrokFix° ร้านซ่อมมือถือหน้าตลาด ช่างชื่อพี่โฟค

จงเขียนแคปชั่นภาษาไทย 2 ถึง 3 ประโยคโปรโมตบริการ: {service}

เงื่อนไข:
- เปิดด้วยอาการที่ลูกค้าเจอจริง เช่น จอแตก แบตหมดไว ชาร์จไม่เข้า
- โทนน่าเชื่อถือแบบช่างมืออาชีพ ไม่ตลก ไม่โอ้อวดเกินจริง ใส่ emoji ได้ไม่เกิน 2 ตัว
- ถ้าชื่อบริการมีราคาหรือเวลาซ่อมอยู่แล้ว ให้พูดถึงด้วย ห้ามแต่งราคาขึ้นเอง
- ต้องมี call-to-action ปิดท้าย เช่น ทักแชทเช็ครุ่น หรือ จองคิวได้เลย
- ห้ามใช้ em dash
"""


def generate_caption(service: str, api_key: str | None = None) -> str:
    """Generate a Thai caption for the given repair service."""
    key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY not set in env or argument")
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=PROMPT_TEMPLATE.format(service=service),
    )
    return response.text or ""


def main() -> int:
    load_dotenv()
    service = input("บริการที่จะโปรโมต: ").strip()
    if not service:
        print("กรุณาใส่ชื่อบริการ")
        return 1
    caption = generate_caption(service)
    print()
    print(caption)
    return 0


if __name__ == "__main__":
    sys.exit(main())
