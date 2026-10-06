#!/usr/bin/env python3
"""Draw the Multipass icon: a fan of three passes, in the Kikaron line-icon style.

    python3 multipass/brand/make_icon.py

Writes apps/multipass/icon/icon.svg (the rail glyph), the same glyph to
static/libraries/kikaron/app-icons/artefacts/multipass.svg, and the tile masters
multipass/brand/icon.svg (rounded, for the web vault) and icon-square.svg (for
the 1024 PNG the iOS app wants). Needs only Python.

Why a script: the rail strokes app icons and forces fill transparent, so there is
no filled card to hide the ones behind. Each back card is therefore drawn as just
the edges that show, with a little clear space where it goes behind the next.
"""
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
W, H, R = 18.4, 12.0, 2.3          # a card: as wide as the square icons (18.4 + stroke), tall enough that nothing inside touches
STEP = 0.1                          # sampling step along the outline
GAP = 0.0                           # back cards run right up to the card in front: their lines meet its outline
PIVOT = (2.7, 20.6)                 # the fan opens from here (bottom left of the front card)
FRONT_CENTRE = (12.0, 14.0)         # bottom edge at y=20.0, where the square icons (app.html) end
ANGLES = {'back': -7.0, 'mid': -3.5, 'front': 0.0}
# Each card behind the front one is a fraction smaller than the one before it, and
# its top edge sits a fixed step higher - so the stack recedes.
SCALES = {'back': 0.84, 'mid': 0.92, 'front': 1.0}
TOPS = {'back': 2.8, 'mid': 5.4, 'front': 8.0}      # y of each card's top edge (centre-line)
TILE = '#6B46C1'


def key_for(angle):
    return next(k for k, v in ANGLES.items() if v == angle)


def scale_for(angle):
    return SCALES[key_for(angle)]


def centre_for(angle):
    """Where a card sits: its top edge is fixed (TOPS), so the centre is that plus
    half its (scaled) height; nudged a little left the further back it is."""
    k = key_for(angle)
    t = {'front': 0.0, 'mid': 0.5, 'back': 1.0}[k]
    return (FRONT_CENTRE[0] - 0.6 * t, TOPS[k] + H * SCALES[k] / 2)


def outline(angle):
    cx, cy = centre_for(angle)
    k = scale_for(angle)
    w, h, r = W * k, H * k, R * k
    pts = []

    def line(x0, y0, x1, y1):
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / STEP))
        pts.extend((x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n))

    def arc(ax, ay, a0, a1):
        n = max(2, int(abs(a1 - a0) * r / STEP))
        pts.extend((ax + r * math.cos(a0 + (a1 - a0) * i / n),
                    ay + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n))

    hw, hh = w / 2, h / 2
    line(-hw + r, -hh, hw - r, -hh); arc(hw - r, -hh + r, -math.pi / 2, 0)
    line(hw, -hh + r, hw, hh - r);   arc(hw - r, hh - r, 0, math.pi / 2)
    line(hw - r, hh, -hw + r, hh);   arc(-hw + r, hh - r, math.pi / 2, math.pi)
    line(-hw, hh - r, -hw, -hh + r); arc(-hw + r, -hh + r, math.pi, 1.5 * math.pi)
    a = math.radians(angle); c, s = math.cos(a), math.sin(a)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]


