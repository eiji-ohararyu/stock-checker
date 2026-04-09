import os
import requests
import pandas as pd

REFRESH_TOKEN = os.environ["JQUANTS_REFRESH_TOKEN"]
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
USER_ID = os.environ["LINE_USER_ID"]

def get_stock_data():
    # 認証URLを最新のものに固定
    auth_url = f"[https://api.jquants.com/v1/token/auth_refresh?refreshtoken=](https://api.jquants.com/v1/token/auth_refresh?refreshtoken=){REFRESH_TOKEN}"
    r = requests.post(auth_url)
    
    # ここでエラーが起きた場合に中身を表示するように変更
    if r.status_code != 200:
        print(f"ログイン失敗。ステータスコード: {r.status_code}")
        print(f"エラー内容: {r.text}")
        return pd.DataFrame() # 空のデータを返す

    data = r.json()
    if "idToken" not in data:
        print(f"レスポンスにidTokenが含まれていません。受け取ったデータ: {data}")
        return pd.DataFrame()

    id_token = data["idToken"]
    headers = {"Authorization": f"Bearer {id_token}"}
    
    # 株価取得（日付を指定しないと最新が取れない場合があるため調整）
    r = requests.get("[https://api.jquants.com/v1/prices/daily_quotes](https://api.jquants.com/v1/prices/daily_quotes)", headers=headers)
    
    if r.status_code != 200:
        print(f"株価取得失敗。ステータスコード: {r.status_code}")
        return pd.DataFrame()

    df = pd.DataFrame(r.json()["daily_quotes"])
    # 4万円以下で買える銘柄
    target = df[df['Close'] < 40000].sort_values('Close', ascending=False)
    return target.head(5)

def notify_line(message):
    url = "[https://api.line.me/v2/bot/message/push](https://api.line.me/v2/bot/message/push)"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}"}
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
