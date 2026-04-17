import os
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import io
import re
from scipy.signal import argrelextrema

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

# --- インデックス統合リスト（TOPIX100 + 日経225 + JPXプライム150） ---
# 重複を排除し、主要な大型・優良株をすべて網羅
STOCKS_LIST = {
    "1332": "ニッスイ", "1605": "INPEX", "1721": "コムシスHD", "1801": "大成建", "1802": "大林組",
    "1803": "清水建", "1808": "長谷工", "1812": "鹿島", "1925": "大和ハウス", "1928": "積水ハウス",
    "1963": "日揮HD", "2002": "日清粉G", "2267": "ヤクルト", "2269": "明治HD", "2282": "日本ハム",
    "2413": "エムスリー", "2433": "博報堂DY", "2501": "サッポロ", "2502": "アサヒ", "2503": "キリンHD",
    "2531": "宝HD", "2768": "双日", "2801": "キッコーマン", "2802": "味の素", "2871": "ニチレイ",
    "2914": "JT", "3088": "マツキヨココ", "3092": "ZOZO", "3099": "三越伊勢丹", "3101": "東洋紡",
    "3103": "ユニチカ", "3105": "日清紡HD", "3289": "東急不動HD", "3382": "セブン＆アイ", "3401": "帝人",
    "3402": "東レ", "3405": "クラレ", "3407": "旭化成", "3436": "SUMCO", "3659": "ネクソン",
    "3861": "王子HD", "3863": "日本製紙", "3923": "ラクス", "4004": "レゾナック", "4005": "住友化学",
    "4021": "日産化学", "4042": "東ソー", "4043": "トクヤマ", "4061": "デンカ", "4063": "信越化",
    "4151": "協和キリン", "4183": "三井化学", "4185": "JSR", "4188": "三菱ケミカル", "4208": "UBE",
    "4307": "野村総合", "4324": "電通グループ", "4385": "メルカリ", "4452": "花王", "4502": "武田薬",
    "4503": "アステラス", "4506": "住友ファーマ", "4507": "塩野義", "4519": "中外薬", "4523": "エーザイ",
    "4527": "ロート", "4528": "小野薬", "4543": "テルモ", "4544": "H.U.G", "4568": "第一三共",
    "4578": "大塚HD", "4587": "ペプチドリーム", "4661": "オリエンタルランド", "4689": "LINEヤフー", "4704": "トレンド",
    "4732": "USS", "4751": "サイバーエージェント", "4755": "楽天グループ", "4768": "大塚商会", "4887": "サワイG",
    "4901": "富士フイルム", "4902": "コニカミノルタ", "4911": "資生堂", "5019": "出光興産", "5020": "ＥＮＥＯＳ",
    "5101": "横浜ゴム", "5108": "ブリヂストン", "5201": "AGC", "5233": "太平洋セメ", "5301": "東海カーボン",
    "5332": "TOTO", "5333": "日本ガイシ", "5401": "日本製鉄", "5406": "神戸鋼", "5411": "JFE",
    "5541": "大平洋金属", "5703": "日本軽金属HD", "5706": "三井金属", "5707": "東邦亜鉛", "5711": "三菱マテリアル",
    "5713": "住友鉱", "5714": "DOWA", "5801": "古河電", "5802": "住友電", "5803": "フジクラ",
    "5831": "しずおかFG", "5901": "東洋製罐G", "6005": "三浦工業", "6098": "リクルート", "6103": "オークマ",
    "6113": "アマダ", "6141": "DMG森精機", "6146": "ディスコ", "6178": "日本郵政", "6201": "豊田織機",
    "6273": "ＳＭＣ", "6301": "コマツ", "6302": "住友重", "6305": "日立建機", "6326": "クボタ",
    "6361": "荏原", "6367": "ダイキン", "6448": "ブラザー", "6471": "日本精工", "6472": "NTN",
    "6473": "ジェイテクト", "6479": "ミネベアミツミ", "6501": "日立", "6503": "三菱電", "6504": "富士電機",
    "6506": "安川電", "6526": "ソシオネクスト", "6594": "ニデック", "6645": "オムロン", "6674": "ＧＳユアサ",
    "6701": "NEC", "6702": "富士通", "6723": "ルネサス", "6724": "エプソン", "6752": "パナソニック",
    "6753": "シャープ", "6758": "ソニーG", "6762": "TDK", "6841": "横河電", "6857": "アドバンテスト",
    "6861": "キーエンス", "6869": "シスメックス", "6902": "デンソー", "6920": "レーザーテック", "6952": "カシオ",
    "6954": "ファナック", "6971": "京セラ", "6976": "太陽誘電", "6981": "村田製", "6988": "日東電工",
    "7003": "三井E&S", "7011": "三菱重", "7012": "川崎重", "7013": "IHI", "7182": "ゆうちょ銀行",
    "7186": "コンコルディア", "7201": "日産自", "7202": "いすゞ", "7203": "トヨタ", "7205": "日野自",
    "7211": "三菱自", "7261": "マツダ", "7267": "ホンダ", "7269": "スズキ", "7270": "ＳＵＢＡＲＵ",
    "7272": "ヤマハ発", "7309": "シマノ", "7532": "パンパシHD", "7731": "ニコン", "7733": "オリンパス",
    "7735": "スクリーン", "7741": "ＨＯＹＡ", "7751": "キヤノン", "7752": "リコー", "7832": "バンナムHD",
    "7911": "凸版印刷", "7912": "大日本印刷", "7951": "ヤマハ", "7956": "ピジョン", "7974": "任天堂",
    "8001": "伊藤忠", "8002": "丸紅", "8015": "豊田通商", "8031": "三井物", "8035": "東エレク",
    "8053": "住友商", "8056": "BIPROGY", "8058": "三菱商", "8113": "ユニチャーム", "8233": "高島屋",
    "8252": "丸井グループ", "8253": "クレディセゾン", "8267": "イオン", "8304": "あおぞら銀", "8306": "三菱UFJ",
    "8308": "りそなHD", "8309": "三井住友トラ", "8316": "三井住友FG", "8331": "千葉銀", "8354": "ふくおかFG",
    "8411": "みずほFG", "8473": "SBI", "8591": "オリックス", "8601": "大和証券G", "8604": "野村HD",
    "8630": "ＳＯＭＰＯ", "8697": "日本取引所", "8725": "ＭＳ＆ＡＤ", "8750": "第一生命HD", "8766": "東京海上",
    "8801": "三井不動", "8802": "三菱地所", "8804": "東京建物", "8830": "住友不動", "9001": "東武",
    "9005": "東急", "9007": "小田急", "9008": "京王", "9009": "京成", "9020": "JR東日本",
    "9021": "JR西日本", "9022": "JR東海", "9064": "ヤマトHD", "9101": "日本郵船", "9104": "商船三井",
    "9107": "川崎汽", "9143": "ＳＧホールディングス", "9201": "JAL", "9202": "ANA", "9432": "NTT",
    "9433": "KDDI", "9434": "ソフトバンク", "9501": "東電HD", "9502": "中部電", "9503": "関西電",
    "9531": "東京ガス", "9532": "大阪ガス", "9602": "東宝", "9613": "NTTデータ", "9684": "スクエニHD",
    "9697": "カプコン", "9733": "ナガセ", "9735": "セコム", "9766": "コナミG", "9843": "ニトリHD",
    "9983": "ファストリ", "9984": "ソフトバンクG"
}

