"""Synchronize modified project files to Desktop AWNG, write update documentation,
and create a complete backup archive for Update 2.1 (Novostroyki & Balconies).
"""
import os
import shutil
import zipfile
from pathlib import Path

ROOT = Path(r"c:\me\Antigravity projects\aroundworldng")
DESKTOP_DIR = Path(r"C:\Users\wilsz\Desktop\AWNG")
BACKUP_DIR = Path(r"C:\Users\wilsz\Desktop\AWNG_backup_update_2.1_novostroyki")

UPDATE_NOTES = """================================================================================
AROUNDWORLDNG / EARTHNG — UPDATE 2.1
РЕАЛИСТИЧНЫЕ НОВОСТРОЙКИ, БАЛКОНЫ И АРХИТЕКТУРА
Дата релиза: 18 ноября 2026
================================================================================

1. УДАЛЕНИЕ СТАРЫХ МУЛЬТЯШНЫХ ТЕКСТУР:
   - Полностью исключены из пулов генерации фасадов старые плоские коробки с примитивными
     синими окнами: pls_blue, pls_pink, pls_green, pnl_blue, off_blue, off_green,
     pls_d_blue, pls_d_tile, pnl_white, pnl_beige.
   - Офисные и коммерческие фасады переведены со старого off_blue на современное
     структурное фасадное остекление (pls_d_monolith_glass) и темные ленточные панели.

2. НОВЫЙ ПУЛ РЕАЛИСТИЧНЫХ НОВОСТРОЕК (18 СТИЛЕЙ, 72 DDS PBR ТЕКСТУРЫ):
   Все текстуры запечены с бесшовной стыковкой (12м основной фасад, 6м торцы),
   полной цепочкой мипмапов, DirectX 10 BC1 (DXT1) компрессией и PBR картами нормалей.
   В пул вошли как ЖК «Капитал» (Кудрово), так и ведущие современные архитектурные стили:
   - brk_d_kapital_amber: ЖК «Капитал» (Кудрово) — теплый янтарно-золотистый керамический кирпич, белые карнизы, витражные лоджии
   - brk_d_kapital_terracotta: ЖК «Капитал» (Кудрово) — фактурный терракотовый кирпич, графитовые рамы, белые обрамления окон
   - pls_d_svetliy_mir: ЖК «Светлый мир» — морской скандинавский стиль (платина, песочный, акцентная бирюза)
   - brk_d_galaktika: ЖК «Галактика» (Эталон) — 3-тоновый клинкер (шоколад, терракота, слоновая кость), эркерный ритм
   - pls_d_strizhi_glass: ЖК «Стрижи» (Setl) — светлые травертиновые плиты, панорамное зеркальное остекление в пол
   - pls_d_life_wood: ЖК «LIFE» (Pioneer) — японско-скандинавский эко-минимализм: композитное дерево кедра, темный графит
   - brk_d_ispanskie_kvartaly: ЖК «Испанские Кварталы» — европейский фактурный клинкер, черные французские балконы
   - pls_d_zeleny_kvartal: ЖК «Зеленый квартал» (Setl) — известняковый белый фасад с хвойно-зелеными нишами
   - pls_d_chistoe_nebo: ЖК «Чистое Небо» (Setl) — глубокий кобальт, индиго и серебристые вентилируемые панели
   - pls_d_monolith_glass: Бизнес-класс — сплошное структурное остекление с межэтажными стемалитовыми поясами
   - pls_d_pik_orange: ПИК — фирменная белая сетка с сочными оранжевыми нишами и корзинами кондиционеров
   - pls_d_pik_cyan: ПИК — акцентный лазурно-голубой цвет с геометрическими окнами
   - pls_d_pik_yellow: ПИК — солнечно-желтые акцентные простенки
   - brk_d_clinker_dark: Темный графитовый ригельный клинкер премиум-сегмента
   - pls_d_setl_scandi: Скандинавский минимализм (Setl City) — графит, теплое дерево, широкие окна
   - pls_d_setl_cappuccino: Setl City — благородные оттенки капучино, бежевого и темного шоколада
   - pls_d_samolet_azure: Группа «Самолет» — светлый композит с небесно-голубыми вставками
   - pls_d_lsr_terracotta: «Группа ЛСР» — горизонтальное терракотово-кремовое членение фасадов

3. МОДЕРНИЗАЦИЯ СИСТЕМЫ 3D-БАЛКОНОВ:
   - Полностью убран ржавый профнастил (clad_tin) на современных зданиях.
   - Ограждения парапетов балконов заменены на современное архитектурное стекло (wall_glass),
     гладкий композит (clad_metal) и темный цокольный камень (plinth).
   - Остекление верхних лоджий переведено на отражающее стекло (wall_glass).
   - Увеличена плотность размещения балконов и лоджий (column = 0.48, glazed = 0.78, глубина 1.05м).
   - Расширен диапазон этажности балконов до 28 этажей (maxFloors = 28) для высотных новостроек.

4. МГНОВЕННОЕ ОБНОВЛЕНИЕ БЕЗ ПЕРЕГЕНЕРАЦИИ:
   - Все 6 архивов планет (mod/, Desktop, BeamNG mods/) обновлены.
   - Поскольку BeamNG считывает фасады и процедурные балконы динамически через generator.lua
     и aroundworldng_planet.zip, все новые текстуры и балконы видны СРАЗУ при обычном запуске игры,
     полная перегенерация карты не требуется.

5. РЕЗЕРВНОЕ КОПИРОВАНИЕ:
   - Создана полная резервная копия билда:
     C:\\Users\\wilsz\\Desktop\\AWNG_backup_update_2.1_novostroyki
   - Предыдущие резервные копии сохранены:
     C:\\Users\\wilsz\\Desktop\\AWNG_backup_working
     C:\\Users\\wilsz\\Desktop\\AWNG_backup_novostroyki_phase1
================================================================================
"""

