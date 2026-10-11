<script lang="ts">
  import uPlot from "uplot";
  import "uplot/dist/uPlot.min.css";
  import { onDestroy } from "svelte";

  interface SeriesSpec {
    label: string;
    color: string;
    width?: number;
    dash?: number[];
    fill?: string;
  }
  interface Props {
    data: (number | null)[][]; // [x, ...ys]
    series: SeriesSpec[];
    height?: number;
    yLabel?: string;
    xLabel?: string;
    xName?: string;
    xUnit?: string;
    syncKey?: string;
    yRange?: [number, number] | null;
    zeroLine?: boolean;
    onCursor?: (x: number | null) => void;
    markers?: { x: number; label: string }[];
  }
  let {
    data,
    series,
    height = 160,
    yLabel = "",
    xLabel = "",
    xName = "Distance",
    xUnit = "m",
    syncKey = "pitwall",
    yRange = null,
    zeroLine = false,
    onCursor,
    markers = [],
  }: Props = $props();

  let el: HTMLDivElement;
  let plot: uPlot | null = null;
  let ro: ResizeObserver | null = null;

  function css(name: string): string {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
  }

  function resolve(c: string): string {
    return c.startsWith("var(") ? css(c.slice(4, -1)) : c;
  }

  function build() {
    if (!el) return;
    plot?.destroy();
    const grid = { stroke: css("--border"), width: 1 };
    const axisFont = "11px " + css("--mono");
    const opts: uPlot.Options = {
      width: el.clientWidth || 600,
      height,
      legend: { show: true, live: true },
      cursor: {
        sync: { key: syncKey, setSeries: false },
        drag: { x: true, y: false },
        points: { size: 6 },
      },
      scales: { x: { time: false }, y: yRange ? { range: yRange } : {} },
      axes: [
        { stroke: css("--muted"), grid, ticks: grid, font: axisFont, label: xLabel, labelFont: axisFont },
        { stroke: css("--muted"), grid, ticks: grid, font: axisFont, label: yLabel, labelFont: axisFont, size: 52 },
      ],
      series: [
        { label: xName, value: (_u, v) => (v == null ? "—" : `${v.toFixed(xUnit === "s" ? 1 : 0)} ${xUnit}`) },
        ...series.map((s) => ({
          label: s.label,
          stroke: resolve(s.color),
          width: s.width ?? 1.5,
          dash: s.dash,
          fill: s.fill ? resolve(s.fill) : undefined,
          spanGaps: false,
          points: { show: false },
          value: (_u: uPlot, v: number | null) => (v == null ? "—" : v.toFixed(Math.abs(v) < 10 ? 2 : 0)),
        })),
      ],
      hooks: {
        setCursor: [
          (u) => {
            const idx = u.cursor.idx;
            onCursor?.(idx == null ? null : (u.data[0][idx] as number));
          },
        ],
        draw: [
          (u) => {
            const ctx = u.ctx;
            ctx.save();
            if (zeroLine) {
              const y0 = u.valToPos(0, "y", true);
              ctx.strokeStyle = css("--faint");
              ctx.setLineDash([4, 4]);
              ctx.beginPath();
              ctx.moveTo(u.bbox.left, y0);
              ctx.lineTo(u.bbox.left + u.bbox.width, y0);
              ctx.stroke();
            }
            ctx.setLineDash([]);
            ctx.fillStyle = css("--muted");
            ctx.font = "10px " + css("--mono");
            for (const m of markers) {
              const x = u.valToPos(m.x, "x", true);
              if (x < u.bbox.left || x > u.bbox.left + u.bbox.width) continue;
              ctx.strokeStyle = css("--border");
              ctx.beginPath();
              ctx.moveTo(x, u.bbox.top);
              ctx.lineTo(x, u.bbox.top + u.bbox.height);
              ctx.stroke();
              ctx.fillText(m.label, x + 3, u.bbox.top + 10);
            }
            ctx.restore();
          },
        ],
      },
    };
    plot = new uPlot(opts, data as uPlot.AlignedData, el);
  }

  $effect(() => {
    // rebuild when series/markers change; cheap update when only data changes
    void series;
    void markers;
    void height;
    build();
    return () => plot?.destroy();
  });

  $effect(() => {
    if (plot && data) plot.setData(data as uPlot.AlignedData);
  });

  $effect(() => {
    ro = new ResizeObserver(() => plot?.setSize({ width: el.clientWidth, height }));
    ro.observe(el);
    return () => ro?.disconnect();
  });

  onDestroy(() => plot?.destroy());
</script>

<div bind:this={el} class="chart"></div>

<style>
  .chart { width: 100%; min-width: 0; }
</style>
