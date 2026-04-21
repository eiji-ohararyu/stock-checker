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

DEBUG_CODE = "4768"
DEBUG_NAME = "大塚商会"
DEBUG_SECTOR = "情報・通信業"

def calculate_indicators(df):
    # 日付で昇順ソート（古い順）
    df = df.sort_values('Date').reset_index(drop=True)
    
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    
    if len(df) < 30: return None
    
    # 移動平均算出
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    # 高値判定
    df['high_10d'] = pd.to_numeric(df['H'], errors='coerce').shift(1).rolling(10).max()
    # ボリンジャーバンド
    df['bbh'] = df['close'].rolling(20).mean() + (df['close'].rolling(20).std() * 2)
    return df

def run_debug_scan(full_df):
    df = calculate_indicators(full_df.copy())
    if df is None: return "データ不足", ""
    
    curr = df.iloc[-1]
    raw_s, d_l = 0, []
    
    # 1. 陽線判定
    is_yang = curr['close'] > curr['open']
    if is_yang: raw_s += 15; d_l.append("陽線(+15)")
    
    # 2. GC判定（物理的交差の事実確認）
    gc_found = False
    for i in range(len(df)-3, len(df)):
        before = df.iloc[i-1]
        after = df.iloc[i]
        if before['ma5'] <= before['ma25'] and after['ma5'] > after['ma25']:
            gc_found = True; break
    if gc_found: raw_s += 20; d_l.append("GC初動(+20)")
    
    # 3. MA25上昇判定
    if df['ma25'].diff().iloc[-3:].min() > 0: raw_s += 25; d_l.append("MA25上昇(+25)")
    
    # 4. 高値突破
    if curr['close'] > curr['high_10d']: raw_s += 20; d_l.append("高値突破(+20)")
    
    # 5. 出来高加点
    vol_score = 0
    base_vol = df['volume'].iloc[-8:-3].mean()
    vol_ratio = curr['volume'] / base_vol if base_vol > 0 else 1.0
    if is_yang:
        if vol_ratio >= 5.0: vol_score = 70; d_l.append(f"出来高x{vol_ratio:.2f}(+70)")
        elif vol_ratio >= 3.0: vol_score = 50; d_l.append(f"出来高x{vol_ratio:.2f}(+50)")
        elif vol_ratio >= 2.0: vol_score = 30; d_l.append(f"出来高x{vol_ratio:.2f}(+30)")
        elif vol_ratio >= 1.5: vol_score = 15; d_l.append(f"出来高x{vol_ratio:.2f}(+15)")
            
    final_score = raw_s + vol_score
    if curr['close'] > curr['bbh']: final_score = int(final_score * 0.7); d_l.append("過熱警戒")
    
    res_label = f"{DEBUG_CODE} {DEBUG_NAME} ({DEBUG_SECTOR})\n{curr['close']:.1f}円 【{final_score}点】\n" + "・".join(d_l)
    
    # 数値ログ作成（直近5日分）
    log_lines = []
    for i in range(len(df)-5, len(df)):
        row = df.iloc[i]
        date_str = row['Date'][5:].replace('-', '.') # MM.DD形式
        log_lines.append(f"{date_str}: 終{row['close']:.1f} (5線:{row['ma5']:.1f} / 25線:{row['ma25']:.1f})")
    
    return res_label, "\n".join(reversed(log_lines))

if __name__ == "__main__":
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    all_prices = []
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)]
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d, "code": DEBUG_CODE})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data: all_prices.extend(data)
            
    if all_prices:
        full_df = pd.DataFrame(all_prices)
        today = datetime.now().strftime('%Y.%m.%d')
        res_text, num_log = run_debug_scan(full_df)
        
        msg = f"{today} デバッグレポート(大塚商会)\n調査対象：{DEBUG_CODE} {DEBUG_NAME}\nデータ取得日数：40日\n\n【判定結果】\n\n{res_text}\n\n【数値ログ（直近5日）】\n{num_log}\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/"
        requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
