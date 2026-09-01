#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ОКОННЫЙ ЗАВОД — рендер ролика для первого экрана.

Собирает сцену целиком кодом: геометрию шести конфигураций окна,
студийный свет, объёмную дымку, камеру с анимацией и переходами.
Интерфейс Blender открывать не нужно.

Запуск:
    blender --background --python render/window_film.py -- [аргументы]

Аргументы:
    --engine  EEVEE | CYCLES     черновик или финал        (по умолч. CYCLES)
    --samples 128                сэмплов на пиксель        (по умолч. 128)
    --res     1920x1080          разрешение                (по умолч. 1920x1080)
    --fps     30                 кадров в секунду          (по умолч. 30)
    --hold    3.0                сколько держится кадр, с  (по умолч. 3.0)
    --trans   1.2                длительность перехода, с  (по умолч. 1.2)
    --shots   0,1,2,3,4,5        какие конфигурации снимать
    --out     render/out         куда складывать кадры
    --preview                    один кадр вместо ролика (быстрая проверка)

Что даёт Cycles, чего не может браузер:
    · честная трассировка сквозь стекло, а не приближение
    · каустика — блики, которые стеклопакет бросает на пол
    · объёмная дымка с настоящими лучами света
    · глубина резкости как у объектива 35 мм на f/2.0
