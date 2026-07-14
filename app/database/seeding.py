from sqlalchemy.orm import Session
from app.models.style import Style

initial_styles = [
    # Categoría: Profesional
    {
        "name": "Corporate Portrait",
        "slug": "corporate-portrait",
        "category": "professional",
        "description": "Fondo neutro, iluminación profesional, traje de negocios.",
        "preview_url": "https://images.unsplash.com/photo-1560250097-0b93528c311a?w=400",
        "example_urls": [
            "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=400",
            "https://images.unsplash.com/photo-1580489944761-15a19d654956?w=400"
        ],
        "base_prompt": "professional corporate style, neutral studio background, business attire, high quality, realistic lighting",
        "tier_required": "free",
        "tags": ["linkedin", "cv", "formal"],
        "sort_order": 1
    },
    {
        "name": "Creative Professional",
        "slug": "creative-professional",
        "category": "professional",
        "description": "Estilo artístico moderno, look casual-elegante.",
        "preview_url": "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400",
        "example_urls": [
            "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=400"
        ],
        "base_prompt": "creative professional style, modern art studio background, smart casual, warm colors, natural expression",
        "tier_required": "free",
        "tags": ["creative", "casual", "portfolio"],
        "sort_order": 2
    },
    {
        "name": "Executive Headshot",
        "slug": "executive-headshot",
        "category": "professional",
        "description": "Pose formal, fondo degradado oscuro, ultra-realista.",
        "preview_url": "https://images.unsplash.com/photo-1519085360753-af0119f7cbe7?w=400",
        "example_urls": [],
        "base_prompt": "executive headshot style, dark gradient background, formal suit, sharp focus, cinematic lighting",
        "tier_required": "free",
        "tags": ["executive", "formal", "portrait"],
        "sort_order": 3
    },
    # Categoría: Gaming / Streamer
    {
        "name": "Neon Gamer",
        "slug": "neon-gamer",
        "category": "gaming",
        "description": "Estilo cyberpunk, luces de neón, fondo oscuro.",
        "preview_url": "https://images.unsplash.com/photo-1566492031773-4f4e44671857?w=400",
        "example_urls": [],
        "base_prompt": "cyberpunk gamer style, neon pink and blue lighting, futuristic aesthetic, dark gaming room background",
        "tier_required": "free",
        "tags": ["cyberpunk", "neon", "gaming"],
        "sort_order": 4
    },
    {
        "name": "Anime Streamer",
        "slug": "anime-streamer",
        "category": "gaming",
        "description": "Arte estilo anime japonés, colores vibrantes.",
        "preview_url": "https://images.unsplash.com/photo-1607604276583-eef5d076aa5f?w=400",
        "example_urls": [],
        "base_prompt": "in japanese anime art style, vibrant colors, digital illustration",
        "tier_required": "free",
        "tags": ["anime", "manga", "vibrant"],
        "sort_order": 5
    },
    {
        "name": "Pixel Art",
        "slug": "pixel-art",
        "category": "gaming",
        "description": "Retrato en arte pixelado retro.",
        "preview_url": "https://images.unsplash.com/photo-1550745165-9bc0b252726f?w=400",
        "example_urls": [],
        "base_prompt": "16-bit retro pixel art style, video game aesthetic, colorful background, pixelated details",
        "tier_required": "free",
        "tags": ["pixel", "retro", "8-bit"],
        "sort_order": 6
    },
    {
        "name": "Cartoon Avatar",
        "slug": "cartoon-avatar",
        "category": "gaming",
        "description": "Estilo cartoon occidental, proporciones exageradas.",
        "preview_url": "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=400",
        "example_urls": [],
        "base_prompt": "in 3D cartoon style like Disney Pixar, exaggerated expressions, bright solid background",
        "tier_required": "free",
        "tags": ["cartoon", "comic", "friendly"],
        "sort_order": 7
    },
    # Categoría: Redes Sociales
    {
        "name": "Gradient Pop",
        "slug": "gradient-pop",
        "category": "social",
        "description": "Fondo con gradiente de colores, moderno y llamativo.",
        "preview_url": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=400",
        "example_urls": [],
        "base_prompt": "in pop art style, dynamic colorful gradient background, high contrast, trendy aesthetic",
        "tier_required": "free",
        "tags": ["gradient", "pop", "modern"],
        "sort_order": 8
    },
    {
        "name": "Minimalist",
        "slug": "minimalist",
        "category": "social",
        "description": "Fondo blanco/negro, minimalismo extremo.",
        "preview_url": "https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=400",
        "example_urls": [],
        "base_prompt": "minimalist high contrast style, clean lines, black and white aesthetic, solid white background",
        "tier_required": "free",
        "tags": ["minimalist", "clean", "simple"],
        "sort_order": 9
    },
    {
        "name": "Sticker Style",
        "slug": "sticker-style",
        "category": "social",
        "description": "Estilo pegatina con borde blanco grueso.",
        "preview_url": "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=400",
        "example_urls": [],
        "base_prompt": "as sticker art, thick white outline, cartoon graphic design, flat colors, transparent look",
        "tier_required": "free",
        "tags": ["sticker", "outline", "pop"],
        "sort_order": 10
    },
    # Categoría: Videojuegos (Pro)
    {
        "name": "Fantasy Hero",
        "slug": "fantasy-hero",
        "category": "gaming-character",
        "description": "Héroe de RPG, armadura medieval, iluminación épica.",
        "preview_url": "https://images.unsplash.com/photo-1514888286974-6c03e2ca1dba?w=400",
        "example_urls": [],
        "base_prompt": "RPG fantasy hero style, wearing detailed armor, glowing reflections, epic medieval background",
        "tier_required": "pro",
        "tags": ["fantasy", "rpg", "armor"],
        "sort_order": 11
    },
    {
        "name": "Sci-Fi Soldier",
        "slug": "sci-fi-soldier",
        "category": "gaming-character",
        "description": "Personaje futurista, traje de combate espacial.",
        "preview_url": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=400",
        "example_urls": [],
        "base_prompt": "sci-fi space marine style, high-tech powered armor, visor glowing, alien planet background",
        "tier_required": "pro",
        "tags": ["sci-fi", "space", "soldier"],
        "sort_order": 12
    },
    {
        "name": "Dark Fantasy",
        "slug": "dark-fantasy",
        "category": "gaming-character",
        "description": "Estilo oscuro, tenebroso, inspiración Dark Souls.",
        "preview_url": "https://images.unsplash.com/photo-1509248961158-e54f6934749c?w=400",
        "example_urls": [],
        "base_prompt": "dark fantasy warrior style, gothic architecture, misty ruins background, eerie dramatic lighting",
        "tier_required": "pro",
        "tags": ["dark", "fantasy", "gothic"],
        "sort_order": 13
    }
]

def seed_styles(db: Session):
    count = db.query(Style).count()
    if count == 0:
        print("Seeding initial styles in database...")
        for s_data in initial_styles:
            style = Style(**s_data)
            db.add(style)
        db.commit()
        print("Seeding finished successfully.")
    else:
        print(f"Database already contains {count} styles. Skipping seeding.")
