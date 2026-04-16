import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
from scipy.signal import argrelextrema

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def normalize_code(raw_code):
    """コード統一（4桁文字列）"""
    s = str(raw_code).strip()
    if s.endswith('.0'): s = s[:-2]
    if len(s) >= 4: return s[:4]
    return s.zfill(4)

def calculate_indicators(df):
    """指標算出（RSI, MA, BB, 出来高）"""
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if len(df) < 25: return df
    
    # 各種インジケータ
    diff = df['close'].diff()
    up, down = diff.clip(lower=0), -diff.clip(upper=0)
    df['rsi'] = up.rolling(14).mean() / (up.rolling(14).mean() + down.rolling(14).mean()) * 100
    df['ma5'], df['ma25'] = df['close'].rolling(5).mean(), df['close'].rolling(25).mean()
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbl'] = df['bbm'] - (df['std'] * 2)
    df['vol_avg'] = df['volume'].rolling(5).mean()
    return df

def detect_up_patterns(prices):
    """形状検知（山谷スキャン）"""
    res = {'score': 0, 'desc': []}
    if len(prices) < 30: return res
    troughs = argrelextrema(prices, np.less_equal, order=5)[0]
    peaks = argrelextrema(prices, np.greater_equal, order=5)[0]

    # ダブルボトム
    if len(troughs) >= 2:
        if abs(prices[troughs[-2]] - prices[troughs[-1]]) / prices[troughs[-2]] < 0.02:
            res['score'] += 40; res['desc'].append("ダブルボトム(+40)")
    # 逆三尊
    if len(troughs) >= 3:
        t1, t2, t3 = prices[troughs[-3]], prices[troughs[-2]], prices[troughs[-1]]
        if t2 < t1 and t2 < t3 and abs(t1 - t3) / t1 < 0.04:
            res['score'] += 50; res['desc'].append("逆三尊(+50)")
    # 三角保合い
    if len(peaks) >= 2 and len(troughs) >= 2:
        if prices[peaks[-2]] > prices[peaks[-1]] and prices[troughs[-2]] < prices[troughs[-1]]:
            res['score'] += 25; res['desc'].append("三角保合い(+25)")
    # ソーサーボトム
    p_win = prices[-20:]
    if len(p_win) == 20:
        c_min = p_win[7:13].min()
        if p_win.min() == c_min and p_win[0] > c_min and p_win[-1] > c_min:
            res['score'] += 35; res['desc'].append("ソーサーボトム(+35)")
    return res

def get_stock_report():
    """メイン処理（名簿・株価・スコア・順位）"""
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    master_dict = {}
    
    # 1. 銘柄名マスタ取得
    try:
        csv_res = requests.get("https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv", timeout=10)
        csv_res.encoding = 'shift_jis'
        csv_df = pd.read_csv(io.StringIO(csv_res.text))
        for _, row in csv_df.iterrows():
            code = normalize_code(row['コード'])
            master_dict[code] = {"name": str(row['銘柄名']).strip(), "sector": str(row['17業種区分']).strip(), "df": None}
    except: pass

    # 2. 株価データ一括取得
    all_data, success_days = [], 0
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(40)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                all_data.extend(data)
                success_days += 1
    
    if not all_data: return 0, []
    
    # 3. 銘柄コードごとに統合
    full_df = pd.DataFrame(all_data).sort_values(['Code', 'Date'])
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        if s_code in master_dict: master_dict[s_code]["df"] = group

    # 4. スコア計算
    up_res = []
    for code, data in master_dict.items():
        if data["df"] is None: continue
        df = calculate_indicators(data["df"].copy())
        
        # 流動性フィルタ
        if len(df) < 25 or df['vol_avg'].iloc[-1] < 100000: continue
        
        prev, curr = df.iloc[-2], df.iloc[-1]
        u_s, d_l = 0, []
        
        # 指標加点
        if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']: u_s += 20; d_l.append("GC発生(+20)")
        if curr['close'] > curr['bbl'] and prev['close'] <= prev['bbl']: u_s += 15; d_l.append("BB下限反発(+15)")
        if curr['volume'] > curr['vol_avg'] * 2: u_s += 20; d_l.append("出来高2倍超(+20)")
        if curr['volume'] > prev['volume']: u_s += 5
        if curr['ma25'] > prev['ma25']: u_s += 10; d_l.append("25日線上向き(+10)")
        if not np.isnan(prev['rsi']) and prev['rsi'] < 35 and curr['rsi'] > prev['rsi']: u_s += 10; d_l.append("RSI底打ち(+10)")
        
        # 急騰加点
        change = ((curr['close'] - prev['close']) / prev['close']) * 100 if prev['close'] > 0 else 0
        if change > 3: u_s += 15; d_l.append(f"急騰 {change:.1f}%(+15)")
        
        # 形状加点
        p = detect_up_patterns(df['close'].values)
        u_s += p['score']; d_l.extend(p['desc'])
        
        # 閾値判定
        if u_s >= 50:
            info = f"{code} {data['name']} ({data['sector']})\n{int(curr['close'])}円"
            up_res.append((u_s, f"{info} 【{u_s}点】\n" + "・".join(d_l)))
            
    # 上位10件
    return success_days, [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    # 実行・LINE通知
    count, up = get_stock_report()
    if up:
        today = datetime.now().strftime('%Y.%m.%d')
        msg = f"{today}　株価評価レポート\n（データ取得日数：{count}）\n\n"
        msg += "【判定：上昇優勢 TOP10】\n\n" + "\n\n".join(up)
        msg += "\n\n───────────────\n詳細確認（SBI証券）:\nhttps://www.sbisec.co.jp/ETGate/?_ControlID=WPLETmgR001Control&_PageID=WPLETmgR001Mdtl20&_DataStoreID=DSWPLETmgR001Control&_ActionID=DefaultAID&burl=iris_top&cat1=market&cat2=top&dir=tl1-top%7Ctl2-map%7Ctl5-jpn&file=index.html&getFlg=on&OutSide=on"
        requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})
