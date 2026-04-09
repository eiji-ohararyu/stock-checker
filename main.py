import os
import requests
import pandas as pd

REFRESH_TOKEN = os.environ["JQUANTS_REFRESH_TOKEN"]
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
USER_ID = os.environ["LINE_USER_ID"]

def get_stock_data():
    r = requests.post(f"https://api.jquants.com/v1/token/auth_refresh?refreshtoken={REFRESH_TOKEN}")
    id_token = r.json()["idToken"]
    headers = {"Authorization": f"Bearer {id_token}"}
    r = requests.get("https://api.jquants.com/v1/prices/daily_quotes", headers=headers)
    df = pd.DataFrame(r.json()["daily_quotes"])
    # 4万円以下で買える銘柄
    target = df[df['Close'] < 40000].sort_values('Close', ascending=False)
    return target.head(5)

def notify_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"}
    body = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=body)

if __name__ == "__main__":
    stocks = get_stock_data()
    if not stocks.empty:
        stock_list = "\n".join([f"コード:{row['Code']} 価格:{row['Close']}円" for _, row in stocks.iterrows()])
        msg = f"【株価通知くん】\nお宝株スキャン完了！\n\n{stock_list}"
        notify_line(msg)
