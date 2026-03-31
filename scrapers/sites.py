"""
SIS Scrapers - Fixed version
Key: 5s connect / 12s read timeout, log BEFORE every request, isolated sessions
"""
import requests, re, json, time, hashlib, random
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SITE_META = {
    "daraz.pk":    {"per_page":40,"tech":"AJAX JSON","color":"#f57224",
                    "fact":"Daraz returns 40 products/page via AJAX. Requires homepage cookie warm-up first."},
    "shophive.com":{"per_page":24,"tech":"Magento 2","color":"#1a73e8",
                    "fact":"Shophive uses Magento 2. 24 products per search page via /catalogsearch/result/"},
    "carrefour.pk":{"per_page":40,"tech":"Next.js","color":"#c8102e",
                    "fact":"Carrefour PK is Next.js — product data is in __NEXT_DATA__ JSON embedded in each page."},
    "metro.pk":    {"per_page":30,"tech":"Magento 2","color":"#003087",
                    "fact":"Metro Online (metro-online.pk) uses Magento 2. ~30 products/page with wholesale pricing."},
    "alfatah.pk":  {"per_page":20,"tech":"Shopify","color":"#00843d",
                    "fact":"Alfatah is Shopify. The /search/suggest.json endpoint returns clean structured product data."},
}

_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
def _ua(): return random.choice(_UA)

# ONE session per site — prevents cookie cross-contamination
_SESS = {}
def _sess(site):
    if site not in _SESS:
        s = requests.Session()
        s.verify = False
        s.headers.update({"Accept-Language":"en-US,en;q=0.9","Accept-Encoding":"gzip, deflate"})
        _SESS[site] = s
    return _SESS[site]

_session = None
def set_session(s): global _session; _session = s

# External logger — app.py injects this so scrapers can log to activity feed
_logger = print
def set_logger(fn): global _logger; _logger = fn

# SHORT timeouts — fail fast, don't hang
CT = 6   # connect timeout seconds
RT = 15  # read timeout seconds

def _get(site, url, hdrs=None, json_req=False):
    h = {"User-Agent":_ua(),
         "Accept":"application/json,*/*;q=0.5" if json_req else "text/html,application/xhtml+xml,*/*;q=0.8"}
    if hdrs: h.update(hdrs)
    _logger(f"  → GET {url[:80]}")
    try:
        r = _sess(site).get(url, headers=h, timeout=(CT,RT), verify=False, allow_redirects=True)
        _logger(f"  ← {r.status_code} ({len(r.content)} bytes)")
        return r
    except requests.exceptions.SSLError:
        try:
            r = requests.get(url, headers=h, timeout=(CT,RT), verify=False)
            _logger(f"  ← {r.status_code} [ssl-bypass]")
            return r
        except Exception as e: _logger(f"  ✗ SSL-FAIL: {str(e)[:60]}"); return None
    except requests.exceptions.ConnectTimeout: _logger(f"  ✗ Connect timeout ({CT}s)"); return None
    except requests.exceptions.ReadTimeout:    _logger(f"  ✗ Read timeout ({RT}s)"); return None
    except requests.exceptions.ConnectionError as e: _logger(f"  ✗ Conn error: {str(e)[:60]}"); return None
    except Exception as e: _logger(f"  ✗ Error: {str(e)[:60]}"); return None

def _cp(v):
    if not v: return None
    c = re.sub(r"[^\d.]","",str(v).replace(",",""))
    try: return float(c) if c else None
    except: return None

def _h(a,b=""): return hashlib.md5(f"{a}|{b}".encode()).hexdigest()[:16]

def _base(src):
    return {"item_id":"","name":"N/A","price_pkr":None,"original_price_pkr":None,
            "discount":"","brand_supplier":"N/A","seller_name":src,"seller_id":"",
            "category_path":"N/A","rating":0.0,"reviews":0,"location":"N/A",
            "image_url":"","product_url":"","description":"","specifications":{},
            "reviews_list":[],"details_fetched":False,"source":src,"_hash":""}

