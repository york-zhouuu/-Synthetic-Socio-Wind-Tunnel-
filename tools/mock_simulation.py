#!/usr/bin/env python3
"""
Synthetic Socio Wind Tunnel — Mock Simulation Demo
Generates terminal output + visualization figures for presentation.

Usage:
    python tools/mock_simulation.py
    python tools/mock_simulation.py --save   # save figures to docs/figures/
"""

import argparse
import random
import time
import math
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
import networkx as nx
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.live import Live
from rich.layout import Layout

# ── reproducible randomness ────────────────────────────────────────────────
random.seed(42)
np.random.seed(42)

console = Console()

# ── color palette ──────────────────────────────────────────────────────────
DARK_BG   = "#0d1117"
ACCENT    = "#e94560"
BLUE      = "#0f3460"
PURPLE    = "#533483"
TEAL      = "#4ecdc4"
GOLD      = "#ffd700"
GRAY      = "#8b949e"

# ══════════════════════════════════════════════════════════════════════════
#  TERMINAL SIMULATION
# ══════════════════════════════════════════════════════════════════════════

AGENT_NAMES = [
    "Emma Chen", "Marcus Liu", "Priya Sharma", "Tom Walsh", "Aiko Tanaka",
    "Carlos Rivera", "Zoe Kim", "James Park", "Laila Hassan", "Noah Miller",
]
LOCATIONS = ["home", "bus_stop", "green_square_plaza", "sunset_bar",
             "central_park", "zetland_café", "office_block_a", "alley_23"]

INTERVENTION_MSG = "🍺 Sunset Bar 今晚神秘试饮，限30人 · 距你 50m"

def fmt_tick(tick: int) -> str:
    hour = 7 + tick // 12
    minute = (tick % 12) * 5
    return f"Day{tick//288+1:02d} {hour:02d}:{minute:02d}"

