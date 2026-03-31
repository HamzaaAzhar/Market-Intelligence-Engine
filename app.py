"""
Scraper Intelligence System — Backend
"""
from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
import requests, json, csv, re, time, io, threading, hashlib, statistics, math, webbrowser
from urllib.parse import quote_plus
from datetime import datetime, timezone
from collections import Counter
import sys, os, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import scrapers + inject logger BEFORE any scraping starts
import scrapers.sites as _sites_mod
from scrapers.sites import (scrape_site, scrape_detail, set_session,
                            SCRAPERS, SITE_META, register_custom, _custom_scrapers)
from scrapers.brand_classifier import enrich_product

app = Flask(__name__)

# ── Store ──────────────────────────────────────────────────────────────────────
store = {
    "datasets":     {},
    "activity_log": [],
    "alerts":       [],
    "api_key":      "",
    "scan": {
        "running":False,"queries":[],"started":None,
        "steps":[],"pct":0,"current_site":"",
        "stats":{"scraped":0,"new":0,"dupes":0,"sites_done":[],"errors":[]},
    },
    "custom_sites":[],
}

def _ts(): return datetime.now().strftime("%H:%M:%S")
def _now(): return datetime.now(timezone.utc).isoformat()

def _log(msg, level="info"):
    """Append to live scan steps AND print to terminal."""
    entry = {"t":_ts(),"msg":msg,"level":level}
    store["scan"]["steps"].append(entry)
    if len(store["scan"]["steps"]) > 300:
        store["scan"]["steps"] = store["scan"]["steps"][-300:]
    print(f"[{_ts()}] {msg}")

# Inject logger into scraper module so every _get() call appears in activity log
_sites_mod.set_logger(_log)

def _all():
    out=[]
    for v in store["datasets"].values(): out.extend(v)
    return out

def _phash(p): return hashlib.md5(f"{p.get('item_id','')}|{p.get('source','')}".encode()).hexdigest()

