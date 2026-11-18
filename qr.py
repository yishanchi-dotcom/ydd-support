"""
极简 QR 码产生器（不需额外套件），用于资产标签。
位元组模式、纠错等级 M、版本 1–6（最多 106 个字元，资产编号足够）。
回传二维阵列 matrix[y][x]，True = 黑点。
"""

# 版本 → (总码字数, 区块数, 每区块纠错码字数)，纠错等级 M
_TABLE = {1: (26, 1, 10), 2: (44, 1, 16), 3: (70, 1, 26), 4: (100, 2, 18), 5: (134, 2, 24), 6: (172, 4, 16)}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}


def _mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(deg):
    result = [0] * (deg - 1) + [1]
    root = 1
    for _ in range(deg):
        for j in range(deg):
            result[j] = _mul(result[j], root)
            if j + 1 < deg:
                result[j] ^= result[j + 1]
        root = _mul(root, 0x02)
    return result


def _rs_remainder(data, div):
    result = [0] * len(div)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(div):
            result[i] ^= _mul(coef, factor)
    return result


def encode(text):
    data = text.encode("utf-8")
    ver = None
    for v in sorted(_TABLE):
        total, blocks, ecc = _TABLE[v]
        if 4 + 8 + len(data) * 8 <= (total - blocks * ecc) * 8:
            ver = v
            break
    if ver is None:
        raise ValueError("内容太长")
    total, nblocks, ecc = _TABLE[ver]
    cap = total - nblocks * ecc
    # 资料位元
    bits = [0, 1, 0, 0] + [(len(data) >> i) & 1 for i in reversed(range(8))]
    for b in data:
        bits += [(b >> i) & 1 for i in reversed(range(8))]
    bits += [0] * min(4, cap * 8 - len(bits))
    bits += [0] * ((8 - len(bits) % 8) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < cap:
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    # 分区块、加纠错码、交错
    per = cap // nblocks
    div = _rs_divisor(ecc)
    dblocks = [words[i * per:(i + 1) * per] for i in range(nblocks)]
    eblocks = [_rs_remainder(b, div) for b in dblocks]
    final = []
    for i in range(per):
        for b in dblocks:
            final.append(b[i])
    for i in range(ecc):
        for b in eblocks:
            final.append(b[i])

    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    fn = [[False] * size for _ in range(size)]

    def setf(x, y, dark):
        mod[y][x] = dark
        fn[y][x] = True

    for i in range(size):           # 定时图形
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):   # 定位图形 + 分隔
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                xx, yy = cx + dx, cy + dy
                if 0 <= xx < size and 0 <= yy < size:
                    setf(xx, yy, max(abs(dx), abs(dy)) not in (2, 4))
    al = _ALIGN[ver]
    n = len(al)
    for i in range(n):              # 校正图形
        for j in range(n):
            if (i == 0 and j == 0) or (i == 0 and j == n - 1) or (i == n - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    setf(al[i] + dx, al[j] + dy, max(abs(dx), abs(dy)) != 1)

    def format_bits(mask):
        d = (0 << 3) | mask         # 纠错等级 M 的格式位 = 00
        rem = d
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        b = ((d << 10) | rem) ^ 0x5412
        bit = lambda i: ((b >> i) & 1) != 0
        for i in range(0, 6):
            setf(8, i, bit(i))
        setf(8, 7, bit(6))
        setf(8, 8, bit(7))
        setf(7, 8, bit(8))
        for i in range(9, 15):
            setf(14 - i, 8, bit(i))
        for i in range(0, 8):
            setf(size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            setf(8, size - 15 + i, bit(i))
        setf(8, size - 8, True)     # 固定黑点

    format_bits(0)                  # 先占位
    i = 0
    right = size - 1
    while right >= 1:               # 依 Z 字形放资料
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not fn[y][x] and i < len(final) * 8:
                    mod[y][x] = ((final[i >> 3] >> (7 - (i & 7))) & 1) != 0
                    i += 1
        right -= 2
    for y in range(size):           # 遮罩 0
        for x in range(size):
            if not fn[y][x] and (x + y) % 2 == 0:
                mod[y][x] = not mod[y][x]
    format_bits(0)
    return mod


def svg(text, px=4, quiet=2):
    m = encode(text)
    n = len(m) + quiet * 2
    rects = "".join('<rect x="%d" y="%d" width="1" height="1"/>' % (x + quiet, y + quiet)
                    for y, row in enumerate(m) for x, v in enumerate(row) if v)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" shape-rendering="crispEdges">'
            '<rect width="100%%" height="100%%" fill="#fff"/><g fill="#000">%s</g></svg>') % (n, n, n * px, n * px, rects)
