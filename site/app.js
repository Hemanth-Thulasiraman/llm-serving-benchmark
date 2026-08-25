(async function () {
  const root = getComputedStyle(document.documentElement);
  const cssVar = (name) => root.getPropertyValue(name).trim();

  const COLORS = {
    naive_hf: cssVar('--series-1'),
    tgi: cssVar('--series-2'),
    vllm: cssVar('--series-3'),
  };
  const TEXT_SECONDARY = cssVar('--text-secondary');
  const TEXT_MUTED = cssVar('--text-muted');
  const GRIDLINE = cssVar('--gridline');
  const CRITICAL = cssVar('--critical');
  const GOOD = cssVar('--good');

  // Data is embedded inline (not fetched) so the page also works when opened
  // directly from disk via file:// — browsers block fetch() of local files
  // under that protocol, which otherwise renders as an empty page.
  const data = JSON.parse(document.getElementById('summary-data').textContent);

  const STACKS = data.meta.stacks; // ['naive_hf','tgi','vllm']
  const LABELS = data.meta.stack_labels;
  const CONCURRENCIES = data.meta.concurrencies;
  const SLA_MS = data.meta.ttft_sla_ms;

  // ---- reshape per_stack_concurrency into stack -> concurrency -> row
  const byStack = {};
  for (const stack of STACKS) byStack[stack] = {};
  for (const row of data.per_stack_concurrency) {
    byStack[row.stack][row.concurrency] = row;
  }

  // ---- hero stat tiles
  //
  // The vLLM-vs-naive throughput ratio deliberately does NOT lead here. It is
  // the largest number on the page but the least self-explanatory one: it is
  // driven mostly by the naive baseline collapsing under load, and a reader who
  // stops at the hero would carry away an inflated impression. It lives in the
  // throughput section instead, directly beside that explanation.
  const h0 = data.hypothesis_check;
  const vllmPeak = byStack.vllm[Math.max(...CONCURRENCIES)];
  const heroStats = [
    { value: `c=${data.sla.vllm.sustained_concurrency}`, label: 'vLLM held p95 TTFT under 1s at every level tested' },
    { value: `${h0.vllm_p95_ttft_ms_at_c30}ms`, label: 'vLLM p95 TTFT at 30 concurrent requests' },
    { value: `${vllmPeak.requests_per_s}/s`, label: 'vLLM peak sustained throughput (requests/sec)' },
    { value: `${data.quantization.mem_reduction_pct}%`, label: '4-bit memory reduction vs. FP16 (single trial)' },
  ];
  const heroStatsEl = document.getElementById('hero-stats');
  for (const s of heroStats) {
    const tile = document.createElement('div');
    tile.className = 'stat-tile';
    tile.innerHTML = `<div class="stat-value">${s.value}</div><div class="stat-label">${s.label}</div>`;
    heroStatsEl.appendChild(tile);
  }

  // ---- shared legend row (built once, describes all line charts)
  const legendEl = document.getElementById('stack-legend');
  for (const stack of STACKS) {
    const item = document.createElement('div');
    item.className = 'item';
    item.innerHTML = `<span class="swatch" style="background:${COLORS[stack]}"></span>${LABELS[stack]}`;
    legendEl.appendChild(item);
  }

  Chart.defaults.font.family = cssVar('--mono') || "ui-monospace, Menlo, Consolas, monospace";
  Chart.defaults.font.size = 11;
  Chart.defaults.color = TEXT_MUTED;

  function lineDataset(stack, field) {
    return {
      label: LABELS[stack],
      data: CONCURRENCIES.map((c) => byStack[stack][c] ? byStack[stack][c][field] : null),
      borderColor: COLORS[stack],
      backgroundColor: COLORS[stack],
      borderWidth: 2,
      pointRadius: 4,
      pointHoverRadius: 6,
      tension: 0.15,
      spanGaps: true,
    };
  }

  function baseLineOptions(yLabel, extraPlugins) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: cssVar('--surface-1'),
          titleColor: cssVar('--text-primary'),
          bodyColor: cssVar('--text-secondary'),
          borderColor: cssVar('--border') || GRIDLINE,
          borderWidth: 1,
          padding: 10,
          usePointStyle: true,
        },
        ...(extraPlugins || {}),
      },
      scales: {
        x: {
          title: { display: true, text: 'Concurrency', color: TEXT_SECONDARY },
          grid: { color: GRIDLINE },
          ticks: { color: TEXT_MUTED },
        },
        y: {
          title: { display: true, text: yLabel, color: TEXT_SECONDARY },
          grid: { color: GRIDLINE },
          ticks: { color: TEXT_MUTED },
          beginAtZero: true,
        },
      },
    };
  }

  const slaLinePlugin = {
    id: 'slaLine',
    afterDraw(chart) {
      const yScale = chart.scales.y;
      if (!yScale || SLA_MS < yScale.min || SLA_MS > yScale.max) return;
      const y = yScale.getPixelForValue(SLA_MS);
      const { left, right } = chart.chartArea;
      const ctx = chart.ctx;
      ctx.save();
      ctx.strokeStyle = CRITICAL;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 4]);
      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(right, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = CRITICAL;
      ctx.font = `11px ${cssVar('--mono') || 'monospace'}`;
      ctx.textAlign = 'right';
      ctx.fillText('1000ms SLA', right, y - 5);
      ctx.restore();
    },
  };

  new Chart(document.getElementById('chart-ttft-p50'), {
    type: 'line',
    data: { labels: CONCURRENCIES, datasets: STACKS.map((s) => lineDataset(s, 'ttft_median_ms')) },
    options: baseLineOptions('TTFT p50 (ms)'),
  });

  new Chart(document.getElementById('chart-ttft-p95'), {
    type: 'line',
    data: { labels: CONCURRENCIES, datasets: STACKS.map((s) => lineDataset(s, 'ttft_p95_ms')) },
    options: baseLineOptions('TTFT p95 (ms)'),
    plugins: [slaLinePlugin],
  });

  new Chart(document.getElementById('chart-throughput-rps'), {
    type: 'line',
    data: { labels: CONCURRENCIES, datasets: STACKS.map((s) => lineDataset(s, 'requests_per_s')) },
    options: baseLineOptions('Requests / sec'),
  });

  new Chart(document.getElementById('chart-throughput-tps'), {
    type: 'line',
    data: { labels: CONCURRENCIES, datasets: STACKS.map((s) => lineDataset(s, 'tokens_per_s_est')) },
    options: baseLineOptions('Estimated tokens / sec'),
  });

  // ---- SLA callouts
  //
  // Three states, not two. A stack that dips back under the SLA above a level
  // it breached has not earned the same clean "within SLA" treatment as one
  // that degrades monotonically — rendering all three identically would
  // overstate the noisy result.
  const slaEl = document.getElementById('sla-callouts');
  const fmtLevels = (levels) => levels.map((c) => `c=${c}`).join(', ');

  for (const stack of STACKS) {
    const info = data.sla[stack];
    const passedSomewhere = info.max_concurrency_under_sla !== null;
    const inconsistent = passedSomewhere && info.consistent === false;

    let headline, detail, statusClass, statusText;

    if (inconsistent) {
      headline = 'Inconsistent';
      detail =
        `p95 TTFT moved in and out of the SLA rather than degrading cleanly — ` +
        `under 1000ms at ${fmtLevels(info.levels_under_sla)}, over at ` +
        `${fmtLevels(info.levels_over_sla)}. With only ${data.meta.trials_per_point} trials ` +
        `per level and several readings sitting essentially on the 1000ms line, ` +
        `this most likely reflects trial-to-trial variance near the threshold ` +
        `rather than a real capacity ceiling. No single number is defensible here.`;
      statusClass = 'mixed';
      statusText = '⚠ boundary noise — not a clean result';
    } else if (passedSomewhere) {
      headline = info.sustained_concurrency;
      detail = info.breached_at
        ? `p95 TTFT stayed under 1000ms through c=${info.sustained_concurrency}, then breached at c=${info.breached_at} and stayed over.`
        : `p95 TTFT stayed under 1000ms at every level tested, up to c=${Math.max(...CONCURRENCIES)}.`;
      statusClass = 'pass';
      statusText = info.breached_at ? '✓ clean pass then breach' : '✓ never breached';
    } else {
      headline = '—';
      detail = 'p95 TTFT never stayed under 1000ms at any tested concurrency.';
      statusClass = 'fail';
      statusText = '✗ SLA not met';
    }

    const div = document.createElement('div');
    div.className = `callout${inconsistent ? ' mixed' : ''}`;
    div.innerHTML = `
      <div class="stack-name"><span class="swatch" style="background:${COLORS[stack]}"></span>${LABELS[stack]}</div>
      <div class="headline">${headline}${inconsistent || headline === '—' ? '' : '<span class="unit">concurrent</span>'}</div>
      <div class="detail">${detail}</div>
      <span class="status ${statusClass}">${statusText}</span>
    `;
    slaEl.appendChild(div);
  }

  // ---- throughput ratio, stated next to the reason it is what it is
  const ratioEl = document.getElementById('throughput-ratio-note');
  if (ratioEl) {
    ratioEl.innerHTML = `
      <span class="figure">${h0.vllm_vs_naive_throughput_ratio_at_c30}×</span> —
      vLLM's throughput advantage over naive HF at 30 concurrent requests. Read
      this as the naive baseline <strong>collapsing</strong> rather than vLLM
      being uniformly 50&times; faster: naive HF processes one request at a time,
      so at c=30 its queue backs up faster than it drains and completed
      throughput falls <em>below</em> its own single-user figure
      (${byStack.naive_hf[30].requests_per_s}/s at c=30 vs.
      ${byStack.naive_hf[1].requests_per_s}/s at c=1). Per-request, the gap is far
      smaller. The honest headline is the shape of the curves above, not this ratio.
    `;
  }

  // ---- KV cache table
  const kvBody = document.querySelector('#kv-table tbody');
  const sortedKv = [...data.kv_cache].sort((a, b) =>
    a.context_length - b.context_length || a.concurrency - b.concurrency);
  for (const row of sortedKv) {
    const tr = document.createElement('tr');
    if (row.oom) tr.className = 'oom-row';
    tr.innerHTML = `
      <td>${row.context_length}</td>
      <td>${row.concurrency}</td>
      <td>${row.kv_cache_estimate_mb ?? '—'}</td>
      <td>${row.peak_mem_mb ?? '—'}</td>
      <td>${row.oom ? 'OOM' : 'OK'}</td>
    `;
    kvBody.appendChild(tr);
  }

  // ---- Quantization comparison
  const quantEl = document.getElementById('quant-grid');
  const q = data.quantization;
  const fmtMb = (v) => `${(v / 1024).toFixed(1)} GB`;
  quantEl.innerHTML = `
    <div class="quant-card">
      <h3>FP16 (baseline)</h3>
      <div class="metric"><span>Memory at rest</span><span class="val">${fmtMb(q.fp16.mem_at_rest_mb)}</span></div>
      <div class="metric"><span>Peak memory</span><span class="val">${fmtMb(q.fp16.peak_mem_mb)}</span></div>
      <div class="metric"><span>Generation time</span><span class="val">${q.fp16.generation_seconds}s</span></div>
      <div class="metric"><span>Tokens / sec</span><span class="val">${q.fp16.tokens_per_second}</span></div>
    </div>
    <div class="arrow">
      <span>&rarr;</span>
      <span class="delta">${q.mem_reduction_pct}% memory<br>${q.speed_change_pct > 0 ? '+' : ''}${q.speed_change_pct}% speed</span>
    </div>
    <div class="quant-card">
      <h3>4-bit</h3>
      <div class="metric"><span>Memory at rest</span><span class="val">${fmtMb(q['4bit'].mem_at_rest_mb)}</span></div>
      <div class="metric"><span>Peak memory</span><span class="val">${fmtMb(q['4bit'].peak_mem_mb)}</span></div>
      <div class="metric"><span>Generation time</span><span class="val">${q['4bit'].generation_seconds}s</span></div>
      <div class="metric"><span>Tokens / sec</span><span class="val">${q['4bit'].tokens_per_second}</span></div>
    </div>
  `;

  // ---- Findings vs hypothesis
  const h = data.hypothesis_check;
  const findingsEl = document.getElementById('findings-card');
  const confirmed = h.throughput_claim_confirmed && h.vllm_meets_ttft_sla_at_c30;
  findingsEl.innerHTML = `
    <span class="verdict-pill ${confirmed ? 'confirmed' : 'partial'}">
      ${confirmed ? '✓ Hypothesis confirmed — with a caveat on why' : '~ Hypothesis partially confirmed'}
    </span>
    <p class="lead">
      Both halves of the original hypothesis held: vLLM stayed under the 1s p95
      TTFT target at 30 concurrent requests, and cleared the ~5&times; throughput
      bar by a wide margin. The margin, though, came from a direction the
      hypothesis didn't anticipate — the naive baseline collapsing rather than
      vLLM being uniformly faster — so the headline ratio deserves less weight
      than the scaling behaviour behind it.
    </p>
    <ul>
      <li>
        <strong>Throughput:</strong> at c=30, vLLM delivered
        <strong>${h.vllm_vs_naive_throughput_ratio_at_c30}&times;</strong> the throughput of naive HF —
        nominally far above the ~5&times; hypothesis, but the ratio overstates the
        engineering result and is better read as naive HF <strong>collapsing under
        load</strong>: with no continuous batching, its request queue backs up
        faster than it can drain, so completed throughput at c=30 actually drops
        below its c=1 value (no failures — just severe queueing delay). A ratio
        against a denominator that is itself degrading is not a clean speedup
        figure. The more meaningful finding is the shape: TGI and vLLM both batch
        and scale throughput near-linearly with concurrency, while the naive loop
        flattens and then reverses.
      </li>
      <li>
        <strong>TTFT SLA:</strong> vLLM's p95 TTFT at c=30 was
        <strong>${h.vllm_p95_ttft_ms_at_c30}ms</strong>, comfortably under the
        1000ms target at every level tested — confirming that half of the
        hypothesis directly. Naive HF degraded cleanly and predictably, breaching
        at c=10 and staying over. TGI did neither: it came in under the SLA at
        c=1 and c=10 but over at c=5, c=20 and c=30, with the c=20 and c=30
        readings landing essentially <em>on</em> the 1000ms line. That
        non-monotonic pattern is not a capacity ceiling — it's most likely
        trial-to-trial variance with only 3 trials per level, and TGI's SLA
        result should be treated as unresolved rather than scored.
      </li>
      <li>
        <strong>Net read:</strong> the hypothesis undersold vLLM's throughput
        advantage at this concurrency range, mainly because it didn't anticipate
        how badly the naive baseline would degrade under concurrent load rather
        than just being slow. The TTFT SLA claim held as stated.
      </li>
    </ul>
  `;
})();
