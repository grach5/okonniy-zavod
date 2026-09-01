"""Один непрерывный проезд камеры по помещению.

Отличие от window_film.py принципиальное. Там было шесть отдельных сцен,
склеенных растворением: изделия подменялись на одном и том же месте, и
глаз читал это как перелистывание картинок, а не как съёмку.

Здесь всё наоборот. Помещение одно, окна разной формы стоят вдоль стены
на своих местах, камера идёт мимо них единым движением без единой
склейки. Ровно так снимают интерьеры: оператор идёт по комнате, планы
рождаются из движения, а не из монтажа.

    blender --background --factory-startup --python render/window_walk.py -- \
            --engine CYCLES --samples 96 --res 1920x1080 --fps 24 --dur 20 \
            --out render/walk

    --stills 12   вместо ролика — раскадровка, быстрая проверка хореографии
    --engine EEVEE  черновик: секунды на кадр вместо минут
"""

import bpy
import bmesh
import math
import os
import sys
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
CORE = os.path.join(HERE, "window_film.py")

# ---------------------------------------------------------------------------
#  Общая часть с window_film.py: материалы, сборка рамы, настройки рендера.
#  Импортировать напрямую нельзя — файл лежит не в пути модулей Blender,
#  поэтому исполняем его в отдельном пространстве имён.
# ---------------------------------------------------------------------------
CORE_NS = {"__name__": "window_film_core", "__file__": CORE}
exec(compile(open(CORE, encoding="utf-8").read(), CORE, "exec"), CORE_NS)

box = CORE_NS["box"]
build_window = CORE_NS["build_window"]
pbr_material = CORE_NS["pbr_material"]
clear_scene = CORE_NS["clear_scene"]
setup_compositor = CORE_NS["setup_compositor"]
mat_profile = CORE_NS["mat_profile"]
mat_glass = CORE_NS["mat_glass"]
mat_hardware = CORE_NS["mat_hardware"]
mat_wall = CORE_NS["mat_wall"]
mat_room_floor = CORE_NS["mat_room_floor"]
mat_reveal = CORE_NS["mat_reveal"]
ASSETS = CORE_NS["ASSETS"]


# ============================================================================
#  Аргументы
# ============================================================================

def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    cfg = {"engine": "CYCLES", "samples": 96, "res": "1920x1080", "fps": 24,
           "dur": 20.0, "out": "render/walk", "stills": 0}
    i = 0
    while i < len(argv):
        key = argv[i].lstrip("-")
        if key in cfg and i + 1 < len(argv):
            v = argv[i + 1]
            cfg[key] = (int(v) if key in ("samples", "fps", "stills")
                        else float(v) if key == "dur" else v)
            i += 2
        else:
            i += 1
    return cfg


CFG = parse_args()
RES_X, RES_Y = (int(v) for v in CFG["res"].lower().split("x"))

# ============================================================================
#  Помещение
# ============================================================================

CEIL = 2.95           # высота потолка
WALL_T = 0.34         # толщина наружной стены
DEPTH = 6.4           # глубина комнаты от окон до дальней стены
X0, X1 = -12.6, 9.6   # границы стены с окнами

F = CORE_NS["F"]      # ширина профиля
I = CORE_NS["I"]      # импост

# Габариты взяты жилые, а не декоративные: балконная дверь 2,15 м —
# в неё проходит человек, и в кадре с потолком 2,95 это сразу видно.
# Именно на этом ломались прошлые версии: окно «в масштабе картинки»
# рядом с настоящим креслом читается как игрушечное.
LAYOUT = [
    dict(id="pano", name="Панорама в пол", x=-9.0, sill=0.10,
         w=2.60, h=2.30, rows=[dict(h=1, cols=[1, 1, 1])], handle=None),

    dict(id="triple", name="Трёхстворчатое", x=-5.4, sill=0.85,
         w=2.10, h=1.40, rows=[dict(h=1, cols=[1, 1, 1])]),

    # Балконный блок — это два проёма в стене, а не один.
    # Под оконной частью остаётся подоконная стенка высотой 0,85; если
    # сделать проём общим, под окном получается дыра до пола.
    dict(id="block_win", name="Балконный блок · окно", x=-2.15, sill=0.85,
         w=1.30, h=1.40, rows=[dict(h=1, cols=[1, 1])], handle=(0.52, -0.42)),

    dict(id="block_door", name="Балконный блок · дверь", x=-1.15, sill=0.10,
         w=0.70, h=2.15,
         rows=[dict(h=0.22, cols=[1]), dict(h=1, cols=[1])],
         handle=(-0.24, -0.30)),

    dict(id="transom", name="С фрамугой", x=1.6, sill=0.60,
         w=1.30, h=1.90,
         rows=[dict(h=0.26, cols=[1]), dict(h=1, cols=[1, 1])],
         handle=(0.52, -0.62)),

    dict(id="double", name="Двухстворчатое", x=4.4, sill=0.85,
         w=1.30, h=1.40, rows=[dict(h=1, cols=[1, 1])]),

    dict(id="single", name="Одностворчатое", x=6.9, sill=1.00,
         w=0.70, h=1.20, rows=[dict(h=1, cols=[1])]),
]

HDRI_FILE = "signal_hill_sunrise_8k.hdr"
HDRI_FALLBACK = "stierberg_sunrise_8k.hdr"
HDRI_ROT = 200        # в окна смотрит бухта с городом на сопках,
                      # солнце низко слева — контровой свет вдоль стены
