"""
Shared utilities for all Stocklyze Vercel API endpoints.
Import this in each api/*.py file.
"""
import os, math, json
from datetime import datetime
import numpy as np

GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MDL = "llama-3.3-70b-versatile"

SECTOR_PE = {
    "Technology": 25.0, "Financial Services": 18.5,
    "Consumer Cyclical": 33.0, "Consumer Defensive": 40.0,
    "Energy": 11.0, "Industrials": 22.0, "Healthcare": 30.0,
    "Basic Materials": 14.0, "Communication Services": 20.0,
    "Utilities": 16.0, "Real Estate": 24.0,
}

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}

def safe(v, d=0.0):
    try:
        f = float(v)
        return d if (math.isnan(f) or math.isinf(f)) else f
    except:
        return d

def fmt_cap(v):
    if not v: return "N/A"
    v = float(v)
    if v >= 1e12: return f"₹{v/1e12:.2f}L Cr"
    if v >= 1e9:  return f"₹{v/1e9:.2f}K Cr"
    if v >= 1e7:  return f"₹{v/1e7:.2f} Cr"
    return f"₹{v:,.0f}"

def yf_sym(s):
    overrides = {
        "M&M": "M&M.NS", "BAJAJ-AUTO": "BAJAJ-AUTO.NS",
        "MCDOWELL-N": "MCDOWELL-N.NS", "NAUKRI": "NAUKRI.NS",
    }
    s = s.upper().strip()
    if s in overrides: return overrides[s]
    if s.startswith("^") or "." in s: return s
    return s + ".NS"

# ── Technical Indicators ──────────────────────────────────────
def calc_rsi(c, n=14):
    if len(c) < n+2: return 50.0
    d = np.diff(c.astype(float))
    g = np.where(d>0,d,0.0); l = np.where(d<0,-d,0.0)
    ag,al = g[:n].mean(), l[:n].mean()
    for i in range(n,len(d)):
        ag=(ag*(n-1)+g[i])/n; al=(al*(n-1)+l[i])/n
    return round(100-(100/(1+ag/al)) if al>1e-10 else 100.0, 2)

def calc_ema(c, n):
    if len(c)<n: return float(c[-1]) if len(c) else 0.0
    k=2/(n+1); v=float(np.mean(c[:n]))
    for x in c[n:]: v=float(x)*k+v*(1-k)
    return round(v,2)

def calc_macd(c):
    if len(c)<35: return {"macd":0,"signal":0,"hist":0}
    def ema_arr(arr,n):
        k=2/(n+1); v=float(np.mean(arr[:n])); out=[v]
        for x in arr[n:]: v=float(x)*k+v*(1-k); out.append(v)
        return np.array(out)
    e12=ema_arr(c,12); e26=ema_arr(c,26)
    ml=e12[-len(e26):]-e26; sig=ema_arr(ml,9)
    return {"macd":round(float(ml[-1]),3),"signal":round(float(sig[-1]),3),"hist":round(float(ml[-1]-sig[-1]),3)}

def calc_adx(h,l,c,n=14):
    if len(c)<n*2+2: return 25.0
    tr,dp,dm=[],[],[]
    for i in range(1,len(c)):
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
        u,d_=h[i]-h[i-1],l[i-1]-l[i]
        dp.append(u if u>d_ and u>0 else 0.0)
        dm.append(d_ if d_>u and d_>0 else 0.0)
    tr,dp,dm=np.array(tr),np.array(dp),np.array(dm)
    def sm(a): s=[a[:n].sum()];[s.append(s[-1]-s[-1]/n+a[i]) for i in range(n,len(a))];return np.array(s)
    st,sd,sm2=sm(tr),sm(dp),sm(dm)
    dip=100*sd/np.maximum(st,1e-10); dim=100*sm2/np.maximum(st,1e-10)
    dx=100*np.abs(dip-dim)/np.maximum(dip+dim,1e-10)
    return round(float(dx[-n:].mean()),2)

def calc_bb(c,n=20,k=2):
    if len(c)<n: v=float(c[-1]);return{"upper":v,"mid":v,"lower":v,"pct":50,"bw":0}
    s=c[-n:]; mid=float(s.mean()); std=float(s.std())
    upper=mid+k*std; lower=mid-k*std; cur=float(c[-1])
    pct=(cur-lower)/(upper-lower)*100 if (upper-lower)>0 else 50
    return{"upper":round(upper,2),"mid":round(mid,2),"lower":round(lower,2),
           "pct":round(pct,1),"bw":round((upper-lower)/mid*100,2) if mid>0 else 0}

def calc_stoch(h,l,c,k=14):
    if len(c)<k: return{"k":50,"d":50}
    hh,ll=h[-k:].max(),l[-k:].min()
    kv=(float(c[-1])-ll)/(hh-ll)*100 if (hh-ll)>0 else 50
    return{"k":round(kv,2),"d":round(kv,2)}

