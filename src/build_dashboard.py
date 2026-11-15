"""Build dashboard/insights_cockpit.html: one self-contained file (Plotly.js inline), 4 tabs, filters.

Tabs: Business pulse · Funnel & experiments · Data health · Market opportunity (PUBLIC DATA).
Filters (country, claim type, device) re-draw the charts in the browser from small pre-aggregated cubes,
the same shape a Looker Studio report would read from BigQuery views.
Usage:  python src/build_dashboard.py   (after src/analysis.py)
"""
import json

from plotly.offline import get_plotlyjs

from common import (AQUA, BG, BLUE, BLUE_LIGHT, BORDER, CARD, COUNTRY_NAME, DISCLAIMER, GREY, INK, INK2, MUTED, ORANGE,
                    RED, ROOT, YELLOW, sim_con, utf8)
from analysis import OUT

DASH = ROOT / "dashboard" / "insights_cockpit.html"


def rows(con, sql):
    df = con.sql(sql).pl()
    out = []
    for r in df.iter_rows(named=True):
        out.append({k: (str(v) if hasattr(v, "isoformat") else (float(v) if v.__class__.__name__ == "Decimal" else v)) for k, v in r.items()})
    return out


def cubes(con):
    c = {}
    c["claims"] = rows(con, """
        select strftime(date_trunc('month', created_at), '%Y-%m') m, market, claim_type, device_category dev,
               count(*) claims, sum(case when status = 'paid' then 1 else 0 end) paid, sum(revenue_eur) revenue,
               sum(amount_due_eur) due, sum(case when first_response = 'accepted' then 1 else 0 end) acc,
               sum(case when first_response is not null then 1 else 0 end) resp,
               sum(case when traffic_source in ('google_ads','meta_ads','microsoft_ads') then 1 else 0 end) paid_channel
        from claims where claim_id not like 'CLD%' group by all order by 1""")
    c["claims_type_month"] = rows(con, """
        select strftime(date_trunc('month', created_at), '%Y-%m') m, market, claim_type, device_category dev, carrier,
               sum(case when first_response = 'accepted' then 1 else 0 end) acc, sum(case when first_response is not null then 1 else 0 end) resp
        from claims where claim_id not like 'CLD%' and airline_response_at is not null group by all""")
    c["spend"] = rows(con, """select strftime(date_trunc('month', date), '%Y-%m') m, country market, platform, campaign_type,
               sum(spend_eur) spend, sum(platform_conversions) reported from ad_spend group by all order by 1""")
    c["funnel"] = rows(con, """
        select strftime(date_trunc('month', event_date), '%Y-%m') m, country market, device_category dev, coalesce(claim_type, 'all') claim_type,
               event_name e, count(distinct ga_session_id) n
        from events where event_name <> 'experiment_exposure' group by all""")
    c["qa_daily"] = rows(con, """
        with ga as (select event_date d, country market, device_category dev, count(distinct ga_session_id) ga from events where event_name = 'claim_submit' group by all),
             crm as (select cast(created_at as date) d, market, device_category dev, count(*) crm from claims where claim_id not like 'CLD%' group by all)
        select strftime(crm.d, '%Y-%m-%d') d, crm.market, crm.dev, crm, coalesce(ga, 0) ga from crm left join ga using (d, market, dev) order by 1""")
    c["platform"] = rows(con, """
        with p as (select strftime(date_trunc('month', date), '%Y-%m') m, country market, platform, sum(platform_conversions) reported from ad_spend group by all),
             k as (select strftime(date_trunc('month', created_at), '%Y-%m') m, market, traffic_source platform, count(*) crm from claims
                   where claim_id not like 'CLD%' and traffic_source in ('google_ads','meta_ads','microsoft_ads') group by all)
        select p.*, coalesce(crm, 0) crm from p left join k using (m, market, platform) order by 1""")
    c["dups"] = rows(con, """select strftime(cast(created_at as date), '%Y-%m-%d') d, market, count(*) n from claims where claim_id like 'CLD%' group by all""")
    return c