HDRI_POWER = 1.9


def span(item):
    """Габарит проёма: ширина, высота и центр по вертикали от пола."""
    if "parts" in item:
        xs, zs = [], []
        for p in item["parts"]:
            dx, dz = p.get("dx", 0), p.get("dz", 0)
            xs += [dx - p["w"] / 2, dx + p["w"] / 2]
            zs += [dz - p["h"] / 2, dz + p["h"] / 2]
        w, h = max(xs) - min(xs), max(zs) - min(zs)
        cx, cz = (max(xs) + min(xs)) / 2, (max(zs) + min(zs)) / 2
    else:
        w, h, cx, cz = item["w"], item["h"], 0.0, 0.0
    return w, h, cx, cz


def opening(item):
    """Проём в мировых координатах: x0, x1, z низа, z верха."""
    w, h, cx, cz = span(item)
    z0 = item["sill"]
    return item["x"] + cx - w / 2, item["x"] + cx + w / 2, z0, z0 + h


# ============================================================================
#  Оболочка помещения
# ============================================================================

def slab(name, w, d, h, x, y, z, mat, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z))
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = (w, d, h)
    bpy.ops.object.transform_apply(scale=True)
    ob.data.materials.append(mat)
    if parent:
        ob.parent = parent
    return ob


def build_shell(mats):
    """Пол, потолок, боковые и дальняя стены."""
    made = []
    wide = X1 - X0
    cx = (X0 + X1) / 2
    made.append(slab("пол", wide + 0.6, DEPTH + 0.6, 0.06,
                     cx, -DEPTH / 2, -0.03, mats["floor"]))
    made.append(slab("потолок", wide + 0.6, DEPTH + 0.6, 0.06,
                     cx, -DEPTH / 2, CEIL + 0.03, mats["wall"]))
    made.append(slab("стена_торец_л", 0.12, DEPTH, CEIL,
                     X0 - 0.06, -DEPTH / 2, CEIL / 2, mats["wall"]))
    made.append(slab("стена_торец_п", 0.12, DEPTH, CEIL,
                     X1 + 0.06, -DEPTH / 2, CEIL / 2, mats["wall"]))
    # дальнюю стену собирает build_doorway: в ней проём
    return made


def build_outer_wall(mats):
    """Наружная стена с шестью проёмами.

    Стена собирается плитами между проёмами, а не булевой резкой: так
    результат не зависит от порядка модификаторов и считается быстрее.
    """
    made = []
    wy = WALL_T / 2
    ops = [opening(it) for it in LAYOUT]

    # простенки между проёмами и по краям стены
    edges = [X0] + [v for o in ops for v in o[:2]] + [X1]
    piers = [(edges[0], edges[1])] + \
            [(ops[i][1], ops[i + 1][0]) for i in range(len(ops) - 1)] + \
            [(ops[-1][1], X1)]
    for i, (a, b) in enumerate(piers):
        if b - a < 0.02:
            continue
        made.append(slab("простенок_%d" % i, b - a, WALL_T, CEIL,
                         (a + b) / 2, wy, CEIL / 2, mats["wall"]))

    # подоконная и надоконная части над каждым проёмом
    for it, (x0, x1, z0, z1) in zip(LAYOUT, ops):
        w = x1 - x0
        cx = (x0 + x1) / 2
        if z0 > 0.02:
            made.append(slab("подоконная_%s" % it["id"], w, WALL_T, z0,
                             cx, wy, z0 / 2, mats["wall"]))
        top = CEIL - z1
        if top > 0.02:
            made.append(slab("надоконная_%s" % it["id"], w, WALL_T, top,
                             cx, wy, z1 + top / 2, mats["wall"]))

        # откосы: светлая грань по периметру проёма, ловит свет
        r = 0.016
        made.append(slab("откос_л_%s" % it["id"], r, WALL_T * 0.98, z1 - z0,
                         x0 + r / 2, wy, (z0 + z1) / 2, mats["reveal"]))
        made.append(slab("откос_п_%s" % it["id"], r, WALL_T * 0.98, z1 - z0,
                         x1 - r / 2, wy, (z0 + z1) / 2, mats["reveal"]))
        made.append(slab("откос_в_%s" % it["id"], w, WALL_T * 0.98, r,
                         cx, wy, z1 - r / 2, mats["reveal"]))
        if z0 > 0.12:
            made.append(slab("подоконник_%s" % it["id"], w + 0.12,
                             WALL_T * 1.45, 0.030,
                             cx, WALL_T * 0.20, z0 - 0.015, mats["reveal"]))
    return made


# ============================================================================
#  Ткани: их нет в бесплатных библиотеках, поэтому строим сами
# ============================================================================

