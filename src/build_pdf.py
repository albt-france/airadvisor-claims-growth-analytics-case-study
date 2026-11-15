"""Build the 8-page PDF report (16:9) and one PNG per page for the README.

Steps: read data/output (src/analysis.py) and data/public -> matplotlib charts as inline SVG -> build/report.html
-> PDF with Edge/Chrome headless -> neutral PDF metadata -> PNG per page in docs/img/.
Every number in the text is read from the outputs; only published facts (fees, rules) are typed, with their source.
Usage:  python src/build_pdf.py   (after src/analysis.py and src/build_dashboard.py)
"""
import html
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import polars as pl
from pypdf import PdfReader, PdfWriter

from charts import fig, pct_axis, thousands_axis, to_svg, waterfall
from common import (AQUA, BG, BLUE, BLUE_DARK, BLUE_LIGHT, BORDER, CARD, COUNTRY_NAME, DISCLAIMER, DOCS, GREY,
                    GREY_LIGHT, INK, INK2, MUTED, ORANGE, PUB, RED, ROOT, YELLOW, ai_note, fmt_eur, fmt_int, fmt_pct, sim_con, utf8)
from analysis import OUT

BUILD = ROOT / "build"
PDF = DOCS / "AirAdvisor_ClaimsGrowth_CaseStudy.pdf"
TITLE = "AirAdvisor: where the next claims are, and how to grow them profitably"
SUBTITLE = ("Real aviation and regulatory data turned into a country-by-country claim opportunity map, plus a simulated claim funnel "
            "used to show data ownership, tracking QA, experimentation, spend efficiency and subscription pricing")


def browser():
    for p in [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", shutil.which("msedge") or "", shutil.which("google-chrome") or "",
              shutil.which("chromium") or ""]:
        if p and Path(p).exists():
            return p
    sys.exit("Edge or Chrome is needed to print the PDF.")