def _img(el):
    if not el: return ""
    for a in ("src","data-src","data-lazy","data-original"):
        v = el.get(a,"")
        if v and len(v)>8 and "data:image" not in v:
            if v.startswith("//"): v="https:"+v
            return v.strip()
    return ""

def _disc(c,o):
    if c and o and o>c>0: return f"{round((o-c)/o*100)}%"
    return ""

def _jblob(html, *keys):
    for key in keys:
        for pat in [rf'"{re.escape(key)}"\s*:\s*(\[[\s\S]{{10,}}\])\s*[,\}}]',
                    rf"'{re.escape(key)}'\s*:\s*(\[[\s\S]{{10,}}\])\s*[,\}}]"]:
            for m in re.finditer(pat, html):
                try:
                    d = json.loads(m.group(1))
                    if d and isinstance(d,list) and d and isinstance(d[0],dict): return d
                except: pass
    return []


# ─── DARAZ ──────────────────────────────────────────────────────────────────
_daraz_warmed = False
def scrape_daraz(query, page=1, **kw):
    global _daraz_warmed
    B = "https://www.daraz.pk"; q = quote_plus(query)
    if not _daraz_warmed:
        _logger("  Warming Daraz session (homepage cookie)…")
        _get("daraz.pk", B, hdrs={"Accept":"text/html","Referer":B})
        _daraz_warmed = True; time.sleep(0.8)

    ajax = f"{B}/catalog/?ajax=true&q={q}&page={page}&sort=popularity&from=input"
    r = _get("daraz.pk", ajax, hdrs={"Referer":f"{B}/catalog/?q={q}","X-Requested-With":"XMLHttpRequest"}, json_req=True)
    if r and r.status_code==200:
        if "json" in r.headers.get("Content-Type",""):
            try:
                jd = r.json()
                items = jd.get("mods",{}).get("listItems",[])
                total_results = (jd.get("mods",{}).get("totalResults") or
                                 jd.get("mainInfo",{}).get("totalResults") or 0)
                if items:
                    out = [_pd(i) for i in items if isinstance(i,dict)]
                    out = [p for p in out if p]
                    if out and total_results:
                        out[0]["_total_results"] = total_results
                    _logger(f"  ✓ Daraz AJAX: {len(out)} products (total={total_results})")
                    return out
            except: pass
        items = _jblob(r.text,"listItems")
        if items:
            out = [_pd(i) for i in items if isinstance(i,dict)]
            _logger(f"  ✓ Daraz embedded JSON: {len(out)} products")
            return [p for p in out if p]

    r2 = _get("daraz.pk", f"{B}/catalog/?q={q}&page={page}", hdrs={"Accept":"text/html","Referer":f"{B}/"})
    if r2 and r2.status_code==200:
        # Try to extract totalResults from __NEXT_DATA__ first
        total_nd = 0
        nd_m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>([\s\S]*?)</script>', r2.text)
        if nd_m:
            try:
                nd = json.loads(nd_m.group(1))
                total_nd = (nd.get("props",{}).get("pageProps",{}).get("initialProps",{})
                              .get("pageData",{}).get("mainInfo",{}).get("totalResults",0) or
                            nd.get("props",{}).get("pageProps",{}).get("pageData",{})
                              .get("mainInfo",{}).get("totalResults",0))
            except: pass
        items = _jblob(r2.text,"listItems")
        if items:
            out = [_pd(i) for i in items if isinstance(i,dict)]
            out = [p for p in out if p]
            if out and total_nd:
                out[0]["_total_results"] = total_nd
            _logger(f"  ✓ Daraz HTML-JSON: {len(out)} products (total={total_nd or '?'})")
            return out
        soup = BeautifulSoup(r2.text,"html.parser")
        cards = soup.select("div[data-item-id],div[data-qa-locator='product-item']")
        if cards:
            out = _daraz_dom(cards,B)
            _logger(f"  ✓ Daraz DOM: {len(out)} products")
            return out
    _logger("  ✗ Daraz: no results"); return []

