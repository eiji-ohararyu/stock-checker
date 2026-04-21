import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import re

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

# 検証ターゲット
DEBUG_CODE = "4768"
DEBUG_NAME = "大塚商会"
DEBUG_SECTOR = "情報・通信業"

def calculate_indicators(df):
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if len(df) < 30: return None
    
    # 移動平均算出
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    # 高値判定（前日までの10日間高値）
    df['high_10d'] = pd.to_numeric(df['H'], errors='coerce').shift(1).rolling(10).max()
    # ボリンジャーバンド（20日、2σ）
    df['bbh'] = df['close'].rolling(20).mean() + (df['close'].rolling(20).std() * 2)
    return df

def run_debug_scan(full_df):
    # 大塚商会のみ抽出
    group = full_df[full_df['Code'] == f"{DEBUG_CODE}0"] # J-Quantsは末尾0の場合あり
    if group.empty:
        group = full_df[full_df['Code'] == DEBUG_CODE]
        
    df = calculate_indicators(group.copy())
    if df is None: return "データ不足のため判定不可"
    
    curr = df.iloc[-1]
    raw_s, d_l = 0, []
    
    # 1. 陽線判定
    is_yang = curr['close'] > curr['open']
    if is_yang: raw_s += 15; d_l.append("陽線(+15)")
    
    # 2. GC判定（直近3日間で、物理的に5日線が25日線を下から上に抜いた事実を確認）
    gc_found = False
    for i in range(len(df)-3, len(df)):
        p_row, c_row = df.iloc[i-1], df.iloc[i]
        # 「前日は5日線 <= 25日線」かつ「当日は5日線 > 25日線」の逆転のみを抽出
        if p_row['ma5'] <= p_row['ma25'] and c_row['ma5'] > c_row['ma25']:
            gc_found = True; break
    if gc_found: raw_s += 20; d_l.append("GC初動(+20)")
    
    # 3. MA25上昇判定
    if df['ma25'].diff().iloc[-3:].min() > 0: raw_s += 25; d_l.append("MA25上昇(+25)")
    
    # 4. 高値突破
    if curr['close'] > curr['high_10d']: raw_s += 20; d_l.append("高値突破(+20)")
    
    # 5. 出来高加点（指定配点による足し算）
    vol_score = 0
    if len(df) >= 15:
        base_vol = df['volume'].iloc[-8:-3].mean()
        vol_ratio = curr['volume'] / base_vol if base_vol > 0 else 1.0
        
        if is_yang:
            if vol_ratio >= 5.0:   vol_score = 70; d_l.append(f"出来高x{vol_ratio:.2f}(+70)")
            elif vol_ratio >= 3.0: vol_score = 50; d_l.append(f"出来高x{vol_ratio:.2f}(+50)")
            elif vol_ratio >= 2.0: vol_score = 30; d_l.append(f"出来高x{vol_ratio:.2f}(+30)")
            elif vol_ratio >= 1.5: vol_score = 15; d_l.append(f"出来高x{vol_ratio:.2f}(+15)")
            
    final_score = raw_s + vol_score
    
    # 6. 過熱警戒（ボリンジャーバンド上抜け）
    if curr['close'] > curr['bbh']:
        final_score = int(final_score * 0.7)
        d_l.append("過熱警戒")
        
    return f"{DEBUG_CODE} {DEBUG_NAME} ({DEBUG_SECTOR})\n{curr['close']:.1f}円 【{final_score}点】\n" + "・".join(d_l)

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 価格データ取得（大塚商会ピンポイント）
    all_prices = []
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d, "code": DEBUG_CODE})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data: all_prices.extend(data)
            
    if all_prices:
        full_df = pd.DataFrame(all_prices).sort_values(['Code', 'Date'])
        today = datetime.now().strftime('%Y.%m.%d')
        
        res_text = run_debug_scan(full_df)
        
        msg = f"{today} デバッグレポート(大塚商会)\n調査対象：{DEBUG_CODE} {DEBUG_NAME}\nデータ取得日数：40日\n\n【判定結果】\n\n{res_text}\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/"
        
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