# ── Scrape ─────────────────────────────────────────────────────────────────────
def run_scrape(query, pages=50, delay=1.5, fetch_details=False, filters=None):
    scan = store["scan"]
    scan.update({"running":True,"queries":[query],"started":_now(),
                 "steps":[],"pct":0,"current_site":"",
                 "stats":{"scraped":0,"new":0,"dupes":0,"sites_done":[],"errors":[]}})

    _log(f"Scan started · query: '{query}' · max {pages} pages/site")
    all_sites = list(SCRAPERS.keys()) + list(_custom_scrapers.keys())
    n = len(all_sites)
    _log(f"Platforms: {', '.join(all_sites)}")

    for si, site in enumerate(all_sites):
        scan["current_site"] = site
        meta = SITE_META.get(site, {})
        _log(f"[{site}] Starting · {meta.get('tech','?')} · ~{meta.get('per_page',40)} products/page")

        ds_key = f"{site}::{query}"
        raw = []; page = 1; empty_streak = 0
        per_page = meta.get("per_page", 40)
        total_pages_known = None  # set after first page if site returns totalResults

        while page <= pages:
            _log(f"[{site}] Fetching page {page}{f'/{total_pages_known}' if total_pages_known else ''}…")
            items = scrape_site(site, query, page)

            # --- Extract total page count from first result (Daraz returns it) ---
            if page == 1 and items and total_pages_known is None:
                # scrape_site may attach _total_results on the first item for Daraz
                total_results = items[0].get("_total_results") if items else None
                if total_results:
                    total_pages_known = math.ceil(int(total_results) / per_page)
                    effective_pages  = min(total_pages_known, pages)
                    _log(f"[{site}] totalResults={total_results} → {total_pages_known} pages (fetching up to {effective_pages})", "ok")
                else:
                    effective_pages = pages
            elif page == 1:
                effective_pages = pages

            if not items:
                empty_streak += 1
                if empty_streak >= 2:
                    _log(f"[{site}] No more results after page {page-1}", "ok")
                    break
                _log(f"[{site}] Page {page} empty (will retry once)", "warn")
            else:
                empty_streak = 0
                raw.extend(items)
                found_so_far = len(raw)
                _log(f"[{site}] Page {page} done · +{len(items)} · running total {found_so_far}", "ok")
                # Stop early if we've already retrieved all known results
                if total_pages_known and page >= total_pages_known:
                    _log(f"[{site}] All {total_pages_known} pages retrieved", "ok")
                    break

            scan["pct"] = max(1, int(((si + page/max(effective_pages,1))/n)*88))
            page += 1
            if page <= effective_pages and items:
                time.sleep(delay)

        # Enrich
        _log(f"[{site}] Enriching {len(raw)} products…")
        for p in raw:
            p["query"] = query
            p["scraped_at"] = _now()
            if not p.get("_hash"): p["_hash"] = _phash(p)
            enrich_product(p)

        # Apply filters
        if filters:
            before = len(raw)
            def _ok(p):
                pr = p.get("price_pkr")
                if filters.get("min_price") and pr and pr < float(filters["min_price"]): return False
                if filters.get("max_price") and pr and pr > float(filters["max_price"]): return False
                if filters.get("min_rating") and (p.get("rating") or 0) < float(filters["min_rating"]): return False
                return True
            raw = [p for p in raw if _ok(p)]
            if len(raw) < before:
                _log(f"[{site}] Filter: {before} → {len(raw)} products")

        # Dedup
        existing = {p["_hash"] for p in store["datasets"].get(ds_key,[])}
        unique   = [p for p in raw if p["_hash"] not in existing]
        dupes    = len(raw) - len(unique)

        if fetch_details and unique:
            sample = unique[:min(8,len(unique))]
            _log(f"[{site}] Fetching details for {len(sample)} products…")
            for p in sample:
                scrape_detail(p); enrich_product(p)

        if ds_key not in store["datasets"]: store["datasets"][ds_key] = []
        store["datasets"][ds_key].extend(unique)
        scan["stats"]["scraped"] += len(raw)
        scan["stats"]["new"]     += len(unique)
        scan["stats"]["dupes"]   += dupes
        scan["stats"]["sites_done"].append(site)
        _log(f"[{site}] Complete · {len(unique)} new · {dupes} dupes · {len(raw)} total", "ok")

        # Discount alerts
        for p in unique:
            m = re.search(r"(\d+)", str(p.get("discount","")))
            if m and int(m.group(1)) >= 40:
                store["alerts"].insert(0,{"type":"high_discount","title":f"{m.group(1)}% Discount",
                    "body":p.get("name","")[:70],"site":site,"price":p.get("price_pkr"),
                    "disc":int(m.group(1)),"url":p.get("product_url",""),"ts":_ts()})

    scan["pct"]=100; scan["running"]=False; scan["current_site"]=""
    total_new = scan["stats"]["new"]
    _log(f"Scan complete · {total_new} new products · {n} platforms done", "ok")

    entry = {"query":query,"time":_now(),"ts":_ts(),"stats":dict(scan["stats"]),"pages":pages,
             "session_insights":_session_insights(query)}
    store["activity_log"].insert(0, entry)
    store["activity_log"] = store["activity_log"][:100]
    store["alerts"] = store["alerts"][:100]
    return entry

def _session_insights(query):
    ap    = [p for p in _all() if p.get("query")==query]
    prices= [p["price_pkr"] for p in ap if p.get("price_pkr")]
    discs = [int(m.group(1)) for p in ap for m in [re.search(r"(\d+)",str(p.get("discount","")))] if m]
    cats  = Counter((p.get("category_classified") or "General") for p in ap)
    return {"query":query,"total":len(ap),
            "avg_price":round(statistics.mean(prices),0) if prices else 0,
            "med_price":round(statistics.median(prices),0) if prices else 0,
            "avg_disc":round(statistics.mean(discs),1) if discs else 0,
            "top_cat":cats.most_common(1)[0][0] if cats else "N/A"}

