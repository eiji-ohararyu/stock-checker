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

# 国内主要株リスト (TOPIX100 / 日経225 / JPX150)
STOCKS_DATA = {
    "1332": ("ニッスイ", "水産・農林業"), "1605": ("INPEX", "鉱業"), "1721": ("コムシスHD", "建設業"), "1801": ("大成建", "建設業"), "1802": ("大林組", "建設業"), "1803": ("清水建", "建設業"), "1808": ("長谷工", "建設業"), "1812": ("鹿島", "建設業"), "1925": ("大和ハウス", "建設業"), "1928": ("積水ハウス", "建設業"), "1963": ("日揮HD", "建設業"), "2002": ("日清粉G", "食料品"),
    "2267": ("ヤクルト", "食料品"), "2269": ("明治HD", "食料品"), "2282": ("日本ハム", "食料品"), "2413": ("エムスリー", "サービス業"), "2433": ("博報堂DY", "サービス業"), "2501": ("サッポロ", "食料品"), "2502": ("アサヒ", "食料品"), "2503": ("キリンHD", "食料品"), "2531": ("宝HD", "食料品"), "2768": ("双日", "卸売業"), "2801": ("キッコーマン", "食料品"), "2802": ("味の素", "食料品"),
    "2871": ("ニチレイ", "食料品"), "2914": ("JT", "食料品"), "3088": ("マツキヨココ", "小売業"), "3092": ("ZOZO", "小売業"), "3099": ("三越伊勢丹", "小売業"), "3101": ("東洋紡", "繊維製品"), "3103": ("ユニチカ", "繊維製品"), "3105": ("日清紡HD", "電気機器"), "3289": ("東急不動HD", "不動産業"), "3382": ("セブン＆アイ", "小売業"), "3401": ("帝人", "繊維製品"), "3402": ("東レ", "繊維製品"),
    "3405": ("クラレ", "化学"), "3407": ("旭化成", "化学"), "3436": ("SUMCO", "金属製品"), "3659": ("ネクソン", "情報・通信業"), "3861": ("王子HD", "パルプ・紙"), "3863": ("日本製紙", "パルプ・紙"), "3923": ("ラクス", "情報・通信業"), "4004": ("レゾナック", "化学"), "4005": ("住友化学", "化学"), "4021": ("日産化学", "化学"), "4042": ("東ソー", "化学"), "4043": ("トクヤマ", "化学"),
    "4061": ("デンカ", "化学"), "4063": ("信越化", "化学"), "4151": ("協和キリン", "医薬品"), "4183": ("三井化学", "化学"), "4185": ("JSR", "化学"), "4188": ("三菱ケミカル", "化学"), "4208": ("UBE", "化学"), "4307": ("野村総合", "情報・通信業"), "4324": ("電通グループ", "サービス業"), "4385": ("メルカリ", "情報・通信業"), "4452": ("花王", "化学"), "4502": ("武田薬", "医薬品"),
    "4503": ("アステラス", "医薬品"), "4506": ("住友ファーマ", "医薬品"), "4507": ("塩野義", "医薬品"), "4519": ("中外薬", "医薬品"), "4523": ("エーザイ", "医薬品"), "4527": ("ロート", "医薬品"), "4528": ("小野薬", "医薬品"), "4543": ("テルモ", "精密機器"), "4544": ("H.U.G", "サービス業"), "4568": ("第一三共", "医薬品"), "4578": ("大塚HD", "医薬品"), "4587": ("ペプチドリーム", "医薬品"),
    "4661": ("オリエンタルランド", "サービス業"), "4689": ("LINEヤフー", "情報・通信業"), "4704": ("トレンド", "情報・通信業"), "4732": ("USS", "サービス業"), "4751": ("サイバーエージェント", "サービス業"), "4755": ("楽天グループ", "サービス業"), "4768": ("大塚商会", "情報・通信業"), "4887": ("サワイG", "医薬品"), "4901": ("富士フイルム", "化学"), "4902": ("コニカミノルタ", "電気機器"), "4911": ("資生堂", "化学"), "5019": ("出光興産", "石油・石炭製品"),
    "5020": ("ＥＮＥＯＳ", "石油・石炭製品"), "5101": ("横浜ゴム", "ゴム製品"), "5108": ("ブリヂストン", "ゴム製品"), "5201": ("AGC", "ガラス・土石製品"), "5233": ("太平洋セメ", "ガラス・土石製品"), "5301": ("東海カーボン", "ガラス・土石製品"), "5332": ("TOTO", "ガラス・土石製品"), "5333": ("日本ガイシ", "ガラス・土石製品"), "5401": ("日本製鉄", "鉄鋼"), "5406": ("神戸鋼", "鉄鋼"), "5411": ("JFE", "鉄鋼"), "5541": ("大平洋金属", "鉄鋼"),
    "5703": ("日本軽金属HD", "非鉄金属"), "5706": ("三井金属", "非鉄金属"), "5707": ("東邦亜鉛", "非鉄金属"), "5711": ("三菱マテリアル", "非鉄金属"), "5713": ("住友鉱", "非鉄金属"), "5714": ("DOWA", "非鉄金属"), "5801": ("古河電", "非鉄金属"), "5802": ("住友電", "非鉄金属"), "5803": ("フジクラ", "非鉄金属"), "5831": ("しずおかFG", "銀行業"), "5901": ("東洋製罐G", "金属製品"), "6005": ("三浦工業", "機械"),
    "6098": ("リクルート", "サービス業"), "6103": ("オークマ", "機械"), "6113": ("アマダ", "機械"), "6141": ("DMG森精機", "機械"), "6146": ("ディスコ", "機械"), "6178": ("日本郵政", "サービス業"), "6201": ("豊田織機", "輸送用機器"), "6273": ("ＳＭＣ", "機械"), "6301": ("コマツ", "機械"), "6302": ("住友重", "機械"), "6305": ("日立建機", "機械"), "6326": ("クボタ", "機械"),
    "6361": ("荏原", "機械"), "6367": ("ダイキン", "機械"), "6448": ("ブラザー", "電気機器"), "6471": ("日本精工", "機械"), "6472": ("NTN", "機械"), "6473": ("ジェイテクト", "機械"), "6479": ("ミネベアミツミ", "電気機器"), "6501": ("日立", "電気機器"), "6503": ("三菱電", "電気機器"), "6504": ("富士電機", "電気機器"), "6506": ("安川電", "電気機器"),
    "6526": ("ソシオネクスト", "電気機器"), "6594": ("ニデック", "電気機器"), "6645": ("オムロン", "電気機器"), "6674": ("ＧＳユアサ", "電気機器"), "6701": ("NEC", "電気機器"), "6702": ("富士通", "電気機器"), "6723": ("ルネサス", "電気機器"), "6724": ("エプソン", "電気機器"), "6752": ("パナソニック", "電気機器"), "6753": ("シャープ", "電気機器"), "6758": ("ソニーG", "電気機器"), "6762": ("TDK", "電気機器"),
    "6841": ("横河電", "電気機器"), "6857": ("アドバンテスト", "電気機器"), "6861": ("キーエンス", "電気機器"), "6869": ("シスメックス", "精密機器"), "6902": ("デンソー", "輸送用機器"), "6920": ("レーザーテック", "電気機器"), "6952": ("カシオ", "電気機器"), "6954": ("ファナック", "電気機器"), "6971": ("京セラ", "電気機器"), "6976": ("太陽誘電", "電気機器"), "6981": ("村田製", "電気機器"), "6988": ("日東電工", "化学"),
    "7003": ("三井E&S", "機械"), "7011": ("三菱重", "機械"), "7012": ("川崎重", "輸送用機器"), "7013": ("IHI", "機械"), "7182": ("ゆうちょ銀行", "銀行業"), "7186": ("コンコルディア", "銀行業"), "7201": ("日産自", "輸送用機器"), "7202": ("いすゞ", "輸送用機器"), "7203": ("トヨタ", "輸送用機器"), "7205": ("日野自", "輸送用機器"), "7211": ("三菱自", "輸送用機器"), "7261": ("マツダ", "輸送用機器"),
    "7267": ("ホンダ", "輸送用機器"), "7269": ("スズキ", "輸送用機器"), "7270": ("ＳＵＢＡＲＵ", "輸送用機器"), "7272": ("ヤマハ発", "輸送用機器"), "7309": ("シマノ", "輸送用機器"), "7532": ("パンパシHD", "小売業"), "7731": ("ニコン", "精密機器"), "7733": ("オリンパス", "精密機器"), "7741": ("ＨＯＹＡ", "精密機器"), "7735": ("SCREEN", "電気機器"), "7751": ("キヤノン", "電気機器"), "7752": ("リコー", "電気機器"),
    "7832": ("バンナムHD", "その他製品"), "7911": ("TOPPAN", "その他製品"), "7912": ("大日本印刷", "その他製品"), "7951": ("ヤマハ", "その他製品"), "7956": ("ピジョン", "その他製品"), "7974": ("任天堂", "その他製品"), "8001": ("伊藤忠", "卸売業"), "8002": ("丸紅", "卸売業"), "8015": ("豊田通商", "卸売業"), "8031": ("三井物", "卸売業"), "8035": ("東エレク", "電気機器"), "8053": ("住友商", "卸売業"),
    "8056": ("BIPROGY", "情報・通信業"), "8058": ("三菱商", "卸売業"), "8113": ("ユニチャーム", "化学"), "8233": ("高島屋", "小売業"), "8252": ("丸井グループ", "小売業"), "8253": ("クレディセゾン", "その他金融業"), "8267": ("イオン", "小売業"), "8304": ("あおぞら銀", "銀行業"), "8306": ("三菱UFJ", "銀行業"), "8308": ("りそなHD", "銀行業"), "8309": ("三井住友トラ", "銀行業"),
    "8316": ("三井住友FG", "銀行業"), "8331": ("千葉銀", "銀行業"), "8354": ("ふくおかFG", "銀行業"), "8411": ("みずほFG", "銀行業"), "8473": ("SBI", "証券、商品先物取引業"), "8591": ("オリックス", "その他金融業"), "8601": ("大和証券G", "証券、商品先物取引業"), "8604": ("野村HD", "証券、商品先物取引業"), "8630": ("ＳＯＭＰＯ", "保険業"), "8697": ("日本取引所", "その他金融業"), "8725": ("ＭＳ＆ＡＤ", "保険業"),
    "8750": ("第一生命HD", "保険業"), "8766": ("東京海上", "保険業"), "8801": ("三井不動", "不動産業"), "8802": ("三菱地所", "不動産業"), "8804": ("東京建物", "不動産業"), "8830": ("住友不動", "不動産業"), "9001": ("東武", "陸運業"), "9005": ("東急", "陸運業"), "9007": ("小田急", "陸運業"), "9008": ("京王", "陸運業"), "9009": ("京成", "陸運業"), "9020": ("JR東日本", "陸運業"),
    "9021": ("JR西日本", "陸運業"), "9022": ("JR東海", "陸運業"), "9064": ("ヤマトHD", "陸運業"), "9101": ("日本郵船", "海運業"), "9104": ("商船三井", "海運業"), "9107": ("川崎汽", "海運業"), "9143": ("ＳＧホールディングス", "陸運業"), "9201": ("JAL", "空運業"), "9202": ("ANA", "空運業"), "9432": ("NTT", "情報・通信業"), "9433": ("KDDI", "情報・通信業"), "9434": ("ソフトバンク", "情報・通信業"),
    "9501": ("東電HD", "電気・ガス業"), "9502": ("中部電", "電気・ガス業"), "9503": ("関西電", "電気・ガス業"), "9531": ("東京ガス", "電気・ガス業"), "9532": ("大阪ガス", "電気・ガス業"), "9602": ("東宝", "サービス業"), "9613": ("NTTデータ", "情報・通信業"), "9684": ("スクエニHD", "情報・通信業"), "9697": ("カプコン", "情報・通信業"), "9733": ("ナガセ", "サービス業"), "9735": ("セコム", "サービス業"), "9766": ("コナミG", "情報・通信業"),
    "9843": ("ニトリHD", "小売業"), "9983": ("ファストリ", "小売業"), "9984": ("ソフトバンクG", "情報・通信業"),
}