def mat_cloth(name, folder, tint, scale=1.4):
    """Ткань из набора карт Poly Haven.

    Именование у них своё — diff/nor_gl/rough вместо Color/NormalGL/
    Roughness у ambientCG, поэтому общий загрузчик тут не подходит.
    """
    base = os.path.join(ASSETS, "textures", folder)
    diff = os.path.join(base, "%s_diff_2k.jpg" % folder)
    if not os.path.exists(diff):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*tint, 1)
        b.inputs["Roughness"].default_value = 0.92
        return m

    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])

    coord = nt.nodes.new("ShaderNodeTexCoord")
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs["Object"], mapping.inputs["Vector"])

    def tex(fname, non_color=True):
        path = os.path.join(base, fname)
        if not os.path.exists(path):
            return None
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(path)
        if non_color:
            n.image.colorspace_settings.name = "Non-Color"
        n.extension = "REPEAT"
        n.projection = "BOX"
        n.projection_blend = 0.30
        nt.links.new(mapping.outputs["Vector"], n.inputs["Vector"])
        return n

    c = tex("%s_diff_2k.jpg" % folder, non_color=False)
    if c:
        mixc = nt.nodes.new("ShaderNodeMixRGB")
        mixc.blend_type = "MULTIPLY"
        mixc.inputs["Fac"].default_value = 0.85
        mixc.inputs[2].default_value = (*tint, 1)
        nt.links.new(c.outputs["Color"], mixc.inputs[1])
        nt.links.new(mixc.outputs["Color"], bsdf.inputs["Base Color"])
    r = tex("%s_rough_2k.jpg" % folder)
    if r:
        nt.links.new(r.outputs["Color"], bsdf.inputs["Roughness"])
    nr = tex("%s_nor_gl_2k.jpg" % folder)
    if nr:
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = 1.0
        nt.links.new(nr.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    print("[материалы] %s — фотоскан %s" % (name, folder))
    return m


def build_curtain(name, x, width, top, bottom, mat, folds=5, amp=0.058):
    """Штора: полотно со складками по синусоиде.

    Ровная плоскость с текстурой ткани читается как бумага. Складки
    дают тень внутри самой шторы — именно она и опознаётся как ткань.
    """
    n = folds * 8
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    rows = 10
    grid = []
    for i in range(n + 1):
        u = i / n
        gx = x - width / 2 + width * u
        col = []
        for j in range(rows + 1):
            v = j / rows
            z = top + (bottom - top) * v
            # книзу складка раскрывается, у карниза почти собрана
            k = 0.35 + 0.65 * v
            wave = (math.sin(u * math.pi * 2 * folds)
                    + 0.42 * math.sin(u * math.pi * 2 * folds * 1.7 + 1.1))
            gy = -WALL_T * 0.05 - amp * k * wave
            col.append(bm.verts.new((gx, gy, z)))
        grid.append(col)
    bm.verts.ensure_lookup_table()
    for i in range(n):
        for j in range(rows):
            bm.faces.new((grid[i][j], grid[i + 1][j],
                          grid[i + 1][j + 1], grid[i][j + 1]))
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.data.materials.append(mat)
    sol = ob.modifiers.new("Толщина", "SOLIDIFY")
    sol.thickness = 0.004
    sub = ob.modifiers.new("Сглаживание", "SUBSURF")
    sub.levels = sub.render_levels = 1
    for p in me.polygons:
        p.use_smooth = True
    return ob


def build_rug(name, x, y, w, d, mat):
    ob = slab(name, w, d, 0.012, x, y, 0.008, mat)
    sol = ob.modifiers.new("Ворс", "BEVEL")
    sol.width = 0.006
    sol.segments = 2
    return ob


# ============================================================================
#  Мебель
# ============================================================================

PROPS = {
    "диван":      "sofa_03",
    "кресло":     "modern_arm_chair_01",
    "кресло2":    "mid_century_lounge_chair",
    "столик":     "modern_coffee_table_01",
    "столик2":    "coffee_table_round_01",
    "стол":       "dining_table",
    "стул":       "dining_chair_02",
    "комод":      "modern_wooden_cabinet",
    "люстра":     "modern_ceiling_lamp_01",
    "книги":      "decorative_book_set_01",
    "ваза":       "ceramic_vase_02",
    "ваза2":      "brass_vase_01",
    "картина":    "hanging_picture_frame_02",
    "растение":   "potted_plant_01",
    "кашпо":      "planter_box_02",
    "цветок":     "anthurium_botany_01",
    "стеллаж":    "wooden_bookshelf_worn",
    "консоль":    "chinese_console_table",
    "табурет":    "metal_stool_01",
    "зеркало":    "ornate_mirror_01",
    "рамка":      "fancy_picture_frame_01",
    "картина2":   "hanging_picture_frame_01",
    "горшок":     "brass_pot_01",
    "кашпо2":     "ceramic_pot",
    "ваза3":      "antique_ceramic_vase_01",
    "часы":       "alarm_clock_01",
    "скамья":     "painted_wooden_bench",
    "столик3":    "modern_coffee_table_02",
}


def load_props():
    base = os.path.join(ASSETS, "models2")
    loaded = {}
    for label, folder in PROPS.items():
        d = os.path.join(base, folder)
        if not os.path.isdir(d):
            continue
        gltf = [f for f in os.listdir(d) if f.endswith(".gltf")]
        if not gltf:
            continue
        before = set(bpy.data.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=os.path.join(d, gltf[0]))
        except Exception as e:
            print("[мебель] %s: не импортировалось (%s)" % (label, e))
            continue
        new = [o for o in set(bpy.data.objects) - before if o.type == "MESH"]
        for o in new:
            o.hide_render = o.hide_viewport = True
        loaded[label] = new
        print("[мебель] %-10s %s (%d об.)" % (label, folder, len(new)))
    return loaded


def place(props, label, x, y, rot=0.0, scale=1.0, z=None, made=None):
    """Ставит предмет так, чтобы он стоял на полу в точке (x, y).

    Импортированные модели приходят с произвольным началом координат,
    поэтому положение считаем по фактическому габариту после поворота,
    а не по координатам из файла.
    """
    src = props.get(label)
    if not src:
        return []
    holder = bpy.data.objects.new("узел_%s" % label, None)
    bpy.context.scene.collection.objects.link(holder)
    holder.rotation_euler = (0, 0, rot)
    holder.scale = (scale, scale, scale)

    copies = []
    for s in src:
        ob = s.copy()
        ob.data = s.data                      # меш общий: память не растёт
        ob.hide_render = ob.hide_viewport = False
        bpy.context.scene.collection.objects.link(ob)
        ob.parent = holder
        copies.append(ob)

    bpy.context.view_layer.update()
    xs, ys, zs = [], [], []
    for ob in copies:
        for c in ob.bound_box:
            v = ob.matrix_world @ Vector(c)
            xs.append(v.x); ys.append(v.y); zs.append(v.z)
    if xs:
        holder.location = (
            x - (max(xs) + min(xs)) / 2,
            y - (max(ys) + min(ys)) / 2,
            (z if z is not None else 0.0) - min(zs),
        )
    if made is not None:
        made += copies
    return copies


def furnish(props, mats):
    """Расстановка по зонам. Пустой метраж — главная примета рендера."""
    made = []
    linen = mats["linen"]
    wool = mats["wool"]

    # --- зона у панорамы: гостиная -------------------------------------
    build_rug("ковёр_гостиная", -8.8, -3.1, 3.4, 2.5, wool)
    place(props, "диван", -8.6, -4.05, math.radians(180), made=made)
    place(props, "столик", -8.8, -2.6, math.radians(4), made=made)
    place(props, "ваза", -8.8, -2.6, 0, z=0.42, made=made)
    place(props, "кресло", -6.6, -3.0, math.radians(-118), made=made)
    place(props, "растение", -10.9, -1.5, math.radians(20), made=made)
    build_curtain("штора_пано_л", -10.62, 0.85, CEIL - 0.12, 0.02, linen)
    build_curtain("штора_пано_п", -7.38, 0.85, CEIL - 0.12, 0.02, linen)

    # --- зона трёхстворчатого: чтение -----------------------------------
    place(props, "кресло2", -5.2, -2.05, math.radians(196), made=made)
    place(props, "столик2", -4.0, -2.35, math.radians(-14), made=made)
    place(props, "книги", -4.0, -2.35, 0, z=0.44, made=made)
    place(props, "кашпо", -3.1, -1.05, math.radians(-8), made=made)
    build_curtain("штора_трёх_л", -6.85, 0.72, CEIL - 0.12, 0.02, linen)

    # --- зона балконного блока ------------------------------------------
    place(props, "растение", -0.35, -1.35, math.radians(-40), made=made)
    place(props, "цветок", -2.15, -0.13, 0, z=0.87, scale=0.8, made=made)

    # --- обеденная зона у фрамуги ---------------------------------------
    place(props, "стол", 1.7, -2.75, math.radians(2), made=made)
    for dx, dy, rz in ((-0.78, -2.05, 180), (0.02, -2.05, 180),
                       (-0.78, -3.45, 0), (0.02, -3.45, 0),
                       (0.92, -2.75, -90)):
        place(props, "стул", 1.7 + dx, dy, math.radians(rz), made=made)
    place(props, "ваза2", 1.7, -2.75, 0, z=0.76, made=made)
    place(props, "люстра", 1.7, -2.75, 0, z=CEIL - 0.62, made=made)

    # --- зона двухстворчатого: комод -------------------------------------
    place(props, "комод", 4.6, -0.62, math.radians(180), made=made)
    place(props, "ваза", 5.3, -0.62, 0, z=0.86, made=made)
    place(props, "книги", 4.0, -0.62, math.radians(12), z=0.86, made=made)
    place(props, "картина", 6.0, -0.02, 0, z=1.55, made=made)

    # --- зона одностворчатого --------------------------------------------
    place(props, "кресло", 7.5, -1.75, math.radians(150), made=made)
    place(props, "растение", 8.6, -1.1, math.radians(-25), made=made)
    place(props, "цветок", 6.9, -0.10, 0, z=1.02, scale=0.8, made=made)

    # --- дальняя стена и торцы -------------------------------------------
    # Пока по глубине комнаты не за что зацепиться взглядом, помещение
    # читается декорацией: у настоящей квартиры вещи есть везде, а не
    # только там, куда смотрит камера.
    back = -DEPTH + 0.34
    place(props, "стеллаж", X0 + 0.55, -3.20, math.radians(90), made=made)
    place(props, "консоль", -3.40, back, math.radians(180), made=made)
    place(props, "зеркало", -3.40, back - 0.30, 0, z=1.05, made=made)
    place(props, "ваза3", -3.05, back, 0, z=0.78, made=made)
    place(props, "часы", -3.72, back, math.radians(-16), z=0.78, made=made)
    place(props, "скамья", 0.60, back + 0.06, math.radians(180), made=made)
    place(props, "картина2", 1.90, back - 0.28, 0, z=1.28, made=made)
    place(props, "рамка", 2.85, back - 0.28, 0, z=1.42, made=made)
    place(props, "горшок", -0.55, back + 0.10, 0, made=made)

    # --- мелочи по зонам ---------------------------------------------------
    build_rug("ковёр_столовая", 1.70, -2.75, 3.2, 2.4, wool)
    place(props, "табурет", -7.35, -3.95, math.radians(24), made=made)
    place(props, "столик3", -6.20, -4.75, math.radians(-8), made=made)
    place(props, "кашпо2", -6.20, -4.75, 0, z=0.42, made=made)
    place(props, "часы", 4.20, -0.62, math.radians(10), z=0.86, made=made)
    place(props, "горшок", 8.95, -3.10, 0, made=made)
    return made



# ============================================================================
#  Достоверность поверхностей
# ============================================================================

def weather(mat, patchy=0.06, rough=0.10, waviness=0.0, wave_scale=1.1):
    """Добавляет материалу историю.

    Ровная заливка одной текстурой — вторая по заметности примета
    рендера после плоского света. У настоящей поверхности цвет гуляет
    крупными пятнами, шероховатость неоднородна, а сама плоскость
    никогда не бывает плоской: штукатурка ведёт стену на миллиметры, и
    в скользящем утреннем свете эта волна видна за метр.
    """
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not bsdf:
        return mat

    if patchy:
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 0.38
        n.inputs["Detail"].default_value = 4.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        lo, hi = 1.0 - patchy, 1.0 + patchy * 0.45
        ramp.color_ramp.elements[0].color = (lo, lo, lo, 1)
        ramp.color_ramp.elements[1].color = (hi, hi, hi, 1)
        nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"])
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 1.0
        src = bsdf.inputs["Base Color"]
        if src.is_linked:
            nt.links.new(src.links[0].from_socket, mix.inputs[1])
        else:
            mix.inputs[1].default_value = src.default_value
        nt.links.new(ramp.outputs["Color"], mix.inputs[2])
        nt.links.new(mix.outputs["Color"], src)

    if rough:
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = 2.6
        n.inputs["Detail"].default_value = 6.0
        ramp = nt.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].color = (1.0 - rough,) * 3 + (1,)
        ramp.color_ramp.elements[1].color = (1.0 + rough,) * 3 + (1,)
        nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"])
        mix = nt.nodes.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs["Fac"].default_value = 1.0
        src = bsdf.inputs["Roughness"]
        if src.is_linked:
            nt.links.new(src.links[0].from_socket, mix.inputs[1])
        else:
            v = src.default_value
            mix.inputs[1].default_value = (v, v, v, 1)
        nt.links.new(ramp.outputs["Color"], mix.inputs[2])
        nt.links.new(mix.outputs["Color"], src)

    if waviness:
        n = nt.nodes.new("ShaderNodeTexNoise")
        n.inputs["Scale"].default_value = wave_scale
        n.inputs["Detail"].default_value = 2.0
        bump = nt.nodes.new("ShaderNodeBump")
        bump.inputs["Strength"].default_value = waviness
        bump.inputs["Distance"].default_value = 0.14
        nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
        src = bsdf.inputs["Normal"]
        if src.is_linked:
            nt.links.new(src.links[0].from_socket, bump.inputs["Normal"])
        nt.links.new(bump.outputs["Normal"], src)
    return mat


