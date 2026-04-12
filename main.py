import os
import requests
import pandas as pd

# Secretsから読み込み
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")

def get_stock_data():
    if not REFRESH_TOKEN:
        print("ERROR: JQUANTS_REFRESH_TOKEN is empty.")
        return pd.DataFrame()

    # URLを直接1行で書き、余計な文字が入らないようにします
    auth_url = "[https://api.jquants.com/v1/token/auth_refresh](https://api.jquants.com/v1/token/auth_refresh)"
    
    # トークンはparamsとして渡す（これが一番安全）
    try:
        r = requests.post(auth_url, params={"refreshtoken": REFRESH_TOKEN.strip()})
        r.raise_for_status()
    except Exception as e:
        print(f"Auth request failed: {e}")
        return pd.DataFrame()

    data = r.json()
    id_token = data.get("idToken")
    if not id_token:
        print(f"idToken not found in response: {data}")
        return pd.DataFrame()

    headers = {"Authorization": f"Bearer {id_token}"}
    
    # 株価取得
    quote_url = "[https://api.jquants.com/v1/prices/daily_quotes](https://api.jquants.com/v1/prices/daily_quotes)"
    try:
        r = requests.get(quote_url, headers=headers)
        r.raise_for_status()
    except Exception as e:
        print(f"Quote request failed: {e}")
        return pd.DataFrame()

    df = pd.DataFrame(r.json().get("daily_quotes", []))
    if df.empty:
        return df

    # 4万円以下で買える銘柄
    target = df[df['Close'] < 40000].sort_values('Close', ascending=False)
    return target.head(5)

def notify_line(message):
    url = "[https://api.line.me/v2/bot/message/push](https://api.line.me/v2/bot/message/push)"
    headers = {
        "Content-Type": "application/json", 
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN.strip()}"
    }
    body = {"to": USER_ID.strip(), "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=body)

if __name__ == "__main__":
    stocks = get_stock_data()
    if not stocks.empty:
        stock_list = "\n".join([f"コード:{row['Code']} 価格:{row['Close']}円" for _, row in stocks.iterrows()])
        msg = f"【株価通知くん】\nお宝株スキャン完了！\n\n{stock_list}"
        notify_line(msg)
    else:
        print("通知対象の銘柄がないか、取得に失敗しました。")
