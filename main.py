import os
import requests

# Secretsの取得
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def notify_line(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]}
    requests.post(url, headers=headers, json=payload)

def test_endpoints():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    
    # 切り分け対象のURLリスト
    targets = [
        "/equities/bars/daily",
        "/prices/daily_quotes",
        "/equities/daily_quotes"
    ]
    
    results = []
    
    for path in targets:
        full_url = host + path
        try:
            r = requests.get(full_url, headers=headers)
            status = r.status_code
            # 成功(200)ならデータ件数を、失敗ならエラー内容を記録
            if status == 200:
                data = r.json()
                # 辞書のキー一覧を取得してデータ構造を確認
                keys = list(data.keys())
                results.append(f"✅ SUCCESS: {path}\nKeys: {keys}")
            else:
                results.append(f"❌ FAILED ({status}): {path}")
        except Exception as e:
            results.append(f"⚠️ ERROR: {path}\n{str(e)}")

    return "\n\n".join(results)

if __name__ == "__main__":
    report = test_endpoints()
    notify_line(f"【通信テスト結果】\n\n{report}")