# ── Analytics ──────────────────────────────────────────────────────────────────
def insights(products):
    if not products: return {}
    prices  = [p["price_pkr"] for p in products if p.get("price_pkr") and p["price_pkr"]>0]
    ratings = [p["rating"]    for p in products if p.get("rating",0)>0]
    sel_c   = Counter(p.get("seller_name","?")      for p in products if p.get("seller_name") not in("N/A","","?"))
    br_c    = Counter(p.get("brand_classified","?") for p in products if p.get("brand_classified") not in("N/A","Unknown","?",""))
    src_c   = Counter(p.get("source","?")           for p in products)
    cat_c   = Counter((p.get("category_classified") or p.get("category_path","?").split(">")[0].strip()) for p in products)
    disc_v  = [int(m.group(1)) for p in products for m in [re.search(r"(\d+)",str(p.get("discount","")))] if m]
    pb={"<1K":0,"1K-5K":0,"5K-15K":0,"15K-50K":0,"50K+":0}
    for pr in prices:
        if pr<1000:pb["<1K"]+=1
        elif pr<5000:pb["1K-5K"]+=1
        elif pr<15000:pb["5K-15K"]+=1
        elif pr<50000:pb["15K-50K"]+=1
        else:pb["50K+"]+=1
    return {"total":len(products),"with_price":len(prices),
        "price_min":round(min(prices),0) if prices else 0,"price_max":round(max(prices),0) if prices else 0,
        "price_avg":round(statistics.mean(prices),0) if prices else 0,
        "price_median":round(statistics.median(prices),0) if prices else 0,
        "price_stdev":round(statistics.stdev(prices),0) if len(prices)>1 else 0,
        "price_buckets":pb,"avg_rating":round(statistics.mean(ratings),2) if ratings else 0,
        "rating_bins":[len([p for p in products if int(p.get("rating",0))==i]) for i in range(6)],
        "pct_discounted":round(len(disc_v)/len(products)*100,1) if products else 0,
        "avg_discount":round(statistics.mean(disc_v),1) if disc_v else 0,
        "unique_sellers":len(sel_c),"unique_brands":len(br_c),
        "top_sellers":sel_c.most_common(12),"top_brands":br_c.most_common(12),
        "top_categories":cat_c.most_common(12),"by_source":dict(src_c),
        "datasets":list(store["datasets"].keys())}

def supplier_intel(products, site=None, cat=None, brand=None):
    prods=products
    if site:  prods=[p for p in prods if p.get("source")==site]
    if cat:   prods=[p for p in prods if cat.lower() in (p.get("category_classified","")).lower()]
    if brand: prods=[p for p in prods if brand.lower() in (p.get("brand_classified","")).lower()]
    sellers={}
    for p in prods:
        name=p.get("seller_name","?"); src=p.get("source","?"); key=f"{src}::{name}"
        if key not in sellers: sellers[key]={"name":name,"source":src,"products":[],"prices":[],"ratings":[],"brands":set(),"cats":set()}
        s=sellers[key]; s["products"].append(p)
        if p.get("price_pkr"): s["prices"].append(p["price_pkr"])
        if p.get("rating",0)>0: s["ratings"].append(p["rating"])
        if p.get("brand_classified") not in("N/A","Unknown",""): s["brands"].add(p["brand_classified"])
        if p.get("category_classified"): s["cats"].add(p["category_classified"])
    result=[]
    for key,s in sellers.items():
        count=len(s["products"]); prices=s["prices"]; ratings=s["ratings"]
        avg_p=round(statistics.mean(prices),0) if prices else 0
        avg_r=round(statistics.mean(ratings),2) if ratings else 0
        stdev=round(statistics.stdev(prices),0) if len(prices)>1 else 0
        quality=round(min(avg_r/5*35,35)+min(math.log(count+1)/math.log(50)*25,25)+min(len(s["brands"])/5*20,20)+max(0,20-(stdev/max(avg_p,1)*100)/5 if avg_p else 0),1)
        disc_v=[int(m.group(1)) for p in s["products"] for m in [re.search(r"(\d+)",str(p.get("discount","")))] if m]
        result.append({"key":key,"name":s["name"],"source":s["source"],"product_count":count,"avg_price":avg_p,
            "min_price":round(min(prices),0) if prices else 0,"max_price":round(max(prices),0) if prices else 0,
            "price_stdev":stdev,"avg_rating":avg_r,"unique_brands":len(s["brands"]),"brands":list(s["brands"])[:5],
            "categories":list(s["cats"])[:4],"avg_discount":round(statistics.mean(disc_v),1) if disc_v else 0,
            "quality_score":quality,"risk":"LOW" if quality>=65 else "MEDIUM" if quality>=40 else "HIGH"})
    return sorted(result,key=lambda x:x["quality_score"],reverse=True)