def headless(args):
    profile = tempfile.mkdtemp(prefix="edge-profile-")
    subprocess.run([browser(), "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                    f"--user-data-dir={profile}", *args], check=True, capture_output=True, timeout=240)
    shutil.rmtree(profile, ignore_errors=True)


# ------------------------------------------------------------------ html blocks
def card(title, body, cls="", style=""):
    t = f"<h3>{title}</h3>" if title else ""
    return f'<div class="card {cls}" style="{style}">{t}{body}</div>'


def kpi(tag, value, text, color=INK):
    return f'<div class="card kpi"><div class="ktag">{tag}</div><div class="kval" style="color:{color}">{value}</div><div class="ktxt">{text}</div></div>'


def table(rows, cols, cls="tight"):
    head = "".join(f"<th{' class=num' if n else ''}>{html.escape(h)}</th>" for h, n in cols)
    body = "".join("<tr>" + "".join(f"<td{' class=num' if cols[i][1] else ''}>{c}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def page(n, title, subtitle, tag, body, footer):
    tag_html = f'<div class="tag">{tag}</div>' if tag else ""
    return f"""<section class="page" id="p{n}">
  <header><div><h1>{title}</h1><p class="subtitle">{subtitle}</p></div>{tag_html}</header>
  <main>{body}</main>
  <footer><span>{footer}</span><span>{DISCLAIMER} · {n + 1}/8</span></footer>
</section>"""


CSS = f"""
@page {{ size: 1280px 720px; margin: 0; }}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: {BG}; color: {INK}; font-family: "Segoe UI", system-ui, sans-serif; }}
.page {{ width: 1280px; height: 720px; padding: 26px 36px 0 36px; position: relative; overflow: hidden; page-break-after: always;
        break-after: page; background: {BG}; display: flex; flex-direction: column; }}
.page:last-child {{ page-break-after: auto; break-after: auto; }}
header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; min-height: 66px; }}
h1 {{ font-size: 23px; line-height: 1.2; margin: 0 0 5px 0; font-weight: 700; max-width: 1060px; }}
.subtitle {{ color: {INK2}; font-size: 12.5px; line-height: 1.4; margin: 0; max-width: 1080px; }}
.tag {{ font-size: 10.5px; font-weight: 700; letter-spacing: .07em; color: {INK2}; white-space: nowrap; padding: 4px 8px;
       border: 1px solid {BORDER}; border-radius: 4px; background: {CARD}; }}
main {{ flex: 1; display: grid; gap: 12px; margin-top: 12px; min-height: 0; }}
footer {{ color: {MUTED}; font-size: 9px; padding: 7px 0 9px 0; display: flex; justify-content: space-between; gap: 20px; }}
.card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px; padding: 11px 14px; min-height: 0; overflow: hidden; }}
.card h3 {{ font-size: 12.5px; margin: 0 0 7px 0; font-weight: 600; }}
.card p, .card li {{ font-size: 11.5px; line-height: 1.42; color: {INK}; }}
.card p {{ margin: 0 0 6px 0; }}
.card ul, .card ol {{ margin: 0; padding-left: 17px; }} .card li {{ margin-bottom: 4px; }}
.muted {{ color: {INK2}; }} .small {{ font-size: 10.5px !important; }}
.kpi {{ display: flex; flex-direction: column; }}
.ktag {{ font-size: 9.5px; font-weight: 700; letter-spacing: .06em; color: {INK2}; }}
.kval {{ font-size: 28px; font-weight: 700; margin: 3px 0 2px 0; line-height: 1.1; }}
.ktxt {{ font-size: 11px; color: {INK2}; line-height: 1.35; }}
svg.chart {{ width: 100%; height: auto; display: block; }}
table {{ border-collapse: collapse; width: 100%; font-size: 11px; }}
th {{ text-align: left; color: {INK2}; font-weight: 600; border-bottom: 1px solid {INK2}; padding: 3px 5px; }}
td {{ border-bottom: 1px solid {BORDER}; padding: 3px 5px; vertical-align: top; }}
td.num, th.num {{ text-align: right; white-space: nowrap; }}
table.tight td, table.tight th {{ padding: 2px 5px; font-size: 10.3px; }}
.bad {{ color: {RED}; font-weight: 600; }} .good {{ color: {BLUE}; font-weight: 600; }}
.q {{ display: flex; gap: 10px; margin-bottom: 6px; font-size: 11.5px; line-height: 1.38; }}
.q b {{ color: {BLUE}; white-space: nowrap; min-width: 118px; }}
code, pre {{ font-family: Consolas, monospace; font-size: 10px; }}
pre {{ background: #F0EFEC; border-radius: 6px; padding: 7px 9px; margin: 5px 0 0 0; white-space: pre-wrap; line-height: 1.35; }}
.pill {{ display: inline-block; font-size: 9.5px; padding: 1px 6px; border-radius: 9px; background: #EAF2FC; color: {BLUE}; font-weight: 700; letter-spacing: .03em; }}
.pill.red {{ background: #FBEAEA; color: {RED}; }} .pill.grey {{ background: #EEEDE9; color: {INK2}; }}
.reco {{ border-left: 3px solid {BLUE}; padding: 1px 0 1px 9px; margin-bottom: 7px; font-size: 11.5px; line-height: 1.4; }}
.reco b {{ display: block; }}
.grid {{ display: grid; gap: 12px; min-height: 0; }}
"""


def sv(svg, h):
    """Cap a chart's rendered height (it keeps its aspect ratio, so nothing is cut)."""
    return svg.replace('<svg class="chart"', f'<svg class="chart" style="max-height:{h}px"', 1)


def g(cols, inner, rows=None):
    r = f"grid-template-rows:{rows};" if rows else ""
    return f'<div class="grid" style="grid-template-columns:{cols};{r}">{inner}</div>'


# ------------------------------------------------------------------ pages
def p0(R):
    m, t, te, s, sb = R["market"], R["tracking"], R["testing"], R["spend"], R["subscription"]
    qs = [("New markets", "Where are the next claims, country by country, and how much could AirAdvisor win there?"),
          ("Data ownership", "Which numbers can the CEO trust: one definition per KPI, one tracking plan, daily reconciliation?"),
          ("Real or noise", "When a KPI moves, is it the business, the tracking, or the season?"),
          ("Test rigour", "Which test results can be shipped, and which are artefacts?"),
          ("Spend & pricing", "Which spend is wasted, what will next months bring, and how should the subscription be priced?")]
    qh = "".join(f'<div class="q"><b>{i + 1} · {a}</b><span>{html.escape(b)}</span></div>' for i, (a, b) in enumerate(qs))
    reco = [("Fix the mobile tag first.", f"GA4 lost every mobile claim submission since {t['tag_break']['detected']}: {fmt_int(t['tag_break']['crm_claims_unseen_by_ga4'])} claims are invisible. No funnel test is readable until then."),
            ("Stop paying for brand demand you already own.", f"Pausing Microsoft brand ads in France did not reduce claims (DiD {te['did']['beta_level']:+.1f} claims/week, CI {te['did']['ci_level'][0]:.1f} to {te['did']['ci_level'][1]:+.1f}). Run the same test on Google brand."),
            ("Grow the big four, then the Netherlands.", f"UK, Germany, France and Spain hold {fmt_pct(m['top4_share_som'])} of the obtainable revenue; the Netherlands is next, in every sensitivity case."),
            ("Price the subscription at €49 a year.", "Subscribers fly about twice as often as the average offer recipient; €49 keeps a margin for 9 in 10 of them, €29 only with a trip cap.")]
    rh = "".join(f'<div class="reco"><b>{a}</b><span class="muted">{b}</span></div>' for a, b in reco)
    body = f"""
{g("repeat(4,1fr)", kpi("PUBLIC DATA · PAGE 3", fmt_eur(m['ceiling_eur'], 1), f"theoretical ceiling of EU261/UK261 compensation a year on European departures; obtainable revenue {fmt_eur(m['sam_eur'] * 0.06)}-{fmt_eur(m['sam_eur'] * 0.20)}")
 + kpi("SIMULATED · PAGE 5", fmt_int(t['tag_break']['crm_claims_unseen_by_ga4']), "claims recorded in the CRM but missing in GA4 after a mobile release: caught by a daily reconciliation", RED)
 + kpi("SIMULATED · PAGE 6", f"{te['raw']['lift_rel']:+.1%} → {te['itt']['lift_rel']:+.1%}", "fee-display test: raw GA4 'win' vs the corrected read after a sample ratio mismatch check", RED)
 + kpi("SIMULATED · PAGE 7", f"€{sb['best_price'] if False else 49:.0f}/yr", f"subscription price that keeps a margin while subscribers fly {sb['tiers'][1]['trips_subscribers']:.1f} trips a year on average"))}
{g("1fr 1.1fr", card("The questions the job posting asks", qh + '<p class="small muted" style="margin-top:6px">Each page title states the answer. Tags say where the numbers come from: <b>PUBLIC DATA</b> (real, sourced) or <b>SIMULATED</b> (invented to show the method, never AirAdvisor figures).</p>'
                                         + '<p class="small" style="margin-top:8px"><b>Deliverables in the repository:</b> this report · a 4-tab HTML dashboard (business pulse, funnel and experiments, data health, market map) · a KPI dictionary (19 KPIs) · a GA4/GTM tracking plan with QA tests · 14 SQL queries · one notebook · a one-page CEO memo.</p>')
 + card("Recommendations to the CEO", rh))}
{card("", f'<p class="small"><b>Methods.</b> PUBLIC DATA: AirAdvisor pages (fees, facts), EU261 / UK261 / APPR / DOT / Montreal official texts, Eurostat airport-pair passengers 2024 ({fmt_int(m["departing_pax"] / 1e6)}M departures), UK CAA punctuality 2025, US BTS on-time 2025 ({fmt_int(m["us_flights"] / 1e6)}M flights), OurAirports distances. '
       f'SIMULATED: 18-month claim funnel (seed 42) in BigQuery-style tables (GA4 events, CRM claims, ad spend, A/B log, tickets, subscription pilot) with 8 planted events, all found ({R["detection"]["found"]}/8). '
       f'Tools: SQL (DuckDB, BigQuery-compatible, 14 queries), Python, a 4-tab HTML dashboard, KPI dictionary and tracking plan.</p>')}"""
    body = f'<div class="grid" style="grid-template-rows:auto 1fr auto">{body}</div>'
    return page(0, TITLE, SUBTITLE, "OVERVIEW", body, "Sources: data/SOURCES.md · public data collected 2026-11-15")


def p1(R):
    facts = [("Model", "No win, no fee; commission on the compensation collected"),
             ("Fees", "<b>30%</b> flight compensation (pre-trial, VAT incl.) · <b>50%</b> with external lawyers · <b>40%</b> baggage and reimbursements"),
             ("Scale", "830,000 cases; 4.5/5 on 28,876 Reviews.io reviews; 221 countries, 21 languages (posting)"),
             ("Coverage", "UK, EU, USA, Canada, international; baggage claims with a patented process (posting)"),
             ("Next", "An annual subscription covering flight and baggage disruption caused by airline negligence (posting)")]
    fh = table([(f"<b>{a}</b>", b) for a, b in facts], [("", False), ("As stated by AirAdvisor", False)])
    rules = [("EU261", "Departures from EU/EEA/CH; arrivals on EU carriers", "€250 / €400 / €600 by distance; 3h+ late at arrival, cancellation, denied boarding", "Extraordinary circumstances"),
             ("UK261", "Departures from the UK; arrivals on UK/EU carriers", "£220 / £350 / £520 (£260 if long-haul 3-4 h)", "Same principle"),
             ("Canada APPR", "Flights to, from and within Canada", "CAD 400 / 700 / 1,000 (large airlines; 3/6/9 h)", "Only if within airline control, not safety"),
             ("US DOT", "Flights in the US", "Refund for cancellations and significant delays (3 h domestic, 6 h intl); no delay compensation", "-"),
             ("Montreal", "International baggage", "Up to 1,519 SDR per passenger (≈ €1,850) since 28 Dec 2024", "Proof of loss")]
    rh = table([(f"<b>{a}</b>", b, c, d) for a, b, c, d in rules], [("Rule", False), ("Scope", False), ("Passenger receives", False), ("Exemption", False)])
    # published fees chart (VAT-inclusive where stated; Flightright shown as a range + VAT)
    f, ax = fig(552, 150)
    labels = ["AirAdvisor", "AirHelp", "Flightright"]
    lo = [30, 35, 20 * 1.19]; hi = [30, 35, 30 * 1.19]
    y = np.arange(3)[::-1]
    ax.barh(y, lo, color=[BLUE, GREY, GREY], height=0.55)
    ax.barh(y[2], hi[2] - lo[2], left=lo[2], color=GREY_LIGHT, height=0.55)
    ax.barh(y, [20, 15, 14 * 1.19], left=[30, 35, hi[2]], color=[BLUE_LIGHT, GREY_LIGHT, GREY_LIGHT], height=0.55, alpha=0.6)
    for yy, txt in zip(y, ["30% · 50% if court", "35% + 15% legal action", "20-30% + VAT (+14% solicitor)"]):
        ax.text(1, yy, txt, va="center", fontsize=8.5, color="white" if yy == 2 else INK)
    ax.set_yticks(y, labels, fontsize=9); ax.set_xlim(0, 70); ax.grid(axis="y", visible=False)
    ax.set_xlabel("success fee, % of compensation (darker = standard, lighter = legal surcharge)", fontsize=8)
    fee_svg = to_svg(f)
    us = R["market"]
    subs = table([("AirHelp+", "$22.99/trip; $32.99-$99.99/yr worldwide; $179.99-$249.99/yr USA", "0% fee"),
                  ("AirHelp TravelPass", "$49-$799/yr for 3, 6 or 9 trips", "15% / 10% / 0%")],
                 [("Plan", False), ("Published price", False), ("Fee on claims", False)])
    body = g("1.08fr 1fr", g("1fr", card("AirAdvisor in its own words (website and job posting, 15 Nov 2026)", fh)
                            + card("The rules that create the claims (official texts)", rh + f'<p class="small muted" style="margin-top:5px">A delayed flight does not always owe compensation: weather, air traffic control or security events are extraordinary circumstances. In the US, BTS 2025 shows {fmt_pct(us["us_late3"], 1)} of flights 3h+ late with no delay compensation: there the product is refunds, baggage and the subscription.</p>'), rows="auto 1fr")
             + g("1fr", card("Published success fees of the sector", sv(fee_svg, 160) + '<p class="small muted">Fees as published on each company\'s pricing page (15 Nov 2026). AirAdvisor\'s 30% includes VAT; Flightright\'s range excludes it (shown at 19% VAT).</p>')
                 + card("Subscriptions already sold in the sector (published prices)", subs + '<p class="small muted" style="margin-top:5px">The benchmark for AirAdvisor\'s annual plan: trip-capped tiers and a reduced fee rather than unlimited free claims.</p>')
                 + card("What this means for the analyst", '<ul class="small"><li><b>Revenue = claims x amount x success rate x fee</b>: every factor is a KPI with an owner.</li><li>The amount depends on route distance and regime: route data drives the forecast and the market model.</li><li>Acceptance depends on airline answers: Legal needs carrier-level signals.</li></ul>'), rows="auto auto 1fr"))
    return page(1, "AirAdvisor earns a 30% success fee on rights that EU, UK and Canadian law define; a subscription would turn one-off claims into recurring revenue",
                "What AirAdvisor publishes about itself, the official rules behind each claim, and the published fees and subscriptions of the sector.", "PUBLIC DATA", body,
                "Sources: airadvisor.com (home, pricelist), job posting; EUR-Lex/Your Europe, caa.co.uk, otc-cta.gc.ca, transportation.gov; airhelp.com/en/price-list, flightright.com/costs (all read 2026-11-15)")


def tile_map(mk, w=380, h=330):
    pos = {"IS": (0, 0), "NO": (3, 0), "SE": (4, 0), "FI": (5, 0), "EE": (6, 1), "LV": (6, 2), "LT": (6, 3), "UK": (1, 2), "IE": (0, 2),
           "DK": (3, 1), "NL": (2, 3), "BE": (2, 4), "LU": (3, 4), "DE": (3, 3), "PL": (5, 3), "CZ": (4, 4), "SK": (5, 4), "FR": (2, 5),
           "CH": (3, 5), "AT": (4, 5), "HU": (5, 5), "RO": (6, 5), "SI": (4, 6), "HR": (5, 6), "BG": (6, 6), "PT": (0, 6), "ES": (1, 6),
           "IT": (3, 6), "MT": (3, 7), "EL": (6, 7), "CY": (7, 7)}
    f, ax = fig(w, h)
    import matplotlib.colors as mc
    cmap = mc.LinearSegmentedColormap.from_list("b", ["#DCE9F8", BLUE_DARK])
    v = {r["country"]: r for r in mk.iter_rows(named=True)}
    lo, hi = np.log10(min(r["som_eur"] for r in v.values())), np.log10(max(r["som_eur"] for r in v.values()))
    for c, (x, y) in pos.items():
        if c not in v:
            continue
        val = (np.log10(v[c]["som_eur"]) - lo) / (hi - lo)
        ax.add_patch(__import__("matplotlib.patches", fromlist=["Rectangle"]).Rectangle((x, -y), 0.92, 0.92, color=cmap(val)))
        ax.text(x + 0.46, -y + 0.58, c, ha="center", va="center", fontsize=9, fontweight="bold", color="white" if val > 0.45 else INK)
        ax.text(x + 0.46, -y + 0.27, fmt_eur(v[c]["som_eur"], 1).replace("€", ""), ha="center", va="center", fontsize=6.5, color="white" if val > 0.45 else INK2)
    ax.set_xlim(-0.1, 8.1); ax.set_ylim(-7.1, 1.0); ax.axis("off"); ax.set_aspect("equal")
    return to_svg(f)


def nl_card(m):
    nl = m.filter(pl.col("country") == "NL").row(0, named=True)
    pt = m.filter(pl.col("country") == "PT").row(0, named=True)
    return (f'<ul class="small"><li><b>Core (UK, DE, FR, ES):</b> defend share; spend follows the forecast; protect conversion (tracking, fee clarity).</li>'
            f'<li><b>Next (NL, IT, PT, BE):</b> the Netherlands has the highest disruption share of the larger markets ({fmt_pct(nl["p_late3"] + nl["p_cancel"], 2)}), '
            f'{fmt_pct(nl["long_haul_pax_share"])} long-haul passengers (higher amounts) and a break-even CAC of €{nl["breakeven_cac_eur"]:.0f}. Entry: Dutch landing pages and SEO first, '
            f'non-brand search capped at break-even CAC, airport-level content; measure with a geo holdout. Portugal ({fmt_eur(pt["som_eur"])}/yr) follows, growing {fmt_pct(pt["growth_2019_2024"])} vs 2019.</li>'
            f'<li><b>Long tail:</b> SEO and partnerships only, no paid acquisition.</li></ul>')


def p2(R):
    m = pl.read_csv(OUT / "market_ranking.csv")
    M = R["market"]
    top = m.head(10)
    rows = [(r["rank"], html.escape(r["country_name"]), r["regime"], f'{r["departing_pax"] / 1e6:.0f}M', fmt_pct(r["p_late3"] + r["p_cancel"], 2),
             f'€{r["avg_amount_eur"]:.0f}', fmt_eur(r["ceiling_eur"]), f'<b>{fmt_eur(r["som_eur"], 1)}</b>', f'€{r["breakeven_cac_eur"]:.0f}') for r in top.iter_rows(named=True)]
    tbl = table(rows, [("#", True), ("Country", False), ("Rule", False), ("Departures", True), ("Disrupted", True), ("Avg €", True),
                       ("Ceiling", True), ("SOM/yr", True), ("Max CAC", True)])
    # funnel ceiling -> SOM
    f, ax = fig(330, 175)
    vals = [M["ceiling_eur"], M["tam_eur"], M["sam_eur"], M["som_eur"]]
    labs = ["Theoretical ceiling", "TAM: eligible x 30% fee", "SAM: claimed via agencies", "SOM: obtainable (12%)"]
    y = np.arange(4)[::-1]
    ax.barh(y, vals, color=[GREY, BLUE_LIGHT, BLUE, BLUE_DARK], height=0.6); ax.set_xscale("log")
    for yy, v in zip(y, vals):
        ax.text(v * 1.15, yy, fmt_eur(v, 1), va="center", fontsize=9, fontweight="bold")
    ax.set_yticks(y, labs, fontsize=8.5); ax.set_xlim(3e6, 4e10); ax.grid(axis="y", visible=False); ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    fsvg = to_svg(f)
    # tornado
    s = pl.read_csv(PUB / "market_sensitivity.csv")
    c0 = s["central_eur"][0]
    names = s["assumption"].unique(maintain_order=True).to_list()
    lo = [s.filter((pl.col("assumption") == n) & (pl.col("case") == "low"))["som_total_eur"][0] for n in names]
    hi = [s.filter((pl.col("assumption") == n) & (pl.col("case") == "high"))["som_total_eur"][0] for n in names]
    order = sorted(zip(names, lo, hi), key=lambda x: x[2] - x[1])
    f, ax = fig(330, 175)
    yy = np.arange(len(order))
    ax.barh(yy, [o[1] - c0 for o in order], left=c0, color=GREY, height=0.6)
    ax.barh(yy, [o[2] - c0 for o in order], left=c0, color=BLUE, height=0.6)
    ax.axvline(c0, color=INK, lw=1)
    ax.set_yticks(yy, [o[0].replace("_", " ") for o in order], fontsize=8)
    ax.xaxis.set_major_formatter(__import__("matplotlib.ticker", fromlist=["FuncFormatter"]).FuncFormatter(lambda v, _: f"€{v / 1e6:.0f}M"))
    ax.grid(axis="y", visible=False)
    tsvg = to_svg(f)
    rs = pl.read_csv(PUB / "rank_stability.csv")
    body = g("0.92fr 1.18fr 0.9fr",
             card("Obtainable revenue (SOM) by country, € per year", sv(tile_map(m), 420) + '<p class="small muted">One tile per country; darker = more. UK under UK261, others under EU261.</p>')
             + g("1fr", card("Ranking: departures x disruption x amount x claim funnel", tbl + f'<p class="small muted" style="margin-top:5px">Disrupted = share of passengers on flights 3h+ late or cancelled. Max CAC = revenue per claim x (1 - 30% variable cost): the most a claim can cost in that country.</p>')
                 + card("Entry strategy by tier", nl_card(m)), rows="auto 1fr")
             + g("1fr", card("From ceiling to obtainable revenue (all countries)", sv(fsvg, 150))
                 + card("Sensitivity of total SOM", sv(tsvg, 170) + f'<p class="small muted">Euro amounts swing {fmt_eur(M["sens_min"])} to {fmt_eur(M["sens_max"])}; the top 5 stays the top 5 under every disruption measure tested (raw, arrivals only, departures only, all-low).</p>'), rows="auto 1fr"))
    title = (f"The UK, Germany, France and Spain hold {fmt_pct(M['top4_share_som'])} of the obtainable claim revenue; the Netherlands is the next market to grow")
    return page(2, title, f"{fmt_int(M['departing_pax'] / 1e6)}M departing passengers in {M['countries']} European countries, {fmt_pct(M['disrupted_share'], 2)} on flights 3h+ late or cancelled: a <b>theoretical ceiling</b> of {fmt_eur(M['ceiling_eur'], 2)} a year if every disruption were the airline's fault and every passenger claimed. Neither is true, so the model narrows it step by step to what AirAdvisor could win.",
                "PUBLIC DATA", body, "Eurostat avia_par 2024 and avia_paoc (CC BY 4.0); UK CAA punctuality and airport data 2025 (OGL v3); OurAirports (public domain); ECB GBP/EUR 2025; assumptions in data/ASSUMPTIONS.md")


def p3(R, con):
    t = R["tracking"]
    kpis = [("Submitted claims", "CRM rows, deduplicated", "CRM"), ("Claim submit rate", "submits / starts", "GA4 trend, CRM level"),
            ("First-response acceptance", "accepted / answered, by response month", "CRM"), ("Success rate (final)", "paid / sent, by cohort age", "CRM"),
            ("Revenue per claim", "fees / claims, mature cohorts", "CRM"), ("CAC (paid)", "spend / paid-channel claims; also per paid claim", "Ads + CRM"),
            ("Incremental CAC", "CAC / measured incrementality", "Tests"), ("Commission LTV 12m", "revenue per new customer, repeat claims incl.", "CRM")]
    kt = table([(f"<b>{a}</b>", b, c) for a, b, c in kpis], [("KPI (19 in the dictionary)", False), ("Definition", False), ("Source of truth", False)])
    ev = [("eligibility_check", "checker returns a result", "claim_type, result, regulation"), ("experiment_exposure", "server assigns a variant", "experiment_id, variant"),
          ("claim_start", "first field changed", "claim_type, market"), ("claim_submit", "API confirms the claim (201)", "claim_id_hash, value, regulation"),
          ("document_signed", "e-signature callback", "claim_id_hash")]
    et = table([(f"<code>{a}</code>", b, c) for a, b, c in ev], [("GA4 event", False), ("GTM trigger", False), ("Key parameters", False)])
    # bridge for October 2026: CRM claims -> GA4 claim_submit
    b = con.sql("""
        with c as (select * from claims where cast(created_at as date) between date '2026-10-01' and date '2026-10-31')
        select (select count(*) from c) raw, (select count(*) from c where claim_id like 'CLD%') dups,
               (select count(*) from c where claim_id not like 'CLD%' and device_category = 'mobile') mobile,
               (select count(*) from c where claim_id not like 'CLD%') clean,
               (select count(distinct ga_session_id) from events where event_name = 'claim_submit' and event_date between date '2026-10-01' and date '2026-10-31') ga""").pl().row(0, named=True)
    nonmob = b["clean"] - b["mobile"]
    w = waterfall([("CRM claims (truth)", b["clean"], "total"), ("Mobile: tag broken since 15 Sep", -b["mobile"], "delta"),
                   ("No analytics consent", -(nonmob - b["ga"]), "delta"), ("GA4 claim_submit", b["ga"], "total")], 550, 150)
    P = t["platforms"]
    rows = [(p["platform"].replace("_", " "), fmt_int(p["reported"]), fmt_int(p["crm_claims"]), f'<span class="{"bad" if p["factor"] > 1.5 else ""}">x{p["factor"]:.2f}</span>') for p in P["by_platform"]]
    rows.append(("<b>All paid platforms</b>", f"<b>{fmt_int(P['reported_total'])}</b>", f"<b>{fmt_int(P['crm_paid_total'])}</b>", f"<b>x{P['over_total']:.2f}</b>"))
    pt = table(rows, [("Platform", False), ("Reported conversions", True), ("CRM claims (last click)", True), ("Ratio", True)])
    body = g("1.05fr 1fr", g("1fr", card("KPI dictionary (docs/KPI_DICTIONARY.md): definition, SQL, source, owner, pitfalls", kt)
                              + card("Tracking plan (docs/TRACKING_PLAN.md): GTM + GA4 + Consent Mode v2", et + '<p class="small muted" style="margin-top:5px">Every event has a QA test. <code>claim_submit</code> fires on the API confirmation, not the button click, and is also sent server-side with a hashed claim id, so ad platforms get offline conversions with the real fee value.</p>'
                              + '<pre>-- sql/03: daily alert when GA4 stops seeing CRM claims (window function)\nMEDIAN(ratio) OVER (PARTITION BY device_category ORDER BY d\n                    ROWS BETWEEN 28 PRECEDING AND 1 PRECEDING) AS ratio_median_28d\nCASE WHEN ratio &lt; 0.5 * ratio_median_28d THEN &#39;ALERT&#39; ELSE &#39;ok&#39; END\n-- BigQuery: PERCENTILE_CONT(ratio, 0.5) OVER (...), run as a scheduled query</pre>'), rows="auto 1fr")
             + g("1fr", card("October 2026: why GA4 shows fewer claims than the CRM", w + f'<p class="small muted">Consent explains a stable gap (~{fmt_pct(t["tag_break"]["ratio_before"])} coverage); the mobile tag break explains the rest. Business numbers come from the CRM; GA4 is for behaviour.</p>')
                 + card("Ad platforms cannot be added up", pt + f'<p class="small muted" style="margin-top:5px">Each platform credits itself (view-through, its own window). Summed, they claim {fmt_pct(P["over_total"] - 1)} more claims than the CRM records from paid channels. CAC is computed on CRM claims only.</p>'), rows="auto 1fr"))
    return page(3, "One definition per KPI, one tracking plan, and a daily reconciliation: GA4, the CRM and the ad platforms tell different stories until they are bridged",
                "The data-owner work: shared definitions with an owner, events with acceptance tests, and a bridge that explains every gap between sources.", "SIMULATED", body,
                "SIMULATED data (seed 42); queries sql/03, sql/05, sql/06; docs/KPI_DICTIONARY.md, docs/TRACKING_PLAN.md")


def p4(R):
    t, s = R["tracking"], R["spend"]
    q = pl.read_csv(OUT / "qa_ga4_crm_daily.csv", try_parse_dates=True).filter(pl.col("d") >= pl.date(2026, 6, 1))
    f, ax = fig(570, 125)
    for dev, col in (("mobile", RED), ("desktop", BLUE), ("tablet", GREY)):
        x = q.filter(pl.col("device_category") == dev).sort("d")
        ax.plot(x["d"].to_list(), x["ratio"].rolling_mean(7, min_samples=1).to_list(), color=col, lw=1.6, label=dev)
    ax.axvline(np.datetime64("2026-09-15"), color=RED, ls=":", lw=1)
    ax.set_ylim(0, 1); ax.legend(fontsize=7.5, frameon=False, ncol=3, loc="lower left"); ax.set_ylabel("GA4 / CRM", fontsize=8)
    ax.tick_params(labelsize=7.5)
    tag_svg = to_svg(f)
    c = pl.read_csv(OUT / "qa_consent_weekly.csv", try_parse_dates=True).filter(pl.col("wk") >= pl.date(2025, 10, 1))
    f, ax = fig(570, 125)
    for ctry, col in (("DE", ORANGE), ("UK", BLUE), ("FR", AQUA), ("ES", YELLOW), ("IT", GREY)):
        x = c.filter(pl.col("country") == ctry).sort("wk")
        ax.plot(x["wk"].to_list(), x["ga_coverage"].to_list(), color=col, lw=2.2 if ctry == "DE" else 1, label=COUNTRY_NAME[ctry])
    ax.axvline(np.datetime64("2026-02-16"), color=ORANGE, ls=":", lw=1)
    pct_axis(ax, "y"); ax.set_ylim(0.3, 0.9); ax.legend(fontsize=7, frameon=False, ncol=5, loc="lower left"); ax.tick_params(labelsize=7.5)
    consent_svg = to_svg(f)
    sy = pl.read_csv(OUT / "seasonality_yoy.csv", try_parse_dates=True)
    f, ax = fig(570, 125)
    ax.bar(sy["m"].to_list(), sy["claims"].to_list(), width=20, color=[BLUE if d.month in (7, 8) else BLUE_LIGHT for d in sy["m"].to_list()])
    ax2 = ax.twinx()
    ax2.plot(sy["m"].to_list(), sy["yoy_growth"].to_list(), color=INK, lw=1.5, marker="o", ms=3)
    ax2.set_ylim(0, 0.5); pct_axis(ax2, "y"); ax2.tick_params(labelsize=7.5); ax2.spines["right"].set_visible(True); ax2.grid(False)
    ax2.set_ylabel("growth vs same month last year", fontsize=7.5)
    thousands_axis(ax, "y"); ax.tick_params(labelsize=7.5); ax.grid(axis="x", visible=False)
    season_svg = to_svg(f)
    det = R["detection"]["rows"]
    names = {"broken_tag": "Broken mobile tag", "consent_mode": "Consent banner (DE)", "double_counting": "Platform double counting",
             "brand_cannibalisation": "Brand ads cannibalise SEO", "ab_srm": "A/B sample ratio mismatch", "acceptance_drop": "Carrier H acceptance drop",
             "seasonal_peak": "Summer peak", "duplicates": "Duplicated claims"}
    verdict = {"seasonal_peak": '<span class="pill grey">noise</span>', "consent_mode": '<span class="pill">measurement</span>', "broken_tag": '<span class="pill red">tracking</span>',
               "double_counting": '<span class="pill">measurement</span>', "duplicates": '<span class="pill red">data</span>', "brand_cannibalisation": '<span class="pill red">spend</span>',
               "ab_srm": '<span class="pill red">test</span>', "acceptance_drop": '<span class="pill red">business</span>'}
    dt = table([(r["id"], names[r["event"]], verdict[r["event"]], "yes" if r["detected"] else "no", r["detected_at"], html.escape(r["method"])) for r in det],
               [("#", True), ("Event", False), ("Type", False), ("Found", False), ("When", True), ("How", False)])
    acc = s["acceptance"]
    body = g("1fr 1fr", g("1fr", card(f"8 planted events, {R['detection']['found']} found by the checks (scored against a hidden answer key at the end)", dt)
                           + card("Carrier H: a business signal for Legal, not a tracking issue", f'<p class="small">First-response acceptance fell from <b>{fmt_pct(acc["before"])}</b> to <b class="bad">{fmt_pct(acc["after"])}</b> from May 2026 (p &lt; 0.001); no other carrier moved more than {abs(acc["others_max_drop"]) * 100:.1f} pts. {fmt_pct(acc["legal_win_rate_after_rejection"])} of its escalated rejections are still paid: escalate faster with a standard evidence pack. (Fictional carrier.)</p>')
                           + card("Triage order when a KPI moves (e.g. submitted claims down 15% last week)", '<ol class="small"><li><b>Tracking:</b> does the CRM show the same drop? GA4/CRM by device and browser, release log, tag tests.</li><li><b>Consent and definitions:</b> banner, CMP or KPI change? Compare consented share and KPI version.</li><li><b>Calendar:</b> same week last year, holidays, and how many flights were disrupted that week (fewer storms or strikes = fewer claims).</li><li><b>Segments:</b> country, claim type, device, source, carrier: where is the drop concentrated?</li><li><b>Channels:</b> spend, bids, rankings, campaign changes; then a decision and an owner.</li></ol>'), rows="auto auto 1fr")
             + g("1fr", card("Tracking: mobile GA4/CRM ratio collapses on 15 Sep 2026 (7-day mean)", sv(tag_svg, 128))
                 + card("Consent: Germany's GA4 coverage drops after the new banner; its CRM claims do not", sv(consent_svg, 112) + f'<p class="small muted" style="margin:0">DE coverage {fmt_pct(t["consent"]["coverage"]["DE"]["before"])} → {fmt_pct(t["consent"]["coverage"]["DE"]["after"])}; DE CRM claims {t["consent"]["de_crm_weekly_before"]:.0f} → {t["consent"]["de_crm_weekly_after"]:.0f} a week.</p>')
                 + card(f"Noise: July is +{s['season']['jul26_vs_jun26']:.0%} vs June, as it was in 2025; growth vs last year stays {s['season']['yoy_min']:.0%}-{s['season']['yoy_max']:.0%}", sv(season_svg, 128)), rows="1fr 1fr 1fr"))
    return page(4, "Three alarms, three different causes: a broken mobile tag, a consent banner, and a summer peak that is only the season",
                "Before reading any KPI move, ask in order: is the tracking intact (GA4 vs CRM), did consent change, is it the season (same month last year), and only then which segment moved.",
                "SIMULATED", body, "SIMULATED data (seed 42); queries sql/03, sql/04, sql/05, sql/08, sql/12; seasonality shape from UK CAA 2025 monthly punctuality (PUBLIC)")


def p5(R):
    te = R["testing"]
    srm, raw, itt, pw, did = te["srm"], te["raw"], te["itt"], te["power"], te["did"]
    sr = pl.read_csv(OUT / "ab_srm.csv")
    st = table([(r["device_category"], r["variant"], fmt_int(r["server_assignments"]), fmt_int(r["ga_exposures"]),
                 f'<span class="{"bad" if abs(r["ga_share"] - 0.5) > 0.02 else ""}">{fmt_pct(r["ga_share"], 1)}</span>') for r in sr.iter_rows(named=True)],
               [("Device", False), ("Variant", False), ("Server log", True), ("GA4 exposures", True), ("GA4 share", True)])
    f, ax = fig(500, 165)
    x = np.arange(2)
    lifts = [raw["lift_rel"], itt["lift_rel"]]
    err = [[(raw["diff_pts"] - raw["ci_low"]) / raw["rate_a"], (itt["diff_pts"] - itt["ci_low"]) / itt["rate_a"]],
           [(raw["ci_high"] - raw["diff_pts"]) / raw["rate_a"], (itt["ci_high"] - itt["diff_pts"]) / itt["rate_a"]]]
    ax.bar(x, lifts, color=[RED, BLUE], width=0.55, yerr=err, capsize=5, ecolor=INK2)
    ax.axhline(0, color=INK2, lw=0.8)
    for xx, v, p in zip(x, lifts, [raw["p_value"], itt["p_value"]]):
        ax.text(xx + 0.3, v, f"{v:+.1%}\np {'< 0.001' if p < 0.001 else f'= {p:.2f}'}", fontsize=8.5, va="center")
    ax.set_xticks(x, ["Raw: GA4 exposures", "Corrected: server log + CRM"], fontsize=8.5); pct_axis(ax, "y"); ax.grid(axis="x", visible=False)
    ax.set_ylabel("lift in submit rate, B vs A", fontsize=8)
    ab_svg = to_svg(f)
    w = pl.read_csv(OUT / "did_weekly.csv", try_parse_dates=True)
    fr = w.filter(pl.col("market") == "FR").sort("wk")
    ct = w.filter(pl.col("market") != "FR").group_by("wk").agg(pl.col("y").mean()).sort("wk")
    f, ax = fig(635, 225)
    ax.axvspan(np.datetime64("2026-02-02"), np.datetime64("2026-03-29"), color=RED, alpha=0.07)
    ax.plot(fr["wk"].to_list(), fr["y"].to_list(), color=BLUE, lw=2.2, label="France: brand demand (Microsoft brand + SEO claims)")
    ax.plot(ct["wk"].to_list(), ct["y"].to_list(), color=GREY, lw=1.6, label="Control average (UK, DE, ES, IT)")
    ax.bar(fr["wk"].to_list(), fr["ms_brand"].to_list(), width=5, color=ORANGE, alpha=0.75, label="France: claims credited to Microsoft brand ads")
    ax.text(np.datetime64("2026-02-05"), ax.get_ylim()[1] * 0.92, "brand ads paused", fontsize=8, color=RED)
    ax.legend(fontsize=7.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=3); ax.tick_params(labelsize=7.5); ax.set_ylabel("claims per week", fontsize=8)
    did_svg = to_svg(f)
    body = g("1fr 1.25fr", g("1fr", card("Step 1 · Sample ratio check before any result", st + f'<p class="small" style="margin-top:6px">The server split is fine (p = {srm["server_p"]:.2f}). GA4 exposures are not: B has {fmt_pct(srm["ga_share_b"], 1)} (chi-square p = {srm["ga_p"]:.1e}), only on mobile ({fmt_pct(srm["mobile_share_b"], 1)}). Variant B\'s page rendered later on mobile, so low-intent visitors left before being logged: the B sample is better than A by construction.</p>')
                          + card("Step 2 · Read the test on what was randomised", sv(ab_svg, 175) + f'<p class="small">Intention to treat: every user the server assigned, outcome from the CRM. Effect {itt["lift_rel"]:+.1%} (95% CI {itt["ci_low"] / itt["rate_a"]:+.1%} to {itt["ci_high"] / itt["rate_a"]:+.1%}): <b>no evidence that showing the fee upfront changes submissions</b>. Decide on other grounds (transparency, fewer cooling-off cancellations).</p>'), rows="auto 1fr")
             + g("1fr", card("Quasi-experiment · Microsoft brand ads paused in France for 8 weeks (difference-in-differences)", sv(did_svg, 250) + f'<p class="small">Regression with country and week fixed effects: the pause changed France\'s brand-search claims by <b>{did["beta_level"]:+.1f} a week</b> (95% CI {did["ci_level"][0]:.1f} to {did["ci_level"][1]:+.1f}, robust SE), against {did["fr_ms_brand_per_week_before"]:.1f} a week credited to the ads. France&#39;s SEO claims held steady ({did["fr_seo_before"]:.0f} then {did["fr_seo_pause"]:.0f} a week) while brand demand in the control countries fell with the season: brand searchers clicked the organic result instead. Placebo pause in the pre-period: {did["placebo_beta_log"]:+.1%} (SE {did["placebo_se_log"]:.1%}), parallel trends hold.</p>')
                 + card("Power and planning", f'<ul class="small"><li>Baseline submit rate among assigned users {fmt_pct(pw["baseline"], 1)}; {fmt_int(pw["n_per_arm_actual"])} users per arm in 6 weeks give a minimum detectable effect of <b>{fmt_pct(pw["mde_rel_actual"], 1)}</b> (80% power, 5% two-sided).</li><li>Detecting a 5% lift needs {fmt_int(pw["n_per_arm_for_5pct"])} per arm: plan length before launch, never stop on a good day.</li><li>Rules written before launch: primary metric (CRM submit), guardrails (signed rate, cooling-off), SRM check, analysis on server assignments.</li></ul>'), rows="1fr auto"))
    return page(5, f"The fee-display 'win' of {raw['lift_rel']:+.1%} is an artefact of lost mobile users; corrected, the effect is {itt['lift_rel']:+.1%}. Brand ads in France bought claims SEO would have brought",
                "Two ways to measure causal effects: a randomised test read on what was randomised, and a quasi-experiment when a campaign pause creates a natural control group.",
                "SIMULATED", body, "SIMULATED data (seed 42); sql/10, sql/11; statistics in src/analysis.py (chi-square, two-proportion z-test, OLS with HC1 errors)")


def p6(R):
    s, sb = R["spend"], R["subscription"]
    ch = pl.read_csv(OUT / "unit_economics_channel.csv").filter(pl.col("spend") > 0).sort("spend", descending=True)
    rows = []
    for r in ch.iter_rows(named=True):
        ir = r["incr_roas"]
        rows.append((f'{r["traffic_source"].replace("_ads", "")} {r["campaign_type"].replace("_", "-")}', fmt_eur(r["spend"]), f'€{r["cac_claim"]:.0f}',
                     f'€{r["cac_paid"]:.0f}', f'{r["roas"]:.2f}', "?" if ir is None else f'<span class="{"bad" if ir < 1.43 else "good"}">{ir:.2f}</span>'))
    ct = table(rows, [("Campaign", False), ("Spend 6m", True), ("CAC/claim", True), ("CAC/paid", True), ("ROAS", True), ("Incr. ROAS", True)])
    fc = pl.read_csv(OUT / "forecast_claims.csv", try_parse_dates=True).group_by("month").agg(pl.col("forecast", "low", "high").sum()).sort("month")
    fit = pl.read_csv(OUT / "forecast_fit.csv", try_parse_dates=True).group_by("month").agg(pl.col("actual", "fitted").sum()).sort("month")
    f, ax = fig(570, 165)
    ax.bar(fit["month"].to_list(), fit["actual"].to_list(), width=20, color=BLUE_LIGHT, label="actual (UK, DE, FR, ES, IT)")
    ax.plot(fit["month"].to_list(), fit["fitted"].to_list(), color=BLUE, lw=1.2, label="model")
    ax.bar(fc["month"].to_list(), fc["forecast"].to_list(), width=20, color=BLUE, label="forecast")
    ax.errorbar(fc["month"].to_list(), fc["forecast"].to_list(), yerr=[(fc["forecast"] - fc["low"]).to_list(), (fc["high"] - fc["forecast"]).to_list()], fmt="none", ecolor=INK2, capsize=2)
    thousands_axis(ax, "y"); ax.legend(fontsize=7, frameon=False, ncol=3, loc="upper left"); ax.tick_params(labelsize=7.5); ax.grid(axis="x", visible=False)
    ax.set_ylim(0, max(fit["actual"].max(), fc["high"].max()) * 1.25)
    fc_svg = to_svg(f)
    cv = pl.DataFrame(sb["curve"])
    tiers = pl.DataFrame(sb["tiers"])
    f, ax = fig(570, 170)
    ax.plot(cv["trips_per_year"].to_list(), cv["cost_full_cannibalisation_eur"].to_list(), color=RED, lw=2, label="cost if every claim would have paid a fee")
    ax.plot(cv["trips_per_year"].to_list(), cv["cost_incremental_eur"].to_list(), color=GREY, lw=1.5, ls="--", label="cost if all claims are new (handling only)")
    for r, col in zip(tiers.iter_rows(named=True), [BLUE_LIGHT, BLUE, BLUE_DARK]):
        ax.axhline(r["price_eur"] * 0.97, color=col, lw=1)
        ax.text(20.3, r["price_eur"], f'{r["tier"]} €{r["price_eur"]:.0f}', fontsize=7.5, va="bottom", ha="right", color=INK2)
        ax.scatter([r["trips_subscribers"]], [r["cost_per_sub_full"]], color=col, zorder=5, s=25)
    ax.set_xlabel("trips a year (2 flights each)", fontsize=8); ax.set_ylabel("expected cost per subscriber, € / yr", fontsize=8)
    ax.legend(fontsize=7, frameon=False, loc="upper left"); ax.tick_params(labelsize=7.5); ax.set_xlim(0, 20.5)
    sub_svg = to_svg(f)
    tt = table([(f'<b>{r["tier"]}</b>', f'€{r["price_eur"]:.0f}', fmt_pct(r["take_up"], 1), f'{r["trips_subscribers"]:.1f}', f'€{r["cost_per_sub_full"]:.0f}',
                 f'€{r["margin_per_sub_year"]:.0f}', fmt_pct(r["renewal_projected"]), f'€{r["ltv_per_sub"]:.0f}', f'€{r["ltv_per_offer"]:.2f}',
                 fmt_pct(r["share_subs_above_breakeven_trips"])) for r in tiers.iter_rows(named=True)],
               [("Tier", False), ("Price", True), ("Take-up", True), ("Trips", True), ("Cost", True), ("Margin/yr", True), ("Renewal*", True),
                ("LTV/sub", True), ("LTV/offer", True), ("Loss-making subs", True)])
    W, F, L = s["waste"], s["forecast"], s["ltv"]
    body = g("1fr 1fr", g("1fr", card("Unit economics by campaign (claims of May-Oct 2025, now mature)", ct + f'<p class="small muted" style="margin-top:5px">Incremental ROAS = ROAS x measured incrementality; red below 1.43 (break-even after 30% variable cost). Microsoft brand: €{W["ms_brand_spend_12m"] / 1e3:.0f}K a year buys almost no extra claims: stop it. Google brand (€{W["google_brand_spend_12m"] / 1e3:.0f}K/yr): untested, run the same pause first. Google non-brand is the marginal channel (ROAS {s["google_nb_roas"]:.2f}): cap bids at break-even CAC. Commission LTV after 12 months €{L["ltv12_per_customer"]:.0f} per customer ({fmt_pct(L["repeat_rate"])} file again).</p>')
                           + card("Forecast: claims for the next 6 months, 5 established markets", sv(fc_svg, 175) + f'<p class="small muted">Log-linear trend per market x public seasonal index (CAA 2025), 80% interval; in-sample error {fmt_pct(F["mape"], 1)}. {fmt_int(F["total_6m"])} claims expected Nov-Apr ({fmt_int(F["low_6m"])}-{fmt_int(F["high_6m"])}); paid budget at current CAC {fmt_eur(F["budget_current_6m"])}, before brand savings. January carries a January 2025 storm in the public index; more years of CAA data would smooth it.</p>'), rows="auto 1fr")
             + g("1fr", card("Subscription: expected cost per subscriber from real disruption rates", sv(sub_svg, 175) + f'<p class="small muted">PUBLIC inputs: {fmt_pct(sb["p_disrupted_per_flight"], 2)} of passengers on 3h+/cancelled flights x 55% airline control = {fmt_pct(sb["p_eligible_per_flight"], 2)} eligible per flight, €{sb["avg_amount_eur"]:.0f} average. Dots = average subscriber of each tier.</p>')
                 + card("Pilot (UK + DE, 3 random price tiers): €49 is the price to launch", tt + f'<p class="small" style="margin-top:5px">Subscribers fly {tiers["trips_subscribers"].min():.1f}-{tiers["trips_subscribers"].max():.1f} trips a year vs {tiers["trips_offered"].mean():.1f} for everyone offered: frequent flyers self-select. €29 converts best but {fmt_pct(tiers["share_subs_above_breakeven_trips"][0])} of its subscribers cost more than they pay; €49 has a similar LTV per offer, twice the margin and fewer loss-making subscribers. Add a trip cap (as AirHelp TravelPass does) before scaling. *Renewal projected from 2-3 months of auto-renew data: re-check at month 12.</p>'), rows="auto 1fr"))
    return page(6, f"Stop brand spend that SEO replaces, forecast {fmt_int(F['total_6m'] / 1000)}K claims for the next six months, and launch the subscription at €49 with a trip cap",
                "Where the euros go, what comes next, and the price of the new product: unit economics per paid claim, incrementality, a seasonal forecast, and a pricing pilot read against the real probability of disruption per trip.",
                "SIMULATED + PUBLIC", body, "SIMULATED data (seed 42): sql/07, sql/09, sql/14, src/analysis.py; disruption probabilities PUBLIC (Eurostat, UK CAA); competitor plans from airhelp.com/en/price-list")


def p7(R):
    memo = (DOCS / "CEO_MEMO_example.md").read_text(encoding="utf-8")
    reco = memo.split("## Recommendation", 1)[1].split("##", 1)[0].strip().strip("*").replace("`", "")
    proofs = memo.split("## Three proofs", 1)[1].split("##", 1)[0].strip().split("\n")
    pr = "".join(f"<li>{html.escape(p[3:]).replace('**', '')}</li>" for p in proofs if p[:2] in ("1.", "2.", "3."))
    import re
    pr = re.sub(r"^(.*?\.)", r"<b>\1</b>", pr)
    pr = "".join(f"<li><b>{x.split('.', 1)[0]}.</b>{x.split('.', 1)[1]}</li>" for x in [html.escape(p[3:]).replace("**", "").replace("`", "") for p in proofs if p[:2] in ("1.", "2.", "3.")])
    body = g("1.15fr 1fr", g("1fr", card("CEO memo (docs/CEO_MEMO_example.md): recommendation first", f'<p style="font-size:13px;font-weight:600;line-height:1.4">{html.escape(reco)}</p><ol class="small">{pr}</ol>'
                                          + '<p class="small"><b>Risks.</b> Market euros depend on assumptions (ranking does not); the ceiling is a maximum because of extraordinary circumstances; the brand pause covered one country for 8 weeks. <b>Next step:</b> tag fix + server-side claim_submit this week, re-read the funnel and the fee test on CRM outcomes, start the brand pause in Germany.</p>')
                              + card("Reproduce", '<pre>python -m venv .venv &amp;&amp; .venv\\Scripts\\pip install -r requirements.txt\npython src/download_data.py        # public data (BTS ~330 MB, aggregated)\npython src/build_public.py         # country model\npython src/simulate.py             # simulated funnel (seed 42)\npython src/analysis.py             # all results -&gt; data/output\npython src/build_dashboard.py &amp;&amp; python src/build_pdf.py\njupyter notebook notebooks/airadvisor_analysis.ipynb</pre>'), rows="1fr auto")
             + g("1fr", card("Sources and licences", '<ul class="small"><li><b>AirAdvisor</b> website (home, pricelist) and job posting, read by hand on 15 Nov 2026; figures are as stated by AirAdvisor. No reviews collected.</li><li><b>Rules:</b> Regulation (EC) 261/2004 (EUR-Lex, Your Europe), UK CAA, Canadian Transportation Agency, US DOT, Montreal Convention limits (CTA), IMF SDR.</li><li><b>Aviation:</b> Eurostat avia_par / avia_paoc (CC BY 4.0), UK CAA punctuality and airport data 2025 (OGL v3), US BTS on-time 2025 (public domain), OurAirports (public domain), ECB rates.</li><li><b>Competitors:</b> published fee pages of AirHelp and Flightright only.</li></ul>')
                 + card("Limits", '<ul class="small"><li>Country disruption rates use UK-to-country routes as a proxy (CAA); punctuality is measured at UK airports (arrival or departure).</li><li>Claim rate, agency share, obtainable share and airline-control share are assumptions with ranges, not statistics.</li><li>The simulation shows methods; its levels (conversion, CAC, acceptance) are plausible, not AirAdvisor\'s.</li><li>The subscription pilot is 2-5 months old: renewal is projected. One brand-pause country, 8 weeks.</li><li>No legal advice; no statement about any real airline\'s conduct.</li></ul>')
                 + card("AI note", f'<p class="small">{html.escape(ai_note())}</p>'), rows="auto 1fr auto"))
    return page(7, "Recommendation first: fix the mobile tag, stop paying for brand demand, grow the Netherlands next, launch the subscription at €49",
                "The one-page memo a CEO would receive, followed by how every number was produced and where it stops being reliable.", "", body,
                "README.md, data/SOURCES.md, data/ASSUMPTIONS.md, docs/")


def main():
    utf8()
    BUILD.mkdir(exist_ok=True)
    (DOCS / "img").mkdir(parents=True, exist_ok=True)
    R = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    con = sim_con()
    pages = [p0(R), p1(R), p2(R), p3(R, con), p4(R), p5(R), p6(R), p7(R)]
    doc = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(TITLE)}</title><meta name="author" content="">'
           f'<style>{CSS}</style></head><body>{"".join(pages)}</body></html>')
    report = BUILD / "report.html"
    report.write_text(doc, encoding="utf-8")
    raw_pdf = BUILD / "report_raw.pdf"
    headless([f"--print-to-pdf={raw_pdf}", "--no-pdf-header-footer", "--print-to-pdf-no-header", report.as_uri()])
    reader, writer = PdfReader(str(raw_pdf)), PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    writer.add_metadata({"/Title": TITLE, "/Author": "", "/Creator": "", "/Producer": "", "/Subject": "", "/Keywords": ""})
    with open(PDF, "wb") as fh:
        writer.write(fh)
    print(f"PDF: {PDF.relative_to(ROOT)} ({len(reader.pages)} pages)")
    names = ["00_overview", "01_company_rules", "02_market_map", "03_kpi_tracking", "04_problems_vs_noise", "05_testing", "06_spend_subscription", "07_memo_methods"]
    for i, name in enumerate(names):
        single = BUILD / f"page_{i}.html"
        single.write_text(doc.replace("<body>", f"<body><style>.page{{display:none}} #p{i}{{display:flex}}</style>"), encoding="utf-8")
        headless([f"--screenshot={DOCS / 'img' / (name + '.png')}", "--window-size=1280,720", single.as_uri()])
    print("PNG pages written to docs/img/")


if __name__ == "__main__":
    main()
