def get_stock_data():
    host = "https://api.jquants.com/v2"
    headers = {"x-api-key": API_KEY}
    name_map = {}
    fetch_error = None
    
    # 銘柄情報の取得（JPXのCSV方式に戻してガードを固める）
    try:
        csv_url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.csv"
        res = requests.get(csv_url, timeout=10)
        res.encoding = 'shift_jis'
        
        # CSVを読み込む際に、コード列を「文字列」として強制指定
        csv_df = pd.read_csv(io.StringIO(res.text), dtype={'コード': str})
        
        for _, row in csv_df.iterrows():
            # コードの空白を除去して先頭4文字を取得
            c_val = str(row['コード']).strip()
            if len(c_val) >= 4:
                code_4 = c_val[:4]
                name_map[code_4] = {
                    "name": str(row['銘柄名']).strip(),
                    "sector": str(row['17業種区分']).strip()
                }
    except Exception as e:
        fetch_error = f"CSV取得失敗({type(e).__name__})"

    # 以降、日足データの取得（ここは通っているはず）
    all_data, success_days = [], 0
    # ...（中略）...

    for code, group in df.groupby('Code'):
        if len(group) < 10: continue
        # ここが最重要：J-QuantsのCode(14070など)を数値として解釈してから4桁の文字列にする
        # これで 14070 -> "1407" となり、name_mapのキーと一致する
        s_code = str(int(code))[:4]
        
        info = name_map.get(s_code)
        if info is None:
            # マップにない場合、なぜ無いのかのヒントを表示
            status = fetch_error if fetch_error else "CSVに存在せず"
            info = {"name": f"不明({status})", "sector": "-"}
