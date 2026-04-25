#!/usr/bin/env python3
"""
visualize_run — 把 suite 跑完的 space_activation 渲染到 Lane Cove atlas 上

读 `data/experiments/<ts>_<suite>/variant_*/seed_*.json`（per-variant
RunMetrics 含 `space_activation: dict[location_id, dwell_ticks]`），
跨 seed 汇总，每 variant 一张子图，颜色深浅 = 累计 dwell tick。

Usage:
    python3 tools/visualize_run.py --run-dir data/experiments/20260425_*_thesis_v1
    python3 tools/visualize_run.py --run-dir <dir> --output trajectory.png
    python3 tools/visualize_run.py --run-dir <dir> --variants baseline,hyperlocal_push

Output: PNG，每 variant 一个 subplot。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon as MplPolygon

from synthetic_socio_wind_tunnel.cartography.lanecove import create_atlas_from_osm


def load_variant_activation(variant_dir: Path) -> tuple[dict[str, float], int]:
    """
    汇总该 variant 所有 seed 的 space_activation。
    返回 (loc_id → 总 dwell ticks, seed 数).
    """
    activation: dict[str, float] = {}
    n_seeds = 0
    for seed_file in sorted(variant_dir.glob("seed_*.json")):
        try:
            data = json.loads(seed_file.read_text(encoding="utf-8"))
            sa = data.get("run_metrics", {}).get("space_activation", {})
            for loc_id, dwell in sa.items():
                activation[loc_id] = activation.get(loc_id, 0.0) + float(dwell)
            n_seeds += 1
        except Exception as e:
            print(f"  [warn] skipping {seed_file.name}: {e}", file=sys.stderr)
    return activation, n_seeds


def render_heatmap_on_axis(
    ax,
    activation: dict[str, float],
    atlas,
    title: str,
    *,
    show_unvisited: bool = True,
    log_scale: bool = True,
) -> None:
    """
    在给定 ax 上画 atlas 轮廓 + 热力图。

    所有 outdoor_area 都画轮廓（淡灰）；activation 中出现的 area 染色。
    """
    # 收集所有 outdoor_area 的 polygons + 它们的值
    visited_polys: list[MplPolygon] = []
    visited_values: list[float] = []
    unvisited_polys: list[MplPolygon] = []

    all_outdoor_ids = atlas.list_outdoor_areas()
    for loc_id in all_outdoor_ids:
        try:
            area = atlas.get_outdoor_area(loc_id)
        except Exception:
            continue
        if area is None or not area.polygon.vertices:
            continue
        verts = [(v.x, v.y) for v in area.polygon.vertices]
        if loc_id in activation and activation[loc_id] > 0:
            visited_polys.append(MplPolygon(verts, closed=True))
            visited_values.append(activation[loc_id])
        elif show_unvisited:
            unvisited_polys.append(MplPolygon(verts, closed=True))

    # 1. 底图：unvisited 轮廓
    if unvisited_polys:
        bg = PatchCollection(
            unvisited_polys, facecolor="#f0f0f0",
            edgecolor="#cccccc", linewidth=0.3, alpha=0.5,
        )
        ax.add_collection(bg)

    # 2. 热力：visited
    if visited_polys:
        values = np.array(visited_values, dtype=float)
        if log_scale:
            values = np.log1p(values)
        # 归一化到 [0, 1]
        vmax = values.max() if len(values) else 1.0
        if vmax <= 0:
            vmax = 1.0

        pc = PatchCollection(visited_polys, cmap="YlOrRd", alpha=0.85)
        pc.set_array(values)
        pc.set_clim(vmin=0, vmax=vmax)
        pc.set_edgecolor("none")
        ax.add_collection(pc)
        plt.colorbar(pc, ax=ax, fraction=0.04, pad=0.02,
                     label="log(1 + dwell ticks)" if log_scale else "dwell ticks")

    ax.set_title(title, fontsize=11)
    ax.autoscale_view()
    ax.set_aspect("equal")
    ax.tick_params(left=False, bottom=False,
                   labelleft=False, labelbottom=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True,
                        help="data/experiments/<ts>_<suite>/")
    parser.add_argument("--output", type=Path, default=None,
                        help="输出 PNG（默认 <run-dir>/heatmap.png）")
    parser.add_argument("--variants", type=str, default=None,
                        help="comma-separated；默认全部 variant_*/")
    parser.add_argument("--linear", action="store_true",
                        help="禁用 log scale（默认 log1p 防止极端值压扁分布）")
    args = parser.parse_args()

    if not args.run_dir.is_dir():
        print(f"error: {args.run_dir} is not a directory", file=sys.stderr)
        return 2

    if args.variants:
        wanted = {v.strip() for v in args.variants.split(",")}
        variant_dirs = [
            d for d in sorted(args.run_dir.iterdir())
            if d.is_dir() and d.name.startswith("variant_")
            and d.name.removeprefix("variant_") in wanted
        ]
    else:
        variant_dirs = [
            d for d in sorted(args.run_dir.iterdir())
            if d.is_dir() and d.name.startswith("variant_")
        ]

    if not variant_dirs:
        print(f"error: no variant_*/ subdirs in {args.run_dir}", file=sys.stderr)
        return 2

    print(f"[load] atlas...")
    atlas = create_atlas_from_osm()

    n = len(variant_dirs)
    cols = min(3, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 5.5, rows * 5))
    axes_arr = np.atleast_1d(axes).ravel()

    for i, vd in enumerate(variant_dirs):
        variant_name = vd.name.removeprefix("variant_")
        print(f"[render] {variant_name}...")
        activation, n_seeds = load_variant_activation(vd)
        if n_seeds == 0:
            print(f"  [warn] no seed_*.json in {vd}", file=sys.stderr)
            axes_arr[i].set_title(f"{variant_name}\n(no data)")
            axes_arr[i].axis("off")
            continue
        title = (
            f"{variant_name}  "
            f"(seeds={n_seeds}, locs={len(activation)})"
        )
        render_heatmap_on_axis(
            axes_arr[i], activation, atlas, title,
            log_scale=not args.linear,
        )

    # 隐藏多余 subplot
    for j in range(n, len(axes_arr)):
        axes_arr[j].axis("off")

    suite_name = args.run_dir.name
    fig.suptitle(
        f"Trajectory Heatmap — {suite_name}", fontsize=13, y=1.00,
    )
    plt.tight_layout()

    output = args.output or (args.run_dir / "heatmap.png")
    plt.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[saved] {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
