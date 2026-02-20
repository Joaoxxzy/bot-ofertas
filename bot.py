import os, re, time, json, asyncio, random
import httpx
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from telegram import Bot

# =======================
# VARIÁVEIS (Railway)
# =======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# 2100s = 35min (~41/dia). Para ~48/dia use 1800.
INTERVALO_SEG = int(os.getenv("INTERVALO_SEG", "2100"))

# quantos termos testar por ciclo e quantos resultados analisar por termo
TERMS_PER_CYCLE = int(os.getenv("TERMS_PER_CYCLE", "5"))
RESULTS_TO_SCAN = int(os.getenv("RESULTS_TO_SCAN", "10"))

# anti-flood: quantas ofertas mandar por ciclo (1 recomendado)
MAX_SEND_PER_CYCLE = int(os.getenv("MAX_SEND_PER_CYCLE", "1"))

# pausa pequena entre requisições internas
INTERNAL_DELAY_SEC = float(os.getenv("INTERNAL_DELAY_SEC", "1.2"))

if not BOT_TOKEN:
    raise RuntimeError("Faltou BOT_TOKEN nas Variables.")
if not CHAT_ID:
    raise RuntimeError("Faltou CHAT_ID nas Variables.")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) RadarOfertasBot/2.0",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# =======================
# CATEGORIAS / KEYWORDS (grande)
# =======================
KEYWORDS = [
    # CASA / COZINHA
    "air fryer", "liquidificador", "batedeira", "cafeteira", "sanduicheira",
    "panela eletrica", "panela de pressão", "jogo de panelas", "kit utensilios cozinha",
    "potes hermeticos", "organizador cozinha", "porta tempero", "escorredor louça",
    # LIMPEZA / ORGANIZAÇÃO
    "mop giratorio", "mop spray", "vassoura magica", "aspirador vertical", "robo aspirador",
    "caixa organizadora", "organizador armario", "sapateira", "cabide veludo", "varal dobravel",
    # CASA (ELÉTRICA/ILUMINAÇÃO)
    "lampada led", "fita led", "filtro de linha", "extensão elétrica", "adaptador tomada",
    # TECH BARATA
    "fone bluetooth", "fone jbl", "caixa de som bluetooth", "smartwatch",
    "carregador turbo", "cabo usb tipo c", "power bank", "suporte celular", "ring light",
    "roteador wifi", "extensor wifi", "camera segurança wifi",
    # GAMES / PC
    "headset gamer", "mouse gamer", "teclado gamer", "mouse pad",
    # BEBÊ
    "fralda bebe", "lenço umedecido", "mamadeira", "chupeta", "banheira bebe",
    # BELEZA / CUIDADOS
    "secador de cabelo", "chapinha", "barbeador eletrico", "aparador de pelos",
    # FITNESS
    "halter", "corda de pular", "tapete yoga", "garrafa termica",
    # FERRAMENTAS
    "parafusadeira", "furadeira", "kit ferramentas", "lanterna led",
    # AUTOMOTIVO
    "suporte celular carro", "carregador veicular", "aspirador automotivo",
]

# =======================
# ANTI-REPETIÇÃO (arquivo local)
# Obs: se o serviço reiniciar, pode repetir algumas ofertas (normal).
# =======================
CACHE_FILE = "sent_cache.json"

def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"sent": {}}

def save_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

def prune_sent(sent: dict, days=7):
    now = time.time()
    limit = days * 24 * 3600
    return {k: v for k, v in sent.items() if now - v <= limit}

def extract_item_id(url: str):
    if not url:
        return None
    m = re.search(r"(MLB-?\d{6,})", url.upper())
    if not m:
        return None
    return m.group(1).replace("-", "")

# =======================
# BUSCA (SITE) + VALIDAÇÃO (API item/user quando possível)
# =======================
async def fetch_listing(keyword: str, limit: int):
    url = f"https://lista.mercadolivre.com.br/{quote_plus(keyword)}"
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=40) as client:
        r = await client.get(url)
        r.raise_for_status()
        html = r.text

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("li.ui-search-layout__item")[:limit]

    out = []
    for c in cards:
        title_el = c.select_one("h2.ui-search-item__title")
        link_el = c.select_one("a.ui-search-link")
        price_el = c.select_one("span.andes-money-amount__fraction")
        if not (title_el and link_el and price_el):
            continue

        title = title_el.get_text(strip=True)
        link = link_el.get("href", "")
        price_txt = price_el.get_text(strip=True)

        txt = c.get_text(" ", strip=True).lower()
        coupon_hint = any(p in txt for p in ["cupom", "com cupom", "aplicar cupom", "cupón"])
        free_ship_hint = ("frete grátis" in txt) or ("frete gratis" in txt)

        item_id = extract_item_id(link)

        out.append({
            "title": title,
            "link": link,
            "price_txt": price_txt,
            "coupon_hint": coupon_hint,
            "free_ship_hint": free_ship_hint,
            "item_id": item_id,
            "keyword": keyword
        })
    return out

async def fetch_item(item_id: str):
    url = f"https://api.mercadolibre.com/items/{item_id}"
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=25) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        return r.json()

async def fetch_user(user_id: int):
    url = f"https://api.mercadolibre.com/users/{user_id}"
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=25) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        return r.json()