def run_terminal_demo(fast: bool = False):
    delay = 0.0 if fast else 0.03

    # ── header ──────────────────────────────────────────────────────────────
    console.print()
    title = Text()
    title.append("  SYNTHETIC SOCIO WIND TUNNEL  ", style="bold white on #e94560")
    title.append("  Hyperlocal Infiltrator  ", style="bold white on #533483")
    console.print(title, justify="center")
    console.print(
        "  Computational Social Science Simulation Engine  ",
        style="dim", justify="center"
    )
    console.print()

    # ── experiment config ────────────────────────────────────────────────────
    config_table = Table(box=box.SIMPLE_HEAD, show_header=True,
                         header_style="bold #4ecdc4", border_style="#533483")
    config_table.add_column("Parameter", style="bold white")
    config_table.add_column("Value", style="#ffd700")
    config_table.add_column("Note", style="dim")

    config_table.add_row("Experiment",      "Digital Lure v1",          "Info Injection")
    config_table.add_row("Location",        "Zetland / Green Square",   "Sydney, NSW")
    config_table.add_row("Agent Count",     "1,000",                    "10 Protagonist + 990 Dynamic")
    config_table.add_row("Simulation Days", "10",                       "3 baseline + 7 observation")
    config_table.add_row("Intervention",    "Day 4 · 18:00",            INTERVENTION_MSG)
    config_table.add_row("LLM Budget",      "~$4.20 / simulated day",   "Sonnet×10 + Haiku×990")
    config_table.add_row("Tick Duration",   "5 min (real time)",        "288 ticks/day · active 7-23h")

    console.print(Panel(config_table, title="[bold]Experiment Configuration[/]",
                        border_style="#0f3460"))
    console.print()

    # ── baseline phase ───────────────────────────────────────────────────────
    console.print("[bold #4ecdc4]━━  PHASE 1: BASELINE  (Day 1–3)  ━━[/]")
    console.print()

    baseline_events = [
        (84,  "Emma Chen",    "home",              "bus_stop",          "commute",   False),
        (86,  "Marcus Liu",   "home",              "office_block_a",    "commute",   False),
        (102, "Priya Sharma", "home",              "bus_stop",          "commute",   False),
        (144, "Emma Chen",    "bus_stop",          "office_block_a",    "work",      False),
        (204, "Tom Walsh",    "office_block_a",    "zetland_café",      "lunch",     False),
        (216, "Aiko Tanaka",  "home",              "central_park",      "walk",      False),
        (240, "Emma Chen",    "office_block_a",    "bus_stop",          "commute",   False),
        (252, "Marcus Liu",   "office_block_a",    "home",              "commute",   False),
        (268, "Priya Sharma", "zetland_café",      "home",              "return",    False),
        (276, "Tom Walsh",    "bus_stop",          "home",              "return",    False),
    ]

    for tick, agent, src, dst, act, social in baseline_events:
        line = Text()
        line.append(f"  {fmt_tick(tick)}  ", style="dim #8b949e")
        line.append(f"{agent:<14}", style="bold white")
        line.append(f"{src:<22}", style="#4ecdc4")
        line.append("→  ", style="dim")
        line.append(f"{dst:<22}", style="#4ecdc4")
        line.append(f"[{act}]", style="dim #533483")
        console.print(line)
        time.sleep(delay)

    console.print()
    console.print("  [dim]Baseline metrics[/]  "
                  "[#8b949e]avg interactions/day:[/] [white]0.8[/]   "
                  "[#8b949e]weak ties formed:[/] [white]1[/]   "
                  "[#8b949e]trajectory curvature:[/] [white]0.12[/]")
    console.print()

    # ── intervention ─────────────────────────────────────────────────────────
    time.sleep(0.1)
    console.print("[bold #e94560]━━  PHASE 2: INTERVENTION  (Day 4 · 18:00)  ━━[/]")
    console.print()

    with console.status("[bold #e94560]Activating Policy Hack: INFO_INJECTION ...", spinner="dots"):
        time.sleep(0.4 if not fast else 0.0)

    console.print(Panel(
        f"[bold white]TYPE[/]       INFO_INJECTION\n"
        f"[bold white]MESSAGE[/]    [yellow]{INTERVENTION_MSG}[/]\n"
        f"[bold white]RADIUS[/]     500m  ·  centered on [cyan]sunset_bar[/]\n"
        f"[bold white]URGENCY[/]    0.80\n"
        f"[bold white]TARGETS[/]    847 agents in range",
        title="[bold #e94560]⚡ Policy Hack Activated[/]",
        border_style="#e94560",
    ))
    console.print()

    # ── replanning ───────────────────────────────────────────────────────────
    console.print("[bold]Agent Replanning Events:[/]")
    console.print()

    replan_agents = [
        ("Emma Chen",    0.82, True,  "curiosity=0.9  routine_adherence=0.3"),
        ("Zoe Kim",      0.75, True,  "curiosity=0.8  routine_adherence=0.4"),
        ("Carlos Rivera",0.61, True,  "curiosity=0.7  routine_adherence=0.5"),
        ("Marcus Liu",   0.44, False, "curiosity=0.4  routine_adherence=0.8"),
        ("Tom Walsh",    0.38, False, "curiosity=0.3  routine_adherence=0.9"),
        ("Priya Sharma", 0.71, True,  "curiosity=0.8  routine_adherence=0.35"),
        ("James Park",   0.55, True,  "curiosity=0.65 routine_adherence=0.55"),
        ("Noah Miller",  0.29, False, "curiosity=0.25 routine_adherence=0.85"),
    ]

    for name, prob, diverted, profile in replan_agents:
        bar = "█" * int(prob * 20) + "░" * (20 - int(prob * 20))
        status = "[bold green]DIVERTED → sunset_bar[/]" if diverted else "[dim]stays on plan[/]"
        console.print(
            f"  [white]{name:<16}[/]  "
            f"[{'green' if prob > 0.5 else 'yellow'}]{bar}[/]  "
            f"[dim]{prob:.2f}[/]  {status}"
        )
        console.print(f"  {'':16}   [dim italic]{profile}[/]")
        time.sleep(delay * 0.5)

    console.print()

    # ── observation phase ────────────────────────────────────────────────────
    console.print("[bold #ffd700]━━  PHASE 3: OBSERVATION  (Day 5–10)  ━━[/]")
    console.print()

    obs_events = [
        (1240, "Emma Chen",    "home",         "sunset_bar",       "social ✦",  True),
        (1240, "Zoe Kim",      "zetland_café", "sunset_bar",       "social ✦",  True),
        (1245, "Carlos Rivera","office_block_a","sunset_bar",      "social ✦",  True),
        (1245, "Priya Sharma", "bus_stop",     "sunset_bar",       "social ✦",  True),
        (1248, "James Park",   "central_park", "sunset_bar",       "social ✦",  True),
        (1252, "Emma Chen",    "sunset_bar",   "alley_23",         "explore",   False),
        (1260, "Zoe Kim",      "sunset_bar",   "green_square_plaza","wander",   True),
        (1262, "Emma Chen",    "alley_23",     "green_square_plaza","encounter",True),
        (1270, "Carlos Rivera","sunset_bar",   "zetland_café",     "follow",    True),
        (1285, "Priya Sharma", "sunset_bar",   "green_square_plaza","wander",   True),
    ]

    for tick, agent, src, dst, act, new_conn in obs_events:
        line = Text()
        line.append(f"  {fmt_tick(tick)}  ", style="dim #8b949e")
        line.append(f"{agent:<14}", style="bold white")
        line.append(f"{src:<22}", style="#4ecdc4")
        line.append("→  ", style="dim")
        line.append(f"{dst:<22}", style="#ffd700")
        line.append(f"[{act}]", style="bold #e94560" if "✦" in act else "#533483")
        if new_conn:
            line.append("  ◈ new tie", style="bold green")
        console.print(line)
        time.sleep(delay)

    console.print()

    # ── metrics summary ──────────────────────────────────────────────────────
    console.print("[bold #4ecdc4]━━  RESULTS SUMMARY  ━━[/]")
    console.print()

    results = Table(box=box.SIMPLE_HEAD, show_header=True,
                    header_style="bold #4ecdc4", border_style="#533483")
    results.add_column("Metric",           style="bold white",  min_width=24)
    results.add_column("Baseline (D1-3)", style="#8b949e",      justify="center")
    results.add_column("Post-Hack (D5-10)",style="#ffd700",     justify="center")
    results.add_column("Effect Size",      style="bold #e94560",justify="center")
    results.add_column("Δ",               justify="center")

    rows = [
        ("Trajectory Deviation",  "0.08",  "0.41",  "+0.33", "↑ 412%"),
        ("Trajectory Curvature",  "0.12",  "0.38",  "+0.26", "↑ 217%"),
        ("New Weak Ties / Day",   "0.9",   "6.4",   "+5.5",  "↑ 611%"),
        ("Social Interactions",   "0.8",   "4.2",   "+3.4",  "↑ 425%"),
        ("Space Activation (bar)","0.04",  "0.63",  "+0.59", "↑ 1475%"),
        ("Space Diversity",       "0.11",  "0.52",  "+0.41", "↑ 373%"),
        ("Network Density",       "0.003", "0.019", "+0.016","↑ 533%"),
    ]
    for m, b, p, e, d in rows:
        results.add_row(m, b, p, e, f"[green]{d}[/]")

    console.print(Panel(results, title="[bold]Experiment: Digital Lure · Treatment vs Control[/]",
                        border_style="#0f3460"))
    console.print()

    # ── protagonist narrative ────────────────────────────────────────────────
    console.print("[bold #533483]━━  PROTAGONIST NARRATIVE EXCERPT  ━━[/]")
    console.print()

    narrative = (
        "[italic dim]Day 4 · Emma Chen · 18:47[/]\n\n"
        "[white]I wasn't going to stop. The office was behind me, the bus ahead. "
        "Then the notification—[/][yellow]'Sunset Bar, 50 meters, mystery tasting, 30 spots'[/][white]. "
        "I've walked past that alley a hundred times and never noticed the sign.\n\n"
        "There were five of us who showed up in the same ten-minute window. "
        "Carlos recognized me from the elevator. We'd never spoken.\n\n"
        "I wrote down three new names tonight. "
        "I don't know their last names yet, but I know the street they live on.[/]"
    )
    console.print(Panel(narrative, title="[bold #533483]📓 First-Person Log · Claude Sonnet[/]",
                        border_style="#533483", padding=(1, 2)))
    console.print()

    console.print(
        "[bold green]  Simulation complete.[/]  "
        "[dim]1,000 agents · 10 days · 2,880 ticks processed[/]"
    )
    console.print()