def _pd(it):
    p=_base("daraz.pk")
    url=it.get("productUrl","") or ""
    if url and not url.startswith("http"): url="https://www.daraz.pk"+url
    cats=it.get("categories",[])
    cat=(" > ".join(c.get("name","") for c in cats if isinstance(c,dict) and c.get("name")) if isinstance(cats,list) else "")
    try:    rat=float(it.get("ratingScore",0) or 0)
    except: rat=0.0
    try:    rev=int(it.get("review",0) or 0)
    except: rev=0
    iid=str(it.get("itemId",it.get("skuId","")) or ""); sid=str(it.get("sellerId","") or "")
    c=_cp(it.get("price")); o=_cp(it.get("originalPrice"))
    p.update({"item_id":iid,"name":str(it.get("name","N/A") or "N/A"),
              "price_pkr":c,"original_price_pkr":o,"discount":str(it.get("discount","") or "") or _disc(c,o),
              "brand_supplier":str(it.get("brandName",it.get("brand","N/A")) or "N/A"),
              "seller_name":str(it.get("sellerName","daraz.pk") or "daraz.pk"),
              "seller_id":sid,"category_path":cat or "N/A","rating":rat,"reviews":rev,
              "location":str(it.get("location","N/A") or "N/A"),
              "image_url":str(it.get("image","") or ""),"product_url":url})
    p["_hash"]=_h(iid,sid); return p if p["name"] not in ("N/A","") else None

def _daraz_dom(cards,base):
    out=[]
    for card in cards[:40]:
        p=_base("daraz.pk")
        try:
            iid=card.get("data-item-id","")
            ne=card.select_one("[class*='title'],[class*='name'],a")
            pe=card.select_one("[class*='price']"); ie=card.select_one("img"); le=card.select_one("a[href]")
            name=ne.get_text(strip=True) if ne else ""
            if not name or len(name)<3: continue
            href=le["href"] if le and le.get("href") else ""
            if href and not href.startswith("http"): href=base+href
            iid=iid or _h(href or name,"daraz")
            p.update({"item_id":iid,"name":name,"price_pkr":_cp(pe.get_text() if pe else ""),
                       "image_url":_img(ie),"product_url":href}); p["_hash"]=_h(iid,"daraz"); out.append(p)
        except: continue
    return out

def scrape_daraz_detail(product):
    url=product.get("product_url","")
    if not url: return product
    r=_get("daraz.pk",url,hdrs={"Accept":"text/html"})
    if not r or r.status_code!=200: return product
    try:
        soup=BeautifulSoup(r.text,"html.parser")
        desc=soup.select_one(".pdp-product-desc,.product-description")
        product["description"]=desc.get_text(" ",strip=True)[:2000] if desc else ""
        specs={}
        for row in soup.select("table.specification tr"):
            cells=row.select("td")
            if len(cells)==2:
                k=cells[0].get_text(strip=True); v=cells[1].get_text(strip=True)
                if k: specs[k]=v
        product["specifications"]=specs; product["details_fetched"]=True
    except Exception as e: _logger(f"  Daraz detail err: {e}")
    return product


# ─── SHOPHIVE ────────────────────────────────────────────────────────────────
def scrape_shophive(query, page=1, **kw):
    B="https://www.shophive.com"; q=quote_plus(query)
    for url in [f"{B}/catalogsearch/result/index/?q={q}&p={page}",
                f"{B}/catalogsearch/result/?q={q}&p={page}"]:
        r=_get("shophive.com",url,hdrs={"Referer":f"{B}/"})
        if not r or r.status_code!=200: continue
        soup=BeautifulSoup(r.text,"html.parser")
        if soup.find(string=re.compile(r"no results|0 items",re.I)) and page>1: return []
        cards=(soup.select("li.product-item") or soup.select("ol.products li.item") or
               soup.select(".products-grid .item") or soup.select("[class*='product-item']"))
        if cards:
            out=_m2cards(cards,"shophive.com",B)
            if out: _logger(f"  ✓ Shophive DOM: {len(out)} products"); return out
        items=_jblob(r.text,"items","products")
        if items:
            out=[_gjson(i,"shophive.com",B) for i in items if isinstance(i,dict)]
            out=[p for p in out if p]
            if out: _logger(f"  ✓ Shophive JSON: {len(out)} products"); return out
    _logger("  ✗ Shophive: no results"); return []


