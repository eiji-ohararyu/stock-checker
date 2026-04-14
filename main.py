import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Secrets
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def calculate_indicators(df):
    df['close'] = pd.to_numeric(df['C'], errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    diff = df['close'].diff()
    up, down = diff.clip(lower=0), -diff.clip(upper=0)
    # RSI
    df['rsi'] = up.rolling(14).mean() / (up.rolling(14).mean() + down.rolling(14).mean()) * 100
    # ボリンジャーバンド
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbu'], df['bbl'] = df['bbm'] + df['std']*2, df['bbm'] - df['std']*2
    # 移動平均
    df['ma5'], df['ma25'] = df['close'].rolling(5).mean(), df['close'].rolling(25).mean()
    df['vol_avg'] = df['volume'].rolling(5).mean()
    return df

def calculate_score(df, info):
    df = calculate_indicators(df)
    if len(df) < 2: return 0, "", 0, ""
    prev, curr = df.iloc[-2], df.iloc[-1]
    u_s, d_s = 0, 0
    u_d, d_d = [], []

    # ① GC/DC (20点)
    if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']: u_s += 20; u_d.append("GC発生(+20)")
    elif prev['ma5'] > prev['ma25'] and curr['ma5'] < prev['ma25']: d_s += 20; d_d.append("DC発生(+20)")
    
    # ② BB (15点)
    if curr['close'] > curr['bbl'] and prev['close'] <= prev['bbl']: u_s += 15; u_d.append("BB反発(+15)")
    elif curr['close'] < curr['bbu'] and prev['close'] >= curr['bbu']: d_s += 15; d_d.append("BB反落(+15)")
    
    # ③ RSI (15点)
    if not np.isnan(curr['rsi']):
        if curr['rsi'] > prev['rsi'] and prev['rsi'] < 35: u_s += 15; u_d.append("RSI底打ち(+15)")
        elif curr['rsi'] < prev['rsi'] and prev['rsi'] > 65: d_s += 15; d_d.append("RSI天井(+15)")
    
    # ④ 騰落率 (15点)
    change = ((curr['close'] - prev['close']) / prev['close']) * 100 if prev['close'] > 0 else 0
    if change > 3: u_s += 15; u_d.append(f"急騰(+15)")
    elif change < -3: d_s += 15; d_d.append(f"急落(+15)")
    
    # ⑤ 出来高 (20点)
    if curr['vol_avg'] > 0 and (curr['volume'] / curr['vol_avg']) > 2:
        u_s += 20; d_s += 20; u_d.append("爆量(+20)"); d_d.append("爆量(+20)")
    
    # ⑥ 25日線 (10点)
    if curr['ma25'] > prev['ma25']: u_s += 10; u_d.append("25線上向(+10)")
    else: d_s += 10; d_d.append("25線下向(+10)")

    header = f"{info['name']} ({info['sector']})\n{curr['close']}円"
    return u_s, f"{header} 【{u_s}点】\n" + "・".join(u_d), d_s, f"{header} 【{d_s}点】\n" + "・".join(d_d)

def get_stock_data():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    name_map = {}
    
    # 1. 銘柄情報の取得 (フィルタリングなし)
    try:
        r_info = requests.get(f"{host}/equities/info", headers=headers)
        if r_info.status_code == 200:
            for item in r_info.json().get("data", []):
                code = str(item.get("Code", ""))[:4]
                name_map[code] = {
                    "name": item.get("CompanyName", "不明"),
                    "sector": item.get("Sector17CodeName", "-")
                }
    except: pass

    # 2. 過去データの収集
    all_data, success_days = [], 0
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(35)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            day_data = r.json().get("data", [])
            if day_data: all_data.extend(day_data); success_days += 1
    
    if not all_data: return "データなし", [], []
    
    # 3. 集計
    df = pd.DataFrame(all_data).sort_values(['Code', 'Date'])
    up_list, down_list = [], []
    for code, group in df.groupby('Code'):
        short_code = str(code)[:4]
        # name_mapになくても計算は続行
        info = name_map.get(short_code, {"name": "不明", "sector": "-"})
        if len(group) < 10: continue
        u_s, u_m, d_s, d_m = calculate_score(group.copy(), info)
        if u_s >= 40: up_list.append((u_s, f"{short_code} {u_m}"))
        if d_s >= 40: down_list.append((d_s, f"{short_code} {d_m}"))

    report = f"成功:{success_days}日"
    return report, [x[1] for x in sorted(up_list, reverse=True)[:10]], [x[1] for x in sorted(down_list, reverse=True)[:10]]

def notify_line(msg):
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})

if __name__ == "__main__":
    rep, up, down = get_stock_data()
    msg = f"【判定結果】{rep}\n\n"
    content = ""
    if up: content += "【総合評価：上昇期待TOP10】\n\n" + "\n\n".join(up)
    if down:
        if content: content += "\n\n" + "─" * 15 + "\n\n"
        content += "【総合評価：下落警戒TOP10】\n\n" + "\n\n".join(down)
    
    if content:
        msg += content + "\n\n" + "─" * 15 + "\n詳細確認（SBI証券）:\nhttps://www.sbisec.co.jp/ETGate"
        notify_line(msg)
    else:
        # ヒットがない場合も状況がわかるように通知
        notify_line(f"【判定結果】{rep}\n\n現在、条件に合う銘柄はありません。")
