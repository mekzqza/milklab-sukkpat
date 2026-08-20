"""FrokFix Job Logger (S2).

Usage:
    python sales_logger.py --model "iPhone 12" --service "เปลี่ยนจอ เกรด A" --price 1290 --warranty 15

Reads GOOGLE_SHEETS_CREDENTIALS and TELEGRAM_BOT_TOKEN (or LINE_CHANNEL_TOKEN) from env.
Appends row [timestamp, model, service, price, warranty_days, status] to the jobs Sheet,
then sends a notification via Telegram or LINE bot.

Pivot note (S4): MilkLab บันทึก [menu, qty, price, total] เพราะขายของเป็นชิ้น
ร้านซ่อมขายงานเป็นเคส เลยเก็บ warranty_days (งานซ่อมมีประกัน) และ status
(เครื่องยังอยู่ที่ร้าน) แทน qty กับ total ซึ่งไม่มีความหมายในโดเมนนี้
"""

import argparse
import json
import os
import sys
from datetime import datetime

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# งานซ่อม
SHEET_ID = "15B2snJ-47tcX6fvioTHcqTeUWCLZ-ydPjgfYkHVFUlU"
# สต็อกอะไหล่ (Fork_fix_stock_gear)
STOCK_SHEET_ID = "1Xeac6AUn0sONIJQBeArbD0h7i9mp56V9LkgV2Zuczys"

JOB_HEADER = ["timestamp", "model", "service", "price", "warranty_days", "status"]
STOCK_HEADER = ["part", "model", "qty", "cost", "price", "lead_days"]

STATUS_RECEIVED = "รับเครื่อง"
STATUS_IN_PROGRESS = "กำลังซ่อม"
STATUS_DONE = "เสร็จรอรับ"


def _open(sheet_id: str):
    raw = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if not raw:
        raise RuntimeError("GOOGLE_SHEETS_CREDENTIALS ไม่ถูกตั้งค่า")
    creds = Credentials.from_service_account_info(
        json.loads(raw),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds).open_by_key(sheet_id).sheet1


def get_sheet():
    """Sheet งานซ่อม"""
    return _open(SHEET_ID)


def get_stock_sheet():
    """Sheet สต็อกอะไหล่"""
    return _open(STOCK_SHEET_ID)


def append_job(
    model: str,
    service: str,
    price: float,
    warranty_days: int = 0,
    status: str = STATUS_RECEIVED,
) -> dict:
    """append งานซ่อม 1 เคสลง Sheet

    Returns dict ของแถวที่ append
    Raises RuntimeError ถ้า credentials ไม่มี หรือ Sheet ไม่ accessible
    """
    timestamp = datetime.now().isoformat()
    row = [timestamp, model, service, price, warranty_days, status]
    get_sheet().append_row(row)
    return dict(zip(JOB_HEADER, row))


def send_notification(message: str) -> str:
    """ส่ง message ไปยัง Telegram bot

    Returns: provider name ที่ใช้ ("telegram")
    Raises RuntimeError ถ้าไม่มี credentials หรือส่งไม่สำเร็จ
    """
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN หรือ TELEGRAM_CHAT_ID ไม่ถูกตั้งค่า")

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": message},
            timeout=10,
        )
        r.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"ส่ง Telegram ล้มเหลว: {exc}") from exc
    return "telegram"


def init_sheets() -> None:
    """เขียน header ลง Sheet ทั้งสองใบถ้ายังว่าง — รันครั้งเดียวตอน setup

    python -c "import sales_logger; sales_logger.init_sheets()"
    """
    for sheet, header in ((get_sheet(), JOB_HEADER), (get_stock_sheet(), STOCK_HEADER)):
        # get_all_values() คืน [[]] เมื่อ sheet ว่าง ซึ่ง truthy ต้องเช็คเนื้อในจริง
        if any(any(c.strip() for c in row) for row in sheet.get_all_values()):
            print(f"[SKIP] {sheet.spreadsheet.title} มีข้อมูลอยู่แล้ว")
            continue
        sheet.append_row(header)
        print(f"[OK] ใส่ header ให้ {sheet.spreadsheet.title}")


def main() -> int:
    parser = argparse.ArgumentParser(description="FrokFix Job Logger")
    parser.add_argument("--model", required=True, help="รุ่นเครื่อง เช่น iPhone 12")
    parser.add_argument("--service", required=True, help="รายการซ่อม")
    parser.add_argument("--price", type=float, required=True, help="ราคา")
    parser.add_argument("--warranty", type=int, default=0, help="ประกัน (วัน)")
    parser.add_argument("--status", default=STATUS_RECEIVED, help="สถานะเครื่อง")
    args = parser.parse_args()

    try:
        job = append_job(args.model, args.service, args.price, args.warranty, args.status)
    except Exception as exc:
        print(f"[ERROR] บันทึก Sheet ล้มเหลว: {exc}", file=sys.stderr)
        print(
            "[HINT] ตรวจ GOOGLE_SHEETS_CREDENTIALS และ share Sheet กับ service account email",
            file=sys.stderr,
        )
        return 1

    try:
        provider = send_notification(
            f"รับงาน {job['model']} — {job['service']} {job['price']} บาท "
            f"ประกัน {job['warranty_days']} วัน"
        )
    except Exception as exc:
        print(f"[WARN] บันทึก Sheet สำเร็จแต่ส่งแจ้งเตือนล้มเหลว: {exc}", file=sys.stderr)
        return 0

    print(f"[OK] บันทึกและแจ้งเตือนผ่าน {provider} เรียบร้อย — {job['service']} {job['price']} บาท")
    return 0


if __name__ == "__main__":
    sys.exit(main())