# ─── CARREFOUR ───────────────────────────────────────────────────────────────
def scrape_carrefour(query, page=1, **kw):
    B="https://www.carrefour.pk"; q=quote_plus(query)
    html_url=f"{B}/search?q={q}&page={page}"
    r=_get("carrefour.pk",html_url,hdrs={"Referer":f"{B}/"})
    if r and r.status_code==200:
        # __NEXT_DATA__ is the most reliable source
        m=re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',r.text,re.DOTALL)
        if m:
            try:
                nd=json.loads(m.group(1))
                pp=nd.get("props",{}).get("pageProps",{})
                items=(pp.get("initialData",{}).get("hits") or pp.get("products") or
                       pp.get("hits") or pp.get("data",{}).get("hits") or [])
                if items:
                    out=[_pcf(i) for i in items if isinstance(i,dict)]
                    out=[p for p in out if p]
                    if out: _logger(f"  ✓ Carrefour NEXT_DATA: {len(out)} products"); return out
            except Exception as e: _logger(f"  Carrefour NEXT_DATA err: {e}")
        for key in ("hits","products","catalogueProducts","items"):
            items=_jblob(r.text,key)
            if items:
                out=[_pcf(i) for i in items if isinstance(i,dict)]
                out=[p for p in out if p]
                if out: _logger(f"  ✓ Carrefour {key}: {len(out)} products"); return out
        soup=BeautifulSoup(r.text,"html.parser")
        cards=(soup.select("[class*='product-card']") or soup.select("[class*='ProductCard']") or
               soup.select("[class*='product-item']") or soup.select("article"))
        if cards:
            out=_gdom(cards,"carrefour.pk",B)
            if out: _logger(f"  ✓ Carrefour DOM: {len(out)} products"); return out
    # API fallback
    for api in [f"{B}/api/2.0/page/custom/all-departments?slug=/search&q={q}&page={page}&size=40&lang=en",
                f"{B}/mafpk/search/v2/en-pk?q={q}&size=40&start={(page-1)*40}&lang=en"]:
        ra=_get("carrefour.pk",api,hdrs={"Accept":"application/json","Referer":html_url},json_req=True)
        if not ra or ra.status_code!=200: continue
        try:
            d=ra.json()
            items=(d.get("hits") or d.get("products") or d.get("items") or
                   d.get("data",{}).get("products") or d.get("results") or [])
            if items:
                out=[_pcf(i) for i in items if isinstance(i,dict)]
                out=[p for p in out if p]
                if out: _logger(f"  ✓ Carrefour API: {len(out)} products"); return out
        except: pass
    _logger("  ✗ Carrefour: no results"); return []

def _pcf(it):
    p=_base("carrefour.pk"); name=it.get("name",it.get("title",""))
    if not name or len(str(name))<2: return None
    pr=it.get("price",it.get("salePrice",{}))
    pv=(pr.get("value",pr.get("amount","")) if isinstance(pr,dict) else pr)
    old=it.get("originalPrice",it.get("regularPrice",""))
    if isinstance(old,dict): old=old.get("value","")
    href=it.get("url",it.get("link",""))
    if href and not href.startswith("http"): href="https://www.carrefour.pk"+("" if href.startswith("/") else "/")+href.lstrip("/")
    img=it.get("image",it.get("thumbnail",""))
    if isinstance(img,dict): img=img.get("url","")
    if img and img.startswith("//"): img="https:"+img
    brand=it.get("brand","N/A")
    if isinstance(brand,dict): brand=brand.get("name","N/A")
    cat=it.get("category",it.get("categoryName","N/A"))
    if isinstance(cat,dict): cat=cat.get("name","N/A")
    if isinstance(cat,list): cat=cat[0] if cat else "N/A"
    iid=str(it.get("id",it.get("sku","")) or "") or _h(name,"carrefour")
    try: rat=float(it.get("rating",it.get("ratingScore",0)) or 0)
    except: rat=0.0
    c=_cp(pv); o=_cp(old)
    p.update({"item_id":iid,"name":str(name),"price_pkr":c,"original_price_pkr":o,"discount":_disc(c,o),
              "brand_supplier":str(brand),"category_path":str(cat),"rating":rat,"image_url":str(img),"product_url":href})
    p["_hash"]=_h(iid,"carrefour"); return p


