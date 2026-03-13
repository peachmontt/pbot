def detect_probability_issues(df):
    """
    Повертає opportunities з token_id, price, size для trader.execute_trade.
    """
    try:
        from config import DEFAULT_ORDER_SIZE, MIN_ARBITRAGE
    except ImportError:
        DEFAULT_ORDER_SIZE = 10.0
        MIN_ARBITRAGE = 0.05

    opportunities = []
    is_pandas = hasattr(df, "iloc")
    n = len(df) if hasattr(df, "__len__") else 0
    if n < 2:
        return opportunities

    for i in range(n - 1):
        if is_pandas:
            row1 = df.iloc[i].to_dict() if hasattr(df.iloc[i], "to_dict") else dict(df.iloc[i])
            row2 = df.iloc[i + 1].to_dict() if hasattr(df.iloc[i + 1], "to_dict") else dict(df.iloc[i + 1])
        else:
            row1 = df[i] if isinstance(df[i], dict) else dict(df[i])
            row2 = df[i + 1] if isinstance(df[i + 1], dict) else dict(df[i + 1])

        p1 = row1.get("price")
        p2 = row2.get("price")
        if p1 is None or p2 is None:
            continue

        edge = float(p2) - float(p1)
        if edge < MIN_ARBITRAGE or p2 <= p1:
            continue
        token_id = row1.get("clob_token_id")
        if not token_id:
            continue
        opportunities.append({
            "market1": row1.get("question"),
            "market2": row2.get("question"),
            "edge": edge,
            "token_id": token_id,
            "price": float(p1),
            "size": DEFAULT_ORDER_SIZE,
            "side": "BUY",
        })

    return opportunities
