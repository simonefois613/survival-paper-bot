import csv, json, math, os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = Path("data"); DATA.mkdir(exist_ok=True)

START_BANKROLL = float(os.getenv("START_BANKROLL", "100"))
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "10000"))
MIN_EDGE = float(os.getenv("MIN_EDGE", "0.08"))
MAX_POSITION_FRAC = float(os.getenv("MAX_POSITION_FRAC", "0.06"))
KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.25"))
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE", "0.40"))
SLIPPAGE = float(os.getenv("SLIPPAGE", "0.002"))
MIN_HOURS_TO_END = float(os.getenv("MIN_HOURS_TO_END", "1"))
MAX_MARKETS = int(os.getenv("MAX_MARKETS", "500"))

s = requests.Session()
s.headers["User-Agent"] = "SurvivalPaperBot/0.2 research"

def now(): return datetime.now(timezone.utc).isoformat()

def get(url, params=None):
    r=s.get(url,params=params,timeout=20); r.raise_for_status(); return r.json()

def j(x, default=[]):
    if isinstance(x,list): return x
    if isinstance(x,str):
        try: return json.loads(x)
        except: return default
    return default

def load():
    p=DATA/"state.json"
    if not p.exists():
        return {"bankroll":START_BANKROLL,"realized_pnl":0,"positions":{},
                "cycles":0,"started_at":now(),"last_cycle":None}
    return json.loads(p.read_text())

def save(st): (DATA/"state.json").write_text(json.dumps(st,indent=2))

def csvlog(name,row):
    p=DATA/name; exists=p.exists()
    with p.open("a",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=row.keys())
        if not exists:w.writeheader()
        w.writerow(row)

def fetch_markets():
    out=[]
    for offset in range(0,MAX_MARKETS,100):
        batch=get(f"{GAMMA}/markets",{
            "active":"true","closed":"false","limit":100,"offset":offset,
            "order":"volumeNum","ascending":"false"})
        if not batch: break
        out.extend(batch)
        if len(batch)<100: break
    return out[:MAX_MARKETS]

def price(token):
    try: return float(get(f"{CLOB}/midpoint",{"token_id":token})["mid"])
    except: return None

def history(token):
    try:
        x=get(f"{CLOB}/prices-history",{
            "market":token,"interval":"1d","fidelity":60})
        return [float(v["p"]) for v in x.get("history",[])]
    except: return []

def fair(prices):
    if len(prices)<8:return None
    p=prices[-1]; r=prices[-12:]
    mean=sum(r)/len(r)
    trend=(p-prices[-6])/5
    vol=math.sqrt(sum((x-mean)**2 for x in r)/max(1,len(r)-1))
    # Hybrid signal: modest momentum + mean reversion, penalized by volatility.
    f=p + .30*trend - .15*(p-mean)
    f -= .10*vol*(1 if p>mean else -1)
    return max(.02,min(.98,f))

def kelly(prob,entry):
    b=1/entry-1; q=1-prob
    full=(b*prob-q)/b if b>0 else 0
    return max(0,full)*KELLY_FRACTION

def settle_and_mark(st, market_index):
    equity=st["bankroll"]; exposure=0
    for key,pos in list(st["positions"].items()):
        m=market_index.get(pos["market_id"])
        if not m:
            exposure += pos["cost"]; equity += pos.get("last_value",pos["cost"]); continue
        outcomes=j(m.get("outcomes"),[])
        prices=j(m.get("outcomePrices"),[])
        tokens=j(m.get("clobTokenIds"),[])
        try:i=tokens.index(pos["token_id"])
        except ValueError:
            equity += pos.get("last_value",pos["cost"]); exposure += pos["cost"]; continue

        if m.get("closed"):
            final=float(prices[i]) if i<len(prices) else 0
            proceeds=pos["shares"]*final
            pnl=proceeds-pos["cost"]
            st["bankroll"] += proceeds
            st["realized_pnl"] += pnl
            csvlog("trades.csv",{
                "timestamp":now(),"action":"SETTLE","market_id":pos["market_id"],
                "question":pos["question"],"token_id":pos["token_id"],
                "price":final,"shares":pos["shares"],"cost":pos["cost"],
                "proceeds":proceeds,"pnl":pnl})
            del st["positions"][key]
        else:
            p=price(pos["token_id"])
            if p is None:p=pos["entry"]
            pos["last_price"]=p
            pos["last_value"]=pos["shares"]*p
            exposure += pos["cost"]
            equity += pos["last_value"]-pos["cost"]
    return equity,exposure