def mat_paint(name, color, roughness=0.36):
    """Крашеная поверхность: плинтус, наличники, радиаторы, дверь."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1)
    b.inputs["Roughness"].default_value = roughness
    b.inputs["Metallic"].default_value = 0.0
    return weather(m, patchy=0.03, rough=0.14)


# ============================================================================
#  Архитектурные детали
# ============================================================================

def build_baseboard(mats):
    """Плинтус по периметру.

    Стена, входящая в пол под прямым углом без плинтуса, не встречается
    ни в одном реальном помещении. Одна эта деталь снимает половину
    ощущения нарисованного.
    """
    made = []
    h, d = 0.092, 0.018
    m = mats["paint"]

    # на стене с окнами плинтус разрывается там, где проём доходит до пола
    cuts = sorted(opening(it)[:2] for it in LAYOUT if it["sill"] < 0.30)
    segs, cur = [], X0
    for x0, x1 in cuts:
        if x0 - cur > 0.05:
            segs.append((cur, x0))
        cur = x1
    if X1 - cur > 0.05:
        segs.append((cur, X1))
    for i, (a, b) in enumerate(segs):
        made.append(slab("плинтус_окна_%d" % i, b - a, d, h,
                         (a + b) / 2, -d / 2, h / 2, m))

    made.append(slab("плинтус_дальний", X1 - X0, d, h,
                     (X0 + X1) / 2, -DEPTH + d / 2, h / 2, m))
    for nm, x, sgn in (("л", X0, 1), ("п", X1, -1)):
        made.append(slab("плинтус_торец_%s" % nm, d, DEPTH, h,
                         x + sgn * d / 2, -DEPTH / 2, h / 2, m))
    return made


def build_radiators(mats):
    """Радиаторы под окнами.

    Для завода это ещё и профессиональная деталь: подоконник над
    радиатором — постоянная тема на замере, от неё зависит и вылет
    подоконника, и то, будет ли окно потеть.
    """
    made = []
    for it in LAYOUT:
        x0, x1, z0, _ = opening(it)
        if z0 < 0.55:
            continue
        w = (x1 - x0) * 0.80
        cx = (x0 + x1) / 2
        top = z0 - 0.13
        h = min(0.50, top - 0.16)
        if h < 0.20:
            continue
        z = top - h / 2
        made.append(slab("радиатор_%s" % it["id"], w, 0.030, h,
                         cx, -0.050, z, mats["rad"]))
        n = max(5, int(w / 0.085))
        step = w / n
        fin = slab("ребро_%s" % it["id"], 0.011, 0.082, h * 0.94,
                   cx - w / 2 + step / 2, -0.090, z, mats["rad"])
        arr = fin.modifiers.new("Секции", "ARRAY")
        arr.count = n
        arr.use_relative_offset = False
        arr.use_constant_offset = True
        arr.constant_offset_displace = (step, 0, 0)
        made.append(fin)
    return made


def build_doorway(mats):
    """Дверной проём в дальней стене: комната перестаёт быть коробкой."""
    made = []
    dx, dw, dh = 5.6, 0.92, 2.10
    y = -DEPTH - 0.06
    for nm, (a, b) in (("л", (X0, dx - dw / 2)), ("п", (dx + dw / 2, X1))):
        made.append(slab("стена_дальняя_%s" % nm, b - a, 0.12, CEIL,
                         (a + b) / 2, y, CEIL / 2, mats["wall"]))
    made.append(slab("стена_дальняя_в", dw, 0.12, CEIL - dh,
                     dx, y, dh + (CEIL - dh) / 2, mats["wall"]))
    for nm, ox in (("л", -dw / 2 - 0.03), ("п", dw / 2 + 0.03)):
        made.append(slab("наличник_%s" % nm, 0.06, 0.022, dh + 0.06,
                         dx + ox, y + 0.07, (dh + 0.06) / 2, mats["paint"]))
    made.append(slab("наличник_в", dw + 0.12, 0.022, 0.06,
                     dx, y + 0.07, dh + 0.03, mats["paint"]))
    # полотно приоткрыто: за ним темнота, и коридор читается сам собой
    leaf = slab("дверь", dw - 0.02, 0.038, dh - 0.02,
                dx - (dw - 0.02) / 2, y + 0.06, (dh - 0.02) / 2, mats["paint"])
    leaf.location.x = dx - dw / 2
    made.append(leaf)
    return made


def build_switches(mats):
    """Розетки и выключатели: мелочь, которая задаёт масштаб."""
    made = []
    spots = [(-6.95, 1.32), (-0.30, 1.32), (3.10, 1.32),
             (-7.60, 0.30), (0.55, 0.30), (5.25, 0.30)]
    for i, (x, z) in enumerate(spots):
        made.append(slab("розетка_%d" % i, 0.082, 0.012, 0.082,
                         x, -0.006, z, mats["paint"]))
    return made


# ============================================================================
#  Хореография: один непрерывный проход
# ============================================================================

# (доля времени, положение камеры, точка взгляда, объектив, диафрагма)
PATH = [
    (0.00, (-11.30, -5.90, 1.66), (-7.20, -0.70, 1.50), 32, 5.6),
    (0.10, (-10.55, -4.55, 1.58), (-8.60, -0.35, 1.38), 32, 5.0),
    (0.21, (-9.55, -2.75, 1.36), (-9.05, -0.05, 1.16), 32, 4.0),
    (0.32, (-7.70, -3.05, 1.56), (-5.80, -0.25, 1.44), 35, 5.0),
    (0.43, (-5.70, -2.35, 1.52), (-5.40, -0.05, 1.48), 35, 4.5),
    (0.53, (-3.95, -3.70, 1.52), (-2.00, -0.15, 1.26), 32, 5.0),
    (0.62, (-2.30, -4.45, 1.50), (-1.65, -0.05, 1.14), 30, 4.5),
    (0.71, (0.30, -1.60, 1.14), (1.45, -0.05, 1.10), 40, 3.2),
    (0.78, (1.32, -1.18, 1.16), (1.86, 0.04, 1.16), 50, 2.4),
    (0.86, (2.85, -2.00, 1.38), (4.40, -0.08, 1.42), 35, 4.5),
    (0.93, (5.15, -2.45, 1.50), (6.88, -0.08, 1.48), 35, 4.5),
    (1.00, (5.60, -5.95, 1.62), (-1.30, -0.50, 1.30), 28, 6.3),
]


def smooth(t):
    """Плавный вход и выход — движение без рывка на стыке участков."""
    return t * t * (3 - 2 * t)


def sample_path(u):
    """Положение камеры в момент u ∈ [0, 1]."""
    for i in range(len(PATH) - 1):
        t0, p0, l0, ln0, f0 = PATH[i]
        t1, p1, l1, ln1, f1 = PATH[i + 1]
        if u <= t1 or i == len(PATH) - 2:
            k = smooth((u - t0) / (t1 - t0)) if t1 > t0 else 0.0
            mix = lambda a, b: [a[j] + (b[j] - a[j]) * k for j in range(3)]
            return (mix(p0, p1), mix(l0, l1),
                    ln0 + (ln1 - ln0) * k, f0 + (f1 - f0) * k)
    return PATH[-1][1], PATH[-1][2], PATH[-1][3], PATH[-1][4]


def animate(scene, cam, target):
    fps = CFG["fps"]
    total = max(2, int(round(CFG["dur"] * fps)))
    scene.render.fps = fps
    scene.frame_start = 1
    scene.frame_end = total

    for f in range(1, total + 1):
        u = (f - 1) / (total - 1)
        pos, look, lens, fstop = sample_path(u)
        cam.location = pos
        cam.keyframe_insert("location", frame=f)
        target.location = look
        target.keyframe_insert("location", frame=f)
        cam.data.lens = lens
        cam.data.keyframe_insert("lens", frame=f)
        cam.data.dof.aperture_fstop = fstop
        cam.data.dof.keyframe_insert("aperture_fstop", frame=f)

    # Микротряска. Идеально ровный проезд выдаёт рельсы: настоящая камера
    # всегда чуть дышит, даже на стабилизаторе.
    if cam.animation_data and cam.animation_data.action:
        for fc in cam.animation_data.action.fcurves:
            if fc.data_path != "location":
                continue
            m = fc.modifiers.new("NOISE")
            m.scale = 11.0
            m.strength = 0.010 if fc.array_index != 1 else 0.006
            m.phase = fc.array_index * 13.7
            m.depth = 1
    if target.animation_data and target.animation_data.action:
        for fc in target.animation_data.action.fcurves:
            m = fc.modifiers.new("NOISE")
            m.scale = 8.0
            m.strength = 0.012
            m.phase = fc.array_index * 7.1
            m.depth = 1
    return total


# ============================================================================
#  Сцена целиком
# ============================================================================

def build_world(scene):
    world = bpy.data.worlds.new("Мир")
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    mp = nt.nodes.new("ShaderNodeMapping")
    tc = nt.nodes.new("ShaderNodeTexCoord")

    path = None
    for name in (HDRI_FILE, HDRI_FALLBACK):
        p = os.path.join(ASSETS, name)
        if os.path.exists(p):
            path = p
            break
    if path:
        env.image = bpy.data.images.load(path)
        nt.links.new(tc.outputs["Generated"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
        mp.inputs["Rotation"].default_value = (0, 0, math.radians(HDRI_ROT))
        bg.inputs["Strength"].default_value = HDRI_POWER
        print("[сцена] панорама: %s" % os.path.basename(path))
    else:
        bg.inputs["Color"].default_value = (0.05, 0.06, 0.08, 1)
        print("[сцена] панорама не найдена")
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    scene.world = world


def build_lights():
    """Один тёплый источник — подвес над обеденным столом.

    Основной свет в сцене дневной, из окон. Практик нужен не для
    освещения, а как смысловая деталь: горящая лампа говорит, что в
    помещении живут, и даёт тёплое пятно в холодной утренней гамме.
    """
    # Солнце отдельным источником, по направлению солнца на панораме.
    # В HDRI диск размазан по нескольким пикселям и даёт только рассеянный
    # свет; резкие косые пятна на полу — главный признак снятого интерьера,
    # и взять их можно лишь направленным источником.
    bpy.ops.object.light_add(type="SUN", location=(0, 6, 4))
    sun = bpy.context.active_object
    sun.name = "Солнце"
    sun.rotation_euler = (math.radians(-84), 0, math.radians(30))
    sun.data.energy = 7.0
    sun.data.angle = math.radians(0.6)
    sun.data.color = (1.0, 0.74, 0.48)

    bpy.ops.object.light_add(type="POINT", location=(1.7, -2.75, CEIL - 0.68))
    lamp = bpy.context.active_object
    lamp.name = "Подвес"
    lamp.data.energy = 34
    lamp.data.shadow_soft_size = 0.09
    lamp.data.color = (1.0, 0.70, 0.42)

    # Ещё два тёплых пятна по зонам: торшер у дивана и подсветка у комода.
    for name, (x, y, z), e in (("Торшер", (-10.4, -3.5, 1.35), 26),
                               ("Бра", (5.6, -0.95, 1.45), 14)):
        bpy.ops.object.light_add(type="POINT", location=(x, y, z))
        o = bpy.context.active_object
        o.name = name
        o.data.energy = e
        o.data.shadow_soft_size = 0.12
        o.data.color = (1.0, 0.72, 0.46)

    # Мягкая заливка. Раньше это была одна панель во весь потолок —
    # она давала свет без спада, и именно от него кадр читался
    # нарисованным. Три источника меньшего размера дают пятна и тени.
    for i, x in enumerate((-10.2, -6.6, -2.8, 1.4, 5.2, 8.4)):
        bpy.ops.object.light_add(type="AREA",
                                 location=(x, -DEPTH * 0.42, CEIL - 0.04))
        f = bpy.context.active_object
        f.name = "Заливка_%d" % i
        f.data.shape = "RECTANGLE"
        f.data.size = 3.4
        f.data.size_y = DEPTH * 0.55
        f.data.energy = 30
        f.data.color = (0.97, 0.94, 0.91)
        f.data.use_shadow = False

    return sun, lamp


def build_haze():
    """Лёгкая дымка: делает видимыми лучи из окон.

    Плотность вдвое ниже прежней. При большой комната тонула в молоке,
    и контраст, ради которого всё затевалось, пропадал.
    """
    bpy.ops.mesh.primitive_cube_add(size=1, location=((X0 + X1) / 2,
                                                      -DEPTH / 2, CEIL / 2))
    fog = bpy.context.active_object
    fog.name = "Дымка"
    fog.scale = (X1 - X0, DEPTH, CEIL)
    bpy.ops.object.transform_apply(scale=True)
    m = bpy.data.materials.new("Дымка")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vol = nt.nodes.new("ShaderNodeVolumeScatter")
    vol.inputs["Color"].default_value = (1.0, 0.92, 0.80, 1)
    vol.inputs["Density"].default_value = 0.007
    vol.inputs["Anisotropy"].default_value = 0.62
    nt.links.new(vol.outputs[0], out.inputs["Volume"])
    fog.data.materials.append(m)
    fog.visible_shadow = False
    return fog


def build_scene():
    clear_scene()
    scene = bpy.context.scene

    mats = dict(p=mat_profile(), g=mat_glass(), h=mat_hardware(),
                wall=mat_wall(), floor=mat_room_floor(), reveal=mat_reveal())
    scan_wall = pbr_material("Штукатурка", "Plaster001", "Plaster001_2K-JPG",
                             scale=0.55, tint=(0.74, 0.72, 0.68))
    scan_floor = pbr_material("Дубовый пол", "WoodFloor051",
                              "WoodFloor051_2K-JPG",
                              scale=0.6, tint=(0.44, 0.36, 0.28))
    if scan_wall:
        mats["wall"] = scan_wall
        mats["reveal"] = scan_wall
    if scan_floor:
        mats["floor"] = scan_floor
    mats["linen"] = mat_cloth("Лён", "rough_linen", (0.78, 0.74, 0.66))
    mats["paint"] = mat_paint("Эмаль", (0.86, 0.85, 0.83), roughness=0.32)
    mats["rad"] = mat_paint("Радиатор", (0.88, 0.87, 0.85), roughness=0.28)
    # Стена — главная поверхность в кадре. Волна по штукатурке в
    # скользящем свете и есть та разница, по которой глаз отличает
    # снятое от посчитанного.
    weather(mats["wall"], patchy=0.055, rough=0.12, waviness=0.16, wave_scale=0.9)
    weather(mats["floor"], patchy=0.045, rough=0.16)
    mats["wool"] = mat_cloth("Шерсть", "wool_boucle", (0.34, 0.30, 0.26))

    build_world(scene)
    objs = build_shell(mats) + build_outer_wall(mats)

    for it in LAYOUT:
        w, h, cx, cz = span(it)
        holder = bpy.data.objects.new("окно_%s" % it["id"], None)
        scene.collection.objects.link(holder)
        holder.location = (it["x"], 0.0, it["sill"] + h / 2 - cz)
        objs += build_window(it, mats, holder)
        print("[окно] %-16s x=%+.2f  %.2f × %.2f м" % (it["name"], it["x"], w, h))

    objs += build_doorway(mats) + build_baseboard(mats)
    objs += build_radiators(mats) + build_switches(mats)

    props = load_props()
    objs += furnish(props, mats)

    # фаска: без неё рёбра ловят свет линейкой и кадр выдаёт компьютер
    for ob in objs:
        if ob.type != "MESH" or len(ob.data.polygons) > 60000:
            continue
        b = ob.modifiers.new("Фаска", "BEVEL")
        b.width = 0.0016
        b.segments = 2
        b.limit_method = "ANGLE"
        b.angle_limit = math.radians(40)
        b.harden_normals = True
        for p in ob.data.polygons:
            p.use_smooth = True

    build_lights()
    build_haze()

    bpy.ops.object.camera_add(location=PATH[0][1])
    cam = bpy.context.active_object
    cam.name = "Камера"
    cam.data.lens = PATH[0][3]
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = PATH[0][4]
    cam.data.sensor_width = 36.0
    scene.camera = cam

    target = bpy.data.objects.new("Точка фокуса", None)
    scene.collection.objects.link(target)
    target.location = PATH[0][2]
    cam.data.dof.focus_object = target
    con = cam.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"

    return scene, cam, target


def setup_render(scene, total):
    r = scene.render
    r.resolution_x, r.resolution_y = RES_X, RES_Y
    r.resolution_percentage = 100
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.image_settings.compression = 15
    r.use_motion_blur = True
    r.motion_blur_shutter = 0.5

    out_dir = os.path.abspath(CFG["out"])
    os.makedirs(out_dir, exist_ok=True)
    r.filepath = os.path.join(out_dir, "кадр_")

    scene.view_settings.view_transform = "AgX"
    scene.view_settings.exposure = 0.60
    scene.view_settings.look = "AgX - Medium High Contrast"

    if CFG["engine"].upper().startswith("E"):
        r.engine = "BLENDER_EEVEE_NEXT"
        ee = scene.eevee
        for attr, val in (("use_raytracing", True), ("taa_render_samples", 48),
                          ("use_volumetric_shadows", True)):
            if hasattr(ee, attr):
                setattr(ee, attr, val)
        print("[рендер] EEVEE Next — черновик")
    else:
        r.engine = "CYCLES"
        cy = scene.cycles
        cy.samples = CFG["samples"]
        cy.use_denoising = True
        cy.use_adaptive_sampling = True
        cy.adaptive_threshold = 0.012
        cy.max_bounces = 12
        cy.transmission_bounces = 12
        cy.transparent_max_bounces = 20
        cy.volume_bounces = 2
        cy.blur_glossy = 0.2
        prefs = bpy.context.preferences.addons["cycles"].preferences
        chosen = None
        for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI"):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                if [d for d in prefs.devices if d.type == backend]:
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
            print("[рендер] Cycles на GPU (%s)" % chosen)
        else:
            cy.device = "CPU"
            print("[рендер] Cycles на процессоре — будет медленно")

    print("[рендер] %dx%d, %d к/с, кадров: %d, %.1f с"
          % (RES_X, RES_Y, CFG["fps"], total, total / CFG["fps"]))


def main():
    scene, cam, target = build_scene()
    total = animate(scene, cam, target)
    setup_render(scene, total)
    setup_compositor(scene)

    if CFG["stills"]:
        n = CFG["stills"]
        for j in range(n):
            f = 1 + round((total - 1) * j / max(n - 1, 1))
            scene.frame_set(f)
            scene.render.filepath = os.path.join(
                os.path.abspath(CFG["out"]), "раскадровка_%02d" % j)
            bpy.ops.render.render(write_still=True)
        print("[готово] раскадровка: %d кадров" % n)
    else:
        bpy.ops.render.render(animation=True)
        print("[готово] все кадры записаны")


if __name__ == "__main__":
    main()
