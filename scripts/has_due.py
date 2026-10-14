"""이번 타임(지금부터 약 70분 안)에 올릴 예약 글이 시트에 있는지 확인한다.
없으면 GitHub 출력값 has=0 을 남겨, 기다리지 않고 바로 끝나게 한다(사용 시간 절약)."""
import json, os, re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import gspread

KST = ZoneInfo("Asia/Seoul")
R = re.compile(r"^\s*예약\s+(\d{2})\.(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})\s*$")

gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_SA_JSON"]))
ws = gc.open_by_key(os.environ["SHEET_ID"]).worksheet(os.environ.get("SHEET_NAME", "시트1"))
now = datetime.now(KST)
n = 0
for (v,) in [(r[0] if r else "",) for r in ws.get("L10:L3000")]:
    m = R.match(v or "")
    if not m:
        continue
    yy, mo, dd, hh, mi = map(int, m.groups())
    t = datetime(2000 + yy, mo, dd, hh, mi, tzinfo=KST)
    if now - timedelta(hours=3) <= t <= now + timedelta(minutes=70):
        n += 1
print(f"이번 타임 예약 글 {n}개")
with open(os.environ["GITHUB_OUTPUT"], "a") as f:
    f.write(f"has={1 if n else 0}\n")