def arbitrage():
    by_name={}
    for p in _all():
        if not p.get("price_pkr"): continue
        key=re.sub(r"[^a-z0-9 ]","",p.get("name","").lower())[:40].strip()
        if not key: continue
        if key not in by_name: by_name[key]=[]
        by_name[key].append(p)
    arb=[]
    for name,prods in by_name.items():
        sources={}
        for p in prods:
            src=p.get("source","")
            if src not in sources or p["price_pkr"]<sources[src]["price"]:
                sources[src]={"price":p["price_pkr"],"url":p.get("product_url",""),"name":p.get("name","")}
        if len(sources)<2: continue
        prices=[v["price"] for v in sources.values()]; lo=min(prices); hi=max(prices)
        if hi<=0: continue
        pct=round((hi-lo)/hi*100,1)
        if pct<5: continue
        arb.append({"name":list(sources.values())[0]["name"][:60],"sites":{k:v["price"] for k,v in sources.items()},
                    "low":lo,"high":hi,"saving_pct":pct,"saving_abs":round(hi-lo,0)})
    return sorted(arb,key=lambda x:x["saving_pct"],reverse=True)[:30]

def market_gaps(products):
    if not products: return {"gaps":[],"category_sites":{},"sites":[]}
    sites=list({p.get("source","?") for p in products})
    cats=list({(p.get("category_classified") or "General") for p in products if p.get("price_pkr")})
    cat_site={}
    for p in products:
        cat=p.get("category_classified") or "General"; src=p.get("source","?"); key=(cat,src)
        if key not in cat_site: cat_site[key]={"prices":[],"ratings":[],"count":0}
        cat_site[key]["count"]+=1
        if p.get("price_pkr"): cat_site[key]["prices"].append(p["price_pkr"])
        if p.get("rating",0)>0: cat_site[key]["ratings"].append(p["rating"])
    gaps=[]
    for cat in cats[:20]:
        for rname,rlo,rhi in [("Budget <1K",0,1000),("Economy 1K-5K",1000,5000),("Mid 5K-15K",5000,15000),("Premium 15K+",15000,1e9)]:
            in_range=[p for p in products if (p.get("category_classified") or "General")==cat and p.get("price_pkr") and rlo<=p["price_pkr"]<rhi]
            if not in_range: continue
            sites_cov=len({p.get("source") for p in in_range})
            all_r=[p["rating"] for p in in_range if p.get("rating",0)>0]
            avg_r=round(statistics.mean(all_r),2) if all_r else 0
            site_ps={src:round(statistics.mean([p["price_pkr"] for p in in_range if p.get("source")==src and p.get("price_pkr")]),0) for src in sites if any(p.get("source")==src and p.get("price_pkr") for p in in_range)}
            gap=round(100-min(len(in_range)/20*35,35)-min(sites_cov/max(len(sites),1)*35,35)-min(avg_r/5*30,30),1)
            if gap<25: continue
            gaps.append({"category":cat,"price_range":rname,"count":len(in_range),"sites_covering":sites_cov,
                "total_sites":len(sites),"avg_price":round(statistics.mean([p["price_pkr"] for p in in_range if p.get("price_pkr")]),0),
                "avg_rating":avg_r,"gap_score":gap,"opportunity":"HIGH" if gap>=70 else "MEDIUM" if gap>=45 else "LOW",
                "site_prices":site_ps,
                "cheapest_site":min(site_ps,key=site_ps.get) if site_ps else "",
                "priciest_site":max(site_ps,key=site_ps.get) if site_ps else "",
                "insight":f"{cat} · {rname}: {sites_cov}/{len(sites)} platforms · avg ★{avg_r}"})
    cat_perf={}
    for cat in cats[:15]:
        cat_perf[cat]={}
        for src in sites:
            d=cat_site.get((cat,src),{})
            if d.get("count",0)>0:
                cat_perf[cat][src]={"count":d["count"],"avg_price":round(statistics.mean(d["prices"]),0) if d["prices"] else 0,"avg_rating":round(statistics.mean(d["ratings"]),2) if d["ratings"] else 0}
    return {"gaps":sorted(gaps,key=lambda x:x["gap_score"],reverse=True)[:40],"category_sites":cat_perf,"sites":sites}

