import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io

# Secrets
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def normalize_code_5(code):
    """
    あらゆるコード入力を『5桁の純粋な数字文字列』に分離・固定する
    """
    try:
        # 小数点や空白を除去して整数文字列にする
        s = str(code).strip().split('.')[0]
        # 4桁（JPX形式）なら末尾に0を付けて5桁にする
        if len(s) == 4:
            return s + "0"
        # 5桁（J-Quants形式）ならそのまま
        return s
    except:
        return ""

def calculate_indicators(df):
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    diff = df['close'].diff()
    up, down = diff.clip(lower=0), -diff.clip(upper=0)
    df['rsi'] = up.rolling(14).mean() / (up.rolling(14).mean() + down.rolling(14).mean()) * 100
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbu'], df['bbl'] = df['bbm'] + (df['std']*2), df['bbm'] - (df['std']*2)
    df['ma5'], df['ma25'] = df['close'].rolling(5).mean(), df['close'].rolling(25).mean()
    df['vol_avg'] = df['volume'].rolling(5).mean()
    return df

def calculate_score(df, info, code_str):
    df = calculate_indicators(df)
    if len(df) < 2: return 0, "", 0, ""
    prev, curr = df.iloc[-2], df.iloc[-1]
    u_s, d_s = 0, 0
    u_d, d_d = [], []

    if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']: u_s += 20; u_d.append("GC発生(+20)")
    elif prev['ma5'] > prev['ma25'] and curr['ma5'] < prev['ma25']: d_s += 20; d_d.append("DC発生(+20)")
    if curr['close'] > curr['bbl'] and prev['close'] <= prev['bbl']: u_s += 15; u_d.append("BB下限反発(+15)")
    elif curr['close'] < curr['bbu'] and prev['close'] >= curr['bbu']: d_s += 15; d_d.append("BB上限反落(+15)")
    if not np.isnan(curr['rsi']):
        if curr['rsi'] > prev['rsi'] and prev['rsi'] < 35: u_s += 15; u_d.append("RSI底打ち(+15)")
        elif curr['rsi'] < prev['rsi'] and prev['rsi'] > 65: d_s += 15; d_d.append("RSI天井打ち(+15)")
    change = ((curr['close'] - prev['close']) / prev['close']) * 100 if prev['close'] > 0 else 0
    if change > 3: u_s += 15; u_d.append(f"急騰 {change:.1f}%(+15)")
    elif change < -3: d_s += 15; d_d.append(f"急落 {change:.1f}%(+15)")
    if curr['vol_avg'] > 0 and (curr['volume'] / curr['vol_avg']) > 2:
        u_s += 20; d_s += 20; u_d.append("出来高2倍超(+20)"); d_d.append("出来高2倍超(+20)")
    if curr['volume'] > prev['volume']: u_s += 5; d_s += 5
    if curr['ma25'] > prev['ma25']: u_s += 10; u_d.append("25日線上向き(+10)")
    else: d_s += 10; d_d.append("25日線下向き(+10)")

    cur_p = int(curr['close']) if not np.isnan(curr['close']) else 0
    # 表示は4桁
    header = f"{code_str[:4]} {info['name']} ({info['sector']})\n{cur_p}円"
    return u_s, f"{header} 【{u_s}点】\n" + "・".join(u_d), d_s, f"{header} 【{d_s}点】\n" + "・".join(d_d)

def get_stock_data():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    name_map = {}
    
    try:
        csv_url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv"
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'shift_jis'
        csv_df = pd.read_csv(io.StringIO(res.text))
        for _, row in csv_df.iterrows():
            # 辞書作成時に5桁に統一
            c_key = normalize_code_5(row.get('コード', ''))
            if c_key:
                name_map[c_key] = {
                    "name": str(row.get('銘柄名', '不明')).strip(),
                    "sector": str(row.get('17業種区分', '-')).strip()
                }
    except Exception as e:
        print(f"辞書作成エラー: {e}")

    all_data, success_days = [], 0
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(35)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            day_data = r.json().get("data", [])
            if day_data:
                all_data.extend(day_data)
                success_days += 1
    
    if not all_data: return "0", [], []
    df = pd.DataFrame(all_data).sort_values(['Code', 'Date'])
    up_list, down_list = [], []
    
    for code, group in df.groupby('Code'):
        if len(group) < 10: continue
        # 検索時も同じ5桁ルールで検索
        s_code_5 = normalize_code_5(code)
        info = name_map.get(s_code_5, {"name": "銘柄不明", "sector": "-"})
        
        u_s, u_m, d_s, d_m = calculate_score(group.copy(), info, s_code_5)
        if u_s > 0: up_list.append((u_s, u_m))
        if d_s > 0: down_list.append((d_s, d_m))

    return str(success_days), [x[1] for x in sorted(up_list, key=lambda x: x[0], reverse=True)[:10]], \
           [x[1] for x in sorted(down_list, key=lambda x: x[0], reverse=True)[:10]]

def notify_line(msg):
    requests.post("https://api.line.me/v2/bot/message/push", 
                  headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}, 
                  json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})

if __name__ == "__main__":
    count, up, down = get_stock_data()
    today = datetime.now().strftime("%Y.%m.%d")
    msg = f"{today}　株価評価レポート\n（データ取得日数：{count}）\n\n"
    if up: msg += "【判定：上昇優勢 TOP10】\n\n" + "\n\n".join(up)
    if down:
        if up: msg += "\n\n───────────────\n\n"
        msg += "【判定：下落優勢TOP10】\n\n" + "\n\n".join(down)
    
    if up or down:
        msg += "\n\n───────────────\n詳細確認（SBI証券）:\nhttps://www.sbisec.co.jp/ETGate/?_ControlID=WPLETmgR001Control&_PageID=WPLETmgR001Mdtl20&_DataStoreID=DSWPLETmgR001Control&_ActionID=DefaultAID&burl=iris_top&cat1=market&cat2=top&dir=tl1-top%7Ctl2-map%7Ctl5-jpn&file=index.html&getFlg=on&OutSide=on"
        notify_line(msg)
