"""Leakage-safe TAIEX regime labels, using only the previous session close."""
def regime_map(index_rows):
    closes=[(r[0],float(r[1])) for r in index_rows]
    out={}
    ma=[]
    for i,(_,close) in enumerate(closes):
        ma.append(sum(x[1] for x in closes[max(0,i-199):i+1])/min(i+1,200))
        if i==0:
            continue
        target_date=closes[i][0]
        prior_close=closes[i-1][1]
        prior_ma=ma[i-1]
        prior_slope=(ma[i-1]-ma[i-21]) if i>=21 else None
        if i-1<219 or prior_slope is None:
            out[target_date]="UNKNOWN"
        elif prior_close>prior_ma and prior_slope>0:
            out[target_date]="BULL"
        elif prior_close<prior_ma and prior_slope<0:
            out[target_date]="BEAR"
        else:
            out[target_date]="SIDEWAYS"
    return out