def price_to_float(price_txt: str):
    t = (price_txt or "").replace(".", "").replace(",", ".")
    try:
        return float(t)
    except:
        return 0.0

def trust_score_and_line(user):
    if not user:
        return 0, "🟡 Vendedor: info indisponível"

    rep = user.get("seller_reputation") or {}
    level = rep.get("level_id") or "n/a"
    power = user.get("power_seller_status") or "n/a"
    tx = rep.get("transactions") or {}
    completed = tx.get("completed") or 0
    ratings = tx.get("ratings") or {}
    negative = float(ratings.get("negative") or 0.0)

    score = 0
    if level.startswith("5_"): score += 3
    elif level.startswith("4_"): score += 2
    elif level.startswith("3_"): score += 1

    if power != "n/a": score += 2
    if completed >= 1000: score += 2
    elif completed >= 200: score += 1

    if negative >= 0.10: score -= 2
    elif negative >= 0.05: score -= 1

    if score >= 5: label = "🟢 Vendedor confiável"
    elif score >= 3: label = "🟡 Vendedor ok"
    else: label = "🔴 Atenção ao vendedor"

    line = f"{label} (rep:{level} | power:{power} | vendas:{completed} | neg:{negative:.2f})"
    return score, line

def make_message(p):
    cupom = ""
    if p.get("coupon_hint"):
        cupom = "\n*🎟️ CUPOM PODE ESTAR DISPONÍVEL NO ANÚNCIO (verifique antes de finalizar)*\n"
    frete = ""
    if p.get("free_ship_hint"):
        frete = "*🚚 Possível FRETE GRÁTIS no anúncio*\n"

    return (
        "🔥 OFERTA NO MERCADO LIVRE 🔥\n\n"
        f"📦 {p['title']}\n"
        f"💰 R$ {p['price']}\n"
        f"{cupom}"
        f"🛡️ {p['trust']}\n"
        f"{frete}\n"
        "🛒 Comprar com desconto:\n"
        "SEU_LINK_AFILIADO_AQUI\n\n"
        "⚡ Promoção pode acabar / estoque limitado!\n"
        f"📍 (Categoria automática: {p['keyword']})\n"
        f"🔗 Link original: {p['link']}"
    )

async def pick_best(keyword: str, sent: dict):
    items = await fetch_listing(keyword, limit=RESULTS_TO_SCAN)
    if not items:
        return None

    candidates = []
    for it in items:
        unique = it["item_id"] or it["link"]
        if unique in sent:
            continue
        candidates.append(it)

    if not candidates:
        return None

    scored = []
    for it in candidates[:RESULTS_TO_SCAN]:
        await asyncio.sleep(INTERNAL_DELAY_SEC)

        price_val = price_to_float(it["price_txt"])
        trust_score = 0
        trust_line = "🟡 Vendedor: info indisponível"

        if it["item_id"]:
            item = await fetch_item(it["item_id"])
            if item and item.get("seller_id"):
                user = await fetch_user(int(item["seller_id"]))
                trust_score, trust_line = trust_score_and_line(user)
                if isinstance(item.get("price"), (int, float)):
                    price_val = float(item["price"])

        # Score: prioriza vendedor + bônus cupom/frete + preço razoável
        score = 0
        score += trust_score * 10
        score += 6 if it["coupon_hint"] else 0
        score += 5 if it["free_ship_hint"] else 0
        score += 2000 / max(price_val, 60)  # menor preço = mais score

        scored.append((score, it, price_val, trust_line))

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0]
    it, price_val, trust_line = best[1], best[2], best[3]

    # se o vendedor explicitamente “atenção”, pula
    if trust_line.startswith("🔴"):
        return None

    price_str = f"{price_val:.2f}".replace(".", ",") if price_val else it["price_txt"]

    return {
        "title": it["title"],
        "price": price_str,
        "link": it["link"],
        "coupon_hint": it["coupon_hint"],
        "free_ship_hint": it["free_ship_hint"],
        "trust": trust_line,
        "keyword": it["keyword"],
        "unique": it["item_id"] or it["link"]
    }

async def main():
    bot = Bot(token=BOT_TOKEN)

    # ✅ Teste imediato
    await bot.send_message(chat_id=CHAT_ID, text="✅ Bot online! Vou começar a te mandar as melhores ofertas automaticamente.")

    cache = load_cache()
    sent = prune_sent(cache.get("sent", {}), days=7)
    cache["sent"] = sent
    save_cache(cache)

    while True:
        try:
            sent_this_cycle = 0
            kws = random.sample(KEYWORDS, k=min(TERMS_PER_CYCLE, len(KEYWORDS)))

            for kw in kws:
                if sent_this_cycle >= MAX_SEND_PER_CYCLE:
                    break

                offer = await pick_best(kw, sent)
                if offer:
                    msg = make_message(offer)
                    await bot.send_message(chat_id=CHAT_ID, text=msg)
                    sent[offer["unique"]] = time.time()
                    cache["sent"] = sent
                    save_cache(cache)
                    sent_this_cycle += 1

            print(f"Ciclo ok | enviadas: {sent_this_cycle} | próximo em {INTERVALO_SEG}s")

        except Exception as e:
            print("ERRO:", repr(e))

        await asyncio.sleep(INTERVALO_SEG)

if __name__ == "__main__":
    asyncio.run(main())
 
