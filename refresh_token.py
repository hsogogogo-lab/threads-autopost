"""
Threads 장기 토큰(60일)을 새로 받아 GitHub Secret(THREADS_TOKEN)을 갱신한다.
매달 1일 GitHub Actions에서 실행된다. 새 토큰은 출력하지 않는다.
"""

import os
import subprocess
import sys

import requests

token = os.environ["THREADS_TOKEN"]
r = requests.get(
    "https://graph.threads.net/refresh_access_token",
    params={"grant_type": "th_refresh_token", "access_token": token},
    timeout=60,
)
if r.status_code != 200:
    print("토큰 갱신 실패:", r.status_code, r.text[:200])
    sys.exit(1)

data = r.json()
new_token = data["access_token"]
days = int(data.get("expires_in", 0)) // 86400

subprocess.run(
    ["gh", "secret", "set", "THREADS_TOKEN", "--repo", os.environ["GITHUB_REPOSITORY"]],
    input=new_token, text=True, check=True,
    env={**os.environ, "GH_TOKEN": os.environ["GH_PAT"]},
)
print(f"토큰 갱신 완료 (유효기간 약 {days}일)")
