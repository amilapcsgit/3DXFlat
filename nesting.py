from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
import math

import ezdxf
from shapely import affinity
from shapely.geometry import Polygon


SUPPORTED_ENTITIES = {"LWPOLYLINE", "POLYLINE", "MTEXT", "TEXT", "LINE", "ARC", "SPLINE", "CIRCLE"}
TRACKED_LAYERS = {"CUT_LINE", "FOLD_LINE", "LABELS", "RELIEF_CUT"}


@dataclass
class Piece:
    name: str
    source_path: Path
    polygon_local: Polygon
    source_doc: ezdxf.EzDxfDocument
    entities: List
    base_point: Tuple[float, float]
    area: float


@dataclass
class Placement:
    piece: Piece
    sheet_index: int
    angle_deg: float
    insert_x: float
    insert_y: float
    placed_polygon: Polygon


def _polyline_to_polygon(entity) -> Polygon | None:
    if entity.dxftype() == "LWPOLYLINE":
        points = [(float(p[0]), float(p[1])) for p in entity.get_points()]
        if len(points) < 3:
            return None
        if not entity.closed and points[0] != points[-1]:
            points.append(points[0])
        poly = Polygon(points)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if not poly.is_empty else None

    if entity.dxftype() == "POLYLINE":
        points = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
        if len(points) < 3:
            return None
        if not entity.is_closed and points[0] != points[-1]:
            points.append(points[0])
        poly = Polygon(points)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if not poly.is_empty else None

    return None


def _read_piece(path: Path) -> Piece | None:
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    cut_polys = []
    for e in msp:
        if e.dxf.layer != "CUT_LINE":
            continue
        p = _polyline_to_polygon(e)
        if p is not None:
            cut_polys.append(p)
    if not cut_polys:
        return None

    cut_poly = max(cut_polys, key=lambda p: p.area)
    minx, miny, _, _ = cut_poly.bounds
    poly_local = affinity.translate(cut_poly, xoff=-minx, yoff=-miny)

    entities = []
    for e in msp:
        if e.dxf.layer in TRACKED_LAYERS and e.dxftype() in SUPPORTED_ENTITIES:
            entities.append(e.copy())

    return Piece(
        name=path.stem,
        source_path=path,
        polygon_local=poly_local,
        source_doc=doc,
        entities=entities,
        base_point=(float(minx), float(miny)),
        area=float(poly_local.area),
    )


def _read_pieces(folder: Path) -> List[Piece]:
    pieces: List[Piece] = []
    for path in sorted(folder.glob("*.dxf")):
        if path.name.upper().startswith("MASTER_PRODUCTION_ROLL"):
            continue
        piece = _read_piece(path)
        if piece is not None:
            pieces.append(piece)
    pieces.sort(key=lambda p: p.area, reverse=True)
    return pieces


def _rotated_normalized(poly: Polygon, angle_deg: float) -> Tuple[Polygon, float, float]:
    r = affinity.rotate(poly, angle_deg, origin=(0.0, 0.0), use_radians=False)
    minx, miny, _, _ = r.bounds
    r = affinity.translate(r, xoff=-minx, yoff=-miny)
    return r, -minx, -miny


def _can_place(poly: Polygon, roll_width: float, placed_clearance: List[Polygon], gap: float) -> bool:
    minx, _, maxx, _ = poly.bounds
    if minx < 0 or maxx > roll_width:
        return False
    clear = poly.buffer(gap * 0.5)
    for p in placed_clearance:
        if clear.intersects(p):
            return False
    return True


def _find_position(
    poly: Polygon,
    roll_width: float,
    gap: float,
    max_sheet_length: float,
    placed: List[Polygon],
    placed_clearance: List[Polygon],
    x_step: float,
) -> Tuple[float, float, Polygon] | None:
    _, _, wmax, hmax = poly.bounds
    width = wmax
    if width > roll_width:
        return None

    y_candidates = {0.0}
    for p in placed:
        y_candidates.add(float(p.bounds[3] + gap))

    for y in sorted(y_candidates):
        if y + hmax > max_sheet_length:
            continue
        x = 0.0
        while x + width <= roll_width + 1e-9:
            candidate = affinity.translate(poly, xoff=x, yoff=y)
            if _can_place(candidate, roll_width, placed_clearance, gap):
                return x, y, candidate
            x += x_step
    return None