def normalize_code(raw_code):
    s = str(raw_code).strip()
    m = re.search(r'\d{4}', s)
    return m.group(0) if m else s.zfill(4)[:4]

def calculate_indicators(df):
    df['open'] = pd.to_numeric(df['O'], errors='coerce')
    df['high'] = pd.to_numeric(df['H'], errors='coerce')
    df['close'] = pd.to_numeric(df.get('AdjustmentClose', df['C']), errors='coerce')
    df['volume'] = pd.to_numeric(df['Vo'], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)
    if len(df) < 40: return None
    
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma25'] = df['close'].rolling(25).mean()
    df['vol_avg_short'] = df['volume'].rolling(2).mean() 
    df['vol_avg_mid'] = df['volume'].rolling(10).mean()
    df['high_10d'] = df['high'].shift(1).rolling(10).max()
    
    df['std'] = df['close'].rolling(20).std()
    df['bbh'] = df['close'].rolling(20).mean() + (df['std'] * 2)
    return df

def detect_bottom_pattern(prices):
    res = {'score': 0, 'desc': []}
    t_idx = argrelextrema(prices, np.less_equal, order=5)[0]
    valid_troughs = []
    for i in t_idx:
        lookback = prices[max(0, i-10):i]
        if len(lookback) > 0 and (lookback.max() - prices[i]) / lookback.max() > 0.03:
            valid_troughs.append(i)
    if len(valid_troughs) >= 2:
        idx1, idx2 = valid_troughs[-2], valid_troughs[-1]
        if (idx2 - idx1) >= 7 and abs(prices[idx1] - prices[idx2]) / prices[idx1] < 0.02:
            res['score'] += 20; res['desc'].append("ダブルボトム(+20)")
    return res

