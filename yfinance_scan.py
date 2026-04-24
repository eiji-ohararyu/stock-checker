import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime
import yfinance as yf
import time

# --- 認証・設定 ---
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

# 主要株リスト（既存のまま）
STOCKS_DATA = {
    # ... (既存の辞書データ)
}

def send_line(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": msg}]}
    try:
        requests.post(url, headers=headers, json=payload)
    except: pass

def calculate_score(s_code, df):
    df = df.dropna(subset=['Close']).reset_index(drop=True)
    if len(df) < 75: return None
    
    close = df['Close']
    open_p = df['Open']
    high = df['High']
    vol = df['Volume']
    
    ma5 = close.rolling(5).mean()
    ma25 = close.rolling(25).mean()
    ma75 = close.rolling(75).mean()
    high_10d = high.shift(1).rolling(10).max()
    bbh = close.rolling(20).mean() + (close.rolling(20).std() * 2)
    
    c_p = close.iloc[-1]
    raw_s, labels = 0, []
    
    # 1. 陽線 (+15)
    is_yang = c_p > open_p.iloc[-1]
    if is_yang: raw_s += 15; labels.append("陽線(+15)")
    
    # 2. GC初動 (+20)
    gc = (ma5.shift(1) <= ma25.shift(1)) & (ma5 > ma25)
    if gc.iloc[-5:].any(): raw_s += 20; labels.append("GC初動(+20)")
    
    # 3. MA上昇判定 (各+10)
    ma5_up = ma5.diff().iloc[-1] > 0
    ma25_up = ma25.diff().iloc[-1] > 0
    if ma5_up: raw_s += 10; labels.append("5日線上昇(+10)")
    if ma25_up: raw_s += 10; labels.append("25日線上昇(+10)")
    
    # 4. トレンド初動 (+30)
    is_po = (ma5.iloc[-1] > ma25.iloc[-1]) and (ma25.iloc[-1] > ma75.iloc[-1])
    is_converged = ((abs(ma5.iloc[-1] - ma75.iloc[-1])) / ma75.iloc[-1]) < 0.03
    if is_po and is_converged and ma5_up and ma25_up:
        raw_s += 30; labels.append("トレンド初動(+30)")
    elif is_po:
        raw_s += 10; labels.append("上昇トレンド継続(+10)")
    elif is_converged and ma5_up and ma25_up:
        raw_s += 10; labels.append("エネルギー収束(+10)")
            
    # 5. 高値突破 (+20)
    if c_p > high_10d.iloc[-1]: raw_s += 20; labels.append("高値突破(+20)")
    
    # 6. 出来高加点 (1.5倍:+30, 3倍:+40)
    base_vol = vol.iloc[-8:-3].mean()
    vol_ratio = vol.iloc[-1] / base_vol if base_vol > 0 else 1.0
    if is_yang:
        if vol_ratio >= 3.0:
            raw_s += 40; labels.append(f"出来高x{vol_ratio:.1f}(+40)")
        elif vol_ratio >= 1.5:
            raw_s += 30; labels.append(f"出来高x{vol_ratio:.1f}(+30)")
            
    # 7. 過熱警戒減点 (-20)
    final_score = raw_s
    if c_p > bbh.iloc[-1]:
        final_score -= 20
        labels.append("過熱警戒(-20)")
    
    return (final_score, s_code, c_p, labels)

def get_ticker_info(s_code):
    """上位10銘柄に選ばれた時だけ名前とセクターをWEBから粘り強く取得"""
    # 1. 既存辞書チェック
    if s_code in STOCKS_DATA:
        return STOCKS_DATA[s_code]
    
    ticker_symbol = f"{s_code}.T"
    try:
        t = yf.Ticker(ticker_symbol)
        
        # 2. info (通常取得) を試行
        info = t.info
        name = info.get('longName') or info.get('shortName')
        sector = info.get('sector') or info.get('industry')
        
        # 3. infoが空なら fast_info (軽量取得) を試行
        if not name:
            name = t.fast_info.get('commonName') or "不明"
        if not sector:
            sector = "ETF/インデックス" if s_code.startswith("1") else "不明"
            
        return (name, sector)
    except:
        # 4. 失敗してもコードだけは返す
        return ("不明", "不明")

def generate_report(results, label_text, is_major):
    if not results: return None
    
    top_10_raw = sorted(results, key=lambda x: x[0], reverse=True)[:10]
    
    formatted_lines = []
    for score, s_code, c_p, labels in top_10_raw:
        # 名前取得の待機（API負荷軽減）
        time.sleep(0.5) 
        name, sector = get_ticker_info(s_code)
        
        label_str = "・".join(labels)
        line = f"{s_code} {name} ({sector})\n{c_p:.1f}円 【{score}点】\n{label_str}"
        formatted_lines.append(line)
        
    today = datetime.now().strftime('%Y.%m.%d')
    target_desc = '国内主要株 (TOPIX100・日経225・JPX150)' if is_major else '国内株式市場 全銘柄'
    header = f"{today} {label_text}\n調査対象：{target_desc}\nデータ取得日数：120日\n\n【判定：上昇優勢 TOP10】\n\n"
    footer = "\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/"
    return header + "\n\n".join(formatted_lines) + footer

if __name__ == "__main__":
    all_codes = [str(i) for i in range(1000, 10000)]
    major_results, all_results = [], []
    
    # ステップ1：軽量スキャン
    print("Step 1: Running Volume Filter (20d)...")
    tickers = [f"{c}.T" for c in all_codes]
    chunk_size = 500
    candidates = []
    
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        try:
            v_data = yf.download(chunk, period="20d", progress=False)['Volume']
            for t in chunk:
                try:
                    v_series = v_data[t].dropna()
                    if len(v_series) >= 8:
                        base = v_series.iloc[-8:-3].mean()
                        curr = v_series.iloc[-1]
                        if base > 0 and (curr / base) > 1.1:
                            candidates.append(t)
                except: continue
        except: continue
        time.sleep(1)
    
    major_tickers = [f"{c}.T" for c in STOCKS_DATA.keys()]
    final_targets = list(set(candidates + major_tickers))
    
    # ステップ2：精密スキャン
    print(f"Step 2: Scoring {len(final_targets)} stocks...")
    for i in range(0, len(final_targets), 100):
        chunk = final_targets[i:i + 100]
        try:
            full_data = yf.download(chunk, period="120d", group_by='ticker', progress=False)
            for t in chunk:
                s_code = t.replace(".T", "")
                try:
                    s_df = full_data[t].dropna() if len(chunk) > 1 else full_data.dropna()
                    if s_df.empty: continue
                    
                    res = calculate_score(s_code, s_df)
                    if res:
                        if s_code in STOCKS_DATA: major_results.append(res)
                        all_results.append(res)
                except: continue
        except: continue
        time.sleep(1)

    # 送信
    m_report = generate_report(major_results, "国内主要株レポート", True)
    if m_report: send_line(m_report)
    
    a_report = generate_report(all_results, "株式市場レポート", False)
    if a_report: send_line(a_report)