def price_trends(products):
    by_src={}
    for p in products:
        src=p.get("source","?")
        if src not in by_src: by_src[src]=[]
        if p.get("price_pkr"): by_src[src].append(p["price_pkr"])
    return {"by_source":{src:{"count":len(ps),"avg":round(statistics.mean(ps),0),"median":round(statistics.median(ps),0),"min":round(min(ps),0),"max":round(max(ps),0)} for src,ps in by_src.items() if ps}}

def _sched_loop():
    while store.get("sched_active"):
        for job in store.get("sched_jobs",[]):
            if not store.get("sched_active"): return
            run_scrape(job["query"],pages=job.get("pages",3),delay=2.0); time.sleep(5)
        for _ in range(store.get("sched_interval",15)*60):
            if not store.get("sched_active"): return
            time.sleep(1)

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/site-meta")
def api_site_meta(): return jsonify(SITE_META)

@app.route("/api/test")
def api_test():
    res={}
    for site,base in [("daraz.pk","https://www.daraz.pk"),("shophive.com","https://www.shophive.com"),
                       ("carrefour.pk","https://www.carrefour.pk"),("metro.pk","https://www.metro-online.pk"),
                       ("alfatah.pk","https://alfatah.pk")]:
        try:
            r=requests.get(base,timeout=(6,12),verify=False,headers={"Accept":"text/html","User-Agent":"Mozilla/5.0"})
            res[site]={"ok":r.status_code<400,"status":r.status_code}
        except requests.exceptions.Timeout: res[site]={"ok":False,"error":"timeout"}
        except Exception as e: res[site]={"ok":False,"error":str(e)[:60]}
    return jsonify(res)

@app.route("/api/scrape",methods=["POST"])
def api_scrape():
    if store["scan"]["running"]: return jsonify({"error":"Scan already running"}),400
    b=request.get_json(force=True)
    queries=[q.strip() for q in b.get("queries",[b.get("query","")]) if q.strip()]
    pages=min(int(b.get("pages",50)),200); delay=float(b.get("delay",1.5))
    fetch_details=bool(b.get("fetch_details",False)); filters=b.get("filters") or {}
    if not queries: return jsonify({"error":"Query required"}),400
    def _run():
        for q in queries: run_scrape(q,pages,delay,fetch_details,filters or None)
    threading.Thread(target=_run,daemon=True).start()
    return jsonify({"status":"started","queries":queries})

@app.route("/api/scan/status")
def api_scan_status(): return jsonify(store["scan"])

@app.route("/api/datasets")
def api_datasets(): return jsonify({k:len(v) for k,v in store["datasets"].items()})

@app.route("/api/dataset/<path:key>")
def api_dataset(key):
    from urllib.parse import unquote
    key = unquote(key)   # JS encodeURIComponent sends %3A%3A; Flask path converter keeps it encoded
    prods=store["datasets"].get(key,[]); return jsonify({"key":key,"count":len(prods),"products":prods})

