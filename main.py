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
        
        info_url = "https://" + host + "/v1/listed/info"
        info_res = requests.get(info_url, headers=headers)
        info_df = pd.DataFrame(info_res.json().get("info", []))
        # ここで文字列型に強制変換してNoneを回避
        info_df['CompanyName'] = info_df['CompanyName'].fillna("不明")
        info_df['Sector17CodeName'] = info_df['Sector17CodeName'].fillna("-")
        name_map = info_df.set_index('Code')[['CompanyName', 'Sector17CodeName']].to_dict('index')
        
        quote_url = "https://" + host + "/v1/prices/daily_quotes"
        r = requests.get(quote_url, headers=headers)
        df = pd.DataFrame(r.json().get("daily_quotes", []))
    except Exception as e:
        print(f"Error during API call: {e}")
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

        is_gc = (prev['ma5'] < prev['ma25']) and (curr['ma5'] > curr['ma25'])
        is_vol_spike_up = (curr['Volume'] > (curr['vol_avg'] * 2)) and (curr['Close'] > prev['Close'])
        if is_gc or is_vol_spike_up:
            reason = "【GC】" if is_gc else "【出来高増】"
            up_list.append(f"{base_info} {reason}")

        is_dc = (prev['ma5'] > prev['ma25']) and (curr['ma5'] < prev['ma25'])
        is_crash = (curr['Volume'] > (curr['vol_avg'] * 2)) and (curr['Close'] < prev['Close'] * 0.95)
        if is_dc or is_crash:
            reason = "【デッドクロス】" if is_dc else "【急落】"
            down_list.append(f"{base_info} {reason}")

    return up_list, down_list

def notify_line(message):
    url = "[https://api.line.me/v2/bot/message/push](https://api.line.me/v2/bot/message/push)"
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
        final_msg += "\n\n───────────────\n詳細確認（SBI証券）:\n[https://www.sbisec.co.jp/ETGate](https://www.sbisec.co.jp/ETGate)"
        notify_line(final_msg)
    else:
        print("シグナルなし")
