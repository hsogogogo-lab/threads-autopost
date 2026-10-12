# threads-autopost

스레드 리스트 시트에서 `예약 YY.MM.DD HH:MM` 상태인 글을 Threads에 자동 게시합니다.

- `post.py`: 30분마다 실행. 본문 게시 → 링크 댓글(광고 주제 태그) → 시트에 O, 날짜, 병합 기록
- `refresh_token.py`: 매달 Threads 토큰 갱신 후 Secret 업데이트
- 필요한 Secrets: `THREADS_TOKEN`, `THREADS_USER_ID`, `GOOGLE_SA_JSON`, `GH_PAT`
