import os
import requests
from datetime import datetime, timedelta

API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def notify_line(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]}
    requests.post(url, headers=headers, json=payload)

def debug_v2():
    host = "https://api.jquants.com/v2"
    path = "/equities/bars/daily"
    
    # 400エラー対策: 日付(date)を指定
    # 直近の営業日（昨日の日付など）を設定
    target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    headers = {"x-api-key": API_KEY}
    params = {
        "date": target_date,
        "code": "7203" # テスト用にトヨタを指定
    }

    try:
        r = requests.get(host + path, headers=headers, params=params)
        
        if r.status_code == 200:
            res = r.json()
            return f"✅ 成功!\nデータ: {str(res)[:200]}"
        else:
            return f"❌ 失敗({r.status_code})\n理由: {r.text}"
            
    except Exception as e:
        return f"⚠️ エラー: {str(e)}"

if __name__ == "__main__":
    report = debug_v2()
    notify_line(f"【V2最終切り分け】\n{report}")