# ─── METRO ───────────────────────────────────────────────────────────────────
def scrape_metro(query, page=1, **kw):
    q=quote_plus(query)
    for base in ["https://www.metro-online.pk","https://metro-online.pk"]:
        for url in [f"{base}/catalogsearch/result/index/?q={q}&p={page}",
                    f"{base}/catalogsearch/result/?q={q}&p={page}"]:
            r=_get("metro.pk",url,hdrs={"Referer":f"{base}/"})
            if not r or r.status_code!=200: continue
            soup=BeautifulSoup(r.text,"html.parser")
            if soup.find(string=re.compile(r"no results|0 items",re.I)): return []
            items=_jblob(r.text,"items","products","listItems")
            if items:
                out=[_pm(i,base) for i in items if isinstance(i,dict)]
                out=[p for p in out if p]
                if out: _logger(f"  ✓ Metro JSON: {len(out)} products"); return out
            cards=(soup.select("li.product-item") or soup.select("ol.products li.item") or
                   soup.select(".products-grid .item") or soup.select("[class*='product-item']"))
            if cards:
                out=_m2cards(cards,"metro.pk",base)
                if out: _logger(f"  ✓ Metro DOM: {len(out)} products"); return out
    _logger("  ✗ Metro: no results"); return []

def _pm(it,base):
    p=_base("metro.pk"); name=it.get("name","")
    if not name or len(str(name))<3: return None
    sku=str(it.get("sku",it.get("id","")) or "")
    href=it.get("url",it.get("url_key",""))
    if href and not href.startswith("http"): href=f"{base}/{href.lstrip('/')}"
    price=None
    for pk in ["price","final_price","special_price"]:
        v=it.get(pk)
        if isinstance(v,dict):
            price=(_cp(v.get("final_price",{}).get("default")) or
                   _cp(v.get("minimum_price",{}).get("final_price",{}).get("value")))
            if price: break
        elif v: price=_cp(v);
        if price: break
    img=""
    for ik in ["image","thumbnail","small_image"]:
        v=it.get(ik,"")
        if isinstance(v,str) and v: img=v if v.startswith("http") else f"{base}/media/catalog/product{v}"; break
        elif isinstance(v,dict): img=v.get("url",""); break
        elif isinstance(v,list) and v:
            f0=v[0]; img=(f0.get("file","") or f0.get("url","")) if isinstance(f0,dict) else str(f0)
            if img and not img.startswith("http"): img=f"{base}/media/catalog/product{img}"
            break
    brand=str(it.get("brand",it.get("manufacturer","")) or "N/A")
    cats=it.get("categories",[]); cat=cats[0].get("name","N/A") if cats and isinstance(cats[0],dict) else "N/A"
    iid=sku or _h(name,"metro")
    try: rat=float(it.get("rating_summary",0) or 0)/20
    except: rat=0.0
    try: rev=int(it.get("review_count",0) or 0)
    except: rev=0
    p.update({"item_id":iid,"name":str(name),"price_pkr":price,"brand_supplier":brand,
              "category_path":cat,"rating":round(rat,1),"reviews":rev,"image_url":img,"product_url":href,"source":"metro.pk"})
    p["_hash"]=_h(iid,"metro"); return p


