from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import json
import os

app = FastAPI(title="Gamer's Archive API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- KONFİGÜRASYON ---
STEAM_API_KEY = os.getenv("STEAM_API_KEY", "E722F690EA2642D98FA54A973F703860")
ITAD_API_KEY = os.getenv("ITAD_API_KEY", "fb00f3da8717cec28c29230c6751e795aaeec8d6")
RAWG_API_KEY = os.getenv("RAWG_API_KEY", "d0cc05e711884b91911e36cb2f2e44cc")
IGDB_CLIENT_ID = os.getenv("IGDB_CLIENT_ID", "2bugrxp3scbr1l493je0fgex1mop4h")
IGDB_CLIENT_SECRET = os.getenv("IGDB_CLIENT_SECRET", "j400fdeqok9biwj8x879k980iuz8ue")

# --- IGDB TOKEN ---
def get_igdb_token():
    try:
        r = requests.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": IGDB_CLIENT_ID,
                "client_secret": IGDB_CLIENT_SECRET,
                "grant_type": "client_credentials"
            },
            timeout=10
        )
        return r.json().get('access_token')
    except:
        return None

# --- ENDPOINTS ---

@app.get("/")
def root():
    return {"status": "Gamer's Archive API çalışıyor 🚀"}

@app.get("/search")
def search_game(query: str):
    """Steam'den oyun ara"""
    try:
        r = requests.get(
            f"https://store.steampowered.com/api/storesearch/?term={query}&l=turkish&cc=TR",
            timeout=10
        ).json()
        items = [i for i in r.get('items', []) if "soundtrack" not in i['name'].lower() and "dlc" not in i['name'].lower()]
        return {"results": items[:3]}
    except:
        return {"results": []}

@app.get("/game/{app_id}")
def get_game_details(app_id: int):
    """Oyun detayları - tüm veriler"""
    result = {}

    # Steam detay
    try:
        det = requests.get(f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=turkish").json()
        if det[str(app_id)]['success']:
            data = det[str(app_id)]['data']
            result['tags'] = [g['description'] for g in data.get('genres', [])][:5]
            result['name'] = data.get('name', '')
    except:
        pass

    # Steam puan
    try:
        r = requests.get(f"https://store.steampowered.com/appreviews/{app_id}?json=1&language=all").json()
        total = r["query_summary"]["total_reviews"]
        positive = r["query_summary"]["total_positive"]
        result['steam_score'] = round((positive / total) * 100) if total > 0 else None
    except:
        pass

    # Steam fiyat (USD)
    try:
        kur = requests.get("https://api.exchangerate-api.com/v4/latest/USD").json()['rates']['TRY']
        result['exchange_rate'] = kur
    except:
        pass

    return result

@app.get("/prices")
def get_prices(name: str, steam_price_usd: float = 0):
    """Tüm mağaza fiyatları"""
    result = {}

    # Epic (ITAD)
    try:
        clean = re.sub(r'\(.*?\)|[:™®]', '', name).strip()
        lookup = requests.get(
            "https://api.isthereanydeal.com/games/lookup/v1",
            params={"key": ITAD_API_KEY, "title": clean},
            timeout=5
        ).json()
        if lookup.get('game'):
            game_id = lookup['game']['id']
            prices = requests.post(
                "https://api.isthereanydeal.com/games/prices/v3",
                params={"key": ITAD_API_KEY, "country": "TR"},
                json=[game_id],
                timeout=5
            ).json()
            if prices:
                for deal in prices[0].get('deals', []):
                    if deal.get('shop', {}).get('id') == 16:
                        result['epic'] = f"{deal['price']['amount']:.0f} TL"
                        break
    except:
        pass

    # PS Store
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(
            f"https://store.playstation.com/store/api/chihiro/00_09_000/tumbler/TR/tr/999/{requests.utils.quote(name)}?suggested_size=5&mode=game",
            headers=headers, timeout=10
        ).json()
        skip = ['dlc', "friend's pass", 'upgrade', 'müzik', 'soundtrack']
        for l in r.get('links', []):
            n = l.get('name', '').lower()
            if name.lower() in n and not any(w in n for w in skip):
                price = l.get('default_sku', {}).get('display_price', '')
                ps_url = f"https://store.playstation.com/tr-tr/search/{requests.utils.quote(name)}"
                result['ps_price'] = price if price else None
                result['ps_url'] = ps_url
                result['ps_available'] = True
                break
    except:
        result['ps_available'] = False

    return result

@app.get("/subscriptions")
def check_subscriptions(name: str):
    """Game Pass ve PS Plus kontrolü"""
    result = {}

    # Game Pass
    try:
        r = requests.get(
            "https://catalog.gamepass.com/sigls/v2?id=fdd9e2a7-0fee-49f6-ad69-4354098401ff&language=tr-TR&market=TR",
            timeout=10
        )
        game_ids = [item['id'] for item in r.json() if 'id' in item]
        ids_str = ",".join(game_ids)
        r2 = requests.get(
            f"https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds={ids_str}&market=TR&languages=tr-TR&MS-CV=DGU1mcuYo0WMMp",
            timeout=15
        )
        products = r2.json().get('Products', [])
        result['gamepass'] = any(
            name.lower() in p['LocalizedProperties'][0]['ProductTitle'].lower()
            for p in products if p.get('LocalizedProperties')
        )
    except:
        result['gamepass'] = False

    # PS Plus (JSON)
    try:
        with open("psplus_games.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        games = data.get("games", [])
        result['psplus'] = any(name.lower() in g.lower() or g.lower() in name.lower() for g in games)
    except:
        result['psplus'] = False

    return result

@app.get("/metacritic")
def get_metacritic(name: str):
    """IGDB'den Metacritic skoru"""
    try:
        token = get_igdb_token()
        if not token:
            return {"score": None}
        clean = re.sub(r'[™®]', '', name).strip()
        r = requests.post(
            "https://api.igdb.com/v4/games",
            headers={
                "Client-ID": IGDB_CLIENT_ID,
                "Authorization": f"Bearer {token}",
                "Content-Type": "text/plain"
            },
            data=f'search "{clean}"; fields name,aggregated_rating; limit 5;',
            timeout=10
        )
        for game in r.json():
            if clean.lower() in game['name'].lower() or game['name'].lower() in clean.lower():
                if game.get('aggregated_rating'):
                    return {"score": round(game['aggregated_rating'])}
    except:
        pass
    return {"score": None}

@app.get("/recommendations")
def get_recommendations(
    puan_min: int = 85,
    puan_max: int = 100,
    tags: str = ""
):
    """RAWG'dan oyun önerileri"""
    try:
        params = {
            "key": RAWG_API_KEY,
            "metacritic": f"{puan_min},{puan_max}",
            "page_size": 15,
            "ordering": "-metacritic",
        }
        if tags:
            params["tags"] = tags
        r = requests.get("https://api.rawg.io/api/games", params=params, timeout=10).json()
        return {"results": [{"name": g['name'], "metacritic": g.get('metacritic')} for g in r.get('results', [])]}
    except:
        return {"results": []}
