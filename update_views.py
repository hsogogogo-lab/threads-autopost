"""
게시 후 24시간이 지난 Threads 글의 조회수를 시트에 기록한다.

- G열(조회수)이 비어 있고, L열이 "O", M열에 게시 ID가 있는 행만 대상
- G열: 게시글 조회수 / H열: 링크 댓글(쿠팡 링크가 들어간 내 답글) 조회수
- 이미 값이 있는 칸은 건드리지 않음
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import gspread
import requests

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1u07Ux7xx6houiqwZBh_6gyMK2Z2BHCzQzF2S97sUS9c")
SHEET_NAME = os.environ.get("SHEET_NAME", "시트1")
TOKEN = os.environ["THREADS_ACCESS_TOKEN"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
MIN_AGE = timedelta(hours=int(os.environ.get("MIN_AGE_HOURS", "24")))
LOOKBACK_ROWS = int(os.environ.get("LOOKBACK_ROWS", "60"))  # 최근 N행만 확인

API = "https://graph.threads.net/v1.0"

# 열 위치 (A=0)
COL_G, COL_H, COL_K, COL_L, COL_M = 6, 7, 10, 11, 12


def api_get(path, **params):
    params["access_token"] = TOKEN
    r = requests.get(f"{API}/{path}", params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"{path} -> {r.status_code} {r.text[:300]}")
    return r.json()


def get_views(media_id):
    data = api_get(f"{media_id}/insights", metric="views").get("data", [])
    for item in data:
        if item.get("name") == "views":
            if "total_value" in item:
                return int(item["total_value"]["value"])
            if item.get("values"):
                return int(item["values"][0]["value"])
    return None


def get_timestamp(media_id):
    ts = api_get(media_id, fields="timestamp")["timestamp"]  # 예: 2026-10-13T03:00:00+0000
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")


def find_link_reply(media_id, link):
    """내 쿠팡 링크 답글의 ID를 찾는다."""
    replies = api_get(f"{media_id}/replies", fields="id,text,username,is_reply_owned_by_me").get("data", [])
    for rep in replies:
        text = rep.get("text") or ""
        mine = rep.get("is_reply_owned_by_me", True)
        if mine and (("link.coupang.com" in text) or (link and link in text)):
            return rep["id"]
    return None


def cell_empty(row, idx):
    return idx >= len(row) or str(row[idx]).strip() == ""


def main():
    gc = gspread.service_account_from_dict(GOOGLE_CREDS)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    rows = ws.get_all_values()
    now = datetime.now(timezone.utc)

    start = max(0, len(rows) - LOOKBACK_ROWS)
    updates, errors = [], []

    for i in range(start, len(rows)):
        row = rows[i]
        rownum = i + 1
        if cell_empty(row, COL_M) or cell_empty(row, COL_L) or row[COL_L].strip() != "O":
            continue
        media_id = row[COL_M].strip()
        if not media_id.isdigit():
            continue
        need_g = cell_empty(row, COL_G)
        need_h = cell_empty(row, COL_H)
        if not (need_g or need_h):
            continue
        try:
            if now - get_timestamp(media_id) < MIN_AGE:
                continue  # 아직 24시간 안 됨
            if need_g:
                v = get_views(media_id)
                if v is not None:
                    updates.append({"range": f"G{rownum}", "values": [[v]]})
            if need_h:
                link = row[COL_K].strip() if not cell_empty(row, COL_K) else ""
                reply_id = find_link_reply(media_id, link)
                if reply_id:
                    hv = get_views(reply_id)
                    if hv is not None:
                        updates.append({"range": f"H{rownum}", "values": [[hv]]})
        except Exception as e:  # 한 행 실패해도 나머지는 진행
            errors.append(f"row {rownum} ({media_id}): {e}")

    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    for u in updates:
        print("updated", u["range"], u["values"][0][0])
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    print(f"done: {len(updates)} cells updated, {len(errors)} errors")
    if errors and not updates:
        sys.exit(1)


if __name__ == "__main__":
    main()
