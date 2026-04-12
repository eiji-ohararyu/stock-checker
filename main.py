import os
import requests
import pandas as pd
import sys

# Secretsから読み込み
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN")
CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
USER_ID = os.getenv("LINE_USER_ID")

def get_stock_data():
    # トークンが読み込めているかチェック（最重要）
    if not REFRESH_TOKEN:
        print("CRITICAL ERROR: JQUANTS_REFRESH_TOKEN is EMPTY")
        return pd.DataFrame()

    # 1. ログイン認証
    auth_url = "[https://api.jquants.com/v1/token/auth_refresh](https://api.jquants.com/v1/token/auth_refresh)"
    # トークンをURLに直接書かず、paramsとして渡す
    r = requests.post(auth_url, params={"refreshtoken": REFRESH_TOKEN})
    
    if r.status_code != 200:
        print(f"ログイン失敗。ステータスコード: {r.status_code}")
        print(f"エラー内容: {r.text}")
        return pd.DataFrame()

    data = r.json()
    id_token = data.get("idToken")
    if not id_token:
        print(f"idTokenが取得できませんでした。データ: {data}")
        return pd.DataFrame()

    headers = {"Authorization": f"Bearer {id_token}"}
    
    # 2. 株価取得
    r = requests.get("[https://api.jquants.com/v1/prices/daily_quotes](https://api.jquants.com/v1/prices/daily_quotes)", headers=headers)
    
    if r.status_code != 200:
        print(f"株価取得失敗。ステータスコード: {r.status_code}")
        return pd.DataFrame()

    # データ変換
    res_json = r.json()
    if "daily_quotes" not in res_json:
        print("株価データが含まれていません。")
        return pd.DataFrame()

    df = pd.DataFrame(res_json["daily_quotes"])
    # 4万円以下で買える銘柄（100株単位を考慮せず、単価のみで判定）
    target = df[df['Close'] < 40000].sort_values('Close', ascending=False)
    return target.head(5)

def notify_line(message):
    url = "[https://api.line.me/v2/bot/message/push](https://api.line.me/v2/bot/message/push)"
    headers = {
        "Content-Type": "application/json", 
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"
    }
    body = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=body)

if __name__ == "__main__":
    stocks = get_stock_data()
    if not stocks.empty:
        stock_list = "\n".join([f"コード:{row['Code']} 価格:{row['Close']}円" for _, row in stocks.iterrows()])
        msg = f"【株価通知くん】\nお宝株スキャン完了！\n\n{stock_list}"
        notify_line(msg)
    else:
        print("通知対象の銘柄がなかったか、エラーにより取得できませんでした。")