@app.route("/api/dataset/delete",methods=["POST"])
def api_del():
    key=request.get_json(force=True).get("key",""); store["datasets"].pop(key,None); return jsonify({"status":"deleted"})

@app.route("/api/insights")
def api_insights():
    site=request.args.get("site",""); query=request.args.get("query","")
    prods=[]
    for k,v in store["datasets"].items():
        pts=k.split("::",1)
        if site  and pts[0]!=site: continue
        if query and (len(pts)<2 or pts[1]!=query): continue
        prods.extend(v)
    if not site and not query: prods=_all()
    return jsonify(insights(prods))

@app.route("/api/insights/summary")
def api_summary():
    prods=_all(); ins=insights(prods)
    per={}
    for k,v in store["datasets"].items():
        ps=[p["price_pkr"] for p in v if p.get("price_pkr")]
        per[k]={"count":len(v),"avg_price":round(statistics.mean(ps),0) if ps else 0,
                "min":round(min(ps),0) if ps else 0,"max":round(max(ps),0) if ps else 0,
                "top_brands":Counter(p.get("brand_classified","?") for p in v if p.get("brand_classified") not in("N/A","Unknown","")).most_common(5)}
    return jsonify({"global":ins,"per_dataset":per,"price_trends":price_trends(prods),"arbitrage":arbitrage()[:5]})

@app.route("/api/insights/compare")
def api_compare():
    a=request.args.get("a",""); b=request.args.get("b","")
    return jsonify({"a":{"key":a,"insights":insights(store["datasets"].get(a,[]))},"b":{"key":b,"insights":insights(store["datasets"].get(b,[]))}})

@app.route("/api/supplier-intel")
def api_supplier():
    r=supplier_intel(_all(),request.args.get("site","") or None,request.args.get("category","") or None,request.args.get("brand","") or None)
    return jsonify({"suppliers":r,"total":len(r)})

@app.route("/api/arbitrage")
def api_arbitrage(): return jsonify({"items":arbitrage()})

@app.route("/api/market-gaps")
def api_market_gaps(): return jsonify(market_gaps(_all()))

@app.route("/api/alerts")
def api_alerts(): return jsonify({"alerts":store["alerts"][:60]})

@app.route("/api/alerts/clear",methods=["POST"])
def api_alerts_clear(): store["alerts"].clear(); return jsonify({"status":"cleared"})

@app.route("/api/activity-log")
def api_activity_log(): return jsonify({"log":store["activity_log"]})

@app.route("/api/activity-log/clear",methods=["POST"])
def api_log_clear(): store["activity_log"].clear(); return jsonify({"status":"cleared"})

@app.route("/api/product/details",methods=["POST"])
def api_product_details():
    b=request.get_json(force=True); item_id=str(b.get("item_id",""))
    match=next((p for p in _all() if p.get("item_id")==item_id),None)
    if not match: return jsonify({"error":"Not found"}),404
    scrape_detail(match); enrich_product(match); return jsonify(match)

@app.route("/api/custom-site/probe",methods=["POST"])
def api_probe():
    b=request.get_json(force=True); url=b.get("url","").strip()
    if not url: return jsonify({"error":"URL required"}),400
    if not url.startswith("http"): url="https://"+url
    from urllib.parse import urlparse
    domain=urlparse(url).netloc.replace("www.","")
    result={"domain":domain,"url":url,"pages":{},"tech_hints":[],"search_url":""}
    try:
        r=requests.get(url,timeout=(8,15),headers={"Accept":"text/html","User-Agent":"Mozilla/5.0"},verify=False)
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(r.text,"html.parser")
        result["pages"]["home_title"]=soup.title.string if soup.title else ""
        ht=r.text.lower()
        if "shopify" in ht: result["tech_hints"].append("Shopify")
        if "magento" in ht or "mage-init" in ht: result["tech_hints"].append("Magento 2")
        if "woocommerce" in ht: result["tech_hints"].append("WooCommerce")
        if "__next_data__" in ht: result["tech_hints"].append("Next.js")
    except: pass
    q=quote_plus(b.get("test_query","laptop"))
    for su in [f"{url}/search?q={q}",f"{url}/search?type=product&q={q}",f"{url}/catalogsearch/result/?q={q}"]:
        try:
            rs=requests.get(su,timeout=(8,15),headers={"Accept":"text/html","User-Agent":"Mozilla/5.0"},verify=False)
            if rs.status_code==200:
                result["search_url"]=su; break
        except: pass
    return jsonify(result)

