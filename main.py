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
    if len(df) < 30: return df
    
    # 移動平均
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    
    # 出来高平均（短期2日 / 中期10日）
    df['vol_avg_short'] = df['volume'].rolling(2).mean()
    df['vol_avg_mid'] = df['volume'].rolling(10).mean()
    
    # 直近10日間の最高値（上抜け判定用）
    df['high_10d'] = df['high'].shift(1).rolling(10).max()
    
    # ボリンジャーバンド（過熱判定用）
    df['bbm'] = df['close'].rolling(20).mean()
    df['std'] = df['close'].rolling(20).std()
    df['bbh'] = df['bbm'] + (df['std'] * 2) # +2σ
    
    return df

def detect_up_patterns(prices):
    """形状検知ロジック（谷の深さ3%・間隔7日以上）"""
    res = {'score': 0, 'desc': []}
    if len(prices) < 40: return res
    
    t_idx = argrelextrema(prices, np.less_equal, order=5)[0]
    p_idx_all = argrelextrema(prices, np.greater_equal, order=5)[0]
    
    valid_troughs = []
    for i in t_idx:
        lookback = prices[max(0, i-10):i]
        if len(lookback) > 0 and (lookback.max() - prices[i]) / lookback.max() > 0.03:
            valid_troughs.append(i)

    # ダブルボトム
    if len(valid_troughs) >= 2:
        idx1, idx2 = valid_troughs[-2], valid_troughs[-1]
        if (idx2 - idx1) >= 7 and abs(prices[idx1] - prices[idx2]) / prices[idx1] < 0.02:
            res['score'] += 40; res['desc'].append("ダブルボトム(+40)")

    # ソーサーボトム
    p_win = prices[-20:]
    c_min_idx = np.argmin(p_win)
    if 5 <= c_min_idx <= 15 and p_win[0] > p_win[c_min_idx] * 1.04 and p_win[-1] > p_win[c_min_idx] * 1.02:
        res['score'] += 35; res['desc'].append("ソーサーボトム(+35)")

    # 三角保合い
    if len(p_idx_all) >= 2 and len(valid_troughs) >= 2:
        if prices[p_idx_all[-2]] > prices[p_idx_all[-1]] and prices[valid_troughs[-2]] < prices[valid_troughs[-1]]:
            res['score'] += 25; res['desc'].append("三角保合い(+25)")
    return res

def get_stock_report():
    """データ収集とスコアリング"""
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # JPXから銘柄名簿を取得
    name_map = {}
    try:
        csv_res = requests.get("https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv", timeout=10)
        csv_res.encoding = 'shift_jis'
        csv_df = pd.read_csv(io.StringIO(csv_res.text))
        for _, row in csv_df.iterrows():
            code = normalize_code(row['コード'])
            name_map[code] = {"name": str(row['銘柄名']).strip(), "sector": str(row['17業種区分']).strip()}
    except: pass

    # 株価データ取得
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
        
        # 必須条件：データ不足または流動性不足（10万株未満）の足切り
        if df is None or df['volume'].iloc[-1] < 100000: continue
        
        curr = df.iloc[-1]
        raw_s, d_l = 0, []
        
        # 陽線判定
        is_yang = curr['close'] > curr['open']
        # 直近高値の上抜け判定
        is_breakout = curr['close'] > curr['high_10d']
        
        # --- 1. GC判定 ---
        gc_detected = False
        for i in range(len(df)-3, len(df)):
            if i <= 0: continue
            # MA5がMA25を上抜けた瞬間、かつMA25が下げ止まっている
            if df['ma5'].iloc[i-1] <= df['ma25'].iloc[i-1] and df['ma5'].iloc[i] > df['ma25'].iloc[i]:
                # 中期線が下げ止まっており、かつ株価が中期線の上にあること
                if df['ma25'].iloc[i] >= df['ma25'].iloc[i-1] and curr['close'] > df['ma25'].iloc[i]:
                    gc_detected = True; break
        if gc_detected: raw_s += 25; d_l.append("GC初動(+25)")

        # --- 2. 補助指標 ---
        # 25日線のトレンド継続性（3日連続上向き）
        if df['ma25'].diff().iloc[-3:].min() >= 0:
            raw_s += 15; d_l.append("25日線トレンド安定(+15)")
        # 急騰
        change = ((curr['close'] - df['close'].iloc[-2]) / df['close'].iloc[-2]) * 100 if df['close'].iloc[-2] > 0 else 0
        if change > 3: raw_s += 15; d_l.append(f"急騰 {change:.1f}%(+15)")
        
        # --- 3. 形状加点 ---
        p = detect_up_patterns(df['close'].values)
        raw_s += p['score']; d_l.extend(p['desc'])
        
        # --- 4. 出来高倍率（信頼度乗算） ---
        # 直近2日平均 / それ以前の10日平均
        base_vol = df['vol_avg_mid'].iloc[-3] if len(df) > 12 else 1.0
        vol_ratio = curr['vol_avg_short'] / base_vol if base_vol > 0 else 1.0
        
        multiplier = 1.0
        # 陽線かつ（上抜け or GC）の場合のみ出来高倍率を適用
        if is_yang and (is_breakout or gc_detected):
            if vol_ratio >= 3.0: multiplier = 3.0
            elif vol_ratio >= 2.0: multiplier = 2.0
            
            if is_breakout: d_l.append("高値上抜け(適用)")
        else:
            if vol_ratio >= 2.0: d_l.append("出来高増(条件未達成により無効)")
        
        # 下落トレンドでの出来高増（逆行）をデバフ
        if curr['close'] < curr['ma25'] and multiplier > 1.0:
            multiplier = 1.0
            d_l.append("下落中の出来高増(除外)")

        # 過熱警戒デバフ（+2σ超えで倍率減衰）
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