# ══════════════════════════════════════════════════════════════════════════
#  MATPLOTLIB VISUALIZATIONS
# ══════════════════════════════════════════════════════════════════════════

def set_dark_style():
    plt.rcParams.update({
        "figure.facecolor":  DARK_BG,
        "axes.facecolor":    "#161b22",
        "axes.edgecolor":    "#30363d",
        "axes.labelcolor":   "#e6edf3",
        "xtick.color":       "#8b949e",
        "ytick.color":       "#8b949e",
        "text.color":        "#e6edf3",
        "grid.color":        "#21262d",
        "grid.linestyle":    "--",
        "grid.alpha":        0.6,
        "font.family":       "monospace",
        "figure.dpi":        150,
    })

# ── Figure 1: Metrics over time ────────────────────────────────────────────

def fig_metrics_over_time() -> plt.Figure:
    set_dark_style()
    days = np.arange(1, 11)

    # mock data: gradual increase post intervention (day 4)
    def curve(baseline, peak, noise=0.05):
        vals = np.zeros(10)
        for i in range(10):
            if i < 3:
                vals[i] = baseline + np.random.normal(0, noise)
            else:
                t = (i - 3) / 6
                vals[i] = baseline + (peak - baseline) * (1 - np.exp(-3 * t)) + np.random.normal(0, noise * 1.5)
        return np.clip(vals, 0, None)

    social_t = curve(0.8, 4.2, 0.1)
    social_c = curve(0.8, 1.1, 0.08)
    weak_t   = curve(0.9, 6.4, 0.2)
    weak_c   = curve(0.9, 1.2, 0.1)
    traj_t   = curve(0.08, 0.41, 0.01)
    traj_c   = curve(0.08, 0.10, 0.01)

    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    fig.suptitle("Synthetic Socio Wind Tunnel — Experiment: Digital Lure",
                 fontsize=13, color="#e6edf3", y=1.02)

    datasets = [
        (axes[0], "Social Interactions / Day",  social_t, social_c),
        (axes[1], "New Weak Ties Formed / Day", weak_t,   weak_c),
        (axes[2], "Trajectory Deviation",       traj_t,   traj_c),
    ]

    for ax, title, treat, ctrl in datasets:
        ax.axvspan(3.5, 10.5, alpha=0.07, color=ACCENT, label="_obs")
        ax.axvline(3.5, color=ACCENT, linewidth=1.5, linestyle="--", alpha=0.8)
        ax.text(3.65, ax.get_ylim()[1] if ax.get_ylim()[1] > 0 else 1,
                "  Hack\n  Day 4", color=ACCENT, fontsize=7.5, va="top")

        ax.plot(days, treat, color=TEAL,  linewidth=2.5, marker="o",
                markersize=5, label="Treatment", zorder=3)
        ax.plot(days, ctrl,  color=GRAY,  linewidth=1.5, marker="o",
                markersize=4, linestyle="--", label="Control", zorder=2, alpha=0.7)

        ax.fill_between(days, treat, ctrl, alpha=0.12, color=TEAL)
        ax.set_title(title, fontsize=10, color=TEAL, pad=8)
        ax.set_xlabel("Simulation Day", fontsize=8)
        ax.set_xticks(days)
        ax.grid(True, alpha=0.4)
        ax.legend(fontsize=8, facecolor="#161b22", edgecolor="#30363d")

    # fix y-axis labels after plot
    for ax, _, treat, _ in datasets:
        ylim = ax.get_ylim()
        ax.axvline(3.5, color=ACCENT, linewidth=1.5, linestyle="--", alpha=0.8)
        ax.text(3.65, ylim[1] * 0.95, "  Hack\n  Day 4",
                color=ACCENT, fontsize=7.5, va="top")

    fig.tight_layout()
    return fig