@app.route("/api/custom-site/build",methods=["POST"])
def api_build():
    b=request.get_json(force=True); probe=b.get("probe",{}); api_key=b.get("api_key","") or store.get("api_key","")
    if not api_key: return jsonify({"error":"API key required"}),400
    prompt=f"""Write a Python scraper function for this site:
Domain: {probe.get('domain','')} | Platform: {', '.join(probe.get('tech_hints',['Unknown']))}
Search URL: {probe.get('search_url','')}

Function name: scrape_{probe.get('domain','site').replace('.','_').replace('-','_')}(query, page=1)
Returns: list of dicts with: item_id, name, price_pkr, brand_supplier, category_path, rating, reviews, image_url, product_url
Use requests with timeout=(8,20), verify=False. Return [] on any error.
Only use: requests, BeautifulSoup, re, json, hashlib, urllib.parse
Return ONLY the function code."""
    def gen():
        try:
            resp=requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":api_key,"anthropic-version":"2023-06-01","content-type":"application/json","accept":"text/event-stream"},
                json={"model":"claude-sonnet-4-6","max_tokens":2000,"stream":True,"messages":[{"role":"user","content":prompt}]},
                stream=True,timeout=120)
            for line in resp.iter_lines():
                if line: yield line.decode("utf-8")+"\n\n"
        except Exception as e: yield f"data: {{\"error\":\"{str(e)}\"}}\n\n"
    return Response(stream_with_context(gen()),mimetype="text/event-stream",headers={"Cache-Control":"no-cache"})

@app.route("/api/custom-site/register",methods=["POST"])
def api_register():
    b=request.get_json(force=True); domain=b.get("domain",""); code=b.get("code","")
    if not domain or not code: return jsonify({"error":"domain and code required"}),400
    try:
        from bs4 import BeautifulSoup as BS
        ns={}
        exec(code,{"requests":requests,"BeautifulSoup":BS,"re":re,"json":json,"hashlib":hashlib,"quote_plus":quote_plus,"time":time},ns)
        fn_name=[k for k in ns if k.startswith("scrape_")][0]; fn=ns[fn_name]
        register_custom(domain,fn); store["custom_sites"].append({"domain":domain,"fn":fn_name,"status":"active"})
        return jsonify({"status":"registered","domain":domain})
    except Exception as e: return jsonify({"error":str(e)}),400

@app.route("/api/custom-sites")
def api_custom_sites(): return jsonify({"sites":[{"domain":s["domain"],"fn":s["fn"],"status":s["status"]} for s in store["custom_sites"]]})

