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
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['high'] = pd.to_numeric(df['H'], errors='coerce')
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if len(df) < 40: return None
    
    # 移動平均
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    
    # 出来高平均（短期2日 / 中期10日）
    df['vol_avg_short'] = df['volume'].rolling(2).mean()
    df['vol_avg_mid'] = df['volume'].rolling(10).mean()
    
    # 各種節目判定用
    df['high_10d'] = df['high'].shift(1).rolling(10).max()
    df['high_20d'] = df['high'].shift(1).rolling(20).max()
    
    # ボリンジャーバンド
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbh'] = df['bbm'] + (df['std'] * 2)
    
    return df

def detect_bottom_pattern(prices):
    """ダブルボトムのみ検知（信頼度重視）"""
    res = {'score': 0, 'desc': []}
    t_idx = argrelextrema(prices, np.less_equal, order=5)[0]
    
    valid_troughs = []
    for i in t_idx:
        lookback = prices[max(0, i-10):i]
        if len(lookback) > 0 and (lookback.max() - prices[i]) / lookback.max() > 0.03:
            valid_troughs.append(i)

    if len(valid_troughs) >= 2:
        idx1, idx2 = valid_troughs[-2], valid_troughs[-1]
        # 谷の間隔が7日以上、かつ谷の深さが2%以内の近似
        if (idx2 - idx1) >= 7 and abs(prices[idx1] - prices[idx2]) / prices[idx1] < 0.02:
            res['score'] += 20; res['desc'].append("ダブルボトム(+20)")
    return res

def get_stock_report():
    """データ収集と再設計スコアリング"""
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    name_map = {}
    try:
        csv_res = requests.get("https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv", timeout=10)
        csv_res.encoding = 'shift_jis'
        csv_df = pd.read_csv(io.StringIO(csv_res.text))
        for _, row in csv_df.iterrows():
            code = normalize_code(row['コード'])
            name_map[code] = {"name": str(row['銘柄名']).strip(), "sector": str(row['17業種区分']).strip()}
    except: pass

    all_prices, success_days = [], 0
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data: all_prices.extend(data); success_days += 1
    
    if not all_prices: return success_days, []
    
    full_df = pd.DataFrame(all_prices).sort_values(['Code', 'Date'])
    up_res = []
    
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        info = name_map.get(s_code, {"name": "不明", "sector": "不明"})
        df = calculate_indicators(group.copy())
        
        if df is None or df['volume'].iloc[-1] < 100000: continue
        
        curr = df.iloc[-1]
        raw_s, d_l = 0, []
        
        # 1. 陽線判定（買いの意志）
        is_yang = curr['close'] > curr['open']
        if is_yang: raw_s += 15; d_l.append("実体陽線(+15)")
        
        # 2. GC判定
        gc_detected = False
        for i in range(len(df)-3, len(df)):
            if i <= 0: continue
            if df['ma5'].iloc[i-1] <= df['ma25'].iloc[i-1] and df['ma5'].iloc[i] > df['ma25'].iloc[i]:
                if df['ma25'].iloc[i] >= df['ma25'].iloc[i-1] and curr['close'] > df['ma25'].iloc[i]:
                    gc_detected = True; break
        if gc_detected: raw_s += 20; d_l.append("GC初動(+20)")

        # 3. MA25右肩上がり（トレンド確定：直近3日連続上昇）
        if df['ma25'].diff().iloc[-3:].min() > 0:
            raw_s += 25; d_l.append("MA25上昇継続(+25)")
            
        # 4. 高値上抜け（節目突破）
        is_breakout = curr['close'] > curr['high_10d']
        if is_breakout: raw_s += 20; d_l.append("高値上抜け(+20)")
        
        # 5. 形状加点（ダブルボトムのみ）
        p = detect_bottom_pattern(df['close'].values)
        raw_s += p['score']; d_l.extend(p['desc'])
        
        # 6. 抵抗近接デバフ（上の壁）
        if curr['close'] * 1.02 > curr['high_20d']:
            raw_s -= 30; d_l.append("抵抗近接(-30)")

        # --- 出来高倍率（信頼度乗算） ---
        multiplier = 1.0
        if len(df) >= 13:
            base_vol = df['vol_avg_mid'].iloc[-3]
            vol_ratio = curr['vol_avg_short'] / base_vol if base_vol > 0 else 1.0
            
            # 陽線 かつ（上抜け or GC）の場合のみ倍率適用
            if is_yang and (is_breakout or gc_detected):
                if vol_ratio >= 3.0: multiplier = 3.0
                elif vol_ratio >= 2.0: multiplier = 2.0
            else:
                if vol_ratio >= 2.0: d_l.append("出来高増(条件未達成により無効)")
        
        # 必須条件デバフ
        if curr['close'] < curr['ma25'] and multiplier > 1.0:
            multiplier = 1.0
            d_l.append("下落中につき倍率除外")

        if curr['close'] > curr['bbh'] and multiplier > 1.0:
            multiplier -= 0.5; d_l.append("過熱警戒(降格)")
        
        final_s = int(raw_s * multiplier)
        if final_s >= 50:
            if multiplier > 1.0: d_l.append(f"出来高倍率 x{multiplier}")
            up_res.append((final_s, f"{s_code} {info['name']} ({info['sector']})\n{int(curr['close'])}円 【{final_s}点】\n" + "・".join(d_l)))
            
    return success_days, [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    count, up = get_stock_report()
    if up:
        today = datetime.now().strftime('%Y.%m.%d')
        msg = f"{today}　株価評価レポート\n\n【判定：上昇優勢 TOP10】\n\n" + "\n\n".join(up) + "\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/"
        requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, json={"to": USER_ID, "messages": [{"type": "text", "text": msg[:5000]}]})