def get_stock_report():
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    all_prices = []
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(60)]
    
    for d in reversed(dates):
        r = requests.get(f"{host}/equities/bars/daily", headers=headers, params={"date": d})
        if r.status_code == 200:
            data = r.json().get("data", [])
            if data: all_prices.extend(data)
    
    if not all_prices: return 0, []
    full_df = pd.DataFrame(all_prices).sort_values(['Code', 'Date'])
    up_res = []
    
    for code, group in full_df.groupby('Code'):
        s_code = normalize_code(code)
        if s_code not in STOCKS_LIST: continue
            
        df = calculate_indicators(group.copy())
        if df is None: continue
        
        curr = df.iloc[-1]
        raw_s, d_l = 0, []
        
        # 判定：陽線
        is_yang = curr['close'] > curr['open']
        if is_yang: raw_s += 15; d_l.append("陽線(+15)")
        
        # 判定：GC（5日線が25日線を上抜け）
        gc_detected = False
        for i in range(len(df)-3, len(df)):
            if i <= 0: continue
            if df['ma5'].iloc[i-1] <= df['ma25'].iloc[i-1] and df['ma5'].iloc[i] > df['ma25'].iloc[i]:
                if df['ma25'].iloc[i] >= df['ma25'].iloc[i-1]:
                    gc_detected = True; break
        if gc_detected: raw_s += 20; d_l.append("GC初動(+20)")

        # 判定：トレンド/高値突破
        if df['ma25'].diff().iloc[-3:].min() > 0:
            raw_s += 25; d_l.append("MA25上昇(+25)")
        if curr['close'] > curr['high_10d']:
            raw_s += 20; d_l.append("高値突破(+20)")

        # 判定：ダブルボトム
        p = detect_bottom_pattern(df['close'].values)
        raw_s += p['score']; d_l.extend(p['desc'])

        # 判定：出来高倍率（直近2日平均）
        multiplier = 1.0
        if len(df) >= 13:
            base_vol = df['vol_avg_mid'].iloc[-3]
            vol_ratio = curr['vol_avg_short'] / base_vol if base_vol > 0 else 1.0
            if is_yang:
                if vol_ratio >= 2.0: multiplier = 2.0
                elif vol_ratio >= 1.5: multiplier = 1.5
        
        if curr['close'] > curr['bbh']:
            multiplier *= 0.7; d_l.append("過熱警戒")

        final_score = int(raw_s * multiplier)
        if final_score >= 40:
            if multiplier > 1.0: d_l.append(f"出来高x{multiplier}")
            name = STOCKS_LIST.get(s_code, "不明")
            up_res.append((final_score, f"{s_code} {name}\n{int(curr['close'])}円 【{final_score}点】\n" + "・".join(d_l)))
            
    return len(up_res), [x[1] for x in sorted(up_res, key=lambda x:x[0], reverse=True)[:10]]

if __name__ == "__main__":
    count, up = get_stock_report()
    if up:
        msg = f"{datetime.now().strftime('%Y.%m.%d')} 市場主要3指数スキャン\n\n" + "\n\n".join(up)
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