# ── 4-Layer Scoring Engine ──────────────────────────────────────
def score_stock(fd, series):
    closes=np.array([d["close"] for d in series],dtype=float)
    highs=np.array([d["high"] for d in series],dtype=float)
    lows=np.array([d["low"] for d in series],dtype=float)
    cur=closes[-1] if len(closes) else 0
    ma50=float(np.mean(closes[-50:])) if len(closes)>=50 else cur
    ma200=float(np.mean(closes[-200:])) if len(closes)>=200 else cur
    sector=fd.get("sector","Technology")
    spe=SECTOR_PE.get(sector,22)
    rsi=calc_rsi(closes); macd=calc_macd(closes)
    adx=calc_adx(highs,lows,closes); bb=calc_bb(closes)
    stch=calc_stoch(highs,lows,closes)
    ema20=calc_ema(closes,20); ema50=calc_ema(closes,50)
    ema200=calc_ema(closes,200) if len(closes)>=200 else ma200
    score=0; L1=L2=L3=L4=0; finds=[]

    rg=safe(fd.get("revenue_growth",0))*100
    if rg>15: L1+=8; finds.append({"t":"p","tx":f"Strong revenue growth {rg:.1f}% YoY"})
    elif rg>8: L1+=5; finds.append({"t":"p","tx":f"Healthy revenue growth {rg:.1f}% YoY"})
    elif rg>0: L1+=2
    else: finds.append({"t":"n","tx":f"Revenue growth {rg:.1f}% — stagnant or declining"})
    pm=safe(fd.get("profit_margins",0))*100
    if pm>20: L1+=6; finds.append({"t":"p","tx":f"Excellent net profit margin {pm:.1f}%"})
    elif pm>12: L1+=4
    elif pm>5: L1+=2
    elif pm>0: L1+=1
    else: finds.append({"t":"n","tx":f"Negative profit margin {pm:.1f}%"})
    roe_v=safe(fd.get("return_on_equity",0))*100
    if roe_v>20: L1+=8; finds.append({"t":"p","tx":f"Excellent ROE {roe_v:.1f}%"})
    elif roe_v>15: L1+=5; finds.append({"t":"p","tx":f"Good ROE {roe_v:.1f}%"})
    elif roe_v>8: L1+=2
    else: finds.append({"t":"n","tx":f"Weak ROE {roe_v:.1f}%"})
    de=safe(fd.get("debt_to_equity",0))/100
    if de<0.3: L1+=4; finds.append({"t":"p","tx":f"Very low Debt/Equity {de:.2f}"})
    elif de<1.0: L1+=2
    elif de>2.0: finds.append({"t":"n","tx":f"High Debt/Equity {de:.2f}"})
    eg=safe(fd.get("earnings_growth",0))*100
    if eg>20: L1+=4; finds.append({"t":"p","tx":f"Accelerating earnings growth {eg:.1f}%"})
    elif eg>10: L1+=2
    elif eg<0: finds.append({"t":"n","tx":f"Declining earnings {eg:.1f}%"})

    pe=safe(fd.get("trailing_pe",0))
    if pe<=0: L2+=10
    elif pe<spe*0.7: L2+=20; finds.append({"t":"p","tx":f"Undervalued: P/E {pe:.1f}x vs sector {spe}x"})
    elif pe<spe: L2+=14; finds.append({"t":"p","tx":f"Fair valuation: P/E {pe:.1f}x below sector {spe}x"})
    elif pe<spe*1.3: L2+=8
    else: finds.append({"t":"n","tx":f"Elevated P/E {pe:.1f}x vs sector {spe}x"})
    pb=safe(fd.get("price_to_book",0))
    if 0<pb<2: L2+=5; finds.append({"t":"p","tx":f"Reasonable P/B {pb:.1f}x"})
    elif pb<4: L2+=2
    elif pb>8: finds.append({"t":"n","tx":f"High P/B {pb:.1f}x"})

    above_200=cur>ma200; above_50=cur>ma50; golden=ma50>ma200
    if above_200: L3+=8; finds.append({"t":"p","tx":"Price above 200-day EMA — long-term uptrend"})
    else: finds.append({"t":"n","tx":"Price below 200-day EMA — long-term trend bearish"})
    if above_50: L3+=5; finds.append({"t":"p","tx":"Price above 50-day EMA — medium-term momentum positive"})
    if golden: L3+=5; finds.append({"t":"p","tx":"Golden Cross active — bullish long-term signal"})
    if 40<=rsi<=70: L3+=4; finds.append({"t":"p","tx":f"RSI {rsi:.1f} in healthy zone"})
    elif rsi<30: L3+=3; finds.append({"t":"p","tx":f"RSI {rsi:.1f} oversold — potential reversal"})
    elif rsi>75: finds.append({"t":"n","tx":f"RSI {rsi:.1f} overbought"})
    if macd["hist"]>0: L3+=3; finds.append({"t":"p","tx":"MACD histogram positive — bullish momentum"})
    else: finds.append({"t":"n","tx":"MACD histogram negative — bearish pressure"})

    inst=safe(fd.get("held_percent_institutions",0))*100
    if inst>50: L4+=12; finds.append({"t":"p","tx":f"High institutional ownership {inst:.1f}%"})
    elif inst>25: L4+=7
    elif inst>10: L4+=3
    insiders=safe(fd.get("held_percent_insiders",0))*100
    if insiders>40: L4+=5; finds.append({"t":"p","tx":f"High insider/promoter holding {insiders:.1f}%"})
    elif insiders>25: L4+=3
    elif insiders<5: finds.append({"t":"n","tx":f"Low insider holding {insiders:.1f}%"})
    beta=safe(fd.get("beta",1),1)
    if beta<0.8: L4+=3; finds.append({"t":"p","tx":f"Low beta {beta:.2f} — defensive stock"})
    elif beta>1.5: finds.append({"t":"n","tx":f"High beta {beta:.2f} — volatile"})

    score=min(100,L1+L2+L3+L4)
    if score>=80: verdict="STRONG BUY"
    elif score>=65: verdict="BUY"
    elif score>=50: verdict="CAUTIOUS BUY"
    elif score>=35: verdict="HOLD"
    elif score>=20: verdict="REDUCE"
    else: verdict="AVOID"

    forecasts=[]
    if len(closes)>=60:
        y=closes[-60:]; x=np.arange(len(y)); n=len(y)
        sx,sy=x.sum(),y.sum()
        slope=(n*(x*y).sum()-sx*sy)/(n*(x**2).sum()-sx**2)
        dd=slope/max(cur,1)*100
        vol=float(np.std(np.diff(closes[-30:])/closes[-30:-1]))*math.sqrt(252) if len(closes)>30 else 0.02
        for lbl,days in [("1 Month",22),("3 Months",66),("6 Months",130),("12 Months",252)]:
            base=cur*(1+dd/100*days)
            margin=vol*math.sqrt(days)*cur*0.5
            forecasts.append({"period":lbl,"days":days,"base":round(base,2),
                              "bull":round(base+margin,2),"bear":round(base-margin*0.75,2),
                              "chg":round((base-cur)/max(cur,1)*100,2)})
    return {
        "score":score,"verdict":verdict,
        "breakdown":{"bh":L1,"val":L2,"tech":L3,"inst":L4},
        "findings":finds[:8],
        "rsi":rsi,"macd":macd,"adx":adx,"bb":bb,"stoch":stch,
        "ema20":ema20,"ema50":ema50,"ema200":ema200,
        "ema_signal":"Bullish" if ema20>ema50 else "Bearish",
        "rsi_signal":"Oversold" if rsi<30 else "Overbought" if rsi>70 else "Neutral",
        "macd_signal":"Bullish" if macd["hist"]>0 else "Bearish",
        "adx_strength":"Strong" if adx>25 else "Moderate" if adx>20 else "Weak",
        "stoch_signal":"Oversold" if stch["k"]<20 else "Overbought" if stch["k"]>80 else "Neutral",
        "above_50":above_50,"above_200":above_200,"golden_cross":golden,
        "forecasts":forecasts,
    }

