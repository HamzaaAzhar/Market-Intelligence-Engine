"""
Brand Intelligence Classifier v2
• 150+ brands with multi-token keyword matching
• Tries: product name, description, seller name, category path
• Returns confidence score alongside classification
"""
import re

# ── Brand definitions ──────────────────────────────────────────────────────────
# Format: "Brand Name": ["keyword1", "keyword2", ...]
# Keywords are matched case-insensitively as word/token substrings
BRANDS = {
    # ── Smartphones & Mobile ──
    "Samsung":      ["samsung","galaxy s","galaxy a","galaxy m","galaxy z","galaxy tab","galaxy note","galaxy book","galaxy buds","galaxy watch"],
    "Apple":        ["apple","iphone","ipad","macbook","airpods","apple watch","apple tv","imac","mac mini","mac pro","macos"],
    "Xiaomi":       ["xiaomi","redmi note","redmi","poco f","poco m","poco x","poco c","mi 10","mi 11","mi 12","mi 13","mi 14","hyper os","miui"],
    "Huawei":       ["huawei","nova 10","nova 9","nova 8","nova 7","nova 5","mate 50","mate 40","mate 30","p60","p50","p40","p30","honor magic","honor x","honor 90"],
    "Honor":        ["honor magic","honor x","honor 90","honor 70","honor 50","honor 20","honor 10"],
    "Oppo":         ["oppo reno","oppo a","oppo f","oppo find","oppo pad","coloros"],
    "Vivo":         ["vivo v","vivo y","vivo x","vivo s","vivo iqoo","funtouch"],
    "Realme":       ["realme narzo","realme gt","realme c","realme 12","realme 11","realme 10","realme 9","realme 8","realme 7","realme 6","realme 5"],
    "OnePlus":      ["oneplus 12","oneplus 11","oneplus 10","oneplus 9","oneplus 8","oneplus nord","one plus"],
    "Motorola":     ["motorola","moto g","moto e","moto edge","razr"],
    "Nokia":        ["nokia g","nokia c","nokia x","nokia"],
    "Tecno":        ["tecno camon","tecno spark","tecno phantom","tecno pop","tecno pova"],
    "Infinix":      ["infinix hot","infinix note","infinix zero","infinix smart"],
    "Itel":         ["itel a","itel p","itel s","itel vision"],
    "ZTE":          ["zte blade","zte axon"],
    "Sony":         ["sony xperia","sony"],
    "Google":       ["google pixel","pixel 8","pixel 7","pixel 6","pixel fold"],
    "Asus Phone":   ["asus zenfone","rog phone"],

    # ── Laptops & PCs ──
    "Dell":         ["dell inspiron","dell xps","dell latitude","dell vostro","dell precision","dell g series","dell g15","dell g16"],
    "HP":           ["hp pavilion","hp spectre","hp envy","hp omen","hp elitebook","hp probook","hp zbook","hp chromebook","hp stream"],
    "Lenovo":       ["lenovo thinkpad","lenovo ideapad","lenovo legion","lenovo yoga","lenovo chromebook","lenovo tab"],
    "Asus Laptop":  ["asus vivobook","asus zenbook","asus tuf","asus rog","asus proart","asus expertbook"],
    "Acer":         ["acer aspire","acer predator","acer nitro","acer swift","acer extensa","acer chromebook"],
    "MSI":          ["msi modern","msi prestige","msi summit","msi katana","msi raider","msi stealth","msi titan"],
    "Apple Mac":    ["macbook pro","macbook air","macbook m1","macbook m2","macbook m3"],

    # ── Televisions & Displays ──
    "LG":           ["lg oled","lg qned","lg nanocell","lg ultragear","lg ultrafine","lg tv","lg refrigerator","lg washing","lg dishwasher","lg air conditioner","lg ac"],
    "TCL":          ["tcl mini led","tcl qled","tcl c","tcl p","tcl s","tcl 32","tcl 43","tcl 50","tcl 55","tcl 65","tcl 75"],
    "Hisense":      ["hisense uled","hisense qled","hisense u8","hisense u7","hisense a7","hisense"],
    "Sony TV":      ["sony bravia","bravia xr","bravia x","sony a95k","sony x95","sony x90","sony x85"],
    "Panasonic":    ["panasonic tv","panasonic refrigerator","panasonic ac","panasonic washing","panasonic microwave"],
    "Philips":      ["philips ambilight","philips tv","philips monitor","philips air purifier","philips iron","philips kettle","philips blender"],

    # ── Appliances — Pakistan Brands ──
    "Dawlance":     ["dawlance"],
    "PEL":          ["pel refrigerator","pel ac","pel tv","pel washing"],
    "Orient":       ["orient tv","orient refrigerator","orient ac","orient washing","orient microwave"],
    "Waves":        ["waves refrigerator","waves washing","waves ac","waves oven"],
    "Gree":         ["gree ac","gree air conditioner","gree heat pump","gree split"],
    "Kenwood":      ["kenwood ac","kenwood refrigerator","kenwood air conditioner","kenwood washing"],
    "Haier":        ["haier","haier refrigerator","haier washing","haier ac","haier tv"],
    "Westpoint":    ["westpoint","west point"],
    "National":     ["national juicer","national blender","national iron","national fan"],
    "Super Asia":   ["super asia"],
    "Ecostar":      ["ecostar"],
    "Changhong":    ["changhong ruba","changhong"],

    # ── Audio ──
    "JBL":          ["jbl flip","jbl charge","jbl pulse","jbl xtreme","jbl go","jbl tune","jbl live","jbl free","jbl partybox","jbl boombox"],
    "Sony Audio":   ["sony wh","sony wf","sony linkbuds","sony srs","sony ht"],
    "Bose":         ["bose quietcomfort","bose soundsport","bose sport","bose soundlink","bose home speaker"],
    "Anker":        ["anker soundcore","soundcore liberty","soundcore life","soundcore q","soundcore a","soundcore motion"],
    "Skullcandy":   ["skullcandy"],
    "Beats":        ["beats studio","beats solo","beats fit","beats flex","beats powerbeats"],
    "Sennheiser":   ["sennheiser"],
    "Audio-Technica":["audio-technica","audio technica"],
    "Harman Kardon":["harman kardon"],

    # ── Cameras ──
    "Canon":        ["canon eos","canon powershot","canon pixma","canon ixus","canon rf","canon ef"],
    "Nikon":        ["nikon d","nikon z","nikon coolpix","nikon nikkor"],
    "Sony Camera":  ["sony alpha","sony a7","sony a6","sony zv","sony fx"],
    "Fujifilm":     ["fujifilm x","fujifilm gfx","fujifilm instax"],
    "GoPro":        ["gopro hero","gopro max","gopro mini"],
    "DJI":          ["dji drone","dji mini","dji air","dji phantom","dji osmo","dji pocket","dji mavic"],

    # ── Accessories & Peripherals ──
    "Logitech":     ["logitech mx","logitech g","logitech m","logitech k","logitech c","logitech h","logitech z","logitech ergo"],
    "Corsair":      ["corsair k","corsair harpoon","corsair virtuoso","corsair void","corsair hs","corsair m55"],
    "Razer":        ["razer blackwidow","razer basilisk","razer naga","razer viper","razer kraken","razer huntsman","razer"],
    "HyperX":       ["hyperx cloud","hyperx fury","hyperx alloy","hyperx"],
    "Epson":        ["epson ecotank","epson workforce","epson expression","epson l"],

    # ── Fashion & Footwear ──
    "Nike":         ["nike air max","nike air force","nike react","nike free","nike zoom","nike dunk","nike blazer","nike pegasus","air jordan","nike sb"],
    "Adidas":       ["adidas ultraboost","adidas superstar","adidas stan smith","adidas gazelle","adidas nmd","adidas yeezy","adidas campus","adidas samba"],
    "Puma":         ["puma suede","puma rs","puma future","puma king","puma cell","puma clyde","puma blaze"],
    "Reebok":       ["reebok classic","reebok club c","reebok nano","reebok floatride","reebok"],
    "New Balance":  ["new balance 990","new balance 574","new balance 550","new balance 327","new balance 1080"],
    "Converse":     ["converse all star","converse chuck","converse run star"],
    "Vans":         ["vans old skool","vans sk8","vans authentic","vans slip-on","vans era"],
    "Bata":         ["bata north star","bata power","bata bubblegummers","bata marie claire"],
    "Servis":       ["servis toz","servis lza","servis kito"],

    # ── Levi's & Denim ──
    "Levi's":       ["levi's 501","levi's 511","levi's 512","levi's 513","levi's 514","levi's wedgie","levi's ribcage","levis"],
    "Polo":         ["polo ralph lauren","ralph lauren"],

    # ── FMCG — Food & Beverage ──
    "Nestle":       ["nescafe","milo","nestea","maggi","kit kat","smarties","quality street","after eight","nestle pure life","lactogen","nan formula"],
    "Unilever":     ["dove shampoo","dove soap","dove body","lifebuoy","surf excel","comfort fabric","sunsilk","clear anti","rexona","lux beauty","close up","signal"],
    "P&G":          ["head & shoulders","pantene pro","pantene shampoo","ariel automatic","tide pods","pampers","always ultra","gillette fusion","gillette mach","olay total","old spice"],
    "Colgate":      ["colgate max fresh","colgate total","colgate sensitive","colgate 360","colgate elmo"],
    "Shan":         ["shan masala","shan biryani","shan nihari","shan korma","shan seekh","shan recipe"],
    "National Foods":["national masala","national biryani","national nihari","national ketchup","national chilli","national foods"],
    "Knorr":        ["knorr noodles","knorr soup","knorr pasta","knorr"],
    "Rooh Afza":    ["rooh afza","hamdard"],
    "Pepsi":        ["pepsi cola","pepsi max","pepsi zero","7up","mountain dew pk","mirinda","sting energy","aquafina"],
    "Coca-Cola":    ["coca cola","coke classic","sprite pk","fanta pk","dasani","minute maid"],

    # ── Beauty & Skincare ──
    "L'Oreal":      ["loreal paris","loreal pro","l'oreal elvive","loreal revitalift","loreal age perfect","maybelline fit me","maybelline fit","garnier fructis","garnier micellar","garnier vitamin c"],
    "Nivea":        ["nivea soft","nivea men","nivea body","nivea sun","nivea creme","nivea lip"],
    "Neutrogena":   ["neutrogena hydro","neutrogena ultra","neutrogena rapid","neutrogena oil free"],
    "Cetaphil":     ["cetaphil gentle","cetaphil moisturizing","cetaphil daily","cetaphil"],
    "The Ordinary": ["the ordinary niacinamide","the ordinary hyaluronic","the ordinary retinol","the ordinary vitamin c","the ordinary aha"],
    "Vaseline":     ["vaseline intensive","vaseline body lotion","vaseline petroleum","vaseline healing"],
    "Ponds":        ["pond's clarant","pond's white beauty","pond's age miracle","ponds"],
    "Revlon":       ["revlon colorstay","revlon ultra","revlon photo ready","revlon"],
    "MAC":          ["mac cosmetics","mac studio","mac mineralize","mac pro"],

    # ── Baby & Kids ──
    "Pampers":      ["pampers active","pampers baby dry","pampers premium","pampers easy ups"],
    "Huggies":      ["huggies ultra","huggies natural","huggies little snugglers"],
    "Johnson's":    ["johnson's baby","johnson baby shampoo","johnson baby oil","johnson baby powder"],
    "Enfamil":      ["enfamil premium","enfamil gentlease","enfamil neuropro"],

    # ── Networking ──
    "TP-Link":      ["tp-link archer","tp-link deco","tp-link tl","tplink"],
    "D-Link":       ["d-link dir","d-link dap","d-link dgs","dlink"],
    "Netgear":      ["netgear nighthawk","netgear orbi","netgear armor","netgear"],
    "Cisco":        ["cisco meraki","cisco rv","cisco catalyst","cisco"],

    # ── Gaming ──
    "PlayStation":  ["playstation 5","playstation 4","ps5 console","ps4 console","dualshock","dualsense"],
    "Xbox":         ["xbox series x","xbox series s","xbox one","xbox controller"],
    "Nintendo":     ["nintendo switch oled","nintendo switch lite","nintendo switch","joy-con"],

    # ── Power & Batteries ──
    "Anker Power":  ["anker powercore","anker powerport","anker nano","anker 737","anker 521","anker 533"],
    "Baseus":       ["baseus powercombo","baseus magnetic","baseus blade","baseus gang"],
}

