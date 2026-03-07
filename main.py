from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
import requests
import re
import json
import os
from typing import Optional

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
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# --- SUPABASE ---
supabase = None

@app.on_event("startup")
def startup():
    global supabase
    if SUPABASE_URL and SUPABASE_KEY:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    else:
        print("WARNING: SUPABASE env vars missing!")

# --- MODELLER ---
class GameAdd(BaseModel):
    user_id: str
    name: str
    category_id: Optional[str] = None
    status: str = "backlog"

class GameUpdate(BaseModel):
    status: Optional[str] = None
    category_id: Optional[str] = None

class CategoryAdd(BaseModel):
    user_id: str
    name: str

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

# --- GENEL ENDPOINTS ---

@app.get("/")
def root():
    return {"status": "Gamer's Archive API çalışıyor 🚀"}

@app.get("/search")
def search_game(query: str):
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
    result = {}
    try:
        det = requests.get(f"https://store.steampowered.com/api/appdetails?appids={app_id}&l=turkish").json()
        if det[str(app_id)]['success']:
            data = det[str(app_id)]['data']
            result['tags'] = [g['description'] for g in data.get('genres', [])][:5]
            result['name'] = data.get('name', '')
    except:
        pass
    try:
        r = requests.get(f"https://store.steampowered.com/appreviews/{app_id}?json=1&language=all").json()
        total = r["query_summary"]["total_reviews"]
        positive = r["query_summary"]["total_positive"]
        result['steam_score'] = round((positive / total) * 100) if total > 0 else None
    except:
        pass
    try:
        kur = requests.get("https://api.exchangerate-api.com/v4/latest/USD").json()['rates']['TRY']
        result['exchange_rate'] = kur
    except:
        pass
    return result

@app.get("/prices")
def get_prices(name: str):
    result = {}
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
                result['ps_price'] = price if price else None
                result['ps_url'] = f"https://store.playstation.com/tr-tr/search/{requests.utils.quote(name)}"
                result['ps_available'] = True
                break
    except:
        result['ps_available'] = False
    return result

@app.get("/subscriptions")
def check_subscriptions(name: str):
    result = {}
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
def get_recommendations(puan_min: int = 85, puan_max: int = 100, tags: str = ""):
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

# --- KULLANICI ENDPOINTS ---

@app.post("/users")
def create_or_get_user(email: str, display_name: str = "", avatar_url: str = ""):
    try:
        existing = supabase.table("users").select("*").eq("email", email).execute()
        if existing.data:
            return existing.data[0]
        new_user = supabase.table("users").insert({
            "email": email,
            "display_name": display_name,
            "avatar_url": avatar_url
        }).execute()
        return new_user.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users/{user_id}/games")
def get_user_games(user_id: str):
    try:
        games = supabase.table("games").select("*, categories(name)").eq("user_id", user_id).execute()
        return {"games": games.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/games")
def add_game(game: GameAdd):
    try:
        result = supabase.table("games").insert({
            "user_id": game.user_id,
            "name": game.name,
            "category_id": game.category_id,
            "status": game.status
        }).execute()
        return result.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/games/{game_id}")
def update_game(game_id: str, update: GameUpdate):
    try:
        data = {k: v for k, v in update.dict().items() if v is not None}
        if update.status == "completed":
            data["completed_at"] = "now()"
        result = supabase.table("games").update(data).eq("id", game_id).execute()
        return result.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/games/{game_id}")
def delete_game(game_id: str):
    try:
        supabase.table("games").delete().eq("id", game_id).execute()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/users/{user_id}/categories")
def get_categories(user_id: str):
    try:
        cats = supabase.table("categories").select("*").eq("user_id", user_id).execute()
        return {"categories": cats.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/categories")
def add_category(cat: CategoryAdd):
    try:
        result = supabase.table("categories").insert({
            "user_id": cat.user_id,
            "name": cat.name
        }).execute()
        return result.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