def _place_pieces(
    pieces: List[Piece],
    roll_width: float,
    gap: float,
    rotation_step_deg: float,
    max_sheet_length: float,
) -> List[Placement]:
    placements: List[Placement] = []
    sheet_polys: List[List[Polygon]] = [[]]
    sheet_clearance: List[List[Polygon]] = [[]]

    if rotation_step_deg <= 0:
        rotation_step_deg = 90.0
    x_step = max(2.0, min(gap * 0.5, 20.0))
    angles = []
    angle = 0.0
    while angle < 360.0:
        angles.append(float(angle))
        angle += rotation_step_deg
    if not angles:
        angles = [0.0]

    for piece in pieces:
        placed_ok = False
        for sheet_index in range(len(sheet_polys)):
            best = None
            for ang in angles:
                poly_rot, shift_x, shift_y = _rotated_normalized(piece.polygon_local, ang)
                pos = _find_position(
                    poly_rot,
                    roll_width=roll_width,
                    gap=gap,
                    max_sheet_length=max_sheet_length,
                    placed=sheet_polys[sheet_index],
                    placed_clearance=sheet_clearance[sheet_index],
                    x_step=x_step,
                )
                if pos is None:
                    continue
                x, y, poly_placed = pos
                top = poly_placed.bounds[3]
                if best is None or top < best["top"] - 1e-9 or (math.isclose(top, best["top"]) and x < best["x"]):
                    best = {
                        "x": x,
                        "y": y,
                        "poly": poly_placed,
                        "angle": ang,
                        "shift_x": shift_x,
                        "shift_y": shift_y,
                        "top": top,
                    }

            if best is not None:
                sheet_polys[sheet_index].append(best["poly"])
                sheet_clearance[sheet_index].append(best["poly"].buffer(gap * 0.5))
                placements.append(
                    Placement(
                        piece=piece,
                        sheet_index=sheet_index,
                        angle_deg=float(best["angle"]),
                        insert_x=float(best["x"] + best["shift_x"]),
                        insert_y=float(best["y"] + best["shift_y"]),
                        placed_polygon=best["poly"],
                    )
                )
                placed_ok = True
                break

        if not placed_ok:
            sheet_polys.append([])
            sheet_clearance.append([])
            new_index = len(sheet_polys) - 1

            # Force best fit in new sheet
            best = None
            for ang in angles:
                poly_rot, shift_x, shift_y = _rotated_normalized(piece.polygon_local, ang)
                pos = _find_position(
                    poly_rot,
                    roll_width=roll_width,
                    gap=gap,
                    max_sheet_length=max_sheet_length,
                    placed=sheet_polys[new_index],
                    placed_clearance=sheet_clearance[new_index],
                    x_step=x_step,
                )
                if pos is None:
                    continue
                x, y, poly_placed = pos
                top = poly_placed.bounds[3]
                if best is None or top < best["top"]:
                    best = {
                        "x": x,
                        "y": y,
                        "poly": poly_placed,
                        "angle": ang,
                        "shift_x": shift_x,
                        "shift_y": shift_y,
                        "top": top,
                    }
            if best is None:
                # Fall back: place at origin without collision checks in dedicated sheet.
                poly_rot, shift_x, shift_y = _rotated_normalized(piece.polygon_local, 0.0)
                best = {
                    "x": 0.0,
                    "y": 0.0,
                    "poly": poly_rot,
                    "angle": 0.0,
                    "shift_x": shift_x,
                    "shift_y": shift_y,
                    "top": poly_rot.bounds[3],
                }
            sheet_polys[new_index].append(best["poly"])
            sheet_clearance[new_index].append(best["poly"].buffer(gap * 0.5))
            placements.append(
                Placement(
                    piece=piece,
                    sheet_index=new_index,
                    angle_deg=float(best["angle"]),
                    insert_x=float(best["x"] + best["shift_x"]),
                    insert_y=float(best["y"] + best["shift_y"]),
                    placed_polygon=best["poly"],
                )
            )

    return placements


def _ensure_layer(doc: ezdxf.EzDxfDocument, name: str, color: int):
    if name not in doc.layers:
        doc.layers.add(name, dxfattribs={"color": color})