# ── Category keywords ──────────────────────────────────────────────────────────
CATEGORIES = {
    "Smartphones":        ["smartphone","mobile phone","cell phone","android phone","5g phone","4g phone","iphone","galaxy phone"],
    "Laptops":            ["laptop","notebook computer","ultrabook","chromebook","gaming laptop","business laptop"],
    "Tablets":            ["tablet","ipad","android tablet","e-reader","e reader","kindle"],
    "Televisions":        ["television","smart tv","led tv","oled tv","qled tv","android tv","4k tv","8k tv","fire tv"],
    "Monitors":           ["monitor","display screen","gaming monitor","curved monitor","ultrawide"],
    "Headphones":         ["headphone","over-ear","on-ear","wireless headphone","noise cancelling headphone"],
    "Earbuds":            ["earbuds","true wireless","tws earphone","in-ear earphone","wireless earphone","airpod","neckband"],
    "Speakers":           ["bluetooth speaker","portable speaker","soundbar","home theatre","party speaker","wireless speaker"],
    "Cameras":            ["dslr camera","mirrorless camera","point and shoot","action camera","instant camera","webcam"],
    "Drones":             ["drone","quadcopter","aerial camera","fpv drone"],
    "Refrigerators":      ["refrigerator","fridge","freezer","double door","side by side fridge"],
    "Air Conditioners":   ["air conditioner","split ac","inverter ac","window ac","portable ac","heat pump"],
    "Washing Machines":   ["washing machine","washer dryer","front load washing","top load washing","semi automatic"],
    "Microwaves":         ["microwave oven","convection microwave","solo microwave","grill microwave"],
    "Kitchen Appliances": ["blender","juicer","air fryer","rice cooker","pressure cooker","electric kettle","food processor","stand mixer","hand mixer","toaster"],
    "Men's Clothing":     ["men shirt","men trouser","men jacket","men kurta","shalwar kameez men","men polo","men t-shirt","men jeans","men hoodie"],
    "Women's Clothing":   ["women dress","women top","ladies kurta","women jeans","women hoodie","abaya","hijab","dupatta","women polo","ladies shirt"],
    "Kids Clothing":      ["kids t-shirt","children clothes","baby clothes","toddler","kids wear","boys shirt","girls frock"],
    "Shoes":              ["shoes","sneakers","running shoes","training shoes","boots","sandals","loafers","mocassins","slides","flip flops","heels","pumps","wedges"],
    "Bags":               ["backpack","handbag","laptop bag","crossbody bag","tote bag","messenger bag","duffel bag","luggage suitcase","travel bag","wallet purse"],
    "Skincare":           ["moisturizer","face serum","sunscreen spf","face wash","toner","face cream","eye cream","face mask","skin brightening","anti aging cream"],
    "Haircare":           ["shampoo","conditioner","hair oil","hair mask","hair color","hair dye","hair serum","hair spray","dry shampoo"],
    "Fragrances":         ["perfume","eau de parfum","eau de toilette","cologne","body mist","deodorant roll-on"],
    "Grocery & Food":     ["flour","rice basmati","sugar","cooking oil","ghee","dal","lentil","salt","masala spice","pickle achar"],
    "Dairy":              ["milk","yogurt","dahi","cheese","butter","cream","whey protein"],
    "Beverages":          ["juice bottle","soft drink can","energy drink","mineral water","tea bag","green tea","coffee beans","instant coffee"],
    "Baby Products":      ["baby diaper","baby wipe","baby formula","baby food","baby shampoo","baby lotion","baby powder","pram stroller","car seat baby"],
    "Furniture":          ["sofa","dining table","coffee table","bed frame","wardrobe","bookshelf","office chair","study desk","shoe rack"],
    "Bedding":            ["mattress","pillow","bed sheet","duvet","quilt","blanket","comforter","pillow cover"],
    "Gaming":             ["gaming console","gaming laptop","gaming chair","gaming headset","gaming mouse","gaming keyboard","mechanical keyboard","game controller","gpu graphics"],
    "Networking":         ["wifi router","mesh router","network switch","ethernet cable","modem","range extender","access point"],
    "Accessories":        ["phone case","phone cover","screen protector","charger","usb cable","power bank","laptop bag","keyboard cover","mouse pad"],
    "Watches":            ["smartwatch","analog watch","digital watch","sports watch","luxury watch","chronograph"],
    "Jewellery":          ["gold ring","necklace","earring","bracelet","diamond","silver jewellery","engagement ring","bangles"],
    "Tools & Hardware":   ["drill machine","power drill","screwdriver set","hammer","wrench","saw","measuring tape","toolbox"],
    "Stationery":         ["notebook","pen","pencil","marker","folder","binder","sticky notes","stapler","tape dispenser","highlighter"],
    "Sports & Fitness":   ["yoga mat","dumbbell","resistance band","treadmill","cycling","football","cricket bat","badminton racket","gym gloves"],
    "Toys":               ["lego","action figure","board game","puzzle","stuffed animal","remote control car","doll house","toy car"],
}