# ── Figure 2: Social Network before/after ──────────────────────────────────

def fig_social_network() -> plt.Figure:
    set_dark_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Social Network Evolution — Before & After Policy Hack",
                 fontsize=13, color="#e6edf3")

    N = 40
    pos_base = {i: (np.cos(2*np.pi*i/N)*3 + np.random.normal(0, 0.4),
                    np.sin(2*np.pi*i/N)*3 + np.random.normal(0, 0.4)) for i in range(N)}

    # ── before: sparse ────────────────────────────────────────────────────
    G_before = nx.Graph()
    G_before.add_nodes_from(range(N))
    protagonist_ids = list(range(10))
    # ~8 edges total
    edges_before = [(0,1),(1,2),(5,6),(10,11),(20,21),(30,31),(0,5),(15,16)]
    G_before.add_edges_from(edges_before)

    colors_b = [ACCENT if i < 10 else "#4a5568" for i in range(N)]
    sizes_b  = [300 if i < 10 else 120 for i in range(N)]

    nx.draw_networkx(G_before, pos=pos_base, ax=ax1,
                     node_color=colors_b, node_size=sizes_b,
                     edge_color=GRAY, width=1.2, alpha=0.85,
                     with_labels=False, arrows=False)
    ax1.set_title(f"BASELINE  ·  {len(edges_before)} connections\nNetwork density: 0.003",
                  color=GRAY, fontsize=10)
    ax1.set_facecolor("#161b22")
    ax1.axis("off")

    # ── after: denser, hub at sunset_bar zone ─────────────────────────────
    G_after = nx.Graph()
    G_after.add_nodes_from(range(N))
    edges_after = list(edges_before)
    # add ~35 more edges concentrated around nodes 0-9 (protagonists)
    # and the "bar cluster" nodes 10-18
    bar_cluster = [0,2,4,6,12,14,16,18,22,24]
    for i in range(len(bar_cluster)):
        for j in range(i+1, len(bar_cluster)):
            if random.random() < 0.55:
                edges_after.append((bar_cluster[i], bar_cluster[j]))
    # some random new cross ties
    for _ in range(12):
        a, b = random.sample(range(N), 2)
        edges_after.append((a, b))
    edges_after = list(set(tuple(sorted(e)) for e in edges_after))
    G_after.add_edges_from(edges_after)

    edge_colors_a = []
    for u, v in G_after.edges():
        if u in bar_cluster and v in bar_cluster:
            edge_colors_a.append(TEAL)
        else:
            edge_colors_a.append(GRAY)

    colors_a = [ACCENT if i < 10 else (TEAL if i in bar_cluster else "#4a5568") for i in range(N)]
    sizes_a  = [300 if i < 10 else (200 if i in bar_cluster else 120) for i in range(N)]

    nx.draw_networkx(G_after, pos=pos_base, ax=ax2,
                     node_color=colors_a, node_size=sizes_a,
                     edge_color=edge_colors_a, width=1.2, alpha=0.85,
                     with_labels=False, arrows=False)
    density = round(len(edges_after) / (N*(N-1)/2), 3)
    ax2.set_title(f"POST-HACK  ·  {len(edges_after)} connections\nNetwork density: {density}",
                  color=TEAL, fontsize=10)
    ax2.set_facecolor("#161b22")
    ax2.axis("off")

    legend_elements = [
        mpatches.Patch(color=ACCENT, label="Protagonist (×10)"),
        mpatches.Patch(color=TEAL,   label="Bar cluster (new ties)"),
        mpatches.Patch(color="#4a5568", label="Background agent"),
    ]
    ax2.legend(handles=legend_elements, loc="lower right",
               facecolor="#161b22", edgecolor="#30363d", fontsize=8)

    fig.tight_layout()
    return fig

