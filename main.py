import os
import requests
import pandas as pd

# Secrets
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def get_stock_data():
    if not REFRESH_TOKEN:
        print("REFRESH_TOKEN is empty")
        return pd.DataFrame()

    # URLを分割して定義し、リンク情報の混入を完全に防ぐ
    host = "api.jquants.com"
    auth_url = "https://" + host + "/v1/token/auth_refresh"
    
    try:
        r = requests.post(auth_url, params={"refreshtoken": REFRESH_TOKEN})
        r.raise_for_status()
        id_token = r.json().get("idToken")
    except Exception as e:
        print(f"Auth failed: {e}")
        return pd.DataFrame()

    quote_url = "https://" + host + "/v1/prices/daily_quotes"
    headers = {"Authorization": "Bearer " + id_token}
    
    try:
        r = requests.get(quote_url, headers=headers)
        r.raise_for_status()
        df = pd.DataFrame(r.json().get("daily_quotes", []))
    except Exception as e:
        print(f"Quote failed: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    # アルゴリズム（仮）：1株400円以下
    target = df[(df['Close'] <= 400) & (df['Close'] > 0)]
    return target.sort_values('Close', ascending=False).head(5)

def notify_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + LINE_TOKEN
    }
    body = {
        "to": USER_ID,
        "messages": [{"type": "text", "text": message}]
    }
    requests.post(url, headers=headers, json=body)

if __name__ == "__main__":
    stocks = get_stock_data()
    if not stocks.empty:
        res = "\n".join([f"{r['Code']} {r['Close']}円" for _, r in stocks.iterrows()])
        notify_line("【スキャン成功】\n" + res)
    else:
        notify_line("【スキャン失敗】条件一致なし、またはエラーです。")