def classify_brand(name: str, description: str = "", extra_fields: dict = None) -> tuple[str, float]:
    """
    Returns (brand_name, confidence 0-1).
    Searches: name, description, brand_supplier field, seller_name.
    """
    fields = [name, description]
    if extra_fields:
        for k in ("brand_supplier","seller_name","category_path"):
            v = extra_fields.get(k,"")
            if v and v not in ("N/A",""):
                fields.append(str(v))

    text = " ".join(fields).lower()
    text = re.sub(r"[^\w\s\-\+\.]"," ", text)   # normalise punctuation

    best_brand = None
    best_score = 0.0

    for brand, keywords in BRANDS.items():
        for kw in keywords:
            kw_norm = kw.lower()
            # Exact boundary match scores higher
            if re.search(r'\b' + re.escape(kw_norm) + r'\b', text):
                # Longer keyword match = more specific = higher confidence
                score = 0.5 + min(len(kw_norm)/30, 0.5)
                if score > best_score:
                    best_score = score
                    best_brand = brand
            elif kw_norm in text:
                score = 0.3 + min(len(kw_norm)/60, 0.3)
                if score > best_score:
                    best_score = score
                    best_brand = brand

    # If brand_supplier field matches something in name, trust it
    if extra_fields:
        bs = str(extra_fields.get("brand_supplier","")).strip()
        if bs and bs not in ("N/A","","Unknown","Other"):
            # Check if known brand alias
            for brand, keywords in BRANDS.items():
                if bs.lower() == brand.lower() or any(bs.lower() == kw.lower() for kw in keywords[:3]):
                    if best_score < 0.85:
                        return brand, 0.85
            # Trust it as-is if it looks like a real brand name (2+ chars, not generic)
            if len(bs) >= 2 and bs.lower() not in ("brand","manufacturer","seller","n/a","na","unknown"):
                if best_score < 0.6:
                    return bs, 0.6

    return (best_brand or "Unknown", round(best_score, 2))


def classify_category(name: str, description: str = "", category_path: str = "") -> str:
    """Classify product into a standard category."""
    text = (name + " " + description + " " + category_path).lower()
    text = re.sub(r"[^\w\s\-]"," ", text)

    best_cat   = None
    best_score = 0

    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw.lower()) + r'\b', text):
                score = len(kw)
                if score > best_score:
                    best_score = score
                    best_cat = cat
            elif kw.lower() in text:
                score = len(kw) // 2
                if score > best_score:
                    best_score = score
                    best_cat = cat

    # fallback: use first segment of category_path
    if not best_cat and category_path and category_path not in ("N/A",""):
        best_cat = category_path.split(">")[0].strip()

    return best_cat or "General"


def enrich_product(product: dict) -> dict:
    """Run brand + category classification. Mutates product dict in-place."""
    name  = product.get("name","")
    desc  = product.get("description","")
    cat   = product.get("category_path","")

    brand, conf = classify_brand(name, desc, product)
    product["brand_classified"]    = brand
    product["brand_confidence"]    = conf
    product["category_classified"] = classify_category(name, desc, cat)
    return product