def groq_analysis(data):
    if not GROQ_KEY: return None
    import requests as req
    finds_text="\n".join(f"{i+1}. {f['tx']}" for i,f in enumerate(data.get("findings",[])))
    prompt=f"""You are a senior equity research analyst at a top Indian brokerage.
Analyze this NSE stock quantitatively:
Stock: {data['name']} ({data['sym']}) | Sector: {data['sector']}
Price: ₹{data['price']} | 52W: ₹{data['l52']}–₹{data['h52']} | P/E: {data['pe']}x (Sector: {data['spe']}x)
Market Cap: {data['mc_fmt']} | Rev Growth: {data['rg']}% | Net Margin: {data['pm']}% | ROE: {data['roe']}%
Institutional: {data['inst']}% | Beta: {data['beta']} | RSI: {data['rsi']} | EMA: {data['ema_signal']}
Score: {data['score']}/100 | Verdict: {data['verdict']}
Findings: {finds_text}

Write professional report:
BUSINESS OVERVIEW
[2 sentences: core business, market position, moat]
FINANCIAL ASSESSMENT
[3 sentences: specific numbers, strengths, weaknesses]
KEY RISKS
1. [Specific risk with data]
2. [Specific risk with data]
ANALYTICAL SUMMARY
[2 sentences: overall picture, what to monitor]
RULES: Never say buy/sell/invest/recommend. No price targets. Professional English."""
    try:
        r=req.post(GROQ_URL,json={"model":GROQ_MDL,"max_tokens":600,"temperature":0.25,
            "messages":[{"role":"user","content":prompt}]},
            headers={"Authorization":f"Bearer {GROQ_KEY}","Content-Type":"application/json"},timeout=25)
        if r.ok: return r.json()["choices"][0]["message"]["content"]
    except: pass
    return None
