#!/usr/bin/env python3
"""
Plot XDP-bench optimization comparison: drops over time per variant.

Reads results from:
    results/optimizing-xdp-bench/XDPRSSRecipe_{baseline,optimized_xdp,optimized_norps,optimized_norps_rxhash}/

Plots dropped pkt/s (received - forwarded) per sample as a line plot,
one line per variant, averaged across iterations.

Usage:
    python3 scripts/plot_xdpbench.py results/optimizing-xdp-bench
"""

import glob
import json
import os
import sys
import webbrowser

import plotly.graph_objects as go
from plotly.subplots import make_subplots

THEME = {
    "background": "#1a170f",
    "foreground": "#eceae5",
    "accent": "#d1b764",
    "cyan": "#5fb3b3",
    "orange": "#d98c5f",
    "coral": "#c97070",
    "grid": "rgba(236, 234, 229, 0.1)",
    "grid_light": "rgba(236, 234, 229, 0.15)",
}

VARIANTS = [
    ("baseline",                "Upstream xdp-bench",                          "solid",   "circle"),
    ("optimized_xdp",           "Stripped xdp-bench",                          "dash",    "square"),
    ("optimized_norps",         "Stripped xdp-bench + no RPS",                 "dot",     "diamond"),
    ("optimized_norps_rxhash",  "Stripped + no RPS + rxhash offloaded",        "dashdot", "cross"),
]


MAX_SAMPLES = 60


def middle_slice(series, n=MAX_SAMPLES):
    """Return the middle n elements of a list."""
    if len(series) <= n:
        return series
    start = (len(series) - n) // 2
    return series[start:start + n]


def apply_terminal_theme(fig):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=THEME["background"],
        plot_bgcolor=THEME["background"],
        font=dict(color=THEME["foreground"]),
        xaxis=dict(
            gridcolor=THEME["grid"],
            zerolinecolor="rgba(236, 234, 229, 0.2)",
            linecolor=THEME["grid_light"],
        ),
        yaxis=dict(
            gridcolor=THEME["grid"],
            zerolinecolor="rgba(236, 234, 229, 0.2)",
            linecolor=THEME["grid_light"],
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )


def extract_cpu_timeseries(cpu_data):
    """Extract per-sample CPU utilization % averaged across active per-CPU keys.

    Uses only individual cpuN keys (skips the aggregate 'cpu' key).
    Trims first 10 and last 10 samples.
    """
    samples = list(cpu_data.values())[0]  # first (only) host
    if len(samples) <= 20:
        return []

    # Find per-CPU keys (exclude aggregate 'cpu')
    per_cpu_keys = [k for k in samples[0] if k.startswith("cpu") and k != "cpu"]
    if not per_cpu_keys:
        return []

    samples = samples[10:-10]
    utils = []
    for s in samples:
        cpu_utils = []
        for ck in per_cpu_keys:
            c = s.get(ck, {})
            cpu_utils.append(100.0 - c.get("idle", 0) - c.get("iowait", 0))
        utils.append(sum(cpu_utils) / len(cpu_utils))
    return middle_slice(utils)


def extract_drops_timeseries(rss_data):
    """Extract per-sample drops_per_cpu["3"] pkt/s from drop_monitor data.

    Skips samples where drops_per_cpu is empty or cpu 3 is absent.
    After filtering, trims first 10 and last 10 samples.
    """
    samples = rss_data.get("drop_monitor", [])
    if not samples:
        return []

    # Keep only samples that have cpu 3 data
    filtered = []
    for s in samples:
        dpc = s.get("drops_per_cpu", {})
        if "3" in dpc:
            filtered.append(s)

    if len(filtered) <= 20:
        return []

    filtered = filtered[10:-10]
    series = [s["drops_per_cpu"]["3"] / s["duration"] for s in filtered]
    return middle_slice(series)


def average_timeseries(all_series):
    """Average multiple time series per sample index (min-length aligned)."""
    if not all_series:
        return []
    min_len = min(len(s) for s in all_series)
    return [
        sum(s[i] for s in all_series) / len(all_series)
        for i in range(min_len)
    ]


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <results/optimizing-xdp-bench>",
              file=sys.stderr)
        sys.exit(1)

    base_dir = sys.argv[1]
    if not os.path.isdir(base_dir):
        print(f"Error: {base_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    fig = go.Figure()
    summary = []  # (label, avg_pps, iterations)

    for suffix, label, dash, symbol in VARIANTS:
        variant_dir = os.path.join(base_dir, f"XDPRSSRecipe_{suffix}")
        if not os.path.isdir(variant_dir):
            print(f"  {label}: directory not found, skipping", file=sys.stderr)
            continue

        rss_files = sorted(glob.glob(os.path.join(variant_dir, "rss_*.json")))
        all_drop_series = []
        for f in rss_files:
            data = json.load(open(f))
            ts = extract_drops_timeseries(data)
            if ts:
                all_drop_series.append(ts)

        if not all_drop_series:
            print(f"  {label}: no valid data, skipping", file=sys.stderr)
            continue

        avg_drops = average_timeseries(all_drop_series)
        avg_drops_overall = sum(avg_drops) / len(avg_drops)
        summary.append((label, avg_drops_overall, len(all_drop_series)))

        print(f"  {label}: {len(all_drop_series)} iterations, "
              f"{len(avg_drops)} samples, avg={avg_drops_overall:.0f} pps",
              file=sys.stderr)

        fig.add_trace(go.Scatter(
            x=list(range(len(avg_drops))),
            y=avg_drops,
            mode="lines",
            name=label,
            line=dict(color=THEME["accent"], width=2, dash=dash),
        ))

    # Print markdown summary table
    if summary:
        baseline_pps = summary[0][1]
        print()
        print("| Variant | Avg pkt/s | Gain |")
        print("|---|---|---|")
        for label, avg, iters in summary:
            gain = (avg - baseline_pps) / baseline_pps * 100
            sign = "+" if gain > 0 else ""
            pps_str = f"{avg / 1e6:.2f}M"
            gain_str = "baseline" if gain == 0 else f"{sign}{gain:.1f}%"
            print(f"| {label} | {pps_str} | {gain_str} |")

    apply_terminal_theme(fig)
    fig.update_layout(
        title="XDP-bench optimization: drops over time",
        xaxis_title="Sample (seconds)",
        yaxis_title="Dropped (pkt/s)",
        yaxis=dict(range=[2_700_000, None]),
    )

    output_path = os.path.join(base_dir, "xdpbench_comparison.html")
    fig.write_html(output_path, include_plotlyjs="cdn")
    print(f"\nPlot saved to {output_path}", file=sys.stderr)
    webbrowser.open(f"file://{os.path.abspath(output_path)}")


if __name__ == "__main__":
    main()