def _write_sheet(path: Path, placements: List[Placement], sheet_index: int):
    doc = ezdxf.new("R2000")
    msp = doc.modelspace()

    _ensure_layer(doc, "CUT_LINE", 1)
    _ensure_layer(doc, "FOLD_LINE", 5)
    _ensure_layer(doc, "LABELS", 3)
    _ensure_layer(doc, "RELIEF_CUT", 2)

    for i, pl in enumerate(placements, start=1):
        block_name = f"PIECE_{sheet_index+1}_{i}"
        block = doc.blocks.new(name=block_name, base_point=(pl.piece.base_point[0], pl.piece.base_point[1], 0.0))
        for ent in pl.piece.entities:
            try:
                block.add_entity(ent.copy())
            except Exception:
                continue
        msp.add_blockref(
            block_name,
            insert=(pl.insert_x, pl.insert_y, 0.0),
            dxfattribs={"rotation": float(pl.angle_deg)},
        )

    doc.saveas(path)


def _group_compact_sheets(placements: List[Placement]) -> Dict[int, List[Placement]]:
    by_sheet: Dict[int, List[Placement]] = {}
    for pl in placements:
        by_sheet.setdefault(pl.sheet_index, []).append(pl)
    non_empty_keys = sorted(k for k, v in by_sheet.items() if v)
    compact_index = {old: new for new, old in enumerate(non_empty_keys)}
    return {compact_index[k]: by_sheet[k] for k in non_empty_keys}


def build_nesting_layout(
    input_dir: str,
    roll_width_mm: float = 2500.0,
    gap_mm: float = 20.0,
    rotation_step_deg: float = 15.0,
    max_sheet_length_mm: float = 10000.0,
) -> Dict:
    source = Path(input_dir)
    pieces = _read_pieces(source)
    if not pieces:
        raise ValueError("No valid DXF pieces with CUT_LINE found in input folder.")

    placements = _place_pieces(
        pieces=pieces,
        roll_width=float(roll_width_mm),
        gap=float(gap_mm),
        rotation_step_deg=float(rotation_step_deg),
        max_sheet_length=float(max_sheet_length_mm),
    )
    by_sheet_compact = _group_compact_sheets(placements)
    used_lengths = {
        i: max(float(p.placed_polygon.bounds[3]) for p in ps) if ps else 0.0
        for i, ps in by_sheet_compact.items()
    }
    return {
        "placements_by_sheet": by_sheet_compact,
        "roll_width_mm": float(roll_width_mm),
        "gap_mm": float(gap_mm),
        "max_sheet_length_mm": float(max_sheet_length_mm),
        "input_count": len(pieces),
        "sheet_count": len(by_sheet_compact),
        "used_length_mm_per_sheet": used_lengths,
    }


def export_nesting_layout(output_dir: str, placements_by_sheet: Dict[int, List[Placement]]) -> List[str]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    sheet_files: List[str] = []
    if len(placements_by_sheet) == 1 and 0 in placements_by_sheet:
        out = target / "MASTER_PRODUCTION_ROLL.dxf"
        _write_sheet(out, placements_by_sheet[0], 0)
        sheet_files.append(str(out))
    else:
        for i in sorted(placements_by_sheet):
            out = target / f"MASTER_PRODUCTION_ROLL_SHEET_{i+1:02d}.dxf"
            _write_sheet(out, placements_by_sheet[i], i)
            sheet_files.append(str(out))
    return sheet_files


def run_nesting(
    input_dir: str,
    output_dir: str,
    roll_width_mm: float = 2500.0,
    gap_mm: float = 20.0,
    rotation_step_deg: float = 15.0,
    max_sheet_length_mm: float = 10000.0,
) -> Dict:
    layout = build_nesting_layout(
        input_dir=input_dir,
        roll_width_mm=roll_width_mm,
        gap_mm=gap_mm,
        rotation_step_deg=rotation_step_deg,
        max_sheet_length_mm=max_sheet_length_mm,
    )
    sheet_files = export_nesting_layout(output_dir=output_dir, placements_by_sheet=layout["placements_by_sheet"])
    return {
        "input_count": layout["input_count"],
        "sheet_count": layout["sheet_count"],
        "sheet_files": sheet_files,
        "used_length_mm_per_sheet": layout["used_length_mm_per_sheet"],
    }