# ─── ALFATAH ─────────────────────────────────────────────────────────────────
def scrape_alfatah(query, page=1, **kw):
    q=quote_plus(query)
    for base in ["https://alfatah.pk","https://www.alfatah.pk","https://www.alfatah.com.pk"]:
        pred=f"{base}/search/suggest.json?q={q}&resources[type]=product&resources[limit]=20"
        r=_get("alfatah.pk",pred,hdrs={"Accept":"application/json"},json_req=True)
        if r and r.status_code==200:
            try:
                d=r.json()
                items=(d.get("resources",{}).get("results",{}).get("products",[]) or d.get("products",[]))
                if items:
                    out=[_paf(i,base) for i in items if isinstance(i,dict)]
                    out=[p for p in out if p]
                    if out: _logger(f"  ✓ Alfatah predict: {len(out)} products"); return out
            except: pass
        for surl in [f"{base}/search?type=product&q={q}&page={page}",
                     f"{base}/search?q={q}&type=product&page={page}"]:
            r2=_get("alfatah.pk",surl,hdrs={"Referer":f"{base}/"})
            if not r2 or r2.status_code!=200: continue
            soup=BeautifulSoup(r2.text,"html.parser")
            cards=(soup.select(".grid__item,.product-card,.grid-product") or
                   soup.select("[class*='product-item'],[class*='ProductItem']") or soup.select("li.product"))
            out=_shcards(cards,"alfatah.pk",base)
            if out: _logger(f"  ✓ Alfatah DOM: {len(out)} products"); return out
    _logger("  ✗ Alfatah: no results"); return []

def _paf(it,base):
    p=_base("alfatah.pk"); name=it.get("title","")
    if not name: return None
    handle=it.get("handle",""); href=f"{base}/products/{handle}" if handle else it.get("url","")
    imgs=it.get("images",[]); img=""
    if isinstance(imgs,list) and imgs:
        i0=imgs[0]; img=(i0.get("src","") if isinstance(i0,dict) else str(i0))
    elif isinstance(it.get("featured_image"),str): img=it["featured_image"]
    elif isinstance(it.get("featured_image"),dict): img=it["featured_image"].get("url","")
    if img.startswith("//"): img="https:"+img
    variants=it.get("variants",[]); price=None
    if variants and isinstance(variants[0],dict): price=_cp(variants[0].get("price",""))
    if not price: price=_cp(it.get("price",""))
    iid=str(it.get("id","")) or _h(name,"alfatah")
    p.update({"item_id":iid,"name":name,"price_pkr":price,"brand_supplier":it.get("vendor","N/A"),
              "category_path":it.get("product_type","N/A"),"image_url":img,"product_url":href,"source":"alfatah.pk"})
    p["_hash"]=_h(iid,"alfatah"); return p


# ─── Shared DOM helpers ───────────────────────────────────────────────────────
def _m2cards(cards,site,base):
    out=[]
    for card in cards[:40]:
        p=_base(site)
        try:
            ne=(card.select_one(".product-item-name a,a.product-item-link") or
                card.select_one(".product-name a,.product-title a") or card.select_one("strong.product-item-name,h2 a,h3 a"))
            pe=(card.select_one(".price-box .price,.special-price .price") or
                card.select_one(".price-wrapper .price") or card.select_one("[data-price-type='finalPrice'] .price") or
                card.select_one("[class*='price']:not([class*='old']):not([class*='regular'])"))
            oe=card.select_one(".old-price .price,.regular-price .price")
            ie=(card.select_one("img.product-image-photo") or card.select_one("img[src*='catalog/product'],img[data-src*='catalog']") or card.select_one("img"))
            be=card.select_one("[class*='brand'],[itemprop='brand'],.manufacturer")
            name=ne.get_text(strip=True) if ne else ""
            if not name or len(name)<3: continue
            href=((ne.get("href","") if ne and ne.get("href") else "") or
                  (card.select_one("a[href]").get("href","") if card.select_one("a[href]") else ""))
            if href and not href.startswith("http"): href=base+("" if href.startswith("/") else "/")+href.lstrip("/")
            img=_img(ie)
            if img and not img.startswith("http") and img.startswith("/"): img=base+img
            c=_cp(pe.get_text() if pe else ""); o=_cp(oe.get_text() if oe else "")
            iid=_h(href or name,site)
            p.update({"item_id":iid,"name":name,"price_pkr":c,"original_price_pkr":o,
                       "discount":_disc(c,o),"brand_supplier":be.get_text(strip=True) if be else "N/A",
                       "image_url":img,"product_url":href}); p["_hash"]=_h(iid,site); out.append(p)
        except: continue
    return out