def cycle():
    st=load(); st["cycles"]+=1; st["last_cycle"]=now()
    try: ms=fetch_markets()
    except Exception as e:
        csvlog("signals.csv",{"timestamp":now(),"status":"ERROR","error":str(e)})
        save(st); return

    idx={str(m.get("id")):m for m in ms}
    equity, exposure=settle_and_mark(st,idx)

    candidates=0; opened=0
    for m in ms:
        try:
            vol=float(m.get("volumeNum") or 0)
            liq=float(m.get("liquidityNum") or 0)
        except: continue
        if vol<MIN_VOLUME or liq<=0: continue

        end=m.get("endDate") or m.get("endDateIso")
        if end:
            try:
                dt=datetime.fromisoformat(end.replace("Z","+00:00"))
                if dt-datetime.now(timezone.utc)<timedelta(hours=MIN_HOURS_TO_END):
                    continue
            except: pass

        outcomes=j(m.get("outcomes"),[])
        tokens=j(m.get("clobTokenIds"),[])
        if not tokens: continue

        # Evaluate each outcome; this supports more than YES/NO while
        # keeping the first version focused on one binary side.
        for i,token in enumerate(tokens[:2]):
            p=price(token)
            if p is None or not .01<p<.99: continue
            hist=history(token); f=fair(hist)
            if f is None: continue
            edge=f-p; candidates+=1
            csvlog("signals.csv",{
                "timestamp":now(),"market_id":m.get("id"),
                "question":m.get("question",""),"outcome":outcomes[i] if i<len(outcomes) else i,
                "token_id":token,"market_price":round(p,6),
                "fair_probability":round(f,6),"edge":round(edge,6),
                "volume":round(vol,2),"liquidity":round(liq,2)})

            key=f"{m.get('id')}:{token}"
            if key in st["positions"] or edge<MIN_EDGE: continue
            if exposure >= equity*MAX_TOTAL_EXPOSURE: continue

            frac=min(MAX_POSITION_FRAC,kelly(f,p))
            cost=equity*frac
            if cost<1: continue

            fill=min(.999,p+SLIPPAGE)
            shares=cost/fill
            st["positions"][key]={
                "market_id":str(m.get("id")),"question":m.get("question",""),
                "token_id":token,"outcome":outcomes[i] if i<len(outcomes) else str(i),
                "shares":shares,"entry":fill,"cost":cost,
                "opened_at":now(),"last_price":fill,"last_value":cost}
            exposure+=cost; opened+=1
            csvlog("trades.csv",{
                "timestamp":now(),"action":"BUY",
                "market_id":m.get("id"),"question":m.get("question",""),
                "outcome":outcomes[i] if i<len(outcomes) else i,
                "token_id":token,"price":round(fill,6),
                "shares":round(shares,6),"cost":round(cost,4),
                "edge":round(edge,6),"fair":round(f,6)})

    # Snapshot equity after opening/marking.
    mtm=0
    for pos in st["positions"].values():
        mtm += pos.get("last_value",pos["cost"])
    total=st["bankroll"]+mtm
    csvlog("equity.csv",{
        "timestamp":now(),"cycle":st["cycles"],
        "cash":round(st["bankroll"],4),
        "open_value":round(mtm,4),
        "equity":round(total,4),
        "realized_pnl":round(st["realized_pnl"],4),
        "open_positions":len(st["positions"]),
        "candidates":candidates,"opened":opened})
    save(st)
    print(json.dumps({
        "cycle":st["cycles"],"time":st["last_cycle"],
        "equity":round(total,4),"cash":round(st["bankroll"],4),
        "realized_pnl":round(st["realized_pnl"],4),
        "open_positions":len(st["positions"]),
        "candidates":candidates,"opened":opened},indent=2))

if __name__=="__main__": cycle()
