/*
 * Hyderabad Gold Rate Teller — dashboard frontend.
 *
 * Plain vanilla JS. No frameworks, no chart library, no CDN dependency:
 * the history chart is a small hand-drawn SVG line, which keeps the page
 * fast-loading and avoids pulling in a dependency just for a single line
 * chart.
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

    els.chart = document.getElementById("chart");
    els.chartWrap = document.getElementById("chart-wrap");
    els.historyNote = document.getElementById("history-note");
    els.rangeButtons = Array.prototype.slice.call(document.querySelectorAll(".range-btn"));

    els.recentList = document.getElementById("recent-list");

    els.tooltip = document.getElementById("chart-tooltip");
    els.tooltipDate = document.getElementById("tooltip-date");
    els.tooltipValue = document.getElementById("tooltip-value");
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

    renderChange(payload.change);
  }

  function renderChange(change) {
    els.changeLine.innerHTML = "";
    var absolute = change && change.absolute;
    var percentage = change && change.percentage;

    if (absolute === null || absolute === undefined || percentage === null || percentage === undefined) {
      var pill = document.createElement("span");
      pill.className = "change-pill neutral";
      pill.textContent = "Change: Not available";
      els.changeLine.appendChild(pill);
      return;
    }

    var isUp = absolute >= 0;
    var sign = isUp ? "+" : "-";
    var arrow = isUp ? "▲" : "▼";
    var pillEl = document.createElement("span");
    pillEl.className = "change-pill " + (isUp ? "up" : "down");
    pillEl.textContent =
      arrow + " " + sign + "₹" + formatInr(Math.abs(absolute)) + " / g (" + sign + Math.abs(percentage).toFixed(2) + "%)";
    els.changeLine.appendChild(pillEl);
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

  function renderRecentRates(payload) {
    var history = Array.isArray(payload.history) ? payload.history.slice() : [];
    els.recentList.innerHTML = "";

    if (!history.length) return;

    var sorted = history.slice().sort(function (a, b) {
      return a.date < b.date ? 1 : a.date > b.date ? -1 : 0; // newest first
    });
    var recent = sorted.slice(0, 4);

    recent.forEach(function (entry) {
      var li = document.createElement("li");
      li.className = "recent-row";

      var label = document.createElement("span");
      label.className = "recent-label";
      label.textContent = relativeLabel(entry.date, payload.date);

      var value = document.createElement("span");
      value.className = "recent-value";
      value.textContent = "₹" + formatInr(entry.rate_per_gram);

      li.appendChild(label);
      li.appendChild(value);
      els.recentList.appendChild(li);
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

  function hideTooltip() {
    if (!els.tooltip) return;
    els.tooltip.hidden = true;
    state.activeIndex = null;
    var activeDot = els.chart.querySelector(".chart-active-dot");
    if (activeDot) activeDot.setAttribute("r", 0);
  }

  function highlightPoint(index) {
    var activeDot = els.chart.querySelector(".chart-active-dot");
    var hitEl = els.chart.querySelector('.chart-hit[data-point-index="' + index + '"]');
    if (!activeDot || !hitEl) return;
    activeDot.setAttribute("cx", hitEl.getAttribute("cx"));
    activeDot.setAttribute("cy", hitEl.getAttribute("cy"));
    activeDot.setAttribute("r", 5);
  }

  function positionTooltip(hitEl) {
    var wrapRect = els.chartWrap.getBoundingClientRect();
    var hitRect = hitEl.getBoundingClientRect();
    var centerX = hitRect.left + hitRect.width / 2 - wrapRect.left;
    var topY = hitRect.top - wrapRect.top;

    els.tooltip.style.left = centerX + "px";
    els.tooltip.style.top = topY + "px";
    els.tooltip.style.transform = "translate(-50%, calc(-100% - 12px))";

    // Clamp horizontally so the tooltip is never clipped outside the
    // chart card, e.g. for the first/last point on a narrow phone screen.
    var tooltipRect = els.tooltip.getBoundingClientRect();
    var cardRect = els.chartWrap.closest(".card").getBoundingClientRect();
    var shift = 0;
    if (tooltipRect.right > cardRect.right - 4) {
      shift = cardRect.right - 4 - tooltipRect.right;
    } else if (tooltipRect.left < cardRect.left + 4) {
      shift = cardRect.left + 4 - tooltipRect.left;
    }
    if (shift !== 0) {
      els.tooltip.style.transform = "translate(calc(-50% + " + shift.toFixed(1) + "px), calc(-100% - 12px))";
    }
  }

  function showTooltipForIndex(index) {
    var points = state.chartPoints;
    if (!points || !points[index] || !els.tooltip) return;

    var point = points[index];
    state.activeIndex = index;
    els.tooltipDate.textContent = formatTooltipDate(point.date);
    els.tooltipValue.textContent = "₹" + formatInr(point.rate_per_gram) + " / gram";
    els.tooltip.hidden = false;

    var hitEl = els.chart.querySelector('.chart-hit[data-point-index="' + index + '"]');
    if (hitEl) positionTooltip(hitEl);
    highlightPoint(index);
  }

  function renderChart() {
    var payload = state.payload;
    if (!payload) return;

    hideTooltip();
    var points = historyForRange(payload.history, state.range);
    state.chartPoints = points;
    var svg = els.chart;

    // Clear everything except the accessible <title>, then rebuild.
    var title = svg.querySelector("title");
    svg.innerHTML = "";
    if (title) svg.appendChild(title);

    if (points.length < 2) {
      els.chartWrap.hidden = true;
      els.historyNote.hidden = false;
      return;
    }

    els.chartWrap.hidden = false;
    els.historyNote.hidden = true;

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
        formatTooltipDate(p.date) + ", 22K gold rate ₹" + formatInr(p.rate_per_gram) + " per gram"
      );

      hit.addEventListener("mouseenter", function () {
        showTooltipForIndex(i);
      });
      hit.addEventListener("mouseleave", function () {
        hideTooltip();
      });
      hit.addEventListener("focus", function () {
        showTooltipForIndex(i);
      });
      hit.addEventListener("blur", function () {
        hideTooltip();
      });
      // `click` fires for both a mouse click and a touch tap (without
      // needing touchstart/touchmove handlers that would risk blocking
      // normal page scrolling), so this alone covers mobile tap-to-show.
      hit.addEventListener("click", function (e) {
        e.stopPropagation();
        if (state.activeIndex === i && !els.tooltip.hidden) {
          hideTooltip();
        } else {
          showTooltipForIndex(i);
        }
      });

      svg.appendChild(hit);
    });
  }

  function setRange(days) {
    state.range = days;
    els.rangeButtons.forEach(function (btn) {
      var active = Number(btn.dataset.range) === days;
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
    renderChart();
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
        renderChart();
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

    // Dismiss the tooltip on a tap/click anywhere outside the chart, and
    // on resize (its position is computed from live element rects, which
    // a resize would make stale until the next hover/tap).
    document.addEventListener("click", function (e) {
      if (els.chartWrap && !els.chartWrap.contains(e.target)) {
        hideTooltip();
      }
    });
    window.addEventListener("resize", hideTooltip);

    load();
  });
})();
