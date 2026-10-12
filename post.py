"""
스레드 자동 게시 스크립트 (GitHub Actions에서 30분마다 실행)

동작:
1. 구글 시트 '시트1'에서 L열이 "예약 YY.MM.DD HH:MM" 이고 그 시간이 지난 행을 찾는다.
2. 본문(D열)을 Threads에 올리고, 그 글에 링크 댓글을 단다. 댓글에는 '광고' 주제 태그를 붙인다.
3. 성공하면 L열을 "O"로, C열에 게시 날짜를 쓰고 같은 날짜 칸을 병합한다. M열에 게시 ID를 남긴다.

본문 작성과 예약 시간 지정은 Claude 예약 작업이 아침에 해 둔다.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import requests
from google.oauth2.service_account import Credentials

KST = ZoneInfo("Asia/Seoul")
API = "https://graph.threads.net/v1.0"

TOKEN = os.environ["THREADS_TOKEN"]
USER_ID = os.environ["THREADS_USER_ID"]
SHEET_ID = os.environ["SHEET_ID"]
SHEET_NAME = os.environ.get("SHEET_NAME", "시트1")
MAX_PER_RUN = int(os.environ.get("MAX_PER_RUN", "2"))   # 한 번 실행에 올리는 최대 개수
TOPIC_TAG = os.environ.get("TOPIC_TAG", "광고")
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"          # 1이면 게시하지 않고 확인만

FIRST_ROW = 10  # 데이터 시작 행
# B..M 열 인덱스 (get("B10:M...") 기준)
B, C, D, E, F, G, H, I, J, K, L, M = range(12)

DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
LINK_INTRO = "궁금한 사람 위해 링크 남겨둘게 👇"

RESERVED = re.compile(r"^\s*예약\s+(\d{2})\.(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})\s*$")
LINK_RE = re.compile(r"https://[^\s,]*coupang\.com[^\s,]*")


def log(*args):
    print(datetime.now(KST).strftime("[%H:%M:%S]"), *args, flush=True)


# ---------------- Threads API ----------------

def _post(path, data):
    data = {**data, "access_token": TOKEN}
    r = requests.post(f"{API}/{path}", data=data, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"{path} {r.status_code}: {r.text[:300]}")
    return r.json()


def create_and_publish(text, reply_to=None, topic_tag=None):
    data = {"media_type": "TEXT", "text": text}
    if reply_to:
        data["reply_to_id"] = reply_to
    if topic_tag:
        data["topic_tag"] = topic_tag
    container = _post(f"{USER_ID}/threads", data)["id"]
    # 서버가 컨테이너를 처리할 시간을 준다
    for wait in (10, 20, 30):
        time.sleep(wait)
        try:
            return _post(f"{USER_ID}/threads_publish", {"creation_id": container})["id"]
        except RuntimeError as e:
            last = e
            log("  게시 대기 중, 다시 시도:", str(e)[:120])
    raise last


def post_with_reply(body, links):
    main_id = create_and_publish(body)
    log("  본문 게시 완료:", main_id)
    reply = f"{DISCLOSURE}\n\n{LINK_INTRO}\n\n" + "\n".join(links)
    try:
        reply_id = create_and_publish(reply, reply_to=main_id, topic_tag=TOPIC_TAG)
    except RuntimeError as e:
        # 댓글에 주제 태그가 거부되면 태그 없이 다시 시도 (고지 문구는 그대로 들어감)
        log("  태그 포함 댓글 실패, 태그 없이 재시도:", str(e)[:120])
        reply_id = create_and_publish(reply, reply_to=main_id)
    log("  링크 댓글 게시 완료:", reply_id)
    return main_id


# ---------------- 구글 시트 ----------------

def open_sheet():
    info = json.loads(os.environ["GOOGLE_SA_JSON"])
    creds = Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    return sh, sh.worksheet(SHEET_NAME)


def cell(row, idx):
    return row[idx].strip() if idx < len(row) and row[idx] else ""


def effective_date(rows, i):
    """병합된 C열에서 i번째 행이 속한 날짜(맨 위 칸 값)를 찾는다."""
    for j in range(i, -1, -1):
        v = cell(rows[j], C)
        if v:
            return v, j
    return "", None


def c_merges(sh, ws):
    meta = sh.fetch_sheet_metadata({"includeGridData": False})
    for s in meta["sheets"]:
        if s["properties"]["sheetId"] == ws.id:
            return [m for m in s.get("merges", [])
                    if m["startColumnIndex"] <= 2 < m["endColumnIndex"]]
    return []


def mark_date_and_merge(sh, ws, rows, i, date_str):
    """i번째 데이터 행에 게시 날짜를 기록하고 같은 날짜로 게시된 위쪽 행들과 C열을 병합한다."""
    sheet_row = FIRST_ROW + i
    merges = c_merges(sh, ws)
    # 이미 같은 날짜로 미리 병합된 칸 안에 있으면 그대로 둔다
    for m in merges:
        if m["startRowIndex"] <= sheet_row - 1 < m["endRowIndex"]:
            top = rows[m["startRowIndex"] - (FIRST_ROW - 1)] if m["startRowIndex"] >= FIRST_ROW - 1 else None
            if top is not None and cell(top, C) == date_str:
                return
    # 위쪽으로 같은 날짜에 게시된(O) 연속 행을 찾는다
    start = i
    while start - 1 >= 0 and cell(rows[start - 1], L) == "O" and effective_date(rows, start - 1)[0] == date_str:
        start -= 1
    top_row, end_row = FIRST_ROW + start, sheet_row
    # 이 범위와 겹치는 기존 C열 병합을 풀 범위 계산
    lo, hi = top_row - 1, end_row
    for m in merges:
        if m["startRowIndex"] < hi and m["endRowIndex"] > lo:
            lo, hi = min(lo, m["startRowIndex"]), max(hi, m["endRowIndex"])
    requests_ = [{"unmergeCells": {"range": {"sheetId": ws.id, "startRowIndex": lo, "endRowIndex": hi,
                                             "startColumnIndex": 2, "endColumnIndex": 3}}}]
    sh.batch_update({"requests": requests_})
    values = [[date_str]] + [[""] for _ in range(end_row - top_row)]
    ws.update(values=values, range_name=f"C{top_row}:C{end_row}")
    if end_row > top_row:
        sh.batch_update({"requests": [{"mergeCells": {
            "range": {"sheetId": ws.id, "startRowIndex": top_row - 1, "endRowIndex": end_row,
                      "startColumnIndex": 2, "endColumnIndex": 3},
            "mergeType": "MERGE_ALL"}}]})
    for idx in range(start, i + 1):
        while len(rows[idx]) <= C:
            rows[idx].append("")
    rows[start][C] = date_str
    for idx in range(start + 1, i + 1):
        rows[idx][C] = ""


# ---------------- 메인 ----------------

def check_token():
    r = requests.get(f"{API}/me", params={"fields": "id,username", "access_token": TOKEN}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"Threads 토큰 확인 실패 {r.status_code}: {r.text[:200]}")
    me = r.json()
    log(f"Threads 연결 확인: @{me.get('username')}")
    if str(me.get("id")) != str(USER_ID).strip():
        raise RuntimeError("THREADS_USER_ID가 토큰의 계정 ID와 다릅니다")


def main():
    now = datetime.now(KST)
    if DRY_RUN:
        check_token()
    sh, ws = open_sheet()
    if DRY_RUN:
        log(f"시트 연결 확인: {sh.title} / {ws.title}")
    rows = ws.get(f"B{FIRST_ROW}:M2000")
    due = []
    for i, row in enumerate(rows):
        m = RESERVED.match(cell(row, L))
        if not m or cell(row, M):
            continue
        yy, mo, dd, hh, mi = map(int, m.groups())
        when = datetime(2000 + yy, mo, dd, hh, mi, tzinfo=KST)
        if when <= now:
            due.append((when, i))
    due.sort()
    if not due:
        log("올릴 글 없음")
        return

    for when, i in due[:MAX_PER_RUN]:
        row = rows[i]
        sheet_row = FIRST_ROW + i
        num, body, product = cell(row, B), cell(row, D), cell(row, E)
        links = LINK_RE.findall(cell(row, K))[:2]
        log(f"{num}번 {product} (예약 {when:%m/%d %H:%M})")
        if not body or not links:
            ws.update(values=[["실패 · 본문 또는 링크 없음"]], range_name=f"L{sheet_row}")
            log("  본문 또는 링크가 없어 건너뜀")
            continue
        if DRY_RUN:
            log("  [DRY_RUN] 게시하지 않음")
            continue
        try:
            main_id = post_with_reply(body, links)
        except Exception as e:  # noqa: BLE001
            ws.update(values=[[f"실패 · {str(e)[:80]}"]], range_name=f"L{sheet_row}")
            log("  실패:", e)
            continue
        date_str = datetime.now(KST).strftime("%y.%m.%d")
        ws.update(values=[["O", main_id]], range_name=f"L{sheet_row}:M{sheet_row}")
        while len(row) <= M:
            row.append("")
        row[L], row[M] = "O", main_id
        mark_date_and_merge(sh, ws, rows, i, date_str)
        log("  시트 기록 완료")
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        log("오류:", e)
        sys.exit(1)
