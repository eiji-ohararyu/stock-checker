import os
import requests
import json
from datetime import datetime, timedelta

# --- 認証設定 ---
API_KEY = os.getenv("JQUANTS_REFRESH_TOKEN", "").strip()
LINE_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
USER_ID = os.getenv("LINE_USER_ID", "").strip()

DEBUG_CODE = "4768" # 大塚商会

def get_raw_api_response():
    host, headers = "https://api.jquants.com/v2", {"x-api-key": API_KEY}
    
    # 75日線を計算するために必要な過去120営業日（約半年分）をカバー
    start_date = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    # APIから生データを取得
    r = requests.get(f"{host}/equities/bars/daily", headers=headers, 
                     params={"code": DEBUG_CODE, "from": start_date, "to": end_date})
    
    if r.status_code != 200:
        return f"API ERROR: {r.status_code}\n{r.text}"
    
    raw_data = r.json().get("data", [])
    
    # 【重要】一切の計算・加工・ソートを行わず、APIから届いた「生の辞書形式」をそのままテキスト化
    raw_lines = []
    for entry in raw_data:
        # JSON形式のまま1行ずつ書き出し
        raw_lines.append(json.dumps(entry, ensure_ascii=False))
    
    return "\n".join(raw_lines)

if __name__ == "__main__":
    # 全データを取得
    full_raw_list = get_raw_api_response()
    
    # LINEの文字数制限（約5000文字）に引っかかる可能性があるため、
    # 50件ずつ分割してでも全件送ります
    chunk_size = 4000 
    messages = [full_raw_list[i:i+chunk_size] for i in range(0, len(full_raw_list), chunk_size)]
    
    for i, msg_content in enumerate(messages):
        title = f"【生データリスト {i+1}/{len(messages)}】\n"
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Authorization": f"Bearer {LINE_TOKEN}"}, 
                      json={"to": USER_ID, "messages": [{"type": "text", "text": title + msg_content}]})