# LINE通知送信
def send_line(msg):
    if not msg: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": msg}]}
    try:
        requests.post(url, headers=headers, json=payload)
    except: pass

# スコア算出
def calculate_score(s_code, df):
    df = df.dropna(subset=['Close']).reset_index(drop=True)
    if len(df) < 75: return None
    
    close, open_p, high, vol = df['Close'], df['Open'], df['High'], df['Volume']
    ma5, ma25, ma75 = close.rolling(5).mean(), close.rolling(25).mean(), close.rolling(75).mean()
    high_10d = high.shift(1).rolling(10).max()
    bbh = close.rolling(20).mean() + (close.rolling(20).std() * 2)
    
    c_p = close.iloc[-1]
    raw_s, labels = 0, []
    
    # 1. 陽線判定(+15)
    if c_p > open_p.iloc[-1]: 
        raw_s += 15
        labels.append("陽線(+15)")
    
    # 2. GC初動判定(+20)
    if ((ma5.shift(1) <= ma25.shift(1)) & (ma5 > ma25)).iloc[-5:].any():
        raw_s += 20
        labels.append("GC初動(+20)")
    
    # 3. MA上昇判定(各+10)
    m5_up, m25_up = ma5.diff().iloc[-1] > 0, ma25.diff().iloc[-1] > 0
    if m5_up: 
        raw_s += 10
        labels.append("5日線上昇(+10)")
    if m25_up: 
        raw_s += 10
        labels.append("25日線上昇(+10)")
    
    # 4. トレンド判定(初動:+30 / 継続・収束:+10)
    is_po = (ma5.iloc[-1] > ma25.iloc[-1] > ma75.iloc[-1])
    is_converged = ((abs(ma5.iloc[-1] - ma75.iloc[-1])) / ma75.iloc[-1]) < 0.03
    if is_po and is_converged and m5_up and m25_up:
        raw_s += 30
        labels.append("トレンド初動(+30)")
    elif is_po:
        raw_s += 10
        labels.append("上昇トレンド継続(+10)")
    elif is_converged and m5_up and m25_up:
        raw_s += 10
        labels.append("エネルギー収束(+10)")
            
    # 5. 高値突破判定(+20)
    if c_p > high_10d.iloc[-1]: 
        raw_s += 20
        labels.append("高値突破(+20)")
    
    # 6. 出来高加点判定(1.5倍:+30/3倍:+40)
    base_vol = vol.iloc[-8:-3].mean()
    vol_ratio = vol.iloc[-1] / base_vol if base_vol > 0 else 1.0
    if c_p > open_p.iloc[-1]:
        if vol_ratio >= 3.0: 
            raw_s += 40
            labels.append(f"出来高x{vol_ratio:.1f}(+40)")
        elif vol_ratio >= 1.5: 
            raw_s += 30
            labels.append(f"出来高x{vol_ratio:.1f}(+30)")
            
    # 7. 過熱警戒判定(-20)
    final_score = raw_s
    if c_p > bbh.iloc[-1]:
        final_score -= 20
        labels.append("過熱警戒(-20)")
    
    return (final_score, s_code, c_p, labels)