def static(results):
    import polars as pl
    s = {}
    s["market"] = pl.read_csv(OUT / "market_ranking.csv").select(
        "rank", "country", "country_name", "regime", "departing_pax", "p_late3", "p_cancel", "avg_amount_eur", "ceiling_eur",
        "tam_eur", "sam_eur", "som_eur", "som_claims", "breakeven_cac_eur", "growth_2019_2024", "long_haul_pax_share", "tier").to_dicts()
    s["sens"] = pl.read_csv(ROOT / "data" / "public" / "market_sensitivity.csv").to_dicts()
    s["stability"] = pl.read_csv(ROOT / "data" / "public" / "rank_stability.csv").to_dicts()
    s["srm"] = pl.read_csv(OUT / "ab_srm.csv").to_dicts()
    s["did"] = pl.read_csv(OUT / "did_weekly.csv").with_columns(pl.col("wk").cast(pl.Utf8)).to_dicts()
    s["detection"] = pl.read_csv(OUT / "detection_scorecard.csv").to_dicts()
    s["acc_change"] = pl.read_csv(OUT / "acceptance_change_by_carrier.csv").to_dicts()
    s["forecast"] = pl.read_csv(OUT / "forecast_claims.csv").to_dicts()
    s["fit"] = pl.read_csv(OUT / "forecast_fit.csv").to_dicts()
    s["tiers"] = pl.read_csv(OUT / "subscription_tiers.csv").to_dicts()
    s["channels"] = pl.read_csv(OUT / "unit_economics_channel.csv").to_dicts()
    s["r"] = {"raw": results["testing"]["raw"], "itt": results["testing"]["itt"], "power": results["testing"]["power"],
              "srm": results["testing"]["srm"], "did": results["testing"]["did"], "ltv": results["spend"]["ltv"],
              "market": {k: v for k, v in results["market"].items() if not isinstance(v, list)}}
    return s


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AirAdvisor insights cockpit</title><meta name="author" content="">
<style>
:root{--ink:%(INK)s;--ink2:%(INK2)s;--muted:%(MUTED)s;--bg:%(BG)s;--card:%(CARD)s;--border:%(BORDER)s;--blue:%(BLUE)s;--red:%(RED)s}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Segoe UI",system-ui,sans-serif}
.wrap{max-width:1400px;margin:0 auto;padding:18px 16px}
header{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-start}
h1{font-size:23px;margin:0 0 4px}.sub{color:var(--ink2);margin:0;font-size:13.5px;max-width:880px}
.tag{font-size:11px;font-weight:700;letter-spacing:.07em;color:var(--ink2);white-space:nowrap}
nav{display:flex;gap:8px;margin:14px 0 10px;flex-wrap:wrap}
nav button{font:inherit;font-size:14px;padding:7px 14px;border:1px solid var(--border);background:var(--card);border-radius:20px;cursor:pointer;color:var(--ink2)}
nav button.on{background:var(--blue);border-color:var(--blue);color:#fff}
.filters{display:flex;gap:12px;flex-wrap:wrap;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px 12px;margin-bottom:12px;font-size:13px;color:var(--ink2)}
.filters select{font:inherit;font-size:13px;padding:3px 6px;border:1px solid var(--border);border-radius:5px;background:#fff}
.tab{display:none}.tab.on{display:block}
.tabtag{font-size:11px;font-weight:700;letter-spacing:.07em;color:var(--ink2);margin:0 0 8px}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:12px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 12px}
.kpi .l{font-size:11px;color:var(--ink2);font-weight:600;letter-spacing:.03em}.kpi .v{font-size:24px;font-weight:700;margin-top:2px}.kpi .s{font-size:11.5px;color:var(--muted)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.span2{grid-column:span 2}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:10px 12px;min-width:0;overflow-x:auto}
.card h3{font-size:14px;margin:4px 2px 6px}.card p{font-size:12.5px;color:var(--ink2);margin:2px 2px 8px;line-height:1.45}
.chart{height:330px}
table{border-collapse:collapse;width:100%%;font-size:12.5px}th{text-align:left;color:var(--ink2);border-bottom:1px solid var(--ink2);padding:5px 6px;white-space:nowrap}
td{border-bottom:1px solid var(--border);padding:4px 6px}td.n{text-align:right}.bad{color:var(--red);font-weight:600}.good{color:var(--blue);font-weight:600}
.pill{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;background:#EAF2FC;color:var(--blue);font-weight:600}
.pill.red{background:#FBEAEA;color:var(--red)}
footer{color:var(--muted);font-size:11px;margin:16px 0}
@media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}.span2{grid-column:span 1}}
</style><script>%(PLOTLY)s</script></head><body><div class="wrap">
<header><div><h1>AirAdvisor insights cockpit</h1>
<p class="sub">Claims, funnel, tracking health and market opportunity in one place. Business tabs use a SIMULATED claim funnel (seed 42, May 2025 to Oct 2026, scaled down, not AirAdvisor data); the market tab uses PUBLIC DATA. Same model ready for Looker Studio on BigQuery.</p></div>
<div class="tag">SIMULATED + PUBLIC DATA</div></header>
<nav><button data-t="pulse">Business pulse</button><button data-t="funnel">Funnel &amp; experiments</button><button data-t="health">Data health</button><button data-t="market">Market opportunity</button></nav>
<div class="filters" id="filters">Filters:
 <label>Country <select id="f_market"><option value="all">All</option></select></label>
 <label>Claim type <select id="f_type"><option value="all">All</option><option>delay</option><option>cancellation</option><option>denied_boarding</option><option>baggage</option></select></label>
 <label>Device <select id="f_dev"><option value="all">All</option><option>mobile</option><option>desktop</option><option>tablet</option></select></label>
 <span id="f_note" style="color:var(--muted)"></span></div>

<section class="tab" id="pulse"><p class="tabtag">SIMULATED</p>
 <div class="kpis" id="kpis"></div>
 <div class="grid2">
  <div class="card"><h3>Claims per month, by country</h3><div id="c_claims" class="chart"></div></div>
  <div class="card"><h3>Revenue booked per month (paid claims x fee)</h3><p>Revenue lags claims by 2-10 months: the last months are not final.</p><div id="c_rev" class="chart" style="height:300px"></div></div>
  <div class="card"><h3>First-response acceptance by month</h3><p>Share of airline first answers that accept the claim. Mature months only are comparable.</p><div id="c_acc" class="chart" style="height:300px"></div></div>
  <div class="card"><h3>Claims by type and country (period)</h3><div id="c_type" class="chart"></div></div>
  <div class="card span2"><h3>Unit economics by channel (claims created May-Oct 2025, mature)</h3><p>CAC per <b>paid</b> claim, not per submitted claim. Brand campaigns adjusted by the measured incrementality (Funnel &amp; experiments tab).</p><div id="t_channels"></div></div>
 </div></section>

<section class="tab" id="funnel"><p class="tabtag">SIMULATED</p>
 <div class="grid2">
  <div class="card"><h3>Funnel by step (GA4, consented sessions)</h3><p>Before the mobile tag break (15 Sep 2026). Filters apply.</p><div id="c_funnel" class="chart"></div></div>
  <div class="card"><h3>Step conversion by device</h3><div id="c_funnel_dev" class="chart"></div></div>
  <div class="card"><h3>Fee-display A/B test: sample ratio check</h3><p id="p_srm"></p><div id="t_srm"></div></div>
  <div class="card"><h3>Raw read vs corrected read</h3><div id="c_ab" class="chart" style="height:300px"></div><p id="p_ab"></p></div>
  <div class="card span2"><h3>Quasi-experiment: Microsoft brand ads paused in France (2 Feb to 29 Mar 2026)</h3><p id="p_did"></p><div id="c_did" class="chart"></div></div>
 </div></section>

<section class="tab" id="health"><p class="tabtag">SIMULATED</p>
 <div class="grid2">
  <div class="card span2"><h3>GA4 claim_submit vs CRM claims, daily ratio by device</h3><p>Healthy ratio = consent rate (~0.6-0.75). A collapse on one device is a tracking problem, not a business problem.</p><div id="c_ratio" class="chart"></div></div>
  <div class="card"><h3>Weekly GA4 coverage of CRM claims by country (desktop + tablet)</h3><p>Germany drops after the new consent banner (16 Feb 2026) while its CRM claims stay flat.</p><div id="c_consent" class="chart"></div></div>
  <div class="card"><h3>Ad platforms report more conversions than the CRM records</h3><div id="c_platform" class="chart"></div></div>
  <div class="card"><h3>Acceptance change by carrier (last 6 months vs 6 months before)</h3><div id="c_carrier" class="chart"></div></div>
  <div class="card"><h3>Alert log: the 8 checks and what they found</h3><div id="t_detect"></div></div>
 </div></section>

<section class="tab" id="market"><p class="tabtag">PUBLIC DATA</p>
 <div class="kpis" id="mkpis"></div>
 <div class="grid2">
  <div class="card"><h3>Obtainable revenue (SOM) by country, EUR per year</h3><p>Tile map: one square per country, colour = SOM. Filters do not apply (public data).</p><div id="c_tiles" class="chart" style="height:400px"></div></div>
  <div class="card"><h3>From theoretical ceiling to SOM, top 10 countries</h3><div id="c_funnel_m" class="chart" style="height:400px"></div></div>
  <div class="card"><h3>Sensitivity: total SOM when one assumption moves</h3><div id="c_tornado" class="chart"></div></div>
  <div class="card"><h3>Ranking and robustness</h3><div id="t_rank" style="max-height:330px;overflow-y:auto;font-size:11.5px"></div></div>
 </div></section>
<footer>SIMULATED: claims, sessions, spend, carriers ("Carrier A-L" are fictional) and results are invented to show methods; they are not AirAdvisor data.
PUBLIC DATA: Eurostat avia_par (2024), UK CAA punctuality and airport statistics (2025), US BTS on-time (2025), OurAirports, ECB; EU261/UK261 amounts from official pages.
The ceiling is a theoretical maximum: extraordinary circumstances remove the right to compensation. %(DISCLAIMER)s</footer>
</div>
<script>
const D = %(DATA)s;
const C = {ink:"%(INK)s",ink2:"%(INK2)s",muted:"%(MUTED)s",border:"%(BORDER)s",card:"%(CARD)s",blue:"%(BLUE)s",blueL:"%(BLUE_LIGHT)s",grey:"%(GREY)s",red:"%(RED)s",orange:"%(ORANGE)s",aqua:"%(AQUA)s",yellow:"%(YELLOW)s"};
const MK = {UK:C.blue,DE:C.orange,FR:C.aqua,ES:C.yellow,IT:"#7B5EA7",NL:C.red};
const NAMES = %(NAMES)s;
const L = (extra) => Object.assign({margin:{l:50,r:20,t:10,b:40},paper_bgcolor:C.card,plot_bgcolor:C.card,font:{family:"Segoe UI, system-ui",size:12,color:C.ink2},
  xaxis:{gridcolor:C.border,linecolor:C.border},yaxis:{gridcolor:C.border,linecolor:C.border},legend:{orientation:"h",y:-0.18},hoverlabel:{font:{size:12}}}, extra||{});
const CFG = {displaylogo:false,responsive:true};
const fmt = (v,d=0) => v==null||isNaN(v) ? "-" : Number(v).toLocaleString("en-GB",{maximumFractionDigits:d,minimumFractionDigits:d});
const eur = v => v>=1e9? "€"+fmt(v/1e9,2)+"bn" : v>=1e6? "€"+fmt(v/1e6,1)+"M" : v>=1e3? "€"+fmt(v/1e3,0)+"K" : "€"+fmt(v,0);
const pct = (v,d=0) => v==null? "-" : fmt(100*v,d)+"%%";
const F = () => ({m:document.getElementById("f_market").value,t:document.getElementById("f_type").value,d:document.getElementById("f_dev").value});
const keep = (r,f,useType=true) => (f.m==="all"||r.market===f.m) && (f.d==="all"||r.dev===f.d) && (!useType||f.t==="all"||r.claim_type===f.t);
const sum = (a,k) => a.reduce((s,r)=>s+(+r[k]||0),0);
function group(a, key, val){const o={}; a.forEach(r=>{o[r[key]]=(o[r[key]]||0)+(+r[val]||0)}); return o;}
const months = [...new Set(D.claims.map(r=>r.m))].sort();
["UK","DE","FR","ES","IT","NL"].forEach(m=>{const o=document.createElement("option");o.value=m;o.textContent=NAMES[m];document.getElementById("f_market").appendChild(o)});

function pulse(){
  const f=F(), cl=D.claims.filter(r=>keep(r,f));
  const sp=D.spend.filter(r=>f.m==="all"||r.market===f.m);
  const mature=cl.filter(r=>r.m<="2025-10");
  const k=[["Claims (18 months)",fmt(sum(cl,"claims")),"submitted, duplicates removed"],
    ["Paid to date",fmt(sum(cl,"paid")),pct(sum(mature,"paid")/sum(mature,"claims"))+" of mature claims (May-Oct 2025)"],
    ["Revenue to date",eur(sum(cl,"revenue")),"fees on paid claims"],
    ["First-response acceptance",pct(sum(cl,"acc")/sum(cl,"resp")),"accepted / answered"],
    ["Paid CAC per claim",(f.t==="all"&&f.d==="all")? "€"+fmt(sum(sp,"spend")/sum(cl,"paid_channel")):"-","spend / claims from paid channels"],
    ["12-month LTV",(f.m==="all"&&f.t==="all"&&f.d==="all")? "€"+fmt(D.s.r.ltv.ltv12_per_customer):"-","revenue per customer, oldest cohorts"]];
  document.getElementById("kpis").innerHTML=k.map(x=>`<div class="kpi"><div class="l">${x[0]}</div><div class="v">${x[1]}</div><div class="s">${x[2]}</div></div>`).join("");
  const mk=[...new Set(cl.map(r=>r.market))].sort();
  Plotly.react("c_claims", mk.map(m=>{const g=group(cl.filter(r=>r.market===m),"m","claims");return {type:"bar",name:NAMES[m],x:months,y:months.map(x=>g[x]||0),marker:{color:MK[m]}}}), L({barmode:"stack"}), CFG);
  const gr=group(cl,"m","revenue");
  Plotly.react("c_rev",[{type:"bar",x:months,y:months.map(x=>gr[x]||0),marker:{color:months.map(x=>x>"2026-04"?C.blueL:C.blue)},hovertemplate:"%%{x}<br>€%%{y:,.0f}<extra></extra>"}],L({yaxis:{gridcolor:C.border,tickprefix:"€"}}),CFG);
  const ca=D.claims_type_month.filter(r=>keep(r,f));
  const tr=[...new Set(ca.map(r=>r.carrier))].sort();
  const ga=group(ca,"m","acc"), gn=group(ca,"m","resp");
  const tH=ca.filter(r=>r.carrier==="Carrier H"), hA=group(tH,"m","acc"), hN=group(tH,"m","resp");
  const ms=months.filter(x=>gn[x]>20);
  Plotly.react("c_acc",[{name:"All carriers",x:ms,y:ms.map(x=>ga[x]/gn[x]),line:{color:C.blue}},{name:"Carrier H (fictional)",x:ms,y:ms.map(x=>hN[x]>=20?hA[x]/hN[x]:null),line:{color:C.red,dash:"dot"}}],L({yaxis:{gridcolor:C.border,tickformat:".0%%",range:[0,0.9]}}),CFG);
  const types=["delay","cancellation","denied_boarding","baggage"];
  Plotly.react("c_type", types.map((t,i)=>{const g=group(cl.filter(r=>r.claim_type===t),"market","claims");return {type:"bar",name:t,x:mk.map(m=>NAMES[m]),y:mk.map(m=>g[m]||0),marker:{color:[C.blue,C.orange,C.aqua,C.grey][i]}}}), L({barmode:"stack"}), CFG);
  const ch=D.s.channels.filter(r=>r.spend>0||true);
  document.getElementById("t_channels").innerHTML="<table><thead><tr><th>Channel</th><th>Campaign</th><th>Claims</th><th>Paid</th><th>Spend</th><th>CAC / claim</th><th>CAC / paid claim</th><th>ROAS</th><th>Incrementality</th><th>Incremental ROAS</th><th>Source</th></tr></thead><tbody>"+
   ch.map(r=>`<tr><td>${r.traffic_source}</td><td>${r.campaign_type}</td><td class="n">${fmt(r.claims)}</td><td class="n">${fmt(r.paid)}</td><td class="n">${r.spend?eur(r.spend):"-"}</td><td class="n">${r.spend?"€"+fmt(r.cac_claim):"-"}</td><td class="n">${r.spend?"€"+fmt(r.cac_paid):"-"}</td><td class="n">${r.spend?fmt(r.roas,2):"-"}</td><td class="n">${r.incrementality==null?"?":pct(r.incrementality)}</td><td class="n ${r.incr_roas!=null&&r.incr_roas<1.43?"bad":""}">${r.incr_roas==null?"?":fmt(r.incr_roas,2)}</td><td style="font-size:11.5px;color:var(--ink2)">${r.incr_source||""}</td></tr>`).join("")+"</tbody></table><p style='margin-top:6px'>Red: incremental ROAS below 1.43, i.e. below break-even after a 30%% variable cost. Brand incrementality comes from the France pause; non-brand channels are assumed fully incremental until tested.</p>";
}

function funnel(){
  const f=F(), pre=D.funnel.filter(r=>r.m<"2026-09");
  const step=(e)=>sum(pre.filter(r=>r.e===e && (f.m==="all"||r.market===f.m) && (f.d==="all"||r.dev===f.d) && (e==="session_start"||f.t==="all"||r.claim_type===f.t)),"n");
  const names=["session_start","eligibility_check","claim_start","claim_submit","document_signed"], v=names.map(step);
  Plotly.react("c_funnel",[{type:"funnel",y:["Sessions","Eligibility check","Claim started","Claim submitted","Documents signed"],x:v,texttemplate:"%%{value:,.0f}<br>%%{percentPrevious:.0%%}",textinfo:"none",marker:{color:[C.grey,C.blueL,C.blueL,C.blue,C.blue]}}],L({margin:{l:120,r:20,t:10,b:20}}),CFG);
  const devs=["mobile","desktop","tablet"];
  const st=(e,d)=>sum(pre.filter(r=>r.e===e&&r.dev===d&&(f.m==="all"||r.market===f.m)&&(e==="session_start"||f.t==="all"||r.claim_type===f.t)),"n");
  const lab=["check / session","start / check","submit / start","signed / submit"];
  Plotly.react("c_funnel_dev",devs.map((d,i)=>({type:"bar",name:d,x:lab,y:[st("eligibility_check",d)/st("session_start",d),st("claim_start",d)/st("eligibility_check",d),st("claim_submit",d)/st("claim_start",d),st("document_signed",d)/st("claim_submit",d)],marker:{color:[C.blue,C.grey,C.aqua][i]}})),L({barmode:"group",yaxis:{gridcolor:C.border,tickformat:".0%%"}}),CFG);
  const s=D.s.r.srm;
  document.getElementById("p_srm").innerHTML=`Server split ${fmt(s.server_a)} / ${fmt(s.server_b)} (p = ${fmt(s.server_p,2)}): fine. GA4 exposures ${fmt(s.ga_a)} / ${fmt(s.ga_b)}: B gets ${pct(s.ga_share_b,1)} instead of 50%%, chi-square p = ${s.ga_p.toExponential(1)} → <span class="bad">sample ratio mismatch</span>, concentrated on mobile (B share ${pct(s.mobile_share_b,1)}).`;
  document.getElementById("t_srm").innerHTML="<table><thead><tr><th>Device</th><th>Variant</th><th>Server assignments</th><th>GA4 exposures</th><th>GA4 share</th></tr></thead><tbody>"+D.s.srm.map(r=>`<tr><td>${r.device_category}</td><td>${r.variant}</td><td class="n">${fmt(r.server_assignments)}</td><td class="n">${fmt(r.ga_exposures)}</td><td class="n ${Math.abs(r.ga_share-0.5)>0.02?"bad":""}">${pct(r.ga_share,1)}</td></tr>`).join("")+"</tbody></table>";
  const raw=D.s.r.raw, itt=D.s.r.itt;
  Plotly.react("c_ab",[{type:"bar",x:["Raw (GA4 exposures)","Corrected (server assignment, CRM)"],y:[raw.lift_rel,itt.lift_rel],marker:{color:[C.red,C.blue]},
    error_y:{type:"data",array:[(raw.ci_high-raw.diff_pts)/raw.rate_a,(itt.ci_high-itt.diff_pts)/itt.rate_a],arrayminus:[(raw.diff_pts-raw.ci_low)/raw.rate_a,(itt.diff_pts-itt.ci_low)/itt.rate_a],color:C.ink2},
    text:[pct(raw.lift_rel,1)+" (p "+(raw.p_value<0.001?"<0.001":fmt(raw.p_value,3))+")",pct(itt.lift_rel,1)+" (p "+fmt(itt.p_value,2)+")"],textposition:"outside"}],L({yaxis:{gridcolor:C.border,tickformat:".0%%",title:"relative lift in submit rate, B vs A"}}),CFG);
  document.getElementById("p_ab").innerHTML=`Raw GA4 read says B wins by ${pct(raw.lift_rel,1)}. Counting every user the server assigned and reading the outcome in the CRM, the effect is ${pct(itt.lift_rel,1)} (95%% CI ${pct(itt.ci_low/itt.rate_a,1)} to ${pct(itt.ci_high/itt.rate_a,1)}). Minimum detectable effect with ${fmt(D.s.r.power.n_per_arm_actual)} users per arm: ${pct(D.s.r.power.mde_rel_actual,1)}.`;
  const did=D.s.did, dd=D.s.r.did; const wk=[...new Set(did.map(r=>r.wk))].sort();
  const avg=(arr)=>arr.reduce((a,b)=>a+b,0)/arr.length;
  const fr=wk.map(w=>did.filter(r=>r.wk===w&&r.market==="FR").map(r=>r.y)[0]);
  const ct=wk.map(w=>avg(did.filter(r=>r.wk===w&&r.market!=="FR").map(r=>r.y)));
  const frms=wk.map(w=>did.filter(r=>r.wk===w&&r.market==="FR").map(r=>r.ms_brand)[0]);
  Plotly.react("c_did",[{name:"France: brand demand (Microsoft brand + SEO claims)",x:wk,y:fr,line:{color:C.blue,width:3}},{name:"Control average (UK, DE, ES, IT)",x:wk,y:ct,line:{color:C.grey,width:2}},{name:"France: Microsoft brand claims",x:wk,y:frms,type:"bar",marker:{color:C.orange},opacity:0.7}],
    L({shapes:[{type:"rect",x0:"2026-02-02",x1:"2026-03-23",y0:0,y1:1,yref:"paper",fillcolor:C.red,opacity:0.07,line:{width:0}}],yaxis:{gridcolor:C.border,title:"claims per week"}}),CFG);
  document.getElementById("p_did").innerHTML=`Weekly claims arriving through brand searches. When the brand ads stopped (shaded), France's total did not fall more than the control countries: difference-in-differences ${fmt(dd.beta_level,1)} claims/week (95%% CI ${fmt(dd.ci_level[0],1)} to ${fmt(dd.ci_level[1],1)}), against ${fmt(dd.fr_ms_brand_per_week_before,1)} claims/week the brand ads were credited with. Most brand-ad claims would have come through SEO anyway.`;
}

function health(){
  const f=F(), q=D.qa_daily.filter(r=>f.m==="all"||r.market===f.m);
  const days=[...new Set(q.map(r=>r.d))].sort();
  const roll=(arr,n=7)=>arr.map((_,i)=>{const s=arr.slice(Math.max(0,i-n+1),i+1).filter(x=>x!=null);return s.length?s.reduce((a,b)=>a+b,0)/s.length:null});
  Plotly.react("c_ratio",["mobile","desktop","tablet"].filter(d=>f.d==="all"||f.d===d).map((d,i)=>{const g=q.filter(r=>r.dev===d),a=group(g,"d","ga"),c=group(g,"d","crm");return {name:d,x:days,y:roll(days.map(x=>c[x]?a[x]/c[x]:null)),line:{color:[C.red,C.blue,C.grey][["mobile","desktop","tablet"].indexOf(d)]}}}),
    L({yaxis:{gridcolor:C.border,range:[0,1],title:"GA4 / CRM (7-day mean)"},shapes:[{type:"line",x0:"2026-09-15",x1:"2026-09-15",y0:0,y1:1,yref:"paper",line:{color:C.red,dash:"dot"}},{type:"line",x0:"2026-02-16",x1:"2026-02-16",y0:0,y1:1,yref:"paper",line:{color:C.orange,dash:"dot"}}],
      annotations:[{x:"2026-09-15",y:0.95,yref:"paper",text:"release: mobile claim_submit lost",showarrow:false,xanchor:"right",font:{color:C.red,size:11}},{x:"2026-02-16",y:0.08,yref:"paper",text:"DE consent banner",showarrow:false,xanchor:"left",font:{color:C.orange,size:11}}]}),CFG);
  const wkq={};q.filter(r=>r.dev!=="mobile").forEach(r=>{const dt=new Date(r.d);const day=(dt.getUTCDay()+6)%%7;dt.setUTCDate(dt.getUTCDate()-day);const w=dt.toISOString().slice(0,10);const k=r.market+"|"+w;wkq[k]=wkq[k]||{ga:0,crm:0};wkq[k].ga+=r.ga;wkq[k].crm+=r.crm});
  const ws=[...new Set(Object.keys(wkq).map(k=>k.split("|")[1]))].sort();
  Plotly.react("c_consent",["UK","DE","FR","ES","IT","NL"].filter(m=>f.m==="all"||f.m===m).map(m=>({name:NAMES[m],x:ws,y:ws.map(w=>wkq[m+"|"+w]&&wkq[m+"|"+w].crm>5?wkq[m+"|"+w].ga/wkq[m+"|"+w].crm:null),line:{color:MK[m],width:m==="DE"?3:1.5}})),L({yaxis:{gridcolor:C.border,tickformat:".0%%",range:[0.3,0.9]}}),CFG);
  const p=D.platform.filter(r=>f.m==="all"||r.market===f.m);
  const pl=["google_ads","meta_ads","microsoft_ads"];
  Plotly.react("c_platform",[{type:"bar",name:"Reported by the platform",x:pl,y:pl.map(x=>sum(p.filter(r=>r.platform===x),"reported")),marker:{color:C.orange}},{type:"bar",name:"CRM claims (last click, UTM)",x:pl,y:pl.map(x=>sum(p.filter(r=>r.platform===x),"crm")),marker:{color:C.blue}}],L({barmode:"group"}),CFG);
  const a=D.s.acc_change.slice().sort((x,y)=>x.change_pts-y.change_pts);
  Plotly.react("c_carrier",[{type:"bar",orientation:"h",y:a.map(r=>r.carrier),x:a.map(r=>r.change_pts),marker:{color:a.map(r=>r.change_pts<-0.1?C.red:C.grey)},text:a.map(r=>(r.change_pts>0?"+":"")+fmt(100*r.change_pts,1)+" pts"),textposition:"auto",hovertemplate:"%%{y}<br>%%{x:.1%%}<extra></extra>"}],L({margin:{l:80,r:50,t:10,b:30},xaxis:{gridcolor:C.border,tickformat:".0%%"}}),CFG);
  document.getElementById("t_detect").innerHTML="<table><thead><tr><th>#</th><th>Check</th><th>Found</th><th>When</th><th>How</th></tr></thead><tbody>"+D.s.detection.map(r=>`<tr><td>${r.id}</td><td>${r.event.replace(/_/g," ")}</td><td>${r.detected?'<span class="pill">yes</span>':'<span class="pill red">no</span>'}</td><td>${r.detected_at}</td><td style="font-size:11.5px">${r.method}</td></tr>`).join("")+"</tbody></table>";
}

function market(){
  const m=D.s.market, r=D.s.r.market;
  const k=[["Theoretical ceiling",eur(r.ceiling_eur),"owed if every 3h+/cancelled passenger were eligible and claimed"],["TAM (agency revenue)",eur(r.tam_eur),"x airline-controlled share x 30%% fee"],["SAM",eur(r.sam_eur),"x claim rate x agency share x payout"],["SOM",eur(r.som_eur),"x obtainable share (12%%)"],["Disrupted passengers",fmt(r.disrupted_pax/1e6,1)+"M",pct(r.disrupted_share,2)+" of "+fmt(r.departing_pax/1e6,0)+"M departures"],["Average amount",eur(r.avg_amount_eur),"per disrupted passenger (route distance)"]];
  document.getElementById("mkpis").innerHTML=k.map(x=>`<div class="kpi"><div class="l">${x[0]}</div><div class="v">${x[1]}</div><div class="s">${x[2]}</div></div>`).join("");
  const pos={IS:[0,0],NO:[3,0],SE:[4,0],FI:[5,0],EE:[6,1],LV:[6,2],LT:[6,3],UK:[1,2],IE:[0,2],DK:[3,1],NL:[2,3],BE:[2,4],LU:[3,4],DE:[3,3],PL:[5,3],CZ:[4,4],SK:[5,4],FR:[2,5],CH:[3,5],AT:[4,5],HU:[5,5],RO:[6,5],SI:[4,6],HR:[5,6],BG:[6,6],PT:[0,6],ES:[1,6],IT:[3,6],MT:[3,7],EL:[6,7],CY:[7,7]};
  const pts=m.filter(x=>pos[x.country]);
  Plotly.react("c_tiles",[{type:"scatter",mode:"markers+text",x:pts.map(x=>pos[x.country][0]),y:pts.map(x=>-pos[x.country][1]),text:pts.map(x=>x.country),textfont:{color:"#fff",size:12},
    marker:{symbol:"square",size:44,color:pts.map(x=>Math.log10(x.som_eur)),colorscale:[[0,"#D6E6F8"],[1,C.blue]],line:{color:"#fff",width:1}},customdata:pts.map(x=>[x.country_name,eur(x.som_eur),x.rank,eur(x.ceiling_eur),pct(x.p_late3,2),pct(x.p_cancel,2)]),
    hovertemplate:"<b>%%{customdata[0]}</b> (rank %%{customdata[2]})<br>SOM %%{customdata[1]} / year<br>ceiling %%{customdata[3]}<br>3h+ late %%{customdata[4]}, cancelled %%{customdata[5]}<extra></extra>"}],
    L({xaxis:{visible:false,range:[-0.7,7.7]},yaxis:{visible:false,range:[-7.7,0.7]},margin:{l:5,r:5,t:5,b:5}}),CFG);
  const t=m.slice(0,10);
  Plotly.react("c_funnel_m",[["Ceiling","ceiling_eur",C.grey],["TAM","tam_eur",C.blueL],["SAM","sam_eur",C.blue],["SOM","som_eur","#104281"]].map(([n,k,c])=>({type:"bar",name:n,y:t.map(x=>x.country_name),x:t.map(x=>x[k]),orientation:"h",marker:{color:c}})),
    L({barmode:"group",xaxis:{type:"log",gridcolor:C.border,title:"EUR per year (log scale)"},yaxis:{autorange:"reversed"},margin:{l:100,r:20,t:10,b:40}}),CFG);
  const s=D.s.sens; const names=[...new Set(s.map(x=>x.assumption))]; const c0=s[0].central_eur;
  const lo=names.map(n=>s.find(x=>x.assumption===n&&x.case==="low").som_total_eur), hi=names.map(n=>s.find(x=>x.assumption===n&&x.case==="high").som_total_eur);
  const order=names.map((n,i)=>[n,lo[i],hi[i]]).sort((a,b)=>(a[2]-a[1])-(b[2]-b[1]));
  Plotly.react("c_tornado",[{type:"bar",orientation:"h",name:"low",y:order.map(x=>x[0].replace(/_/g," ")),x:order.map(x=>x[1]-c0),base:c0,marker:{color:C.grey}},{type:"bar",orientation:"h",name:"high",y:order.map(x=>x[0].replace(/_/g," ")),x:order.map(x=>x[2]-c0),base:c0,marker:{color:C.blue}}],
    L({barmode:"overlay",margin:{l:150,r:20,t:10,b:40},xaxis:{gridcolor:C.border,title:"total SOM, EUR per year"},shapes:[{type:"line",x0:c0,x1:c0,y0:0,y1:1,yref:"paper",line:{color:C.ink}}]}),CFG);
  const st={};D.s.stability.forEach(x=>st[x.country]=x);
  document.getElementById("t_rank").innerHTML="<table><thead><tr><th>#</th><th>Country</th><th>Departures</th><th>3h+ late</th><th>Cancelled</th><th>Ceiling</th><th>SOM / yr</th><th>Break-even CAC</th><th>Rank range</th><th>Tier</th></tr></thead><tbody>"+
   m.map(x=>{const s=st[x.country];const rr=s?[s.central,s.no_shrinkage,s.arrivals_only,s.departures_only,s.all_low]:[x.rank];return `<tr><td>${x.rank}</td><td style="white-space:nowrap">${x.country_name}</td><td class="n">${fmt(x.departing_pax/1e6,1)}M</td><td class="n">${pct(x.p_late3,2)}</td><td class="n">${pct(x.p_cancel,2)}</td><td class="n">${eur(x.ceiling_eur)}</td><td class="n"><b>${eur(x.som_eur)}</b></td><td class="n">€${fmt(x.breakeven_cac_eur)}</td><td class="n">${Math.min(...rr)}-${Math.max(...rr)}</td><td>${x.tier}</td></tr>`}).join("")+"</tbody></table>";
}

const btns=[...document.querySelectorAll("nav button")], tabs=[...document.querySelectorAll(".tab")];
const draw={pulse,funnel,health,market};
function show(id){btns.forEach(b=>b.classList.toggle("on",b.dataset.t===id));tabs.forEach(t=>t.classList.toggle("on",t.id===id));
  document.getElementById("f_note").textContent=id==="market"?"(public data: filters not applied)":"";draw[id]();try{history.replaceState(null,"","#"+id)}catch(e){}}
btns.forEach(b=>b.addEventListener("click",()=>show(b.dataset.t)));
["f_market","f_type","f_dev"].forEach(i=>document.getElementById(i).addEventListener("change",()=>{const on=document.querySelector(".tab.on");draw[on.id]()}));
show((location.hash||"#pulse").slice(1) in draw ? (location.hash||"#pulse").slice(1) : "pulse");
</script></body></html>"""


def main():
    utf8()
    results = json.loads((OUT / "results.json").read_text(encoding="utf-8"))
    con = sim_con()
    data = cubes(con)
    data["s"] = static(results)
    page = PAGE % dict(INK=INK, INK2=INK2, MUTED=MUTED, BG=BG, CARD=CARD, BORDER=BORDER, BLUE=BLUE, BLUE_LIGHT=BLUE_LIGHT,
                       GREY=GREY, RED=RED, ORANGE=ORANGE, AQUA=AQUA, YELLOW=YELLOW, PLOTLY=get_plotlyjs(), DISCLAIMER=DISCLAIMER,
                       DATA=json.dumps(data, separators=(",", ":"), default=str), NAMES=json.dumps(COUNTRY_NAME))
    DASH.parent.mkdir(exist_ok=True)
    DASH.write_text(page, encoding="utf-8")
    print(f"{DASH.relative_to(ROOT)} written ({len(page) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
