import os
import requests
import pandas as pd

# Secrets
REFRESH_TOKEN = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def get_stock_data():
    if not REFRESH_TOKEN: return [], []
    host = "api.jquants.com"
    
    try:
        auth_url = "https://" + host + "/v1/token/auth_refresh"
        r = requests.post(auth_url, params={"refreshtoken": REFRESH_TOKEN})
        id_token = r.json().get("idToken")
        headers = {"Authorization": "Bearer " + id_token}
        
        # 銘柄情報の取得
        info_url = "https://" + host + "/v1/listed/info"
        info_res = requests.get(info_url, headers=headers)
        info_df = pd.DataFrame(info_res.json().get("info", []))
        
        # 【修正ポイント】辞書を作る前にNoneを確実に埋める
        info_df['CompanyName'] = info_df['CompanyName'].fillna("不明").astype(str)
        info_df['Sector17CodeName'] = info_df['Sector17CodeName'].fillna("-").astype(str)
        
        name_map = info_df.set_index('Code')[['CompanyName', 'Sector17CodeName']].to_dict('index')
        
        # 株価データの取得
        quote_url = "https://" + host + "/v1/prices/daily_quotes"
        r = requests.get(quote_url, headers=headers)
        df = pd.DataFrame(r.json().get("daily_quotes", []))
    except Exception as e:
        # エラー内容を詳しく表示するように変更
        print(f"DEBUG: {e}")
        return [], []

    if df.empty: return [], []

    df = df.sort_values(['Code', 'Date'])
    df['ma5'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(window=5).mean())
    df['ma25'] = df.groupby('Code')['Close'].transform(lambda x: x.rolling(window=25).mean())
    df['vol_avg'] = df.groupby('Code')['Volume'].transform(lambda x: x.rolling(window=5).mean())

    latest = df.groupby('Code').tail(2)
    
    up_list, down_list = [], []
    
    for code, group in latest.groupby('Code'):
        if len(group) < 2: continue
        prev, curr = group.iloc[0], group.iloc[1]
        
        info = name_map.get(code, {"CompanyName": "不明", "Sector17CodeName": "-"})
        name = info["CompanyName"]
        sector = info["Sector17CodeName"]
        base_info = f"{code} {name} ({sector})\n{curr['Close']}円"

        # 上昇優勢
        is_gc = (prev['ma5'] < prev['ma25']) and (curr['ma5'] > curr['ma25'])
        is_vol_spike_up = (curr['Volume'] > (curr['vol_avg'] * 2)) and (curr['Close'] > prev['Close'])
        if is_gc or is_vol_spike_up:
            reason = "【GC】" if is_gc else "【出来高増】"
            up_list.append(f"{base_info} {reason}")

        # 下落優勢
        is_dc = (prev['ma5'] > prev['ma25']) and (curr['ma5'] < prev['ma25'])
        is_crash = (curr['Volume'] > (curr['vol_avg'] * 2)) and (curr['Close'] < prev['Close'] * 0.95)
        if is_dc or is_crash:
            reason = "【デッドクロス】" if is_dc else "【急落】"
            down_list.append(f"{base_info} {reason}")

    return up_list, down_list

def notify_line(message):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + LINE_TOKEN}
    body = {"to": USER_ID, "messages": [{"type": "text", "text": message}]}
    requests.post(url, headers=headers, json=body)

if __name__ == "__main__":
    up, down = get_stock_data()
    final_msg = ""
    if up:
        final_msg += "【判定：上昇優勢】\n以下の銘柄が見つかりました：\n\n" + "\n\n".join(up[:10])
    if down:
        if final_msg: final_msg += "\n\n" + "───────────────" + "\n\n"
        final_msg += "【判定：下落優勢】\n以下の銘柄が見つかりました：\n\n" + "\n\n".join(down[:10])
    
    if final_msg:
        final_msg += "\n\n───────────────\n詳細確認（SBI証券）:\nhttps://www.sbisec.co.jp/ETGate"
        notify_line(final_msg)
    else:
        print("シグナルなし")