# ── Figure 3: Trajectory heatmap ───────────────────────────────────────────

def fig_trajectory_heatmap() -> plt.Figure:
    set_dark_style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("Agent Trajectory Heatmap — Zetland District",
                 fontsize=13, color="#e6edf3")

    W, H = 100, 80

    def make_grid(peak_locs, spread=6, noise_level=0.3):
        grid = np.random.exponential(noise_level, (H, W)) * 0.5
        for (cy, cx), weight in peak_locs:
            for y in range(H):
                for x in range(W):
                    d = math.sqrt((y-cy)**2 + (x-cx)**2)
                    grid[y, x] += weight * math.exp(-d**2 / (2*spread**2))
        return grid

    # Baseline: strong lines (commute corridors), no hotspots
    baseline_peaks = [
        ((40, 50), 8),   # horizontal commute corridor
        ((20, 50), 5),
        ((60, 50), 5),
        ((40, 20), 3),   # bus stop
        ((40, 80), 3),   # office
    ]
    baseline_grid = make_grid(baseline_peaks, spread=4, noise_level=0.15)
    # strengthen horizontal corridor
    baseline_grid[38:43, :] += 3.0
    baseline_grid[18:23, :] += 1.5

    # Post-hack: new hotspot at sunset_bar (30, 70), more spreading
    posthack_peaks = baseline_peaks + [
        ((30, 70), 15),   # sunset_bar — dominant hotspot
        ((50, 60), 5),    # green square plaza
        ((25, 55), 4),    # alley discovery
    ]
    posthack_grid = make_grid(posthack_peaks, spread=6, noise_level=0.2)
    posthack_grid[38:43, :] += 2.0  # commute still there but less dominant

    cmap_b = plt.cm.Blues
    cmap_p = plt.cm.plasma

    im1 = ax1.imshow(baseline_grid, cmap=cmap_b, aspect="auto", interpolation="gaussian")
    ax1.set_title("BASELINE  ·  Routine Commute Pattern",
                  color=GRAY, fontsize=10)
    ax1.set_xlabel("East–West (100m grid)", fontsize=8)
    ax1.set_ylabel("North–South (80m grid)", fontsize=8)
    ax1.text(50, 40, "commute\ncorridor", color="white", fontsize=7,
             ha="center", va="center", alpha=0.7)
    plt.colorbar(im1, ax=ax1, shrink=0.7, label="Agent density")

    im2 = ax2.imshow(posthack_grid, cmap=cmap_p, aspect="auto", interpolation="gaussian")
    ax2.set_title("POST-HACK  ·  Spatial Activation Shift",
                  color=TEAL, fontsize=10)
    ax2.set_xlabel("East–West (100m grid)", fontsize=8)
    ax2.text(70, 30, "[HOT]\nSunset Bar", color="white", fontsize=8,
             ha="center", va="center", fontweight="bold")
    ax2.text(60, 50, "Green Sq.", color="white", fontsize=7.5,
             ha="center", va="center", alpha=0.8)
    plt.colorbar(im2, ax=ax2, shrink=0.7, label="Agent density")

    fig.tight_layout()
    return fig

