/*
 * Hyderabad Gold Rate Teller — dashboard frontend.
 *
 * Plain vanilla JS. No frameworks, no chart library, no CDN dependency:
 * the history chart is a small hand-drawn SVG line, which keeps the page
 * fast-loading and avoids pulling in a dependency just for a line chart.
 * The same chart/tooltip logic is reused for both the 22K and 24K charts
 * via a small "chart context" object (see charts.k22 / charts.k24 below).
 *
 * All gold-rate data comes from ./data/gold_rates.json, produced by the
 * Python pipeline (see app/data_export.py and scripts/update_gold_rate_data.py).
 * This script never talks to Goodreturns directly.
 */

(function () {
  "use strict";

  var DATA_URL = "data/gold_rates.json";

  var state = {
    payload: null,
    range: 7,
  };

  var els = {};

  // Two independent chart contexts sharing the same rendering/tooltip
  // logic. Each tracks its own currently-plotted points and open-tooltip
  // state, so hovering one chart never affects the other.
  var charts = {
    k22: { key: "k22", label: "22K Gold Rate", points: [], activeIndex: null },
    k24: { key: "k24", label: "24K Gold Rate", points: [], activeIndex: null },
  };

  function cacheElements() {
    els.loading = document.getElementById("loading-state");
    els.error = document.getElementById("error-state");
    els.errorDetail = document.getElementById("error-detail");
    els.retryButton = document.getElementById("retry-button");
    els.content = document.getElementById("content");

    els.ratePerGram = document.getElementById("rate-per-gram");
    els.rate8g = document.getElementById("rate-8g");
    els.rate10g = document.getElementById("rate-10g");
    els.changeLine = document.getElementById("change-line");
    els.rateDate = document.getElementById("rate-date");
    els.rateUpdated = document.getElementById("rate-updated");
    els.sourceLink = document.getElementById("source-link");

    els.rate24kValueWrap = document.getElementById("rate-24k-value-wrap");
    els.rupee24k = document.getElementById("rupee-24k");
    els.rate24kPerGram = document.getElementById("rate-24k-per-gram");
    els.rate24k8g = document.getElementById("rate-24k-8g");
    els.rate24k10g = document.getElementById("rate-24k-10g");
    els.change24kLine = document.getElementById("change-24k-line");

    els.rangeButtons = Array.prototype.slice.call(document.querySelectorAll(".range-btn"));
    els.recentTableBody = document.getElementById("recent-table-body");

    charts.k22.svg = document.getElementById("chart");
    charts.k22.wrap = document.getElementById("chart-wrap");
    charts.k22.historyNote = document.getElementById("history-note");
    charts.k22.tooltip = document.getElementById("chart-tooltip");
    charts.k22.tooltipDate = document.getElementById("tooltip-date");
    charts.k22.tooltipValue = document.getElementById("tooltip-value");

    charts.k24.svg = document.getElementById("chart-24k");
    charts.k24.wrap = document.getElementById("chart-wrap-24k");
    charts.k24.historyNote = document.getElementById("history-note-24k");
    charts.k24.tooltip = document.getElementById("chart-tooltip-24k");
    charts.k24.tooltipDate = document.getElementById("tooltip-24k-date");
    charts.k24.tooltipValue = document.getElementById("tooltip-24k-value");
  }

  function showState(name) {
    els.loading.hidden = name !== "loading";
    els.error.hidden = name !== "error";
    els.content.hidden = name !== "content";
  }

  // Indian-style comma grouping, e.g. 140150 -> "1,40,150"
  function formatInr(amount) {
    var rounded = Math.round(Number(amount));
    var negative = rounded < 0;
    var s = String(Math.abs(rounded));
    var grouped;
    if (s.length <= 3) {
      grouped = s;
    } else {
      var last3 = s.slice(-3);
      var rest = s.slice(0, -3);
      var parts = [];
      while (rest.length > 2) {
        parts.unshift(rest.slice(-2));
        rest = rest.slice(0, -2);
      }
      if (rest) parts.unshift(rest);
      grouped = parts.join(",") + "," + last3;
    }
    return (negative ? "-" : "") + grouped;
  }

  var MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // Fixed 3-letter abbreviation regardless of browser/locale (some locales
  // render "Sept" instead of "Sep" via Intl -- this keeps the tooltip
  // format exact and consistent everywhere).
  function formatTooltipDate(isoDate) {
    var parts = (isoDate || "").split("-");
    if (parts.length !== 3) return isoDate || "--";
    var year = parts[0];
    var month = Number(parts[1]);
    var day = Number(parts[2]);
    return day + " " + (MONTH_ABBR[month - 1] || "") + " " + year;
  }

  function formatDisplayDate(isoDate) {
    // isoDate: "YYYY-MM-DD" -> "11 September 2026"
    var parts = (isoDate || "").split("-");
    if (parts.length !== 3) return isoDate || "--";
    var d = new Date(Date.UTC(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2])));
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
  }

  function formatUpdatedAt(iso) {
    if (!iso) return "--";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    var datePart = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
    var timePart = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return datePart + ", " + timePart;
  }

  function renderChangeInto(targetEl, change) {
    targetEl.innerHTML = "";
    var absolute = change && change.absolute;
    var percentage = change && change.percentage;

    if (absolute === null || absolute === undefined || percentage === null || percentage === undefined) {
      var pill = document.createElement("span");
      pill.className = "change-pill neutral";
      pill.textContent = "Change: Not available";
      targetEl.appendChild(pill);
      return;
    }

    var isUp = absolute >= 0;
    var sign = isUp ? "+" : "-";
    var arrow = isUp ? "▲" : "▼";
    var pillEl = document.createElement("span");
    pillEl.className = "change-pill " + (isUp ? "up" : "down");
    pillEl.textContent =
      arrow + " " + sign + "₹" + formatInr(Math.abs(absolute)) + " / g (" + sign + Math.abs(percentage).toFixed(2) + "%)";
    targetEl.appendChild(pillEl);
  }

  function renderCurrent(payload) {
    var current = payload.current || {};
    els.ratePerGram.textContent = formatInr(current.rate_per_gram);
    els.rate8g.textContent = "₹" + formatInr(current.rate_8g);
    els.rate10g.textContent = "₹" + formatInr(current.rate_10g);
    els.rateDate.textContent = formatDisplayDate(payload.date);
    els.rateUpdated.textContent = formatUpdatedAt(payload.updated_at);
    if (payload.source_url) {
      els.sourceLink.href = payload.source_url;
    }

    renderChangeInto(els.changeLine, payload.change);
  }

  function renderCurrent24k(payload) {
    var gold24k = payload.gold_24k || {};
    var current = gold24k.current;

    if (!current) {
      els.rate24kValueWrap.classList.add("unavailable");
      els.rupee24k.hidden = true;
      els.rate24kPerGram.textContent = "Not available";
      els.rate24k8g.textContent = "--";
      els.rate24k10g.textContent = "--";
      renderChangeInto(els.change24kLine, null);
      return;
    }

    els.rate24kValueWrap.classList.remove("unavailable");
    els.rupee24k.hidden = false;
    els.rate24kPerGram.textContent = formatInr(current.rate_per_gram);
    els.rate24k8g.textContent = "₹" + formatInr(current.rate_8g);
    els.rate24k10g.textContent = "₹" + formatInr(current.rate_10g);
    renderChangeInto(els.change24kLine, gold24k.change);
  }

  function daysBetween(isoDateA, isoDateB) {
    var a = new Date(isoDateA + "T00:00:00Z");
    var b = new Date(isoDateB + "T00:00:00Z");
    return Math.round((a.getTime() - b.getTime()) / 86400000);
  }

  function relativeLabel(entryDate, todayDate) {
    var diff = daysBetween(todayDate, entryDate);
    if (diff === 0) return "Today";
    if (diff === 1) return "Yesterday";
    if (diff > 1) return diff + " days ago";
    // A future-dated entry shouldn't normally occur, but fall back to the
    // actual date rather than asserting a relative label that isn't true.
    return new Date(entryDate + "T00:00:00Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
    });
  }

  // Looks up the rate for an exact date in a history array, or null if
  // that purity has no record for that date -- never estimated/interpolated.
  function findRateForDate(history, isoDate) {
    if (!Array.isArray(history)) return null;
    for (var i = 0; i < history.length; i++) {
      if (history[i] && history[i].date === isoDate) return history[i].rate_per_gram;
    }
    return null;
  }

  function renderRecentRates(payload) {
    var history22k = Array.isArray(payload.history) ? payload.history.slice() : [];
    var history24k = (payload.gold_24k && Array.isArray(payload.gold_24k.history)) ? payload.gold_24k.history : [];

    els.recentTableBody.innerHTML = "";
    if (!history22k.length) return;

    // 22K is the required, always-present purity, so its dates form the
    // backbone of "recent" rows; 24K is looked up per date and marked
    // "Not available" rather than estimated if that date has no 24K entry.
    var sorted22k = history22k.slice().sort(function (a, b) {
      return a.date < b.date ? 1 : a.date > b.date ? -1 : 0; // newest first
    });
    var recent = sorted22k.slice(0, 4);

    recent.forEach(function (entry) {
      var tr = document.createElement("tr");

      var dateCell = document.createElement("td");
      dateCell.textContent = relativeLabel(entry.date, payload.date);
      tr.appendChild(dateCell);

      var cell22k = document.createElement("td");
      cell22k.className = "value-22k";
      cell22k.textContent = "₹" + formatInr(entry.rate_per_gram);
      tr.appendChild(cell22k);

      var rate24k = findRateForDate(history24k, entry.date);
      var cell24k = document.createElement("td");
      if (rate24k === null || rate24k === undefined) {
        cell24k.className = "value-unavailable";
        cell24k.textContent = "Not available";
      } else {
        cell24k.className = "value-24k";
        cell24k.textContent = "₹" + formatInr(rate24k);
      }
      tr.appendChild(cell24k);

      els.recentTableBody.appendChild(tr);
    });
  }

  function historyForRange(history, days) {
    if (!Array.isArray(history)) return [];
    var sorted = history.slice().sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
    });
    return sorted.slice(-days);
  }

  // --- Chart tooltip (works for both mouse hover and touch tap) ---
  // All functions below take a chart context (charts.k22 or charts.k24)
  // so the exact same logic drives both charts independently.

  function hideTooltip(ctx) {
    if (!ctx.tooltip) return;
    ctx.tooltip.hidden = true;
    ctx.activeIndex = null;
    var activeDot = ctx.svg.querySelector(".chart-active-dot");
    if (activeDot) activeDot.setAttribute("r", 0);
  }

  function hideAllTooltips() {
    hideTooltip(charts.k22);
    hideTooltip(charts.k24);
  }

  function highlightPoint(ctx, index) {
    var activeDot = ctx.svg.querySelector(".chart-active-dot");
    var hitEl = ctx.svg.querySelector('.chart-hit[data-point-index="' + index + '"]');
    if (!activeDot || !hitEl) return;
    activeDot.setAttribute("cx", hitEl.getAttribute("cx"));
    activeDot.setAttribute("cy", hitEl.getAttribute("cy"));
    activeDot.setAttribute("r", 5);
  }

  function positionTooltip(ctx, hitEl) {
    var wrapRect = ctx.wrap.getBoundingClientRect();
    var hitRect = hitEl.getBoundingClientRect();
    var centerX = hitRect.left + hitRect.width / 2 - wrapRect.left;
    var topY = hitRect.top - wrapRect.top;

    ctx.tooltip.style.left = centerX + "px";
    ctx.tooltip.style.top = topY + "px";
    ctx.tooltip.style.transform = "translate(-50%, calc(-100% - 12px))";

    // Clamp horizontally so the tooltip is never clipped outside the
    // chart card, e.g. for the first/last point on a narrow phone screen.
    var tooltipRect = ctx.tooltip.getBoundingClientRect();
    var cardRect = ctx.wrap.closest(".card").getBoundingClientRect();
    var shift = 0;
    if (tooltipRect.right > cardRect.right - 4) {
      shift = cardRect.right - 4 - tooltipRect.right;
    } else if (tooltipRect.left < cardRect.left + 4) {
      shift = cardRect.left + 4 - tooltipRect.left;
    }
    if (shift !== 0) {
      ctx.tooltip.style.transform = "translate(calc(-50% + " + shift.toFixed(1) + "px), calc(-100% - 12px))";
    }
  }

  function showTooltipForIndex(ctx, index) {
    var points = ctx.points;
    if (!points || !points[index] || !ctx.tooltip) return;

    var point = points[index];
    ctx.activeIndex = index;
    ctx.tooltipDate.textContent = formatTooltipDate(point.date);
    ctx.tooltipValue.textContent = "₹" + formatInr(point.rate_per_gram) + " / gram";
    ctx.tooltip.hidden = false;

    var hitEl = ctx.svg.querySelector('.chart-hit[data-point-index="' + index + '"]');
    if (hitEl) positionTooltip(ctx, hitEl);
    highlightPoint(ctx, index);
  }

  function renderChartInto(ctx, historyData) {
    hideTooltip(ctx);
    var points = historyForRange(historyData, state.range);
    ctx.points = points;
    var svg = ctx.svg;

    // Clear everything except the accessible <title>, then rebuild.
    var title = svg.querySelector("title");
    svg.innerHTML = "";
    if (title) svg.appendChild(title);

    if (points.length < 2) {
      ctx.wrap.hidden = true;
      ctx.historyNote.hidden = false;
      return;
    }

    ctx.wrap.hidden = false;
    ctx.historyNote.hidden = true;

    var width = 320;
    var height = 140;
    var padTop = 12;
    var padBottom = 20;
    var padLeft = 4;
    var padRight = 4;

    var rates = points.map(function (p) { return p.rate_per_gram; });
    var minRate = Math.min.apply(null, rates);
    var maxRate = Math.max.apply(null, rates);
    if (minRate === maxRate) {
      minRate -= 1;
      maxRate += 1;
    }
    // A little breathing room above/below the line.
    var span = maxRate - minRate;
    minRate -= span * 0.1;
    maxRate += span * 0.1;

    var plotWidth = width - padLeft - padRight;
    var plotHeight = height - padTop - padBottom;

    function xFor(i) {
      return padLeft + (points.length === 1 ? plotWidth / 2 : (i / (points.length - 1)) * plotWidth);
    }
    function yFor(rate) {
      return padTop + plotHeight - ((rate - minRate) / (maxRate - minRate)) * plotHeight;
    }

    var ns = "http://www.w3.org/2000/svg";

    // Horizontal gridlines (min/mid/max)
    [0, 0.5, 1].forEach(function (frac) {
      var y = padTop + plotHeight * frac;
      var line = document.createElementNS(ns, "line");
      line.setAttribute("x1", padLeft);
      line.setAttribute("x2", width - padRight);
      line.setAttribute("y1", y);
      line.setAttribute("y2", y);
      line.setAttribute("class", "chart-grid");
      svg.appendChild(line);
    });

    var linePath = points.map(function (p, i) {
      return (i === 0 ? "M" : "L") + xFor(i).toFixed(2) + "," + yFor(p.rate_per_gram).toFixed(2);
    }).join(" ");

    var fillPath =
      linePath +
      " L" + xFor(points.length - 1).toFixed(2) + "," + (height - padBottom).toFixed(2) +
      " L" + xFor(0).toFixed(2) + "," + (height - padBottom).toFixed(2) +
      " Z";

    var fillEl = document.createElementNS(ns, "path");
    fillEl.setAttribute("d", fillPath);
    fillEl.setAttribute("class", "chart-fill");
    svg.appendChild(fillEl);

    var lineEl = document.createElementNS(ns, "path");
    lineEl.setAttribute("d", linePath);
    lineEl.setAttribute("class", "chart-line");
    svg.appendChild(lineEl);

    // Dot on the last (most recent) point, plus the first for reference.
    [0, points.length - 1].forEach(function (i) {
      var dot = document.createElementNS(ns, "circle");
      dot.setAttribute("cx", xFor(i).toFixed(2));
      dot.setAttribute("cy", yFor(points[i].rate_per_gram).toFixed(2));
      dot.setAttribute("r", 3);
      dot.setAttribute("class", "chart-dot");
      svg.appendChild(dot);
    });

    // A handful of date labels along the x-axis (first, middle, last).
    var labelIndexes = points.length <= 2 ? [0, points.length - 1] : [0, Math.floor((points.length - 1) / 2), points.length - 1];
    labelIndexes.forEach(function (i) {
      var label = document.createElementNS(ns, "text");
      label.setAttribute("x", xFor(i).toFixed(2));
      label.setAttribute("y", height - 4);
      label.setAttribute("text-anchor", i === 0 ? "start" : i === points.length - 1 ? "end" : "middle");
      label.setAttribute("class", "chart-axis-label");
      var d = new Date(points[i].date + "T00:00:00Z");
      label.textContent = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
      svg.appendChild(label);
    });

    // Active-point highlight (shown only while a tooltip is open).
    var activeDot = document.createElementNS(ns, "circle");
    activeDot.setAttribute("class", "chart-active-dot");
    activeDot.setAttribute("r", 0);
    svg.appendChild(activeDot);

    // One generously-sized, invisible hit target per point, for both
    // mouse hover (desktop) and tap (mobile/touch) -- see showTooltipForIndex.
    points.forEach(function (p, i) {
      var hit = document.createElementNS(ns, "circle");
      hit.setAttribute("cx", xFor(i).toFixed(2));
      hit.setAttribute("cy", yFor(p.rate_per_gram).toFixed(2));
      hit.setAttribute("r", 14);
      hit.setAttribute("class", "chart-hit");
      hit.setAttribute("data-point-index", String(i));
      hit.setAttribute("tabindex", "0");
      hit.setAttribute("role", "button");
      hit.setAttribute(
        "aria-label",
        formatTooltipDate(p.date) + ", " + ctx.label + " ₹" + formatInr(p.rate_per_gram) + " per gram"
      );

      hit.addEventListener("mouseenter", function () {
        showTooltipForIndex(ctx, i);
      });
      hit.addEventListener("mouseleave", function () {
        hideTooltip(ctx);
      });
      hit.addEventListener("focus", function () {
        showTooltipForIndex(ctx, i);
      });
      hit.addEventListener("blur", function () {
        hideTooltip(ctx);
      });
      // `click` fires for both a mouse click and a touch tap (without
      // needing touchstart/touchmove handlers that would risk blocking
      // normal page scrolling), so this alone covers mobile tap-to-show.
      hit.addEventListener("click", function (e) {
        e.stopPropagation();
        if (ctx.activeIndex === i && !ctx.tooltip.hidden) {
          hideTooltip(ctx);
        } else {
          showTooltipForIndex(ctx, i);
        }
      });

      svg.appendChild(hit);
    });
  }

  function renderCharts() {
    var payload = state.payload;
    if (!payload) return;
    renderChartInto(charts.k22, payload.history);
    renderChartInto(charts.k24, (payload.gold_24k && payload.gold_24k.history) || []);
  }

  function setRange(days) {
    state.range = days;
    els.rangeButtons.forEach(function (btn) {
      var active = Number(btn.dataset.range) === days;
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    renderCharts();
  }

  function attachRangeButtons() {
    els.rangeButtons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        setRange(Number(btn.dataset.range));
      });
    });
  }

  function load() {
    showState("loading");
    // Cache-busting query param: GitHub Pages / browsers can otherwise
    // serve a stale copy of the JSON for a while after it changes.
    var url = DATA_URL + "?t=" + Date.now();

    fetch(url, { cache: "no-store" })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("Server returned HTTP " + response.status);
        }
        return response.json();
      })
      .then(function (payload) {
        if (!payload || !payload.current || typeof payload.current.rate_per_gram !== "number") {
          throw new Error("Data file is missing the expected rate fields.");
        }
        state.payload = payload;
        renderCurrent(payload);
        renderCurrent24k(payload);
        renderCharts();
        renderRecentRates(payload);
        showState("content");
      })
      .catch(function (err) {
        els.errorDetail.textContent = err && err.message ? err.message : "Unknown error.";
        showState("error");
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    cacheElements();
    attachRangeButtons();
    els.retryButton.addEventListener("click", load);

    // Dismiss any open tooltip on a tap/click outside both charts, and on
    // resize (a tooltip's position is computed from live element rects,
    // which a resize would make stale until the next hover/tap).
    document.addEventListener("click", function (e) {
      var insideK22 = charts.k22.wrap && charts.k22.wrap.contains(e.target);
      var insideK24 = charts.k24.wrap && charts.k24.wrap.contains(e.target);
      if (!insideK22 && !insideK24) {
        hideAllTooltips();
      }
    });
    window.addEventListener("resize", hideAllTooltips);

    load();
  });
})();
