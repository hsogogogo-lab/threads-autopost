"""게시 30시간 뒤 Threads 조회수를 시트 G열(본문), H열(링크 댓글)에 기록한다.

대상: L열 "O" + M열 게시 ID 있음 + G열 비어 있음 + 게시 후 30시간 경과.
환경변수:
  THREADS_ACCESS_TOKEN          Threads API 토큰 (게시용과 같은 것)
  GOOGLE_SERVICE_ACCOUNT_JSON   시트 접근용 서비스 계정 JSON 문자열
  SPREADSHEET_ID                시트 ID
  VIEWS_DELAY_HOURS             (기본값: 30)
"""
import json, os, sys, datetime as dt
import requests, gspread

API = "https://graph.threads.net/v1.0"
TOKEN = os.environ["THREADS_ACCESS_TOKEN"]
SHEET_ID = os.environ["SPREADSHEET_ID"]
DELAY = dt.timedelta(hours=float(os.environ.get("VIEWS_DELAY_HOURS", "30")))
FIRST_ROW = 10  # 데이터 시작 행 (B10)


def get(path, **params):
    params["access_token"] = TOKEN
    r = requests.get(f"{API}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def views(media_id):
    data = get(f"{media_id}/insights", metric="views").get("data", [])
    for m in data:
        if m.get("name") == "views":
            if m.get("values"):
                return int(m["values"][0]["value"])
            if "total_value" in m:
                return int(m["total_value"]["value"])
    return None


def my_link_reply(media_id, me):
    """내 계정이 단 댓글 중 쿠팡 링크가 들어간 첫 댓글 ID."""
    replies = get(f"{media_id}/replies", fields="id,username,text,timestamp").get("data", [])
    mine = [r for r in replies if r.get("username") == me]
    for r in mine:
        if "coupang" in (r.get("text") or ""):
            return r["id"]
    return mine[0]["id"] if mine else None


def main():
    gc = gspread.service_account_from_dict(json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]))
    ws = gc.open_by_key(SHEET_ID).worksheet("시트1")
    rows = ws.get(f"B{FIRST_ROW}:M2000")
    me = get("me", fields="username")["username"]
    now = dt.datetime.now(dt.timezone.utc)
    updates = []
    done = 0
    for i, r in enumerate(rows):
        r = (r + [""] * 12)[:12]
        num, G, H, L, M = r[0], r[5].strip(), r[6].strip(), r[10].strip(), r[11].strip()
        if L != "O" or not M or G:
            continue
        row = FIRST_ROW + i
        try:
            ts = get(M, fields="timestamp")["timestamp"]
            posted = dt.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
            if now - posted < DELAY:
                continue
            v = views(M)
        except Exception as e:
            print("본문 조회수 실패 1건:", type(e).__name__)
            continue
        if v is None:
            print("본문 조회수 없음 1건")
            continue
        updates.append({"range": f"G{row}", "values": [[v]]})
        msg = f"[{num}] 행 {row}: 본문 {v}"
        if not H:
            try:
                rid = my_link_reply(M, me)
                hv = views(rid) if rid else None
                if hv is not None:
                    updates.append({"range": f"H{row}", "values": [[hv]]})
                    msg += f", 댓글 {hv}"
                else:
                    msg += ", 댓글 조회수 없음"
            except Exception as e:
                msg += f", 댓글 조회수 실패: {e}"
        done += 1
    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    print(f"조회수 기록 {done}건")


if __name__ == "__main__":
    sys.exit(main())
