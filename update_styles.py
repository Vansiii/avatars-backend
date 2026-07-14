"""
Script para actualizar los base_prompts de los estilos en la base de datos.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database.database import SessionLocal
from app.models.style import Style

def update_styles():
    db = SessionLocal()
    try:
        print("\n" + "=" * 70)
        print("🔄 ACTUALIZANDO BASE_PROMPTS DE ESTILOS")
        print("=" * 70 + "\n")
        
        # Nuevos base_prompts (más sutiles, actúan como modificadores)
        updates = {
            "corporate-portrait": "professional corporate style, neutral studio background, business attire, high quality, realistic lighting",
            "creative-professional": "creative professional style, modern art studio background, smart casual, warm colors, natural expression",
            "executive-headshot": "executive headshot style, dark gradient background, formal suit, sharp focus, cinematic lighting",
            "neon-gamer": "cyberpunk gamer style, neon pink and blue lighting, futuristic aesthetic, dark gaming room background",
            "anime-streamer": "in japanese anime art style, vibrant colors, digital illustration",
            "pixel-art": "16-bit retro pixel art style, video game aesthetic, colorful background, pixelated details",
            "cartoon-avatar": "in 3D cartoon style like Disney Pixar, exaggerated expressions, bright solid background",
            "gradient-pop": "in pop art style, dynamic colorful gradient background, high contrast, trendy aesthetic",
            "minimalist": "minimalist high contrast style, clean lines, black and white aesthetic, solid white background",
            "sticker-style": "as sticker art, thick white outline, cartoon graphic design, flat colors, transparent look",
            "fantasy-hero": "RPG fantasy hero style, wearing detailed armor, glowing reflections, epic medieval background",
            "sci-fi-soldier": "sci-fi space marine style, high-tech powered armor, visor glowing, alien planet background",
            "dark-fantasy": "dark fantasy warrior style, gothic architecture, misty ruins background, eerie dramatic lighting",
        }
        
        updated_count = 0
        for slug, new_prompt in updates.items():
            style = db.query(Style).filter(Style.slug == slug).first()
            if style:
                old_prompt = style.base_prompt
                style.base_prompt = new_prompt
                print(f"✅ {slug}:")
                print(f"   Antes: {old_prompt[:80]}...")
                print(f"   Ahora: {new_prompt}\n")
                updated_count += 1
            else:
                print(f"⚠️  Estilo '{slug}' no encontrado en la base de datos\n")
        
        db.commit()
        
        print("=" * 70)
        print(f"✅ {updated_count} estilos actualizados exitosamente")
        print("=" * 70 + "\n")
        
        print("🎯 CAMBIO PRINCIPAL:")
        print("   Los base_prompts ahora son MODIFICADORES de estilo,")
        print("   no descripciones completas. El prompt del usuario")
        print("   va PRIMERO para tener mayor control.\n")
        
        print("📝 EJEMPLO:")
        print('   Usuario escribe: "Homero Simpson chino"')
        print('   Estilo: Anime Streamer')
        print('   Prompt final: "Homero Simpson chino, in japanese anime art style, vibrant colors, digital illustration"')
        print("   Resultado esperado: Homero en estilo anime ✅\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    update_styles()
