"""Turn a Claude Design export (one bundled .html) into the app/ folder the pipeline feeds.

    python tools/unpack_design.py path/to/Roomtone_Dashboard.html

Writes app/index.html plus app/assets/* (React, d3, fonts, the world map) and applies three small
patches so the app reads real data from app/rt.js instead of its built-in prototype tables:
  1. per-source datasets come from RT.sources (the app's own merge still combines them)
  2. sub-topics and example posts come from the dataset's `subs`
  3. the world map loads from the local asset instead of a CDN
Re-run after every re-export from Claude Design.
"""
import base64, gzip, json, re, sys, zlib
from pathlib import Path

EXT = {"application/javascript": ".js", "text/javascript": ".js", "application/json": ".json", "font/woff2": ".woff2",
       "text/css": ".css", "image/png": ".png", "image/svg+xml": ".svg"}


def block(s, t):
    m = re.search(r'<script type="__bundler/' + t + r'">', s)
    st = m.end(); en = s.find("</script>", st)
    return s[st:en]


def main(path, out=Path("app")):
    s = Path(path).read_text()
    tpl, man, ext = json.loads(block(s, "template")), json.loads(block(s, "manifest")), json.loads(block(s, "ext_resources"))
    names = {e["uuid"]: e["id"] for e in ext}
    assets = out / "assets"; assets.mkdir(parents=True, exist_ok=True)
    for uuid, v in man.items():
        raw = base64.b64decode(v["data"])
        if v.get("compressed"):
            try: raw = gzip.decompress(raw)
            except Exception: raw = zlib.decompress(raw)
        nice = names.get(uuid, "")
        if nice.startswith("http"):
            fname = nice.rsplit("/", 1)[-1]
        elif nice == "landJson":
            fname = "land-110m.json"
        else:
            fname = uuid[:8] + EXT.get(v["mime"], "")
        if raw.startswith(b"window.RT="):
            tpl = re.sub(r'<script src="' + uuid + r'"></script>\n?', "", tpl)  # prototype data: replaced by rt.js
            continue
        (assets / fname).write_bytes(raw)
        tpl = tpl.replace(uuid, "assets/" + fname)
    # rt.js is the live data: load it before the app runtime; __resources maps CDN urls to local copies
    resmap = {nice: "assets/" + nice.rsplit("/", 1)[-1] for nice in names.values() if nice.startswith("http")}
    resmap["landJson"] = "assets/land-110m.json"
    if (assets / "babel.min.js").exists():  # optional offline copy: npm pack @babel/standalone@7.29.0
        resmap["https://unpkg.com/@babel/standalone@7.29.0/babel.min.js"] = "assets/babel.min.js"
    tpl = tpl.replace("<head>", "<head>\n<title>Roomtone</title>\n<script>window.__resources=" + json.dumps(resmap) + ";</script>\n<script src=\"rt.js\"></script>", 1)
    # --- patches to the app script -------------------------------------------------------------
    m = re.search(r'<script type="text/x-dc"[^>]*>', tpl); st = m.end(); en = tpl.find("</script>", st)
    app = tpl[st:en]
    app, n1 = re.subn(r'const d=k==="all"\?mergeSources\(base,SOURCES\.map\(S=>this\.data\(S\.key\)\)\):makeSource\(base,SOURCES\.find\(S=>S\.key===k\)\);',
        'const RS=base.sources||{};SOURCES.forEach(S=>{const r=RS[S.key];if(r){S.live=!!r.live;S.method=r.method||S.method;S.collected=r.collected||S.collected;S.langs=r.langs||S.langs;}});'
        'const d=k==="all"?mergeSources(base,SOURCES.map(S=>this.data(S.key))):(RS[k]?RS[k]:makeSource(base,SOURCES.find(S=>S.key===k)));', app)
    app = app.replace('curS.name.toUpperCase()+(curS.live?"":" · PROTOTYPE")', 'curS.name.toUpperCase()+(curS.live?"":curS.practice?" · PRACTICE":" · PROTOTYPE")')
    app = app.replace('"Prototype · modelled from the Bluesky run to show the filter, not collected"', '(curS.practice?"Practice stream · collected and scored by the same pipeline, not real accounts yet":"Prototype · modelled from the Bluesky run to show the filter, not collected")')
    app = app.replace('S.langs=r.langs||S.langs;}', 'S.langs=r.langs||S.langs;S.practice=!!r.practice;}')
    app = app.replace('status:S.live?"Live":"Prototype"', 'status:S.live?"Live":(S.practice?"Practice":"Prototype")')
    app = app.replace('stColor:S.live?"#1f6e43":"#b8461b"', 'stColor:S.live?"#1f6e43":(S.practice?"#1d5aa6":"#b8461b")')
    app = app.replace('stBorder:S.live?"rgba(47,154,95,.35)":"rgba(235,104,52,.5)"', 'stBorder:S.live?"rgba(47,154,95,.35)":(S.practice?"rgba(42,120,214,.4)":"rgba(235,104,52,.5)")')
    app = app.replace('].slice(0,8).map((c,i)=>({...c,n:String(i+1).padStart(2,"0")}));', ',...((RT.extra_changes||[]).map(t=>({rule:"cross-source",text:t})))].slice(0,8).map((c,i)=>({...c,n:String(i+1).padStart(2,"0")}));')
    # thin or early live data: never show "1 in Infinity"; say what is missing instead
    app = app.replace('function pct(v,dp){return (v*100).toFixed(dp==null?0:dp)+"%";}', 'function pct(v,dp){return (v==null||!isFinite(v))?"–":(v*100).toFixed(dp==null?0:dp)+"%";}')
    app = app.replace('one_in:Math.round(1/wb)', 'one_in:(wb>0?Math.round(1/wb):0)')
    app = app.replace('const prevOneIn=Math.round(1/RT.prev_wb)', 'const prevOneIn=(RT.prev_wb>0?Math.round(1/RT.prev_wb):0)')
    app = app.replace('oneIn:hd.one_in,', 'oneIn:(hd.one_in>0&&isFinite(hd.one_in)?hd.one_in:"?"),')
    app = app.replace('deltaText:`${down?"↓":"↑"} from 1 in ${prevOneIn} yesterday · ${pct(RT.prev_wb,1)} → ${pct(hd.wasted_breath_last_24h,1)}`', 'deltaText:(hd.human_engagements_last_24h>0&&RT.prev_wb>0?`${down?"↓":"↑"} from 1 in ${prevOneIn} yesterday · ${pct(RT.prev_wb,1)} → ${pct(hd.wasted_breath_last_24h,1)}`:"collecting · not enough data yet")')
    app, n2 = re.subn(r'const S=SUBS\[s\.topic\]\|\|\[\]', 'const S=(RT.subs&&RT.subs[s.topic]&&RT.subs[s.topic].length?RT.subs[s.topic]:SUBS[s.topic])||[]', app)
    app, n3 = re.subn(r'\(window\.__resources&&window\.__resources\.landJson\)\|\|"https://cdn\.jsdelivr\.net/npm/world-atlas@2/land-110m\.json"', '"assets/land-110m.json"', app)
    app = app.replace("PROTOTYPE SPLIT · NOT IN RESULTS.JSON YET", "SPLIT FROM RESULTS.JSON")
    tpl = tpl[:st] + app + tpl[en:]
    tpl = tpl.replace("Only Bluesky is collected today (practice stream). Mastodon, Reddit and YouTube are modelled from the Bluesky run to prototype the filter.", "Every source runs through the same collector, privacy gate and score. A source marked Practice is a simulated stream; Live means collected from the platform.")
    tpl = tpl.replace("Prototype split · not in results.json yet", "Split from results.json").replace("color:#b8461b;border:1px solid rgba(235,104,52,.45);padding:5px 8px;border-radius:6px;white-space:nowrap\">Split", "color:#1d5aa6;border:1px solid rgba(42,120,214,.4);padding:5px 8px;border-radius:6px;white-space:nowrap\">Split")
    tpl = tpl.replace("</body>", '<script src="float.js"></script>\n</body>')  # floating gallery of redacted example posts
    (out / "index.html").write_text(tpl)
    print(f"wrote {out}/index.html and {len(list(assets.iterdir()))} assets; patches applied: sources={n1} subs={n2} map={n3}")


if __name__ == "__main__":
    main(sys.argv[1])