# ══════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="Save figures to docs/figures/")
    parser.add_argument("--fast", action="store_true", help="Skip typing delays")
    parser.add_argument("--no-terminal", action="store_true", help="Skip terminal demo")
    parser.add_argument("--no-figures", action="store_true", help="Skip figure generation")
    args = parser.parse_args()

    if not args.no_terminal:
        run_terminal_demo(fast=args.fast)

    if not args.no_figures:
        console.print("[bold]Generating visualization figures ...[/]")
        console.print()

        figs = [
            ("metrics_over_time",  fig_metrics_over_time,  "Fig 1 — Metrics over time"),
            ("social_network",     fig_social_network,     "Fig 2 — Social network evolution"),
            ("trajectory_heatmap", fig_trajectory_heatmap, "Fig 3 — Trajectory heatmap"),
        ]

        save_dir = Path(__file__).parent.parent / "docs" / "figures"
        if args.save:
            save_dir.mkdir(parents=True, exist_ok=True)

        for name, fn, label in figs:
            with console.status(f"[dim]Rendering {label} ...[/]"):
                fig = fn()

            if args.save:
                path = save_dir / f"{name}.png"
                fig.savefig(path, dpi=180, bbox_inches="tight",
                            facecolor=DARK_BG, edgecolor="none")
                console.print(f"  [green]✓[/]  {label}  →  [dim]{path}[/]")
            else:
                plt.show()

            plt.close(fig)

        console.print()
        if args.save:
            console.print(f"[bold green]All figures saved to[/] [cyan]{save_dir}[/]")
        else:
            console.print("[bold green]Done.[/]  Run with [yellow]--save[/] to export PNGs.")

if __name__ == "__main__":
    main()