def _shcards(cards,site,base):
    out=[]
    for card in cards[:40]:
        p=_base(site)
        try:
            ne=(card.select_one(".grid-product__title,.product-card__title,.product__title") or
                card.select_one("a[href*='/products/']") or card.select_one("[class*='title'],h2,h3"))
            pe=(card.select_one(".grid-product__price,.product-card__price,.price") or card.select_one("[class*='price']"))
            le=card.select_one("a[href*='/products/'],a[href]"); ie=card.select_one("img")
            name=ne.get_text(strip=True) if ne else ""
            if not name or len(name)<3: continue
            href=le.get("href","") if le else ""
            if href and not href.startswith("http"): href=base+href
            img=_img(ie)
            if img.startswith("//"): img="https:"+img
            iid=_h(href or name,site)
            p.update({"item_id":iid,"name":name,"price_pkr":_cp(pe.get_text() if pe else ""),
                       "image_url":img,"product_url":href}); p["_hash"]=_h(iid,site); out.append(p)
        except: continue
    return out

def _gdom(cards,site,base):
    out=[]
    for card in cards[:40]:
        p=_base(site)
        try:
            ne=card.select_one("[class*='title'],[class*='name'],h2,h3,h4,a")
            pe=card.select_one("[class*='price']"); le=card.select_one("a[href]"); ie=card.select_one("img")
            name=ne.get_text(strip=True) if ne else ""
            if not name or len(name)<3: continue
            href=le.get("href","") if le else ""
            if href and not href.startswith("http"): href=base+("" if href.startswith("/") else "/")+href.lstrip("/")
            img=_img(ie)
            if img.startswith("//"): img="https:"+img
            iid=_h(href or name,site)
            p.update({"item_id":iid,"name":name,"price_pkr":_cp(pe.get_text() if pe else ""),
                       "image_url":img,"product_url":href}); p["_hash"]=_h(iid,site); out.append(p)
        except: continue
    return out

def _gjson(it,site,base):
    p=_base(site); name=it.get("name",it.get("title",""))
    if not name: return None
    href=it.get("url",it.get("link",""))
    if href and not href.startswith("http"): href=base+href
    iid=str(it.get("id","") or "") or _h(name,site)
    c=_cp(it.get("price",it.get("final_price",""))); o=_cp(it.get("regular_price",""))
    img=it.get("image",it.get("thumbnail",""))
    if isinstance(img,dict): img=img.get("url","")
    if img and not img.startswith("http") and img.startswith("/"): img=base+img
    p.update({"item_id":iid,"name":name,"price_pkr":c,"original_price_pkr":o,"discount":_disc(c,o),
               "brand_supplier":it.get("brand","N/A"),"image_url":str(img),"product_url":href})
    p["_hash"]=_h(iid,site); return p


# ─── Custom sites ─────────────────────────────────────────────────────────────
_custom_scrapers={}
def register_custom(domain,fn): _custom_scrapers[domain]=fn; SITE_META[domain]={"per_page":20,"tech":"AI-Generated","color":"#8b5cf6","fact":f"Custom scraper for {domain}."}


# ─── Registry ─────────────────────────────────────────────────────────────────
SCRAPERS={"daraz.pk":scrape_daraz,"shophive.com":scrape_shophive,
          "carrefour.pk":scrape_carrefour,"metro.pk":scrape_metro,"alfatah.pk":scrape_alfatah}
DETAIL_SCRAPERS={"daraz.pk":scrape_daraz_detail}

def scrape_site(site,query,page=1):
    if site in _custom_scrapers:
        try: return _custom_scrapers[site](query,page) or []
        except Exception as e: _logger(f"  ✗ Custom {site}: {e}"); return []
    fn=SCRAPERS.get(site)
    if not fn: return []
    try: return fn(query,page) or []
    except Exception as e: _logger(f"  ✗ {site}: {e}"); return []

def scrape_detail(product):
    fn=DETAIL_SCRAPERS.get(product.get("source",""))
    if fn:
        try: return fn(product)
        except: pass
    return product
