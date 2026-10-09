"""Page frame geometry: where the source page, markers, QR and footer sit on an issued page.

Every issued page is A4 at 200 DPI. All boxes are [x, y, w, h] px, origin top-left.
PDF points = px * PT, and PDF y runs upwards: pdf_y = (H - y - h) * PT.
"""
from dataclasses import dataclass

DPI = 200
PT = 72 / DPI  # points per px
MAX_PAGES = 10  # per document, at issue and at verify
DICTIONARY = "DICT_4X4_50"
SIDE, TOP, BAND = 122, 56, 268  # px: side margins (the markers live there), top margin, bottom band (QR + footer text)
MARKER, INSET = 84, 20
QR = 234


@dataclass(frozen=True)
class Layout:
    landscape: bool
    size: tuple[int, int]  # (W, H) px
    content: list[int]  # the source page is fitted into this box, aspect kept, centred
    markers: dict[int, list[int]]  # ArUco id -> [x, y] of its top-left corner; ids in order TL, TR, BR, BL
    qr: list[int]
    footer: list[int]  # text area left of the QR

    @property
    def ignore(self) -> list[list[int]]:
        """Boxes the visual diff skips: each marker (+12 px) and the QR box (+6 px)."""
        m = [[x - 12, y - 12, MARKER + 24, MARKER + 24] for x, y in self.markers.values()]
        x, y, w, h = self.qr
        return m + [[x - 6, y - 6, w + 12, h + 12]]


def layout(landscape: bool) -> Layout:
    w, h = (2339, 1654) if landscape else (1654, 2339)
    far_x, far_y = w - INSET - MARKER, h - INSET - MARKER
    first = 4 if landscape else 0  # marker ids 0-3 = portrait, 4-7 = landscape
    corners = [[INSET, INSET], [far_x, INSET], [far_x, far_y], [INSET, far_y]]
    qr_x, band_y = w - SIDE - QR, h - BAND + 14
    return Layout(landscape, (w, h), [SIDE, TOP, w - 2 * SIDE, h - TOP - BAND],
                  {first + i: c for i, c in enumerate(corners)},
                  [qr_x, band_y, QR, QR], [SIDE, band_y, qr_x - SIDE - 24, QR])


def for_marker_id(marker_id: int) -> Layout | None:
    """The layout a detected marker belongs to, or None for an id Signet doesn't use."""
    return layout(marker_id >= 4) if 0 <= marker_id <= 7 else None


if __name__ == "__main__":
    for ls in (False, True):
        L = layout(ls)
        W, H = L.size
        boxes = [[x, y, MARKER, MARKER] for x, y in L.markers.values()] + [L.qr, L.footer, L.content]
        assert all(x >= 0 and y >= 0 and x + w <= W and y + h <= H for x, y, w, h in boxes), boxes
        for i, a in enumerate(boxes):  # nothing in the frame overlaps anything else
            for b in boxes[i + 1:]:
                assert a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1], (a, b)
        assert for_marker_id(min(L.markers)) == L
    print("layout ok")
