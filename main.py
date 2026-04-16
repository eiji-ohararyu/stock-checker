import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
from scipy.signal import argrelextrema
import re

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

def normalize_code(raw_code):
    """銘柄コードを4桁に統一"""
    s = str(raw_code).strip()
    m = re.search(r'\d{4}', s)
    return m.group(0) if m else s.zfill(4)[:4]

def calculate_indicators(df):
    """テクニカル指標算出"""
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if len(df) < 25: return df
    
    # RSI
    diff = df['close'].diff()
    up, down = diff.clip(lower=0), -diff.clip(upper=0)
    df['rsi'] = up.rolling(14).mean() / (up.rolling(14).mean() + down.rolling(14).mean()) * 100
    
    # 移動平均・ボリンジャーバンド
    df['ma5'], df['ma25'] = df['close'].rolling(5).mean(), df['close'].rolling(25).mean()
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbl'] = df['bbm'] - (df['std'] * 2)
    df['vol_avg'] = df['volume'].rolling(5).mean()
    return df

def detect_up_patterns(prices):
    """形状検知ロジック"""
    res = {'score': 0, 'desc': []}
    if len(prices) < 40: return res
    
    # 山谷の検出（前後5日）
    t_idx = argrelextrema(prices, np.less_equal, order=5)[0]
    p_idx = argrelextrema(prices, np.greater_equal, order=5)[0]
    
    # 意味のある谷の抽出（直近高値から3%以上下落）
    valid_troughs = []
    for i in t_idx:
        lookback = prices[max(0, i-10):i]
        if len(lookback) > 0 and (lookback.max() - prices[i]) / lookback.max() > 0.03:
            valid_troughs.append(i)

    # ダブルボトム判定（谷の間隔7日以上）
    if len(valid_troughs) >= 2:
        idx1, idx2 = valid_troughs[-2], valid_troughs[-1]
        t1, t2 = prices[idx1], prices[idx2]
        if (idx2 - idx1) >= 7 and abs(t1 - t2) / t1 < 0.02:
            res['score'] += 50; res['desc'].append("ダブルボトム(+50)")

    # ソーサーボトム判定（20日間のU字）
    p_win = prices[-20:]
    c_min_idx = np.argmin(p_win)
    if 5 <= c_min_idx <= 15:
        c_min = p_win[c_min_idx]
        if p_win[0] > c_min * 1.04 and p_win[-1] > c_min * 1.02:
            res['score'] += 40; res['desc'].append("ソーサーボトム(+40)")

    # 三角保合い判定
    if len(p_idx) >= 2 and len(valid_troughs) >= 2:
        if prices[p_idx[-2]] > prices[p_idx[-1]] and prices[valid_troughs[-2]] < prices[valid_troughs[-1]]:
            res['score'] += 30; res['desc'].append("三角保合い(+30)")

    return res

def get_stock_report():
    """データ収集とスコアリング"""
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 名簿マスタ取得
    name_map = {}
    try:
        csv_res = requests.get("https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv", timeout=10)
        csv_res.encoding = 'shift_jis'
        csv_df = pd.read_csv(io.StringIO(csv_res.text))
        for _, row in csv_df.iterrows():
            code = normalize_code(row['コード'])
            name_map[code] = {"name": str(row['銘柄名']).strip(), "sector": str(row['17業種区分']).strip()}
    except: pass

    # 株価データ一括取得（直近60日）
    all_prices, success_days = [], 0
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data:
                all_prices.extend(data)
                success_days += 1
    
    if not all_prices: return success_days, []
    
    # 銘柄ごとにスコア計算
    full_df = pd.DataFrame(all_prices).sort_values(['Code', 'Date'])
    up_res = []
    
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        info = name_map.get(s_code, {"name": "不明", "sector": "不明"})
        
        df = calculate_indicators(group.copy())
        if len(df) < 25 or df['vol_avg'].iloc[-1] < 100000: continue
        
        prev, curr = df.iloc[-2], df.iloc[-1]
        u_s, d_l = 0, []
        
        # 指標加点
        if prev['ma5'] < prev['ma25'] and curr['ma5'] > curr['ma25']: u_s += 20; d_l.append("GC発生(+20)")
        if curr['close'] > curr['bbl'] and prev['close'] <= prev['bbl']: u_s += 15; d_l.append("BB下限反発(+15)")
        if curr['volume'] > curr['vol_avg'] * 2: u_s += 20; d_l.append("出来高2倍超(+20)")
        if curr['ma25'] > prev['ma25']: u_s += 10; d_l.append("25日線上向き(+10)")
        
        # 急騰加点
        change = ((curr['close'] - prev['close']) / prev['close']) * 100 if prev['close'] > 0 else 0
        if change > 3: u_s += 15; d_l.append(f"急騰 {change:.1f}%(+15)")
        
        # 形状加点
        p = detect_up_patterns(df['close'].values)
        u_s += p['score']
        d_l.extend(p['desc'])
        
        # TOP10選出用リストへ
        if u_s >= 50:
            msg_part = f"{s_code} {info['name']} ({info['sector']})\n{int(curr['close'])}円 【{u_s}点】\n" + "・".join(d_l)
            up_res.append((u_s, msg_part))
            
    return success_days, [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    # レポート生成・LINE通知
    count, up = get_stock_report()
    if up:
        today = datetime.now().strftime('%Y.%m.%d')
        msg = f"{today}　株価評価レポート\n（データ取得日数：{count}）\n\n"
        msg += "【判定：上昇優勢 TOP10】\n\n" + "\n\n".join(up)
        msg += "\n\n───────────────\n詳細確認（SBI証券）: https://www.sbisec.co.jp/ETGate/"
        requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})
