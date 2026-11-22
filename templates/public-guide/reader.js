(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("guide-data").textContent);
  const main = document.getElementById("main");
  const search = document.getElementById("query");
  const storeKey = "bof-atelier.public-guide.v1";
  const session = {bof3: {}, bof4: {}};
  let prefs = {};
  try {
    const saved = JSON.parse(localStorage.getItem(storeKey) || "{}");
    if (saved && typeof saved === "object" && !Array.isArray(saved)) prefs = saved;
  } catch { /* Browsers can disable file-origin storage. Reading stays available. */ }
  let game, page, params, book, volume, state, rows, lookup, prefsAvailable = true;
  let entered = false;
  const escape = value => String(value ?? "").replace(/[&<>"']/g, ch =>
    ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"})[ch]);
  const normal = text => String(text).normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase();
  function savePrefs() {
    try { localStorage.setItem(storeKey, JSON.stringify(prefs)); }
    catch { prefsAvailable = false; }
  }
  function href(id = "", options = {}) {
    const query = new URLSearchParams(options).toString();
    return "#" + game + (id ? "/" + encodeURIComponent(id) : "") + (query ? "?" + query : "");
  }
  function anchor(id, label, cls = "", options = {}) {
    return '<a class="' + cls + '" href="' + escape(href(id,options)) + '">' + escape(label) + '</a>';
  }
  function action(id, label, attrs = "") {
    return '<button type="button" class="plain-action" data-action="' + id + '" ' + attrs + '>' + escape(label) + '</button>';
  }
  function plate(art, cls = "") {
    const id = /^[a-z0-9-]+$/.test(art) ? art : volume.theme;
    return '<span class="plate '+cls+'" aria-hidden="true" style="--painting:var(--art-'+id+')"></span>';
  }
  function corePages() {
    const common = volume.article;
    const result = [{id:common.id,title:common.title,lead:common.intro,category:"Field notes",art:volume.theme,
      sections:common.sections.map(([title,text]) => ({title,text}))}];
    if (game === "bof3") {
      result.push({id:"genes",title:volume.toolTitle,lead:volume.toolNote,art:"flame",category:"Dragon genes"});
      specimens.forEach(s => result.push({id:s.id,title:s.name,category:"Dragon genes",lead:s.shape,
        art:s.id,links:["genes"],sections:[{title:"Initial AP",text:String(s.ap)}]}));
    } else {
      result.push({id:"masters",title:volume.toolTitle,lead:volume.toolNote,art:"iv-training",category:"Masters"},
        {id:"rwolf",title:"Rwolf",lead:"Master growth per level",art:"iv-training",category:"Masters",links:["masters"]});
    }
    return result;
  }
  function readState() {
    const [path, query = ""] = location.hash.slice(1).split("?",2);
    const [volumeId, entry] = path.split("/");
    game = volumeId === "bof4" ? "bof4" : "bof3";
    page = (entry === "index" || entry === "guide" ? "" : entry || "");
    if (volumeId && !["bof3","bof4"].includes(volumeId)) page = "missing";
    params = new URLSearchParams(query);
    book = data[game];
    volume = volumes[game === "bof3" ? "iii" : "iv"];
    state = session[game];
    const saved = prefs[game];
    const existing = saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
    if (!Array.isArray(existing.pins)) existing.pins = [];
    if (!Number.isInteger(existing.through) || existing.through < 0 || existing.through >= book.route.length) existing.through = 1;
    prefs[game] = existing;
    rows = [...book.route,...corePages(),...book.articles];
    lookup = new Map(rows.map(row => [row.id,row]));
    if (!state.genes) state.genes = [];
  }
  function unlocked(row) {
    const pos = book.route.findIndex(stop => stop.id === (row.unlock || row.id));
    return pos <= prefs[game].through;
  }
  function textSearch(row) {
    const records = [...(row.items || []), ...(row.encounters || []), ...(row.records || [])];
    return normal([row.title,row.category,row.region,row.lead,...(row.landmarks || []),
      ...(row.steps || []),...(row.sections || []).map(s=>s.title+" "+s.text),
      ...records.map(r=>r.name+" "+r.where+" "+r.detail)].filter(Boolean).join(" "));
  }
  function rowLink(row, note = "", idx = 0, thumbnail = false) {
    const graphic = thumbnail ? plate(row.art,"miniature") :
      idx ? '<span class="number">'+String(idx).padStart(2,"0")+'</span>' : "";
    return '<a class="row-link" href="'+escape(href(row.id))+'">'+graphic+'<span><span class="name">'+
      escape(row.title)+'</span>'+(note ? '<span class="desc">'+escape(note)+'</span>' : "")+
      '</span><span class="arrow" aria-hidden="true">↗</span></a>';
  }
  function crumb(section, current) {
    return '<nav class="crumb" aria-label="Breadcrumb">'+anchor("",volume.title)+' / <span>'+
      (current ? anchor(section === "Walkthrough" ? "walk" : "wiki",section) : escape(section))+'</span></nav>';
  }
  function head(title,lead="") {
    return '<header class="page-head"><h1>'+escape(title)+'</h1>'+(lead?'<p class="lead">'+escape(lead)+'</p>':"")+'</header>';
  }
  function folio(row, section, label, lead) {
    return crumb(section,true)+'<header class="folio"><div class="head-copy"><p class="eyebrow">'+escape(label)+
      '</p><h1>'+escape(row.title)+'</h1>'+(lead?'<p class="lead">'+escape(lead)+'</p>':"")+'</div>'+plate(row.art)+'</header>';
  }
  function home() {
    const tool = lookup.get(volume.tool);
    const feature = (row,note) => '<a class="feature" href="'+escape(href(row.id))+'">'+plate(row.art)+
      '<span><strong>'+escape(row.title)+'</strong><small>'+escape(note)+'</small></span></a>';
    const lead = game === "bof3" ? "Trace Ryu’s journey from Dauna Mine. Find the next landmark, a hidden item or a dragon recipe." :
      "Follow the trail from the sandflier wreck. Find a route, learn an enemy skill or compare a master’s lessons.";
    return '<section class="cover">'+plate(volume.theme,"cover-art")+'<div class="cover-copy"><div class="eyebrow">'+
      'PlayStation · US edition</div><h1>'+escape(volume.title)+'</h1><p>'+lead+'</p><div class="actions">'+
      anchor("walk","Open walkthrough","cta")+anchor("wiki","Browse field wiki","plain-action")+'</div></div></section>'+
      '<div class="home-grid"><section><div class="section-head"><h2>Opening route</h2>'+anchor("walk","All "+book.route.length+" stops","text-link")+'</div>'+
      book.route.slice(0,2).map((r,i)=>rowLink(r,r.region,i+1,true)).join("")+'</section><section><div class="section-head">'+
      '<h2>Field notes</h2>'+anchor("wiki","All "+book.articles.length+" wiki pages","text-link")+'</div>'+
      feature(tool,volume.toolNote)+feature(lookup.get(volume.article.id),game==="bof3"?"Ordinary saves and returning to a file":"Transformation and evocation")+'</section></div>';
  }
  function routeIndex() {
    const limit = prefs[game].through;
    const visible = state.routes ? book.route : book.route.slice(0,limit+1);
    let region = "";
    let html = "";
    for (const [i,row] of visible.entries()) {
      if (region !== row.region) {
        if (region) html += '</div>';
        region = row.region;
        html += '<div class="list-group"><h2>'+escape(region)+'</h2>';
      }
      html += rowLink(row,"",i+1);
    }
    if (region) html += '</div>';
    return crumb("Walkthrough")+head("Walkthrough",book.route.length+" stops, in story order.")+
      '<div class="collection">'+html+(limit < book.route.length-1 ? action("routes",state.routes?"Hide later stops":"Show later stops",
      'aria-expanded="'+Boolean(state.routes)+'"') : "")+'</div>';
  }
  function wikiIndex() {
    const subjects = [...new Set(book.articles.map(r=>r.category))];
    const category = params.get("subject") || "";
    const current = subjects.includes(category) ? category : "";
    const groups = current ? [current] : subjects;
    let html = crumb("Field wiki")+head("Field wiki","Browse by subject or search for a place, item or enemy.")+
      '<div class="collection"><label class="select-label" for="subject">Subject</label><select id="subject"><option value="">All subjects</option>'+
      subjects.map(c=>'<option '+(c===current?"selected ":"")+'value="'+escape(c)+'">'+escape(c)+'</option>').join("")+'</select>';
    if (!current) html += '<section class="list-group"><h2>Quick reference</h2>'+
      corePages().filter(r=>r.id===volume.tool || r.id===volume.article.id).map(r=>rowLink(r,r.lead)).join("")+'</section>';
    for (const group of groups) {
      const members = book.articles.filter(r=>r.category===group);
      const shown = state["group:"+group];
      html += '<section class="list-group" data-subject="'+escape(group)+'"><h2>'+escape(group)+'</h2>'+
        members.filter(r=>shown || unlocked(r)).map(r=>rowLink(r)).join("");
      if (members.some(r=>!unlocked(r))) html += action("group",shown?"Hide later articles":"Show later articles",
        'data-group="'+escape(group)+'" aria-expanded="'+Boolean(shown)+'"');
      html += '</section>';
    }
    return html+'</div>';
  }
  function bibliography(row) {
    const list = (row.sources || []).map(id=>book.sources[id]).filter(Boolean);
    if (!list.length) return "";
    function sourceLink(source) {
      try {
        const url = new URL(source.url);
        if (url.protocol === "https:" && !url.username && !url.password) {
          return '<a href="'+escape(url.href)+'" rel="noreferrer">'+escape(source.title)+'</a>';
        }
      } catch { /* Printed and title-only sources have no web destination. */ }
      return escape(source.title);
    }
    return '<details><summary>Sources</summary><ul class="notes">'+list.map(s=>'<li>'+sourceLink(s)+'</li>').join("")+'</ul></details>';
  }
  function controls(row,isStop) {
    const pinned = prefs[game].pins.includes(row.id);
    const boundary = prefs[game].through === book.route.indexOf(row);
    return '<div class="tools-row">'+action("pin",pinned?"Bookmarked":"Bookmark page",'aria-pressed="'+pinned+'"')+
      (isStop ? action("boundary",boundary?"Current spoiler boundary":"Set spoiler boundary here",'aria-pressed="'+boundary+'"') : "")+'</div>'+
      (!prefsAvailable ? '<p class="fact">Your browser keeps these choices for this session.</p>' : "");
  }
  function related(row) {
    const list = (row.links || []).map(id=>lookup.get(id)).filter(r=>r && unlocked(r));
    return !list.length ? "" : '<section><h2>Related pages</h2><div class="tags">'+list.map(r=>anchor(r.id,r.title)).join("")+'</div></section>';
  }
  function recordsTable(records, category) {
    if (!records?.length) return "";
    return '<div class="table-wrap"><table class="table"><caption>'+escape(category)+'</caption>'+
      '<thead><tr><th scope="col">Name</th><th scope="col">Where</th><th scope="col">'+
      (category==="Items"?"How to find it":"Field notes")+'</th></tr></thead><tbody>'+
      records.map(r=>'<tr><td>'+escape(r.name)+'</td><td>'+escape(r.where)+'</td><td>'+escape(r.detail)+'</td></tr>').join("")+'</tbody></table></div>';
  }
  function diagram(map) {
    const lines = map.paths.map(([from,to])=>{
      const p = map.points[from], q = map.points[to];
      const dx = q.x - p.x, dy = (q.y-p.y)/1.66;
      return '<i class="line" style="left:'+Number(p.x)+'%;top:'+Number(p.y)+'%;width:'+Math.hypot(dx,dy)+
        '%;transform:rotate('+Math.atan2(dy,dx)+'rad)"></i>';
    });
    const points = map.points.map((p,i)=>'<b style="left:'+Number(p.x)+'%;top:'+Number(p.y)+'%">'+(i+1)+'</b>');
    return '<details><summary>Route diagram · '+escape(map.title)+'</summary><div class="diagram" aria-hidden="true">'+
      lines.join("")+points.join("")+'</div><ol class="legend">'+map.points.map(p=>'<li>'+escape(p.name)+
      '<span>'+escape(p.note)+'</span></li>').join("")+'</ol></details>';
  }
  function floorKey(floors) {
    if (!floors.length) return "";
    const selected = Number(params.get("floor"));
    const idx = Number.isInteger(selected) && selected >= 0 && selected < floors.length ? selected : 0;
    const floor = floors[idx];
    return '<section><h2>Floor landmarks</h2><label class="select-label" for="floor">Floor</label><select id="floor">'+
      floors.map((f,i)=>'<option value="'+i+'" '+(i===idx?"selected":"")+'>'+escape(f.name)+'</option>').join("")+'</select>'+
      (floor.landmarks?.length ? '<ol class="legend">'+floor.landmarks.map(p=>'<li>'+escape(p.name)+'</li>').join("")+'</ol>' :
      '<p class="fact">This floor has no numbered landmarks.</p>')+
      '<p class="fact">The Windows app draws the floor plan from your imported US disc.</p></section>';
  }
  function walkthrough(row) {
    const areas = row.sectionsByArea || [];
    const area = areas.find(s=>s.name===params.get("area")) || areas[0];
    const n = book.route.indexOf(row);
    const start = area?.firstStep ?? 0, end = area?.endStep ?? row.steps.length;
    const direction = i => '<li><strong>'+escape(row.landmarks[i])+'</strong>'+escape(row.steps[i])+'</li>';
    const inArea = r=>!area || r.where.toLowerCase().includes(area.name.toLowerCase());
    const choice = areas.length ? '<nav class="tabs" aria-label="Area">'+areas.map(a=>
      '<a href="'+escape(href(row.id,{area:a.name}))+'" aria-current="'+(area===a)+'">'+escape(a.name)+'</a>').join("")+'</nav>' : "";
    const warning = row.warning && (!area || area.warning) ? '<aside class="warning"><strong>'+
      escape(row.warning.label)+'</strong>'+escape(row.warning.text)+'</aside>' : "";
    const routeDiagram = row.map && (!area || area===areas[0]) ? diagram(row.map) : "";
    const next=book.route[n+1], prior=book.route[n-1];
    return folio(row,"Walkthrough",row.region+" · Stop "+(n+1)+" of "+book.route.length,area?.lead || row.lead)+choice+
      '<div class="reading-grid"><div class="prose">'+warning+'<section><h2>Directions</h2><ol class="steps">'+direction(start)+'</ol></section>'+
      '<details><summary>Give me a hint</summary><p>'+escape(area?.hint || row.hint)+'</p></details>'+
      (end>start+1?'<details><summary>Show full route</summary><ol class="steps" start="2">'+
      row.steps.slice(start+1,end).map((_,i)=>direction(start+1+i)).join("")+'</ol></details>':"")+
      recordsTable((row.items || []).filter(inArea),"Items")+recordsTable((row.encounters || []).filter(inArea),"Enemies")+
      '<details><summary>Field notes</summary><p>'+escape(area?.tip || row.tip)+'</p>'+
      (row.lore && (!area || area.lore)?'<h3>Did you know?</h3><p>'+escape(row.lore)+'</p>':"")+'</details>'+
      bibliography(row)+'</div><aside class="rail">'+floorKey((row.floors || []).filter(f=>!area || f.name.startsWith(area.name)))+
      routeDiagram+related(row)+controls(row,true)+'</aside></div><nav class="article-foot" aria-label="Walkthrough pages">'+
      (prior?anchor(prior.id,"← Previous stop","text-link"):anchor("walk","All stops","text-link"))+
      (next?anchor(next.id,"Next stop →","text-link"):anchor("walk","All stops","text-link"))+'</nav>';
  }
  function geneResult() {
    const ids = specimens.map(s=>s.id).filter(id=>state.genes.includes(id));
    if (!ids.length) return "Choose a gene to see its form and initial AP.";
    const result = data.extras.recipes[ids.join("+")];
    return '<strong>'+escape(result.form)+'</strong>'+escape(result.cost)+' initial AP · '+escape(result.detail);
  }
  function genePicker() {
    return '<section aria-label="Gene recipe"><div class="genes">'+specimens.map(s=>
      '<button type="button" class="gene" data-action="gene" data-id="'+escape(s.id)+'" aria-pressed="'+
      state.genes.includes(s.id)+'">'+plate(s.id)+'<span>'+escape(s.name)+'</span></button>').join("")+
      '</div><div class="result" id="gene-result" role="status">'+geneResult()+'</div>'+
      '<p class="fact">These three elemental genes have seven combinations. The Windows app can read the full gene table from your imported disc.</p></section>';
  }
  function masters(row) {
    const choices = row.id==="rwolf" ? [masterExamples[1]] : masterExamples;
    return '<div class="table-wrap"><table class="table compact"><caption>Growth per level</caption>'+
      '<thead><tr><th scope="col">Stat</th>'+choices.map(m=>'<th scope="col">'+escape(m.name)+'</th>').join("")+
      '</tr></thead><tbody>'+statNames.map((s,i)=>'<tr><th scope="row">'+escape(s)+'</th>'+
      choices.map(m=>'<td>'+(m.stats[i]>0?"+":"")+m.stats[i]+'</td>').join("")+'</tr>').join("")+'</tbody></table></div>';
  }
  function article(row) {
    let body = "";
    if (row.id === "genes") body += genePicker();
    if (game==="bof4" && ["masters","rwolf"].includes(row.id)) body += masters(row);
    for (const s of row.sections || []) {
      body += '<section><h2>'+escape(s.title)+'</h2><p>'+escape(s.text)+'</p></section>';
    }
    if (row.records) body += recordsTable(row.records,row.table === "items" ? "Items" : "Enemies");
    if (row.id === "genes") body += '<details><summary>Specimen notes</summary>'+specimens.map(s=>rowLink(lookup.get(s.id),s.shape)).join("")+'</details>';
    if (row.id === "masters") body += anchor("rwolf","Rwolf’s growth record","text-link");
    return folio(row,"Field wiki",row.category,row.lead)+'<div class="reading-grid"><div class="prose">'+body+
      bibliography(row)+'</div><aside class="rail">'+related(row)+controls(row,false)+'</aside></div>';
  }
  function searchPage() {
    const query = (params.get("q") || "").trim().slice(0,140);
    const intro = crumb("Search")+head("Search",query ? "Results for “"+query+"” in "+volume.title+"." : "Find a place, item, enemy or guide entry.");
    if (!query) return intro;
    const term = normal(query);
    const matches = rows.filter(r=>textSearch(r).includes(term));
    const rank = r=>normal(r.title).includes(term)?0:r.records?.some(item=>normal(item.name).includes(term))?1:2;
    matches.sort((a,b)=>rank(a)-rank(b));
    const reveal = state.searchTerm===query;
    const shown = matches.filter(r=>reveal || unlocked(r));
    function describe(row) {
      const item = (row.records || []).find(r=>normal(r.name).includes(term));
      return [row.category || "Walkthrough", item ? item.name+" · "+item.where : row.region].filter(Boolean).join(" · ");
    }
    return intro+'<div class="collection">'+shown.map(r=>rowLink(r,describe(r))).join("")+
      (!shown.length?'<p class="empty">'+(matches.length ? "No matches within your spoiler boundary." : "No matching pages. Try another name or a shorter search.")+'</p>':"")+
      (matches.some(r=>!unlocked(r)) ? action("matches",reveal?"Hide later matches":"Show later matches",'aria-expanded="'+reveal+'"') : "")+'</div>';
  }
  function bookmarks() {
    const marked = prefs[game].pins.map(id=>lookup.get(id)).filter(Boolean);
    return crumb("Bookmarks")+head("Bookmarks")+ '<div class="collection">'+(marked.length ?
      marked.map(r=>rowLink(r,r.category||"Walkthrough")).join("") :
      '<p class="empty">Choose <strong>Bookmark page</strong> on a walkthrough stop or wiki entry to keep it here.</p>')+'</div>';
  }
  function render() {
    readState();
    const row = lookup.get(page);
    let content, title;
    if (row) {
      content = row.region ? walkthrough(row) : article(row);
      title = row.title;
    } else {
      const sections = {"":[home,volume.title],walk:[routeIndex,"Walkthrough"],route:[routeIndex,"Walkthrough"],
        wiki:[wikiIndex,"Field wiki"],bookmarks:[bookmarks,"Bookmarks"],search:[searchPage,"Search"]};
      const section = Object.hasOwn(sections,page) ? sections[page] : null;
      content = section ? section[0]() : head("Page not found","This link does not match a page in this volume.")+anchor("","Back to the volume","cta");
      title = section ? section[1] : "Page not found";
    }
    document.body.dataset.game = game;
    document.body.dataset.page = page || "cover";
    document.getElementById("imprint").href = href();
    document.querySelectorAll("[data-volume]").forEach(a=>a.setAttribute("aria-current",String(a.dataset.volume===game)));
    const active = row ? (row.region?"walk":"wiki") : page==="route"?"walk":page;
    document.getElementById("book-nav").innerHTML=[["","Overview"],["walk","Walkthrough"],["wiki","Field wiki"],["bookmarks","Bookmarks"]]
      .map(([id,name])=>'<a href="'+href(id)+'"'+(active===id?' aria-current="page"':"")+'>'+name+'</a>').join("");
    main.innerHTML=content;
    search.value=page==="search"?(params.get("q")||"").slice(0,140):"";
    document.title=title+(page?" · "+volume.title:"")+" · BoF Atelier Field Guide";
  }
  document.getElementById("search").addEventListener("submit",event=>{
    event.preventDefault();
    const term=search.value.trim();
    state.searchTerm=null;
    const next=href("search",term?{q:term}:{});
    if (location.hash===next) { render(); main.focus(); }
    else location.hash=next;
  });
  document.querySelector(".skip").addEventListener("click",event=>{ event.preventDefault(); main.focus(); });
  document.addEventListener("keydown",event=>{
    if (event.key==="/" && !event.ctrlKey && !event.altKey && !event.metaKey &&
        !event.target.closest("input,select,textarea,[contenteditable=true]")) {
      event.preventDefault(); search.focus();
    }
  });
  main.addEventListener("click",event=>{
    const button=event.target.closest("button[data-action]");
    if (!button) return;
    const which=button.dataset.action, group=button.dataset.group;
    if (which==="gene") {
      const id=button.dataset.id;
      state.genes=state.genes.includes(id)?state.genes.filter(g=>g!==id):[...state.genes,id];
      button.setAttribute("aria-pressed",String(state.genes.includes(id)));
      document.getElementById("gene-result").innerHTML=geneResult();
      return;
    }
    if (which==="routes") state.routes=!state.routes;
    if (which==="group") state["group:"+group]=!state["group:"+group];
    if (which==="matches") {
      const term=(params.get("q")||"").trim().slice(0,140);
      state.searchTerm=state.searchTerm===term?null:term;
    }
    if (which==="pin") {
      const pins=prefs[game].pins;
      prefs[game].pins=pins.includes(page)?pins.filter(id=>id!==page):[...pins,page];
      savePrefs();
    }
    if (which==="boundary") {
      prefs[game].through=book.route.findIndex(r=>r.id===page);
      state.routes=false; state.searchTerm=null;
      for (const key of Object.keys(state)) if (key.startsWith("group:")) delete state[key];
      savePrefs();
    }
    render();
    const match=Array.from(main.querySelectorAll("button[data-action]")).find(b=>b.dataset.action===which && b.dataset.group===group);
    match?.focus({preventScroll:true});
  });
  main.addEventListener("change",event=>{
    const element=event.target;
    if (element.id==="subject") location.hash=href("wiki",element.value?{subject:element.value}:{});
    if (element.id==="floor") {
      const options=Object.fromEntries(params.entries());
      options.floor=element.value;
      location.hash=href(page,options);
    }
  });
  window.addEventListener("hashchange",()=>{
    const from=game, previous=page, oldParams=params;
    render();
    if (entered && from===game && previous===page && oldParams.get("area")===params.get("area")) {
      const changed=oldParams.get("floor")!==params.get("floor")?"floor":oldParams.get("subject")!==params.get("subject")?"subject":"";
      if (changed) { document.getElementById(changed)?.focus({preventScroll:true}); return; }
    }
    main.focus({preventScroll:true});
    window.scrollTo(0,0);
  });
  render();
  document.getElementById("download-guide").hidden = !["http:", "https:"].includes(location.protocol);
  entered=true;
})();
