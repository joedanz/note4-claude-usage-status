W, H = 400, 300
HEADER_H = 22
PACE_H = 20
TOP = HEADER_H + PACE_H          # 42
SIDE_W = 92
MAIN_W = W - SIDE_W              # 308
ROWS_TOP = TOP + 2               # 44
ROWS_H = H - ROWS_TOP            # 256
MAX_ROWS = 3
BAR_X0 = 94
BAR_X1 = MAIN_W - 10             # 298
BAR_H = 30


def row_box(i: int, n: int) -> tuple[int, int, int, int]:
    h = ROWS_H // n
    y0 = ROWS_TOP + i * h
    return (0, y0, MAIN_W, y0 + h)


def bar_box(i: int, n: int) -> tuple[int, int, int, int]:
    _, y0, _, y1 = row_box(i, n)
    cy = (y0 + y1) // 2 - 6
    return (BAR_X0, cy - BAR_H // 2, BAR_X1, cy + BAR_H // 2)