def main():
    print("1. Writing update notes...")
    (ROOT / "README_UPDATE_INFO.txt").write_text(UPDATE_NOTES, encoding="utf-8")
    (DESKTOP_DIR / "README_UPDATE_INFO.txt").write_text(UPDATE_NOTES, encoding="utf-8")

    print("2. Syncing updated files to Desktop AWNG...")
    files_to_sync = [
        Path("aroundworldng/fast_photo.py"),
        Path("aroundworldng/fast_facade.py"),
        Path("aroundworldng/planet/materials.json"),
        Path("mod/lua/ge/extensions/e2r/generator.lua"),
        Path("tests/test_novostroyki_integration.py"),
        Path("tests/test_generator_integrity.py"),
        Path("scripts/pack_novostroyki_into_planets.py"),
    ]

    for rel in files_to_sync:
        src = ROOT / rel
        dst = DESKTOP_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  Synced {rel} -> Desktop")

    # Also sync generated DDS textures to Desktop/out/generated_novostroyki
    gen_src = ROOT / "out" / "generated_novostroyki"
    gen_dst = DESKTOP_DIR / "out" / "generated_novostroyki"
    gen_dst.mkdir(parents=True, exist_ok=True)
    for dds in gen_src.glob("*.dds"):
        shutil.copy2(dds, gen_dst / dds.name)
    print(f"  Synced {len(list(gen_src.glob('*.dds')))} DDS files to Desktop out/generated_novostroyki")

    print("3. Creating full labeled backup for Update 2.1...")
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Copy all essential files and folders into backup
    for item in ["app", "aroundworldng", "mod", "tests", "scripts", "out",
                 "AroundWorldNG.bat", "AroundWorldNG.py", "BUILD_INFO.json",
                 "README_UPDATE_INFO.txt", "README.md", "requirements-fast.txt"]:
        src_item = ROOT / item
        dst_item = BACKUP_DIR / item
        if src_item.is_file():
            shutil.copy2(src_item, dst_item)
        elif src_item.is_dir():
            shutil.copytree(src_item, dst_item)

    print(f"  Backup successfully created at {BACKUP_DIR}")
    print("Done!")

if __name__ == "__main__":
    main()