"""

import bpy
import bmesh
import math
import sys
import os
from mathutils import Vector

# ============================================================================
#  Аргументы
# ============================================================================

def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    cfg = {
        "engine": "CYCLES", "samples": 128, "res": "1920x1080", "fps": 30,
        "hold": 3.0, "trans": 1.2, "shots": "0,1,2,3,4,5",
        "out": "render/out", "preview": False, "stills": 0,
    }
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--preview":
            cfg["preview"] = True; i += 1; continue
        key = a.lstrip("-")
        if key in cfg and i + 1 < len(argv):
            val = argv[i + 1]
            cfg[key] = int(val) if key in ("samples", "fps", "stills") else (
                float(val) if key in ("hold", "trans") else val)
            i += 2
        else:
            i += 1
    return cfg


CFG = parse_args()
RES_X, RES_Y = (int(v) for v in CFG["res"].lower().split("x"))
SHOT_IDS = [int(s) for s in str(CFG["shots"]).split(",") if s.strip() != ""]

# ============================================================================
#  Конфигурации изделий
#  rows — деление по высоте, cols — по ширине внутри строки.
#  Те же шесть кадров, что и в живой сцене на сайте.
# ============================================================================

F = 0.062   # ширина профиля
I = 0.050   # импост
D = 0.090   # монтажная глубина

CONFIGS = [
    dict(id="single", name="Одностворчатое", w=0.62, h=1.14,
         rows=[dict(h=1, cols=[1])],
         sill=0.85, move={'a': (0.55, 1.62, 0.3, 0.0, -0.1), 'b': (0.16, 1.02, 0.06, 0.0, -0.22), 'fstop': 4.5, 'name': 'наезд'},
         cam=(0, 0, 0)),
dict(id="double", name="Двухстворчатое", w=1.00, h=1.32,
         rows=[dict(h=1, cols=[1, 1])],
         sill=0.85, move={'a': (-1.35, 1.18, 0.1, 0.0, -0.24), 'b': (0.95, 1.18, 0.1, 0.0, -0.24), 'fstop': 5.6, 'name': 'проезд вбок'},
         cam=(0, 0, 0)),
dict(id="triple", name="Трёхстворчатое", w=1.62, h=1.32,
         rows=[dict(h=1, cols=[1, 1, 1])],
         sill=0.80, move={'a': (-0.3, 1.52, -0.42, 0.0, -0.3), 'b': (-0.1, 1.34, 0.34, 0.0, -0.18), 'fstop': 6.3, 'name': 'общий план с подъёмом'},
         cam=(0, 0, 0)),
dict(id="transom", name="С фрамугой", w=1.04, h=1.52,
         rows=[dict(h=0.32, cols=[1]), dict(h=1, cols=[1, 1])],
         sill=0.75, move={'a': (1.15, 0.216, -0.50, 0.30, -0.52), 'b': (0.92, 0.175, -0.36, 0.30, -0.46), 'fstop': 2.8, 'lens': 50, 'name': 'деталь на фурнитуре'},
         cam=(0, 0, 0)),
# окно и дверь рядом: у двери высота больше, поэтому это две рамы
    dict(id="block", name="Балконный блок",
         parts=[
             dict(w=1.02, h=0.96, dx=-0.44, dz=0.25,
                  rows=[dict(h=1, cols=[1, 1])], handle=(0.40, -0.30)),
             dict(w=0.66, h=1.46, dx=0.42, dz=0.0,
                  rows=[dict(h=0.34, cols=[1]), dict(h=1, cols=[1])], handle=(-0.22, -0.34)),
         ],
         sill=0.10, move={'a': (-1.25, 1.24, -0.05, 0.0, -0.26), 'b': (1.25, 1.24, 0.12, 0.0, -0.26), 'fstop': 5.6, 'name': 'облёт по дуге'},
         cam=(0, 0, 0)),
dict(id="pano", name="Панорама в пол", w=2.25, h=1.52,
         rows=[dict(h=1, cols=[1, 1, 1])],
         handle=None,
         sill=0.06, move={'a': (0.2, 0.92, 0.02, 0.0, -0.24), 'b': (-0.35, 1.28, 0.22, 0.0, -0.16), 'fstop': 6.3, 'name': 'отъезд'},
         cam=(0, 0, 0)),
]

# ============================================================================
#  Материалы
# ============================================================================

def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def node_material(name, build):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    shader = build(nt)
    nt.links.new(shader.outputs[0], out.inputs["Surface"])
    return mat


def rough_variation(nt, node, lo, hi, scale=90.0, detail=6.0):
    """Гуляющая шероховатость на основе шума.

    Постоянное значение по всей поверхности даёт мёртвый ровный блик —
    это первое, по чему картинка читается как компьютерная.
    """
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = detail
    tex.inputs["Roughness"].default_value = 0.55
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["To Min"].default_value = lo
    ramp.inputs["To Max"].default_value = hi
    nt.links.new(tex.outputs["Fac"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], node.inputs["Roughness"])
    return tex


def mat_profile():
    """ПВХ-профиль антрацит: матовый, с живым неровным бликом."""
    def build(nt):
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        p.inputs["Base Color"].default_value = (0.030, 0.032, 0.038, 1)
        p.inputs["Metallic"].default_value = 0.0
        if "Specular IOR Level" in p.inputs:
            p.inputs["Specular IOR Level"].default_value = 0.45
        rough_variation(nt, p, 0.28, 0.52, scale=140, detail=8)
        # микрорельеф: у пластика поверхность не зеркально гладкая
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.08
        n2 = nt.nodes.new("ShaderNodeTexNoise")
        n2.inputs["Scale"].default_value = 420
        n2.inputs["Detail"].default_value = 6
        nt.links.new(n2.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
        return p
    return node_material("Профиль ПВХ", build)


def mat_glass():
    """Стеклопакет: преломление 1.52 плюс пыль и разводы.

    Идеально чистого стекла не бывает. Лёгкая грязь на поверхности —
    то, что сразу отличает съёмку от рендера.
    """
    def build(nt):
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        p.inputs["Base Color"].default_value = (1, 1, 1, 1)
        p.inputs["IOR"].default_value = 1.52
        p.inputs["Transmission Weight"].default_value = 1.0
        if "Coat Weight" in p.inputs:
            p.inputs["Coat Weight"].default_value = 0.28
        # пыль и разводы: шероховатость гуляет пятнами
        rough_variation(nt, p, 0.004, 0.020, scale=18, detail=9)
        smudge = nt.nodes.new("ShaderNodeBump")
        smudge.inputs["Strength"].default_value = 0.010
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 9
        n.inputs["Detail"].default_value = 10
        nt.links.new(n.outputs["Fac"], smudge.inputs["Height"])
        nt.links.new(smudge.outputs["Normal"], p.inputs["Normal"])
        return p
    return node_material("Стеклопакет", build)


def mat_hardware():
    """Фурнитура: металл цвета шампань."""
    def build(nt):
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        p.inputs["Base Color"].default_value = (0.72, 0.64, 0.50, 1)
        p.inputs["Metallic"].default_value = 1.0
        p.inputs["Roughness"].default_value = 0.22
        return p
    return node_material("Фурнитура", build)


def mat_floor():
    """Пол: тёмный, слегка глянцевый — он ловит каустику от стекла."""
    def build(nt):
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        p.inputs["Base Color"].default_value = (0.006, 0.006, 0.008, 1)
        p.inputs["Roughness"].default_value = 0.22
        p.inputs["Metallic"].default_value = 0.15
        return p
    return node_material("Пол", build)


ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def pbr_material(name, folder, prefix, scale=1.0, tint=None):
    """Материал из фотосканированного набора карт ambientCG.

    Процедурные заливки читаются как компьютер, потому что у них нет
    истории: ни пятен, ни следов износа. Снятая с реальной поверхности
    карта даёт всё это бесплатно.
    """
    base = os.path.join(ASSETS, "textures", folder)
    files = {
        "Color":        f"{prefix}_Color.jpg",
        "Roughness":    f"{prefix}_Roughness.jpg",
        "NormalGL":     f"{prefix}_NormalGL.jpg",
    }
    if not os.path.exists(os.path.join(base, files["Color"])):
        return None

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])

    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    def tex(fname, non_color=True):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(os.path.join(base, fname))
        if non_color:
            n.image.colorspace_settings.name = "Non-Color"
        n.extension = "REPEAT"
        n.projection = "BOX"
        n.projection_blend = 0.30
        nt.links.new(mapping.outputs["Vector"], n.inputs["Vector"])
        return n

    col = tex(files["Color"], non_color=False)
    if tint:
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 1.0
        mix.inputs[2].default_value = (*tint, 1)
        nt.links.new(col.outputs["Color"], mix.inputs[1])
        nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        nt.links.new(col.outputs["Color"], bsdf.inputs["Base Color"])

    rough = tex(files["Roughness"])
    nt.links.new(rough.outputs["Color"], bsdf.inputs["Roughness"])

    nor = tex(files["NormalGL"])
    nmap = nt.nodes.new("ShaderNodeNormalMap")
    nmap.inputs["Strength"].default_value = 0.8
    nt.links.new(nor.outputs["Color"], nmap.inputs["Color"])
    nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def mat_wall():
    """Стена комнаты: светлая штукатурка, матовая."""
    def build(nt):
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        p.inputs["Base Color"].default_value = (0.165, 0.160, 0.152, 1)
        rough_variation(nt, p, 0.72, 0.95, scale=26, detail=8)
        # фактура штукатурки
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = 0.22
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 160
        n.inputs["Detail"].default_value = 10
        nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
        nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
        return p
    return node_material("Стена", build)


def mat_room_floor():
    """Пол комнаты: тёмное дерево, слегка отражает свет из окна."""
    def build(nt):
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        p.inputs["Base Color"].default_value = (0.062, 0.050, 0.038, 1)
        p.inputs["Roughness"].default_value = 0.35
        return p
    return node_material("Пол комнаты", build)


def mat_reveal():
    """Откос: чуть светлее стены, ловит свет из проёма."""
    def build(nt):
        p = nt.nodes.new("ShaderNodeBsdfPrincipled")
        p.inputs["Base Color"].default_value = (0.30, 0.292, 0.278, 1)
        p.inputs["Roughness"].default_value = 0.7
        return p
    return node_material("Откос", build)


def mat_backdrop():
    """Свет за окном.

    Сферический градиент здесь трижды схлопывался в пятно: его радиус
    считается в координатах объекта, а плоскость масштабируется под каждую
    конфигурацию. Ровная эмиссия ведёт себя предсказуемо и читается именно
    так, как надо — пасмурное небо за стеклом.
    """
    mat = bpy.data.materials.new("Свет за окном")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (1.0, 0.84, 0.62, 1)
    emit.inputs["Strength"].default_value = 2.0
    nt.links.new(emit.outputs[0], out.inputs["Surface"])
    return mat


# ============================================================================
#  Геометрия
# ============================================================================

def box(name, w, h, d, x, y, z, mat, parent):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z))
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = (w, d, h)
    bpy.ops.object.transform_apply(scale=True)
    ob.data.materials.append(mat)
    ob.parent = parent
    return ob


ROOM_W = 15.0     # ширина стены: с запасом, чтобы кадр никогда не «протекал»
ROOM_H = 3.10     # высота потолка
WALL_T = 0.34     # толщина стены: даёт откосы и глубину проёма


def load_props():
    """Мебель и растения из бесплатной библиотеки Poly Haven.

    Пустая комната читается как тестовый рендер: глазу не за что
    зацепиться и нечем измерить масштаб. Реальные предметы дают и то,
    и другое, а заодно приносят свои фотосканированные материалы.
    """
    base = os.path.join(ASSETS, "models2")
    items = {
        "кресло":   ("mid_century_lounge_chair", "mid_century_lounge_chair_2k.gltf"),
        "столик":   ("coffee_table_round_01",    "coffee_table_round_01_2k.gltf"),
        "растение": ("potted_plant_01",          "potted_plant_01_2k.gltf"),
        "цветок":   ("anthurium_botany_01",      "anthurium_botany_01_2k.gltf"),
    }
    loaded = {}
    for label, (folder, fname) in items.items():
        path = os.path.join(base, folder, fname)
        if not os.path.exists(path):
            continue
        before = set(bpy.data.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=path)
        except Exception as e:
            print(f"[мебель] {label}: не импортировалось ({e})")
            continue
        new = [o for o in set(bpy.data.objects) - before if o.type == "MESH"]
        for o in new:
            o.hide_render = o.hide_viewport = True      # оригинал прячем
        loaded[label] = new
        print(f"[мебель] {label}: {len(new)} объектов")
    return loaded


def place_props(props, cfg, parent, floor_z):
    """Расставляет копии предметов в комнате вокруг окна."""
    made = []
    layout = [
        ("кресло",   (-1.15, -1.35), math.radians(28),  1.0),
        ("столик",   (-0.30, -2.05), math.radians(-12), 1.0),
        ("растение", ( 1.25, -1.05), math.radians(15),  1.0),
    ]
    for label, (x, y), rot, sc in layout:
        for src in props.get(label, []):
            ob = src.copy()
            ob.data = src.data                     # общие меши: память не растёт
            ob.hide_render = ob.hide_viewport = False
            bpy.context.scene.collection.objects.link(ob)
            ob.location = (src.location.x + x, src.location.y + y, src.location.z + floor_z)
            ob.rotation_euler = (src.rotation_euler.x, src.rotation_euler.y, rot)
            ob.scale = tuple(v * sc for v in src.scale)
            ob.parent = parent
            made.append(ob)
    # цветок на подоконнике
    for src in props.get("цветок", []):
        ob = src.copy()
        ob.data = src.data
        ob.hide_render = ob.hide_viewport = False
        bpy.context.scene.collection.objects.link(ob)
        ob.location = (src.location.x + 0.30, src.location.y - 0.13,
                       src.location.z + cfg.get("_sill_z", 0))
        ob.scale = tuple(v * 0.8 for v in src.scale)
        ob.parent = parent
        made.append(ob)
    return made


def build_room(cfg, mats, parent):
    """Стена с проёмом, откосы, пол и потолок вокруг изделия.

    Проём собирается из четырёх кусков стены, а не булевой операцией:
    так надёжнее и не зависит от порядка модификаторов.
    """
    # У составных конфигураций (окно + дверь) общего габарита нет —
    # считаем его как объединение частей.
    if "parts" in cfg:
        xs, zs = [], []
        for pt in cfg["parts"]:
            dx, dz = pt.get("dx", 0), pt.get("dz", 0)
            xs += [dx - pt["w"] / 2, dx + pt["w"] / 2]
            zs += [dz - pt["h"] / 2, dz + pt["h"] / 2]
        W, H = max(xs) - min(xs), max(zs) - min(zs)
        cx, cz = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2
    else:
        W, H = cfg["w"], cfg["h"]
        cx = cz = 0.0

    sill = cfg.get("sill", 0.85)
    made = []

    def slab(name, w, d, h, x, y, z, m):
        bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z))
        ob = bpy.context.active_object
        ob.name = name
        ob.scale = (w, d, h)
        bpy.ops.object.transform_apply(scale=True)
        ob.data.materials.append(m)
        ob.parent = parent
        made.append(ob)
        return ob

    floor_z = cz - H / 2 - sill
    ceil_z = floor_z + ROOM_H
    wy = WALL_T / 2                       # стена стоит за плоскостью окна

    left_w = (ROOM_W - W) / 2
    slab("стена_л", left_w, WALL_T, ROOM_H, cx - (W + left_w) / 2, wy, floor_z + ROOM_H / 2, mats["wall"])
    slab("стена_п", left_w, WALL_T, ROOM_H, cx + (W + left_w) / 2, wy, floor_z + ROOM_H / 2, mats["wall"])

    top_h = ceil_z - (cz + H / 2)
    if top_h > 0.01:
        slab("стена_в", W, WALL_T, top_h, cx, wy, cz + H / 2 + top_h / 2, mats["wall"])
    bot_h = (cz - H / 2) - floor_z
    if bot_h > 0.01:
        slab("стена_н", W, WALL_T, bot_h, cx, wy, floor_z + bot_h / 2, mats["wall"])

    # откосы: светлая полоса по периметру проёма, ловит свет
    r = 0.014
    slab("откос_л", r, WALL_T * 0.98, H, cx - (W / 2 - r / 2), wy, cz, mats["reveal"])
    slab("откос_п", r, WALL_T * 0.98, H, cx + (W / 2 - r / 2), wy, cz, mats["reveal"])
    slab("откос_в", W, WALL_T * 0.98, r, cx, wy, cz + H / 2 - r / 2, mats["reveal"])
    if bot_h > 0.01:
        slab("подоконник", W + 0.10, WALL_T * 1.5, 0.028, cx, WALL_T * 0.22, cz - H / 2 - 0.014, mats["reveal"])

    cfg["_sill_z"] = cz - H / 2 + 0.014
    slab("пол", ROOM_W * 1.6, 16.0, 0.04, 0, -6.0, floor_z - 0.02, mats["floor"])
    slab("потолок", ROOM_W * 1.6, 16.0, 0.04, 0, -6.0, ceil_z + 0.02, mats["wall"])
    slab("стена_боковая_л", 0.04, 16.0, ROOM_H, -ROOM_W * 0.5, -6.0, floor_z + ROOM_H / 2, mats["wall"])
    slab("стена_боковая_п", 0.04, 16.0, ROOM_H,  ROOM_W * 0.5, -6.0, floor_z + ROOM_H / 2, mats["wall"])

    cfg["_floor_z"] = floor_z
    return made


def build_window(cfg, mats, parent):
    """Собирает конфигурацию. Составные (окно + дверь) — из нескольких рам."""
    if "parts" in cfg:
        made = []
        for i, part in enumerate(cfg["parts"]):
            sub = dict(part)
            sub["id"] = f'{cfg["id"]}{i}'
            made += build_window(sub, mats, parent)
        return made

    W, H = cfg["w"], cfg["h"]
    DX = cfg.get("dx", 0.0)
    DZ = cfg.get("dz", 0.0)
    made = []
    def add(name, w, h, d, x, y, z, m):
        # смещение части внутри составной конфигурации
        made.append(box(name, w, h, d, x + DX, y, z + DZ, m, parent=parent))

    # свет позади именно этого изделия
    # внешняя рама
    add(f'{cfg["id"]}_рама_л', F, H, D, -(W / 2 - F / 2), 0, 0, mats["p"])
    add(f'{cfg["id"]}_рама_п', F, H, D,  (W / 2 - F / 2), 0, 0, mats["p"])
    if not cfg.get("arch"):
        add(f'{cfg["id"]}_рама_в', W - F * 2, F, D, 0, 0,  H / 2 - F / 2, mats["p"])
    add(f'{cfg["id"]}_рама_н', W - F * 2, F, D, 0, 0, -(H / 2 - F / 2), mats["p"])

    inner_w, inner_h = W - F * 2, H - F * 2
    total_row = sum(r["h"] for r in cfg["rows"])
    y_cursor = inner_h / 2

    for ri, row in enumerate(cfg["rows"]):
        row_h = (row["h"] / total_row) * inner_h - (I / 2 if ri > 0 else 0)
        row_top = y_cursor
        row_mid = row_top - row_h / 2

        if ri > 0:
            add(f'{cfg["id"]}_импост_г{ri}', inner_w, I, D, 0, 0, row_top + I / 2, mats["p"])

        total_col = sum(row["cols"])
        usable = inner_w - (len(row["cols"]) - 1) * I
        x_cursor = -inner_w / 2

        for ci, c in enumerate(row["cols"]):
            cw = (c / total_col) * usable
            if ci > 0:
                add(f'{cfg["id"]}_импост_в{ri}{ci}', I, row_h, D, x_cursor + I / 2, 0, row_mid, mats["p"])
                x_cursor += I
            add(f'{cfg["id"]}_стекло{ri}{ci}', cw, row_h, 0.028,
                x_cursor + cw / 2, 0, row_mid, mats["g"])
            x_cursor += cw

        y_cursor = row_top - row_h - I / 2

    # арочное завершение: тор, у которого отрезана нижняя половина
    if cfg.get("arch"):
        r = W / 2
        bpy.ops.mesh.primitive_torus_add(
            major_radius=r - F / 2, minor_radius=F / 2,
            major_segments=64, minor_segments=8,
            location=(DX, 0, DZ + H / 2), rotation=(math.pi / 2, 0, 0))
        arc = bpy.context.active_object
        arc.name = f'{cfg["id"]}_арка'
        me = arc.data
        bm = bmesh.new(); bm.from_mesh(me)
        for v in [v for v in bm.verts if v.co.y < -1e-4]:
            bm.verts.remove(v)
        bm.to_mesh(me); bm.free()
        me.materials.append(mats["p"])
        arc.parent = parent
        made.append(arc)

        bpy.ops.mesh.primitive_circle_add(
            vertices=64, radius=r - F, fill_type="NGON",
            location=(DX, 0, DZ + H / 2), rotation=(math.pi / 2, 0, 0))
        gl = bpy.context.active_object
        gl.name = f'{cfg["id"]}_стекло_арка'
        me = gl.data
        bm = bmesh.new(); bm.from_mesh(me)
        for v in [v for v in bm.verts if v.co.y < -1e-4]:
            bm.verts.remove(v)
        bm.to_mesh(me); bm.free()
        me.materials.append(mats["g"])
        gl.parent = parent
        made.append(gl)

    # фурнитура
    handle = cfg.get("handle", "auto")
    if handle is not None:
        hx, hz = (inner_w / 2 - 0.06, -H / 2 + 0.34) if handle == "auto" else handle
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.026, depth=0.022, vertices=24,
            location=(hx + DX, -(D / 2 - 0.01), hz + DZ), rotation=(math.pi / 2, 0, 0))
        rose = bpy.context.active_object
        rose.name = f'{cfg["id"]}_розетка'
        rose.data.materials.append(mats["h"])
        rose.parent = parent
        made.append(rose)
        add(f'{cfg["id"]}_ручка', 0.024, 0.19, 0.024, hx, -(D / 2 + 0.02), hz - 0.10, mats["h"])

    return made


# ============================================================================
#  Сцена
# ============================================================================

def build_scene():
    clear_scene()
    scene = bpy.context.scene
    mats = dict(p=mat_profile(), g=mat_glass(), h=mat_hardware(), b=mat_backdrop(),
                wall=mat_wall(), floor=mat_room_floor(), reveal=mat_reveal())

    # Фотосканы вместо процедурных заливок, если наборы карт на месте
    scan_wall = pbr_material("Штукатурка", "Plaster001", "Plaster001_2K-JPG",
                             scale=0.55, tint=(0.42, 0.41, 0.39))
    scan_floor = pbr_material("Дубовый пол", "WoodFloor051", "WoodFloor051_2K-JPG",
                              scale=0.6, tint=(0.44, 0.36, 0.28))
    if scan_wall:
        mats["wall"] = scan_wall
        mats["reveal"] = scan_wall
        print("[материалы] стена — фотоскан штукатурки")
    if scan_floor:
        mats["floor"] = scan_floor
        print("[материалы] пол — фотоскан дубовой доски")

    # Мир — панорама реального места. Она даёт три вещи сразу:
    # вид сквозь стекло, физически верный свет и отражения в стеклопакете.
    world = bpy.data.worlds.new("Мир")
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    wout = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    mp = nt.nodes.new("ShaderNodeMapping")
    tc = nt.nodes.new("ShaderNodeTexCoord")

    hdri = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "assets", HDRI_FILE)
    if os.path.exists(hdri):
        env.image = bpy.data.images.load(hdri)
        nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        # доворачиваем панораму так, чтобы солнце било в окно сбоку
        mp.inputs["Rotation"].default_value = (0, 0, math.radians(HDRI_ROT))
        bg.inputs["Strength"].default_value = HDRI_POWER
        print(f"[сцена] панорама: {os.path.basename(hdri)}, поворот {HDRI_ROT}°")
    else:
        bg.inputs["Color"].default_value = (0.05, 0.06, 0.08, 1)
        bg.inputs["Strength"].default_value = 1.0
        print("[сцена] панорама не найдена — фон залит ровным цветом")
    nt.links.new(bg.outputs[0], wout.inputs["Surface"])
    scene.world = world

    # объёмная дымка: из-за неё видны лучи света — в браузере такого не будет
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, -5.0, 0))
    fog = bpy.context.active_object
    fog.name = "Дымка"
    fog.scale = (16, 16, 5)
    bpy.ops.object.transform_apply(scale=True)
    fog_mat = bpy.data.materials.new("Дымка")
    fog_mat.use_nodes = True
    nt = fog_mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumeScatter")
    vol.inputs["Color"].default_value = (1.0, 0.90, 0.76, 1)
    vol.inputs["Density"].default_value = 0.022
    vol.inputs["Anisotropy"].default_value = 0.55
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    fog.data.materials.append(fog_mat)
    fog.visible_shadow = False

    # Отдельных ламп больше нет: свет целиком приходит с панорамы сквозь
    # проём — так же, как в настоящей комнате. Единственная добавка —
    # слабая заливка спереди, чтобы профиль не проваливался в чёрный.
    bpy.ops.object.light_add(type="AREA", location=(1.6, -3.4, 0.4))
    fill = bpy.context.active_object
    fill.name = "Заливка"
    fill.data.energy = 45
    fill.data.size = 3.0
    fill.data.color = (0.86, 0.90, 1.0)
    fill.rotation_euler = (math.radians(96), 0, math.radians(38))

    # держатель, вокруг которого крутятся изделия
    pivot = bpy.data.objects.new("Держатель", None)
    scene.collection.objects.link(pivot)

    props = load_props()

    groups = []
    for cfg in CONFIGS:
        holder = bpy.data.objects.new(f'кадр_{cfg["id"]}', None)
        scene.collection.objects.link(holder)
        holder.parent = pivot
        win_objs = build_window(cfg, mats, holder)
        room_objs = build_room(cfg, mats, holder)
        room_objs += place_props(props, cfg, holder, cfg.get("_floor_z", -1.5))
        for ob in win_objs + room_objs:
            if ob.type != "MESH":
                continue
            bev = ob.modifiers.new("Фаска", "BEVEL")
            bev.width = 0.0016          # 1.6 мм — как у настоящего профиля
            bev.segments = 2
            bev.limit_method = "ANGLE"
            bev.angle_limit = math.radians(40)
            bev.harden_normals = True
            for poly in ob.data.polygons:
                poly.use_smooth = True
        groups.append(dict(cfg=cfg, holder=holder,
                           objs=win_objs + room_objs, win=win_objs))

    # камера: 35 мм с открытой диафрагмой — отсюда мягкий задний план
    bpy.ops.object.camera_add(location=(0, -3.2, 0))
    cam = bpy.context.active_object
    cam.name = "Камера"
    cam.data.lens = 35
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = 5.0
    scene.camera = cam

    target = bpy.data.objects.new("Точка фокуса", None)
    scene.collection.objects.link(target)
    cam.data.dof.focus_object = target
    con = cam.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"

    return dict(scene=scene, cam=cam, target=target, groups=groups, fog=fog)


# ============================================================================
#  Анимация: те же переходы, что и в живой сцене
# ============================================================================

BASE_YAW = math.radians(6)    # лёгкий доворот: окно стоит в стене, сильный разворот тут не нужен
HDRI_FILE = "stierberg_sunrise_8k.hdr"
HDRI_ROT = 234               # солнце прямо за окном: контровой свет сквозь стеклопакет                # поворот панорамы, градусы: ставим солнце сбоку от окна
HDRI_POWER = 1.35             # яркость окружения
CAM_SIDE = 0.72               # снос камеры вбок: кадр перестаёт быть фронтальным
CAM_DROP = 0.16              # посадка ниже: в кадр входит пол со светом

# Доля кадра, которую занимает изделие. Остальное — воздух вокруг.
FIT_H = 0.56
FIT_W = 0.64
SENSOR = 36.0                 # мм, полный кадр по горизонтали


def fit_distance(objs, lens, res_x, res_y):
    """На каком расстоянии изделие впишется в кадр с заданным запасом.

    Считаем по фактическому габариту собранной геометрии: у одностворчатого
    окна и у панорамы он отличается вчетверо, и одна дистанция на всех
    неизбежно обрезает часть конфигураций.
    """
    xs, zs = [], []
    for ob in objs:
        if ob.type != "MESH":
            continue
        for corner in ob.bound_box:
            v = ob.matrix_world @ Vector(corner)
            xs.append(v.x); zs.append(v.z)
    if not xs:
        return 4.0
    w = max(xs) - min(xs)
    h = max(zs) - min(zs)
    # разворот увеличивает видимую ширину на глубину профиля
    w = w * math.cos(BASE_YAW) + 0.09 * math.sin(BASE_YAW)

    sensor_h = SENSOR * res_y / res_x
    d_by_h = h / (FIT_H * 2 * math.tan(math.atan(sensor_h / (2 * lens))))
    d_by_w = w / (FIT_W * 2 * math.tan(math.atan(SENSOR / (2 * lens))))
    return max(d_by_h, d_by_w)


def ease(t):
    return 4 * t ** 3 if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def animate(S):
    scene, cam, target, groups = S["scene"], S["cam"], S["target"], S["groups"]
    bpy.context.view_layer.update()
    for g in groups:
        g["lens"] = g["cfg"]["move"].get("lens", 35)
        g["dist"] = fit_distance(g["win"], g["lens"], RES_X, RES_Y)
        print(f'[кадр] {g["cfg"]["name"]:18} дистанция {g["dist"]:.2f} м')
    fps = CFG["fps"]
    scene.render.fps = fps
    hold_f = int(round(CFG["hold"] * fps))
    trans_f = int(round(CFG["trans"] * fps))
    cycle_f = hold_f + trans_f
    shots = [groups[i] for i in SHOT_IDS]
    total = cycle_f * len(shots)

    scene.frame_start = 1
    scene.frame_end = total

    # конфигурации вне выборки прячем насовсем, иначе они остаются
    # видимыми по умолчанию и накладываются на кадр
    for g in groups:
        if g in shots:
            continue
        g["holder"].hide_viewport = g["holder"].hide_render = True
        for ob in g["objs"]:
            ob.hide_viewport = ob.hide_render = True

    def key_group(g, frame, alpha, offset_y, rot_z, scale):
        h = g["holder"]
        h.location = (0, offset_y, 0)
        h.rotation_euler = (0, 0, rot_z)
        h.scale = (scale, scale, scale)
        h.keyframe_insert("location", frame=frame)
        h.keyframe_insert("rotation_euler", frame=frame)
        h.keyframe_insert("scale", frame=frame)
        vis = alpha > 0.004
        h.hide_viewport = not vis
        h.hide_render = not vis
        h.keyframe_insert("hide_viewport", frame=frame)
        h.keyframe_insert("hide_render", frame=frame)
        for ob in g["objs"]:
            ob.hide_viewport = not vis
            ob.hide_render = not vis
            ob.keyframe_insert("hide_viewport", frame=frame)
            ob.keyframe_insert("hide_render", frame=frame)

    for f in range(1, total + 1):
        t = (f - 1) / cycle_f
        idx = int(t) % len(shots)
        nxt = (idx + 1) % len(shots)
        local = (f - 1) - idx * cycle_f
        k = 0.0 if local <= hold_f else ease((local - hold_f) / max(trans_f, 1))

        for gi, g in enumerate(shots):
            if gi == idx:
                key_group(g, f, 1 - k, -k * 0.35, BASE_YAW - k * 0.10, 1 - k * 0.05)
            elif gi == nxt:
                key_group(g, f, k, (1 - k) * 0.35, BASE_YAW + (1 - k) * 0.10, 0.95 + k * 0.05)
            else:
                key_group(g, f, 0, 0, BASE_YAW, 1)

        # Положение камеры внутри плана: движение идёт всё время, а не
        # только на стыке. Именно из-за статики предыдущая версия читалась
        # как слайд-шоу, а не как съёмка.
        u = min(local / max(cycle_f - 1, 1), 1.0)

        def cam_state(shot, t):
            m = shot["cfg"]["move"]
            e = ease(t)
            a, b = m["a"], m["b"]
            side, dmul, hgt, lx, lz = [a[i] + (b[i] - a[i]) * e for i in range(5)]
            d = shot["dist"] * dmul
            return (side, -d, hgt), (lx, 0.0, lz)

        pos_a, look_a = cam_state(shots[idx], u)
        pos_b, look_b = cam_state(shots[nxt], 0.0)
        pos = [pos_a[i] + (pos_b[i] - pos_a[i]) * k for i in range(3)]
        look = [look_a[i] + (look_b[i] - look_a[i]) * k for i in range(3)]

        # облёт: на дуге камера должна идти по окружности, а не по прямой
        if shots[idx]["cfg"]["move"].get("name") == "облёт по дуге" and k < 0.5:
            pos[1] -= abs(math.sin(u * math.pi)) * shots[idx]["dist"] * 0.10

        la, lb = shots[idx]["lens"], shots[nxt]["lens"]
        cam.data.lens = la + (lb - la) * k
        cam.data.keyframe_insert("lens", frame=f)

        fa = shots[idx]["cfg"]["move"].get("fstop", 5.0)
        fb = shots[nxt]["cfg"]["move"].get("fstop", 5.0)
        cam.data.dof.aperture_fstop = fa + (fb - fa) * k
        cam.data.dof.keyframe_insert("aperture_fstop", frame=f)

        cam.location = pos
        cam.keyframe_insert("location", frame=f)
        target.location = look
        target.keyframe_insert("location", frame=f)

    # Микротряска: идеально ровный проезд камеры выдаёт рельсы.
    # Шум по положению и наклону имитирует съёмку с рук.
    if cam.animation_data and cam.animation_data.action:
        for fc in cam.animation_data.action.fcurves:
            if fc.data_path != "location":
                continue
            m = fc.modifiers.new("NOISE")
            m.scale = 14.0
            m.strength = 0.0075 if fc.array_index != 1 else 0.004
            m.phase = fc.array_index * 11.3
            m.depth = 1

    # ступенчатая интерполяция для видимости, плавная — для движения
    for g in groups:
        ad = g["holder"].animation_data
        if ad and ad.action:
            for fc in ad.action.fcurves:
                if "hide" in fc.data_path:
                    for kp in fc.keyframe_points:
                        kp.interpolation = "CONSTANT"
        for ob in g["objs"]:
            ad = ob.animation_data
            if ad and ad.action:
                for fc in ad.action.fcurves:
                    for kp in fc.keyframe_points:
                        kp.interpolation = "CONSTANT"
    return total


# ============================================================================
#  Настройки рендера
# ============================================================================

def setup_render(S, total):
    scene = S["scene"]
    r = scene.render
    r.resolution_x, r.resolution_y = RES_X, RES_Y
    r.resolution_percentage = 100
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.image_settings.compression = 15

    # Смаз по затвору: без него движение читается как компьютерная анимация,
    # а не как снятый материал.
    r.use_motion_blur = True
    r.motion_blur_shutter = 0.55

    out_dir = os.path.abspath(CFG["out"])
    os.makedirs(out_dir, exist_ok=True)
    r.filepath = os.path.join(out_dir, "кадр_")

    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = -0.20     # киношная тональная кривая
    scene.view_settings.look = "AgX - Medium High Contrast"

    if CFG["engine"].upper().startswith("E"):
        scene.render.engine = "BLENDER_EEVEE_NEXT"
        ee = scene.eevee
        if hasattr(ee, "use_raytracing"):
            ee.use_raytracing = True
        if hasattr(ee, "taa_render_samples"):
            ee.taa_render_samples = 64
        if hasattr(ee, "use_volumetric_shadows"):
            ee.use_volumetric_shadows = True
        print("[рендер] EEVEE Next — черновик")
    else:
        scene.render.engine = "CYCLES"
        cy = scene.cycles
        cy.samples = CFG["samples"]
        cy.use_denoising = True
        cy.max_bounces = 24
        cy.transmission_bounces = 20      # чтобы луч прошёл сквозь несколько стёкол
        cy.transparent_max_bounces = 24
        cy.caustics_reflective = True
        cy.caustics_refractive = True     # каустика от стекла на полу
        cy.volume_bounces = 2
        cy.blur_glossy = 0.6

        prefs = bpy.context.preferences.addons["cycles"].preferences
        chosen = None
        for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                gpus = [d for d in prefs.devices if d.type == backend]
                if gpus:
                    for d in prefs.devices:
                        d.use = (d.type == backend) or d.type == "CPU"
                    chosen = backend
                    break
            except Exception:
                continue
        if chosen:
            cy.device = "GPU"
            try:
                cy.denoiser = "OPTIX" if chosen == "OPTIX" else "OPENIMAGEDENOISE"
            except Exception:
                pass
            names = [d.name for d in prefs.devices if d.use and d.type != "CPU"]
            print(f"[рендер] Cycles на GPU ({chosen}): {', '.join(names) or '—'}")
        else:
            cy.device = "CPU"
            print("[рендер] Cycles на процессоре — GPU не найден, будет медленно")

    print(f"[рендер] {RES_X}x{RES_Y}, {CFG['fps']} fps, кадров: {total}")
    print(f"[рендер] выход: {out_dir}")


# ============================================================================

def setup_compositor(scene):
    """Дефекты объектива, из-за которых кадр читается как снятый.

    Идеальная оптика существует только в рендере: реальный объектив даёт
    ореол вокруг ярких мест, расходится по цвету к краям и темнит углы.

    В Blender 4.5 часть настроек переехала из свойств узла во входные
    сокеты, поэтому значения ставим через помощник, который знает оба
    варианта — иначе скрипт ломается при смене версии.
    """
    def put(node, name, value):
        if name in node.inputs:
            node.inputs[name].default_value = value
            return True
        attr = name.lower().replace(" ", "_")
        if hasattr(node, attr):
            setattr(node, attr, value)
            return True
        return False

    scene.use_nodes = True
    nt = scene.node_tree
    nt.nodes.clear()

    rl = nt.nodes.new("CompositorNodeRLayers")
    out = nt.nodes.new("CompositorNodeComposite")

    # ореол вокруг яркого проёма — так ведёт себя настоящая оптика
    glare = nt.nodes.new("CompositorNodeGlare")
    glare.glare_type = "FOG_GLOW"
    if hasattr(glare, "quality"):
        glare.quality = "HIGH"
    put(glare, "Threshold", 0.75)
    put(glare, "Strength", 0.14)
    put(glare, "Size", 8)
    if hasattr(glare, "mix"):
        glare.mix = -0.7

    # хроматическая аберрация: к краям кадра цвета расходятся
    lens = nt.nodes.new("CompositorNodeLensdist")
    put(lens, "Distortion", 0.004)
    put(lens, "Dispersion", 0.0040)
    put(lens, "Fit", True)

    # виньетка: объектив всегда темнит углы
    ell = nt.nodes.new("CompositorNodeEllipseMask")
    if hasattr(ell, "width"):
        ell.width, ell.height = 0.88, 0.94
    else:
        put(ell, "Size", (0.88, 0.94))
    blur = nt.nodes.new("CompositorNodeBlur")
    blur.filter_type = "GAUSS"
    blur.use_relative = False
    blur.size_x = blur.size_y = 200
    vig = nt.nodes.new("CompositorNodeMixRGB")
    vig.blend_type = "MULTIPLY"
    vig.inputs["Fac"].default_value = 0.40

    # плёночный грейд: тени уходят в холодный синий, света — в тёплый.
    # Без этого рендер читается как рендер: у цифры тени нейтрально-серые,
    # у плёнки — никогда.
    grade = nt.nodes.new("CompositorNodeColorBalance")
    grade.correction_method = "LIFT_GAMMA_GAIN"
    grade.lift = (0.985, 0.995, 1.022)      # тени холоднее
    grade.gamma = (1.005, 1.000, 0.992)
    grade.gain = (1.028, 1.008, 0.972)      # света теплее

    # плёночная кривая: приподнятая подошва и мягкое плечо в светах
    curve = nt.nodes.new("CompositorNodeCurveRGB")
    cm = curve.mapping
    c = cm.curves[3]
    c.points[0].location = (0.0, 0.010)
    c.points[1].location = (1.0, 0.985)
    # S-образная кривая: плёнка держит контраст в середине тона, а не
    # растягивает его равномерно — без этого кадр выглядит вялым
    c.points.new(0.26, 0.20)
    c.points.new(0.74, 0.83)
    cm.update()

    nt.links.new(rl.outputs["Image"], grade.inputs["Image"])
    nt.links.new(grade.outputs["Image"], curve.inputs["Image"])
    nt.links.new(curve.outputs["Image"], glare.inputs["Image"])
    nt.links.new(glare.outputs["Image"], lens.inputs["Image"])
    nt.links.new(lens.outputs["Image"], vig.inputs[1])
    nt.links.new(ell.outputs["Mask"], blur.inputs["Image"])
    nt.links.new(blur.outputs["Image"], vig.inputs[2])
    nt.links.new(vig.outputs["Image"], out.inputs["Image"])
    print("[оптика] засветка, хроматическая аберрация и виньетка включены")


def main():
    S = build_scene()
    total = animate(S)
    setup_render(S, total)
    setup_compositor(S["scene"])

    if CFG["stills"]:
        # раскадровка: n равномерных кадров по всему ролику — быстрая
        # проверка хореографии до полного просчёта
        n = CFG["stills"]
        for j in range(n):
            f = 1 + round((total - 1) * j / max(n - 1, 1))
            S["scene"].frame_set(f)
            S["scene"].render.filepath = os.path.join(
                os.path.abspath(CFG["out"]), "раскадровка_%02d" % j)
            bpy.ops.render.render(write_still=True)
        print("[готово] раскадровка: %d кадров" % n)
    elif CFG["preview"]:
        S["scene"].frame_set(max(1, total // 3))
        S["scene"].render.filepath = os.path.join(os.path.abspath(CFG["out"]), "превью")
        bpy.ops.render.render(write_still=True)
        print("[готово] превью-кадр записан")
    else:
        bpy.ops.render.render(animation=True)
        print("[готово] все кадры записаны")


if __name__ == "__main__":
    main()