@app.route("/api/ai/stream",methods=["POST"])
def api_ai():
    b=request.get_json(force=True); prompt=b.get("prompt","")
    api_key=b.get("api_key","") or store.get("api_key","")
    if not api_key: return jsonify({"error":"No API key. Add it in Settings."}),400
    if not prompt: return jsonify({"error":"No prompt"}),400
    def gen():
        try:
            resp=requests.post("https://api.anthropic.com/v1/messages",
                headers={"x-api-key":api_key,"anthropic-version":"2023-06-01","content-type":"application/json","accept":"text/event-stream"},
                json={"model":"claude-sonnet-4-6","max_tokens":2000,"stream":True,"messages":[{"role":"user","content":prompt}]},
                stream=True,timeout=120)
            if not resp.ok:
                try: err=resp.json().get("error",{}).get("message","API error")
                except: err=f"HTTP {resp.status_code}"
                yield f"data: {{\"type\":\"error\",\"error\":\"{err}\"}}\n\n"; return
            for line in resp.iter_lines():
                if line: yield line.decode("utf-8")+"\n\n"
        except Exception as e: yield f"data: {{\"type\":\"error\",\"error\":\"{str(e)}\"}}\n\n"
    return Response(stream_with_context(gen()),mimetype="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.route("/api/settings",methods=["GET","POST"])
def api_settings():
    if request.method=="POST":
        b=request.get_json(force=True)
        if "api_key" in b: store["api_key"]=b["api_key"]
        return jsonify({"status":"saved"})
    return jsonify({"api_key_set":bool(store["api_key"])})

@app.route("/api/scheduler/start",methods=["POST"])
def api_sched_start():
    b=request.get_json(force=True)
    if store.get("sched_active"): return jsonify({"error":"Already running"}),400
    jobs=[{"query":q.strip(),"pages":int(b.get("pages",3))} for q in b.get("queries",[]) if q.strip()]
    if not jobs: return jsonify({"error":"Queries required"}),400
    store.update({"sched_active":True,"sched_jobs":jobs,"sched_interval":int(b.get("interval",15))})
    threading.Thread(target=_sched_loop,daemon=True).start()
    return jsonify({"status":"started"})

@app.route("/api/scheduler/stop",methods=["POST"])
def api_sched_stop(): store["sched_active"]=False; return jsonify({"status":"stopped"})

@app.route("/api/scheduler/status")
def api_sched_status(): return jsonify({"active":store.get("sched_active",False),"jobs":store.get("sched_jobs",[]),"interval":store.get("sched_interval",15)})

@app.route("/api/clear",methods=["POST"])
def api_clear():
    key=(request.get_json(force=True) or {}).get("key","")
    if key: store["datasets"].pop(key,None)
    else: store["datasets"].clear()
    return jsonify({"status":"cleared"})

@app.route("/api/export/csv",methods=["POST"])
def export_csv():
    b=request.get_json(force=True); key=b.get("key","")
    prods=store["datasets"].get(key,_all()) if key else _all()
    if not prods: return jsonify({"error":"No data"}),400
    flat=[]
    for p in prods:
        row={k:v for k,v in p.items() if k not in("specifications","_hash","reviews_list")}
        for k,v in p.get("specifications",{}).items(): row[f"spec_{k}"]=v
        flat.append(row)
    keys=list(dict.fromkeys(k for r in flat for k in r))
    out=io.StringIO(); w=csv.DictWriter(out,fieldnames=keys,extrasaction="ignore")
    w.writeheader(); w.writerows(flat)
    mem=io.BytesIO(out.getvalue().encode("utf-8-sig")); mem.seek(0)
    safe=re.sub(r"[^\w]","_",key or "all")
    return send_file(mem,mimetype="text/csv",as_attachment=True,download_name=f"sis_{safe}.csv")

@app.route("/api/export/json",methods=["POST"])
def export_json():
    b=request.get_json(force=True); key=b.get("key","")
    prods=store["datasets"].get(key,_all()) if key else _all()
    if not prods: return jsonify({"error":"No data"}),400
    mem=io.BytesIO(json.dumps(prods,ensure_ascii=False,indent=2).encode()); mem.seek(0)
    safe=re.sub(r"[^\w]","_",key or "all")
    return send_file(mem,mimetype="application/json",as_attachment=True,download_name=f"sis_{safe}.json")

if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 5000))

    print("══════════════════════════════════════════════════")
    print("  Scraper Intelligence System")
    print(f"  Open: http://0.0.0.0:{port}")
    print("  Stop: Ctrl+C")
    print("══════════════════════════════════════════════════")

    app.run(host="0.0.0.0", port=port, debug=False)