def inside(p, angle):
    cx, cy = centre_for(angle)
    a = -math.radians(angle); c, s = math.cos(a), math.sin(a)
    x, y = p[0] - cx, p[1] - cy
    lx, ly = x * c - y * s, x * s + y * c
    k = scale_for(angle)
    r = R * k + GAP
    qx, qy = abs(lx) - (W * k / 2 + GAP - r), abs(ly) - (H * k / 2 + GAP - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r < 0


def rdp(pts, eps):
    if len(pts) < 3:
        return pts
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    best, idx = -1.0, 0
    for i in range(1, len(pts) - 1):
        d = (abs(dy * (pts[i][0] - x0) - dx * (pts[i][1] - y0)) / length
             if length > 1e-9 else math.hypot(pts[i][0] - x0, pts[i][1] - y0))
        if d > best:
            best, idx = d, i
    if best > eps:
        return rdp(pts[:idx + 1], eps)[:-1] + rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def runs(angle, uppers):
    pts = outline(angle)
    hidden = [any(inside(p, u) for u in uppers) for p in pts]
    n = len(pts)
    if not any(hidden):
        return [pts], True
    start = next(i for i in range(n) if hidden[i])
    out, cur = [], []
    for k in range(n):
        i = (start + k) % n
        if hidden[i]:
            if len(cur) > 3:
                out.append(cur)
            cur = []
        else:
            cur.append(pts[i])
    if len(cur) > 3:
        out.append(cur)
    return out, False


def _near(p, q):
    return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2


def region(angle, uppers):
    """The visible part of a card - the card minus the cards in front of it - as one
    closed loop of points: its own outline where nothing covers it, and the outline
    of the covering cards where they cut into it. Drawn as one shape, the washed fill
    covers exactly what shows, and the cut edge lies right on the front card's line,
    so the back card's lines meet it instead of stopping short."""
    own = [p for p in outline(angle) if not any(inside(p, u) for u in uppers)]
    cut = []
    for u in uppers:
        others = [o for o in uppers if o != u]
        for p in outline(u):
            if inside(p, angle) and not any(inside(p, o) for o in others):
                cut.append(p)
    pts = own + cut
    start = min(range(len(pts)), key=lambda i: (pts[i][0], pts[i][1]))
    chain, left = [pts[start]], pts[:start] + pts[start + 1:]
    while left:
        j = min(range(len(left)), key=lambda i: _near(chain[-1], left[i]))
        if _near(chain[-1], left[j]) > 0.6 ** 2:
            break
        chain.append(left.pop(j))
    if len(chain) < 0.9 * len(pts):
        raise SystemExit('region(%s): boundary did not close (%d of %d points)'
                         % (angle, len(chain), len(pts)))
    return chain


def main():
    back = [region(ANGLES['back'], [ANGLES['mid'], ANGLES['front']])]
    mid = [region(ANGLES['mid'], [ANGLES['front']])]
    front_pts = outline(0.0)
    allpts = [p for r in back + mid + [front_pts] for p in r]
    ox = oy = 0.0   # the FRONT card is what is centred, not the whole fan

    def d_open(r):
        pts = rdp([(x + ox, y + oy) for x, y in r], 0.01)
        return 'M' + ' L'.join(f'{x:.2f} {y:.2f}' for x, y in pts)

    def d_closed(r):
        pts = [(x + ox, y + oy) for x, y in r]
        h = len(pts) // 2
        a, b = rdp(pts[:h + 1], 0.01), rdp(pts[h:] + [pts[0]], 0.01)
        pts = a[:-1] + b
        return 'M' + ' L'.join(f'{x:.2f} {y:.2f}' for x, y in pts[:-1]) + ' Z'

    fx, fy = FRONT_CENTRE[0] + ox, FRONT_CENTRE[1] + oy
    parts = [f'<path d="{d_closed(r)}"/>' for r in back + mid]
    parts.append(f'<path d="{d_closed(front_pts)}"/>')
    parts += [
        f'<rect x="{fx - 6.8:.2f}" y="{fy - 3.4:.2f}" width="3.6" height="3.6" rx="0.9"/>',
        f'<path d="M{fx - 1.0:.2f} {fy - 2.4:.2f} h6.4"/>',
        f'<path d="M{fx - 1.0:.2f} {fy - 0.4:.2f} h4.0"/>',
        f'<path d="M{fx - 6.8:.2f} {fy + 3.0:.2f} h13.6"/>',
    ]
    glyph = '\n'.join('  ' + p for p in parts)
    ys = [p[1] for r in back + mid + [front_pts] for p in r]
    xs = [p[0] for r in back + mid + [front_pts] for p in r]
    cx_box, cy_box = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    rail = f'''<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg" fill="none">
  <!-- MULTIPASS: a fan of three passes, each turned a few degrees from the last, the
       front one with a photo square and lines of text. Each card is one
       closed shape (the chrome strokes app icons and gives every shape the house
       semi-transparent wash), and a back card is the part of it that shows - its
       cut edge lies on the front card's line, so its lines run right up to it. Generated by multipass/brand/make_icon.py. No transform
       wrappers. Original drawing. -->
{glyph}
</svg>
'''
    (ROOT / 'apps/multipass/icon/icon.svg').write_text(rail)
    (ROOT / 'static/libraries/kikaron/app-icons/artefacts/multipass.svg').write_text(rail)
    for name, rx in (('icon.svg', 26), ('icon-square.svg', 0)):
        (ROOT / 'multipass/brand' / name).write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
<!-- Multipass icon, Kikaron style: a colour tile with the white line glyph of
     apps/multipass/icon/icon.svg, scaled. Generated by make_icon.py. -->
<rect width="120" height="120" rx="{rx}" fill="{TILE}"/>
<g transform="translate(60 60) scale(3.8) translate(-{cx_box:.2f} -{cy_box:.2f})" fill="#fff" fill-opacity="0.45" stroke="#fff" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
{glyph}
</g>
</svg>
''')
    print('ok', len(parts), 'paths')


if __name__ == '__main__':
    main()