# 銘柄情報取得
def get_ticker_info(s_code):
    if s_code in STOCKS_DATA: return STOCKS_DATA[s_code]
    try:
        t = yf.Ticker(f"{s_code}.T")
        name = t.fast_info.get('commonName') or t.ticker_metadata.get('longName') or "不明"
        sector = t.ticker_metadata.get('sector') or "ETF/その他"
        return (name, sector)
    except: return ("不明", "不明")

# レポート文字列生成
def generate_report(results, label_text):
    if not results: return None
    top_10 = sorted(results, key=lambda x: x[0], reverse=True)[:10]
    lines = []
    for score, code, price, lbs in top_10:
        name, sector = get_ticker_info(code)
        lines.append(f"{code} {name} ({sector})\n{price:.1f}円 【{score}点】\n" + "・".join(lbs))
    
    header = f"{datetime.now().strftime('%Y.%m.%d')} {label_text}\n\n【判定：上昇優勢 TOP10】\n\n"
    return header + "\n\n".join(lines) + "\n\n───────────────\n詳細確認: https://www.sbisec.co.jp/ETGate/"

# メイン処理
if __name__ == "__main__":
    major_results, all_results = [], []
    
    # 1. 国内主要銘柄 スコア計算
    print("Step 1: Processing Major Stocks...")
    major_tickers = [f"{c}.T" for c in STOCKS_DATA.keys()]
    major_data = yf.download(major_tickers, period="120d", group_by='ticker', progress=False)
    
    for t in major_tickers:
        code = t.replace(".T", "")
        try:
            df = major_data[t].dropna()
            res = calculate_score(code, df)
            if res: major_results.append(res)
        except: continue

    # 2. 全銘柄 スコア計算
    print("Step 2: Filtering and Processing All Stocks...")
    all_codes = [str(i) for i in range(1000, 10000)]
    all_tickers = [f"{c}.T" for c in all_codes]
    v_data = yf.download(all_tickers, period="20d", progress=False)['Volume']
    candidates = []
    for c in all_codes:
        t_key = f"{c}.T"
        if t_key not in v_data: continue
        try:
            v = v_data[t_key].dropna()
            if len(v) >= 8 and (v.iloc[-1] / v.iloc[-8:-3].mean()) > 1.1: 
                candidates.append(t_key)
        except: continue
    
    if candidates:
        candidate_data = yf.download(candidates, period="120d", group_by='ticker', progress=False)
        for t in candidates:
            code = t.replace(".T", "")
            try:
                df = candidate_data[t].dropna() if len(candidates) > 1 else candidate_data.dropna()
                res = calculate_score(code, df)
                if res: all_results.append(res)
            except: continue

    # データ統合
    all_results.extend(major_results)
    unique_all = {res[1]: res for res in all_results}.values()

    # レポート送信
    send_line(generate_report(major_results, "国内主要株レポート"))
    send_line(generate_report(list(unique_all), "株式市場レポート"))

# --- AI Guidelines ---
# 1. Never edit parts that were not explicitly requested for modification.
# 2. Comments must be simple and content-explanatory. Avoid context-specific or personal remarks.
# 3. Always state clearly in the conversation when code or comments are being edited.
# 4. Do not output code spontaneously during conversation.
# 5. Always output the full code in text block format.
