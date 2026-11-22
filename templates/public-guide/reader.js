(() => {
  "use strict";
  const books = JSON.parse(document.getElementById("guide-data").textContent);
  const main = document.getElementById("main");
  const dialog = document.getElementById("overlay");
  const storeKey = "bof-atelier.public-guide.v1";
  const $ = (selector, node = document) => node.querySelector(selector);
  const escape = value => String(value ?? "").replace(/[&<>"']/g, char =>
    ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[char]));
  const normal = searchText;
  const selectedGenes = new Set();
  const readingHistory = new Map();
  const byGame = {};
  let game, book, volume, entries, page, params, routePage, area, sheet, reader;
  let step, showAllSteps, currentAddress = "", dialogOpener, readingSection = "";
  let slot = "", origin = null, nextOrigin = null, slotCount = 0;
  const historySession = Date.now().toString(36) + Math.random().toString(36).slice(2);
  let storageAvailable = true;
  let preferences = {};
  const reveals = {bof3:false, bof4:false};

  try {
    const raw = JSON.parse(localStorage.getItem(storeKey) || "{}");
    if (raw && typeof raw === "object" && !Array.isArray(raw)) preferences = raw;
  } catch { storageAvailable = false; }

  function savePreferences() {
    try { localStorage.setItem(storeKey, JSON.stringify(preferences)); }
    catch { storageAvailable = false; }
  }
  function href(id = "", query = {}, title = game) {
    const suffix = new URLSearchParams(query).toString();
    return "#" + title + (id ? "/" + encodeURIComponent(id) : "") + (suffix ? "?" + suffix : "");
  }
  function link(url, label, attrs = "") {
    return `<a href="${escape(url)}" ${attrs}>${escape(label)}</a>`;
  }
  function button(action, label, css = "quiet", attrs = "") {
    return `<button type="button" class="${css}" data-action="${action}" ${attrs}>${escape(label)}</button>`;
  }
  function scene(art) {
    const id = /^[a-z0-9-]+$/.test(art) ? art : volume.theme;
    return `--scene:var(--art-${id})`;
  }
  function note(text) { document.getElementById("announce").textContent = text; }
  function volumeMetadata(title) { return volumes[title === "bof4" ? "iv" : "iii"]; }

  function catalogue(title, data) {
    const meta = volumeMetadata(title);
    const core = meta.article;
    const corePages = [{id:core.id, title:core.title, lead:core.intro, category:"Field notes", art:meta.theme,
      sections:core.sections.map(([heading,text]) => ({title:heading,text})), sources:["manual"]}];
    if (title === "bof3") {
      corePages.push({id:"genes", title:"Dragon genes", lead:"Combine Flame, Frost and Thunder.", category:"Dragon genes", art:"flame"});
      for (const specimen of specimens) {
        corePages.push({id:specimen.id, title:specimen.name, lead:specimen.shape, category:"Dragon genes", art:specimen.id});
      }
    } else {
      corePages.push({id:"masters", title:"Master training", lead:"Find a teacher and see what an apprentice can learn.", category:"Masters & villagers", art:"iv-training"},
        {id:"rwolf", title:"Rwolf", lead:"His classroom is the ridge west of Chamba.", category:"Masters & villagers", art:"iv-training", unlock:"dam-kyria"});
    }
    const records = new Map([...data.route, ...corePages, ...data.articles].map(r => [r.id,r]));
    for (const entity of Object.values(data.entities || {})) {
      records.set(entity.id, {...entity, title:entity.name, lead:"", entity:true});
    }
    for (const stop of data.route) {
      for (const part of stop.sectionsByArea || []) {
        const id = part.id;
        if (id === stop.id) continue;
        const illustration = data.fieldSheets[id];
        records.set(id, {id, title:illustration?.title || part.name, lead:illustration?.objective || part.lead,
          area:part.name, stop:stop.id, unlock:illustration?.unlock || stop.id,
          category:illustration?.category || "Walkthrough", art:illustration?.art || stop.art});
      }
    }
    return records;
  }
  function readAddress() {
    const [path, rawQuery = ""] = location.hash.slice(1).split("?",2);
    const [title, encoded] = path.split("/");
    const aliases = {bof3:"bof3", bof4:"bof4", iii:"bof3", iv:"bof4"};
    game = Object.hasOwn(aliases,title) ? aliases[title] : "bof3";
    let id;
    try { id = decodeURIComponent(encoded || ""); } catch { id = "missing"; }
    page = !title || Object.hasOwn(aliases,title) ? id : "missing";
    if (["index","guide","home"].includes(page)) page = "";
    if (page === "route") page = "walk";
    if (game === "bof4" && page === "deep-diver") page = "item.deep diver";
    if (game === "bof4" && page === "mage-goo") page = "enemy.mage goo";
    params = new URLSearchParams(rawQuery);
    book = books[game];
    volume = volumeMetadata(game);
    entries = byGame[game] ??= catalogue(game,book);
    const existing = preferences[game];
    reader = existing && typeof existing === "object" && !Array.isArray(existing) ? existing : {};
    preferences[game] = reader;
    if (!Array.isArray(reader.pins)) reader.pins = [];
    if (!Number.isInteger(reader.through) || reader.through < 0 || reader.through >= book.route.length) reader.through = 1;
    if (!reader.spot && reader.through > 1) reader.spot = book.route[reader.through].id;
    routePage = book.route.find(r => r.id === page);
    area = null;
    const areaSheet = book.fieldSheets[page];
    if (!routePage && areaSheet) routePage = book.route.find(r => r.id === areaSheet.stop);
    if (!routePage && entries.get(page)?.area) routePage = entries.get(entries.get(page).stop);
    if (routePage?.sectionsByArea) {
      const parts = routePage.sectionsByArea;
      area = parts.find(a => a.name === params.get("area")) || parts.find(a => a.id === page);
      // A chapter URL saved before the split identifies a floor in the original chapter-wide list.
      if (page === routePage.id && !areaSheet && !params.has("area") && params.has("floor")) {
        const original = routePage.floors || [];
        const floor = params.has("map") ? original.find(f => f.mapId === Number(params.get("map")) &&
          f.section === Number(params.get("section"))) : original[Number(params.get("floor"))];
        const owner = floor && parts.find(a => a.floorIds.includes(floor.mapId));
        if (owner) {
          area = owner;
          params.set("floor",String(original.filter(f => owner.floorIds.includes(f.mapId)).indexOf(floor)));
        }
      }
      // Before the village and woodland pages were split, these URLs numbered their floors together.
      if (!params.has("map") && params.has("floor")) {
        const legacy = Number(params.get("floor"));
        if (game === "bof3" && page === "cedar" && !params.has("area") && legacy === 3) {
          area = parts.find(a => a.id === "mcneil");
          params.set("floor","0");
        } else if (game === "bof4" && area?.id === "kyria" && [1,2,3].includes(legacy)) {
          const woods = parts.find(a => a.id === "kyria-woods");
          if (woods) {
            area = woods;
            params.set("floor",String(legacy - 1));
          }
        }
      }
      if (!area && params.has("floor")) area = parts[0];
      if (area) page = area.id;
    }
    sheet = book.fieldSheets[page];
  }
  function withinBoundary(row) {
    const index = book.route.findIndex(stop => stop.id === (row.unlock || row.id));
    return index <= reader.through;
  }
  function displayed(row) { return reveals[game] || withinBoundary(row); }
  function titleOf(id) { return book.fieldSheets[id]?.title || entries.get(id)?.title || id; }
  function observationAt(observation,id) {
    return Boolean(id && (observation.areaIds?.length ? observation.areaIds.includes(id) : observation.stop === id));
  }
  function canReadObservation(row) {
    if (reveals[game] || withinBoundary(entries.get(row.unlock || row.stop))) return true;
    // Following the treasure from its map opens that area's sighting even on a direct link.
    const origin = entries.get(params.get("at"));
    if (!origin) return false;
    return observationAt(row,origin.id);
  }
  function showReveal(label = "Show later names") {
    return button("reveal", reveals[game] ? "Hide later names" : label, "text-button", `aria-expanded="${reveals[game]}"`);
  }
  function navItem(id,label,match = page === id) {
    return link(href(id),label,match ? 'aria-current="page"' : "");
  }
  function sidebar() {
    const mark = entries.get(reader.spot);
    const tabs = ["bof3","bof4"].map(title => link(href("",{},title), title === "bof3" ? "III" : "IV",
      `aria-label="${volumeMetadata(title).title}" aria-current="${title === game}"`)).join("");
    const topic = (id,label) => link(href("wiki",{subject:id}), label, page === "wiki" && params.get("subject") === id ? 'aria-current="page"' : "");
    const combat = game === "bof3" ? navItem("enemy-skills","Enemy skills") : navItem("combination-magic","Combos");
    const nearby = routePage ? book.route.slice(Math.max(0,book.route.indexOf(routePage)-1),book.route.indexOf(routePage)+2) :
      book.route.slice(Math.max(0,reader.through-1),reader.through+1);
    return `<div class="volume-art"><div><div class="eyebrow">Field Guide</div><strong>${escape(volume.title)}</strong></div>
      <nav class="volume-tabs" aria-label="Choose a game">${tabs}</nav></div>
      <div class="spine-body"><nav aria-label="Read">
        ${navItem("walk","Walkthrough", page === "walk" || Boolean(routePage))}${navItem("wiki","Field wiki", page === "wiki" && !params.has("subject"))}
        ${navItem("bookmarks","Bookmarks")}</nav><hr class="rule"><p class="eyebrow">Reference</p>
        <nav aria-label="Game reference">${game === "bof3" ? navItem("genes","Dragon genes") : navItem("dragons","Dragon forms")}
        ${game === "bof4" ? navItem("masters","Masters & skills") : topic("Masters & companions","Masters")}
        ${combat}${game === "bof4" ? navItem("learning-skills","Enemy skills") : ""}${topic("Item ledger","Items")}${topic("Bestiary","Bestiary")}</nav>
        <hr class="rule"><p class="eyebrow">${mark ? "Your reading place" : "On the journey"}</p>
        <nav aria-label="Reading place">${mark ? navItem(mark.id,titleOf(mark.id)) :
          nearby.filter(r => displayed(r) || (!sheet?.unlock && r.id === routePage?.id)).map(r => navItem(r.id,titleOf(r.id))).join("")}</nav></div>`;
  }
  function banner(title,lead,section,art,compact = false) {
    return `<header class="panorama${compact ? " compact" : ""}" style="${scene(art)}"><div class="hero-copy">
      <div class="eyebrow">${escape(section)}</div><h1>${escape(title)}</h1>
      ${lead ? `<p>${escape(lead)}</p>` : ""}</div></header>`;
  }
  function detailTrail() {
    const row = entries.get(page);
    if (!row) return "";
    let parent = href("wiki"), title = "Field wiki";
    const at = entries.get(params.get("at"));
    if (origin) {
      parent = origin.address;
      title = origin.title;
    } else if (routePage) {
      parent = href("walk"); title = "Walkthrough";
    } else if (row.entity && at && row.observations.some(o => observationAt(o,at.id))) {
      const selected = {entry:row.name,view:row.category === "Item ledger" ? "items" : "enemies"};
      const sighting = params.get("sighting");
      if (row.observations.some(o=>observationAt(o,at.id) && o.where === sighting)) selected.sighting = sighting;
      parent = href(at.id,selected);
      title = titleOf(at.id);
    } else if (row.category === "Walkthrough" && entries.has(row.unlock)) {
      parent = href(row.unlock); title = titleOf(row.unlock);
    } else if (game === "bof3" && specimens.some(s => s.id === page)) {
      parent = href("genes"); title = "Dragon genes";
    } else if (page === "rwolf" || page.startsWith("teacher-")) {
      parent = game === "bof4" ? href("masters") : href("wiki",{subject:row.category});
      title = game === "bof4" ? "Master training" : row.category;
    } else if (row.category) {
      parent = href("wiki",{subject:row.category}); title = row.category;
    }
    return `<nav class="detail-trail" aria-label="Reader navigation"><a href="${escape(parent)}" ${origin ? "data-reading-back" : ""}
      aria-label="${escape("Back to " + title)}"><span aria-hidden="true">←</span> ${escape(title)}</a></nav>`;
  }
  function readingPanels(choices) {
    const panels = choices.filter(p => p.body);
    if (!panels.length) return "";
    if (!panels.some(p => p.id === readingSection)) readingSection = panels[0].id;
    if (panels.length === 1) return panels[0].body;
    return `<div class="reading-sections"><div class="section-tabs" role="tablist" aria-label="On this page">
      ${panels.map(p => `<button type="button" role="tab" id="tab-${p.id}" aria-controls="panel-${p.id}" aria-selected="${p.id === readingSection}"
        tabindex="${p.id === readingSection ? 0 : -1}" data-action="view" data-view="${p.id}">${escape(p.label)}</button>`).join("")}</div>
      ${panels.map(p => `<section role="tabpanel" id="panel-${p.id}" aria-labelledby="tab-${p.id}" tabindex="0"
        data-view-panel="${p.id}" ${p.id === readingSection ? "" : "hidden"}>${p.body}</section>`).join("")}</div>`;
  }
  function switchSection(id) {
    const tab = [...main.querySelectorAll("[role=tab][data-view]")].find(t=>t.dataset.view === id);
    if (!tab) return;
    readingSection = id;
    for (const t of main.querySelectorAll("[role=tab][data-view]")) {
      const chosen = t === tab;
      t.setAttribute("aria-selected",String(chosen));
      t.tabIndex = chosen ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !chosen;
    }
    const next = new URLSearchParams(params);
    next.delete("entry");
    next.delete("sighting");
    if (id === main.querySelector("[role=tab]").dataset.view && !next.has("floor")) next.delete("view");
    else next.set("view",id);
    replaceReadingAddress(next);
  }
  function listed(rows, descriptive = true) {
    return `<ul class="entry-list">${rows.map(row =>
      `<li><a href="${escape(row.url || href(row.id))}"><strong>${escape(row.title || titleOf(row.id))}</strong>
      ${descriptive && row.description ? `<small>${escape(row.description)}</small>` : ""}</a></li>`).join("")}</ul>`;
  }
  function namedLinks(ids) {
    const rows = [...new Set(ids || [])].map(id => entries.get(id)).filter(Boolean);
    if (!rows.length) return "";
    const visible = rows.filter(displayed);
    const hidden = visible.length < rows.length;
    return `<div class="links">${visible.map(row => link(href(row.id),titleOf(row.id))).join("")}
      ${hidden ? showReveal("Show later references") : ""}</div>`;
  }
  function bibliography(keys, detail = "") {
    const record = entries.get(page);
    const chapters = sheet?.sourceSections || routePage?.sourceSections || record?.sourceSections ||
      (record?.table ? entries.get(record.unlock)?.sourceSections : []) || [];
    const sources = [...new Set(keys || [])].filter(id => book.sources[id]);
    if (!sources.length && !detail) return "";
    return `<details class="bibliography" data-panel="sources"><summary>Sources</summary>${detail ? `<p>${escape(detail)}</p>` : ""}
      <ul>${sources.map(id => {
        const source = book.sources[id];
        const names = chapters.filter(ref=>ref.source === id).map(ref=>escape(ref.section));
        return `<li>${source.url ? link(source.url,source.title,'rel="noreferrer"') : escape(source.title)}
          ${names.map(name => `<small class="source-chapter">${name}</small>`).join("")}</li>`;
      }).join("")}</ul></details>`;
  }
  function controls(id = page, stop) {
    const pinned = reader.pins.includes(id);
    const marked = reader.spot === id;
    return `<div class="page-tools">${button("pin",pinned ? "Bookmarked" : "Bookmark page","quiet",`aria-pressed="${pinned}"`)}
      ${stop ? button("mark",marked ? "Reading place saved" : "Mark my place","text-button",`data-stop="${escape(stop)}"`) : ""}
      ${storageAvailable ? "" : '<span class="meta">Changes last for this session.</span>'}</div>`;
  }
  function volumeCover() {
    const third = game === "bof3";
    const mark = entries.get(reader.spot);
    const cards = [
      [mark?.id || "walk", mark ? titleOf(mark.id) : "Walkthrough", third ? "iii-woods" : "kurok-wind",
        mark ? "Return to your reading place." : "Follow the route from the opening scene."],
      ["wiki","Field wiki",third ? "iii-port" : "iv-dragon","Find an item, enemy or skill."],
      [volume.tool,third ? "Dragon genes" : "Master training",third ? "flame" : "iv-training",
        third ? "Mix genes and check the initial AP cost." : "Find a teacher and check the lessons."]
    ];
    return banner(volume.title, third ? "From Dauna Mine to the road beyond the highlands." :
      "Follow the sandflier’s trail across the South Desert.","Field Guide · US PlayStation",volume.theme) +
      `<div class="leaf cover-grid">${cards.map(([id,name,art,desc]) =>
      `<a class="cover-link" href="${href(id)}"><span aria-hidden="true" class="picture" style="${scene(art)}"></span>
        <span class="copy"><strong>${escape(name)}</strong><small>${escape(desc)}</small></span></a>`).join("")}</div>`;
  }
  function routeIndex() {
    const visible = book.route.filter(stop => displayed(stop) ||
      stop.sectionsByArea?.some(part => displayed(entries.get(part.id))));
    const grouped = new Map();
    for (const stop of visible) {
      if (!grouped.has(stop.region)) grouped.set(stop.region,[]);
      grouped.get(stop.region).push(stop);
    }
    const parts = [...grouped].map(([chapter,stops]) => {
      const rows = stops.flatMap(r => r.sectionsByArea ? r.sectionsByArea.filter(a => displayed(entries.get(a.id))).map(a => {
        return {id:a.id,title:titleOf(a.id),description:a.lead};
      }) : [{id:r.id,title:titleOf(r.id)}]);
      return `<section><h2 class="chapter-name">${escape(chapter)}</h2>${listed(rows)}</section>`;
    });
    const mark = entries.get(reader.spot) || book.route[0];
    return banner("Walkthrough","Choose a place on the journey.",volume.title,volume.theme,true) +
      `<div class="leaf index-layout"><aside class="sidebar"><span class="eyebrow">${reader.spot ? "Your reading place" : "Begin here"}</span>
        <h2>${link(href(mark.id),titleOf(mark.id))}</h2><p class="meta">Mark a route to choose how far the contents reveal.</p>
        ${showReveal("Show later stops")}</aside><div>${parts.join("")}</div></div>`;
  }
  function wiki() {
    const all = [...entries.values()].filter(r => (!r.region && !r.area) || book.fieldSheets[r.id]?.category);
    const categories = [...new Set(all.map(r=>r.category).filter(Boolean))];
    const current = categories.includes(params.get("subject")) ? params.get("subject") : "";
    const eligible = all.filter(r => (!current || r.category === current) && displayed(r));
    const categoryLinks = ["",...categories].map(c => `<li>${link(href("wiki",c ? {subject:c} : {}),c || "All subjects",
      c === current ? 'aria-current="true"' : "")}</li>`).join("");
    const groups = current ? [current] : categories;
    return banner("Field wiki","Look up a place, a creature or a skill.",volume.title,game === "bof3" ? "iii-port" : "iv-dragon",true) +
      `<div class="leaf index-layout"><nav aria-label="Subjects"><ul class="subjects">${categoryLinks}</ul></nav>
        <div>${groups.map(c => {
          const rows = eligible.filter(r => r.category === c);
          if (!rows.length) return "";
          rows.sort((a,b) => Number(Boolean(a.table))-Number(Boolean(b.table)) || a.title.localeCompare(b.title));
          return `<section><h2 class="chapter-name">${escape(c)}</h2>${listed(rows.map(r=>({
            id:r.id,title:r.title,description:r.entity ? r.observations[0].where : r.table ? r.lead : ""
          })))}</section>`;
        }).join("")}${!eligible.length ? '<p>These entries are later in the journey.</p>' : ""}
        ${showReveal("Show later articles")}</div></div>`;
  }
  const entityId = (kind,name) => (kind === "items" ? "item." : "enemy.") + name.trim().toLowerCase();

  function areaRecords(stop, part, kind, routeSheet) {
    const rows = (stop[kind] || []).filter(r => !part || r.areaIds.includes(part.id));
    const notes = kind === "items" ? routeSheet?.optional : routeSheet?.enemies;
    return rows.map(record => {
      const matching = (notes || []).filter(n => (n.record || n.name) === record.name);
      const unique = matching.length === 1 && rows.filter(r=>r.name === record.name).length === 1;
      const extra = unique ? matching[0] : matching.find(n=>n.where === record.where);
      if (!extra) return record;
      // Authored directions can add a turn or a battle cue. The named entry retains the complete source record.
      return {...record, place:kind === "items" ? extra.where : record.where,
        directions:kind === "items" ? extra.advice : extra.detail};
    });
  }
  function recordTable(records,kind,fromPage) {
    if (!records?.length) return "";
    const items = kind === "items";
    const label = items ? "Items" : "Enemies";
    return `<div class="table-wrap"><table class="entries" aria-label="${label}">
      <thead><tr><th scope="col">${items ? "Item" : "Enemy"}</th><th scope="col">${items ? "Where to look" : "In battle"}</th></tr></thead>
      <tbody>${records.map(r => {
        const id = entityId(kind,r.name);
        const at = r.areaIds?.length && !r.areaIds.includes(fromPage) ? r.areaIds[0] : fromPage;
        const url = href(id, at ? {at,sighting:r.where} : {});
        return `<tr tabindex="-1" data-record="${escape(r.name)}" data-sighting="${escape(r.where)}"><th scope="row">
          ${entries.has(id) ? link(url,r.name) : escape(r.name)}<small>${escape(r.place || r.where)}</small></th>
          <td>${escape(r.directions || r.detail)}</td></tr>`;
      }).join("")}</tbody></table></div>`;
  }
  function placePanels(stop, directionsBody, floorBody, notes) {
    return readingPanels([
      {id:"directions",label:"Directions",body:directionsBody},
      {id:"floors",label:"Floors",body:floorBody},
      {id:"items",label:"Items",body:recordTable(areaRecords(stop,area,"items",sheet),"items",page)},
      {id:"enemies",label:"Enemies",body:recordTable(areaRecords(stop,area,"encounters",sheet),"encounters",page)},
      {id:"notes",label:"Notes",body:notes}
    ]);
  }
  function warning(text,label = "Missable") {
    return text ? `<aside class="warning" aria-label="${escape(label)}"><span aria-hidden="true">!</span>
      <div><strong>${escape(label)}</strong>${escape(text)}</div></aside>` : "";
  }
  function floors(stop,part) {
    const sheets = (stop.floors || []).filter(f=>!part || part.floorIds.includes(f.mapId));
    if (!sheets.length) return "";
    const requested = params.has("map") ? sheets.findIndex(f => f.mapId === Number(params.get("map"))
      && f.section === Number(params.get("section"))) : Number(params.get("floor"));
    const i = Number.isInteger(requested) && requested >= 0 && requested < sheets.length ? requested : 0;
    const floor = sheets[i];
    const options = sheets.map((f,index)=>`<option value="${index}" data-map="${f.mapId}" data-section="${f.section}" ${i === index ? "selected" : ""}>${escape(f.name)}</option>`);
    return `<details class="floor-key" data-panel="floor" open><summary>Floor landmarks</summary>
      <label for="floor">Floor</label><select id="floor">${options.join("")}</select>
      ${floor.landmarks?.length ? `<ol>${floor.landmarks.map(p=>`<li>${escape(p.name)}</li>`).join("")}</ol>` :
        "<p>This floor has no numbered landmarks.</p>"}</details>`;
  }
  function areaNavigation(stop) {
    if (!stop.sectionsByArea) return "";
    const areas = stop.sectionsByArea.map(a => {
      const nextChapter = sheet?.unlock && sheet.nextSheet === a.id && !displayed(entries.get(a.id));
      return link(href(a.id), nextChapter ? "Next stop" : a.name === "Dam" ? "The Dam" : a.name,
        a.name === area?.name ? 'aria-current="page"' : "");
    });
    return `<nav class="region-strip" aria-label="Area"><span class="eyebrow">On this road</span>${areas.join("")}</nav>`;
  }
  function sheetMap(current) {
    const art = books.extras.diagrams[current.id];
    return `<div class="map-board"><img src="${art.image}" width="760" height="390" alt="${escape(current.mapAlt)}">
      ${current.steps.map(s => {
        const [x,y] = art.points[s.key];
        return button("step","","map-pin",`style="left:${x}%;top:${y}%" data-number="${s.key}"
          aria-pressed="${s.key === step}" aria-label="${escape(s.key + ". " + s.title)}"`);
      }).join("")}</div>`;
  }
  function routeSteps() {
    if (sheet) return sheet.steps;
    if (!routePage || (routePage.sectionsByArea && !area)) return [];
    const first = area?.firstStep || 0;
    return routePage.steps.slice(first,area?.endStep).map((body,i)=>{
      const title = routePage.landmarks?.[first+i] || ("Step " + (i+1));
      return {key:i+1,title,body,topic:routePage.stepTopics?.[title]};
    });
  }
  function stepList() {
    return `<ol class="steps${sheet ? "" : " written"}">${routeSteps().map(s => `<li>
      <button type="button" data-action="step" data-number="${s.key}" class="step-button" aria-pressed="${s.key === step}">
        <span class="num">${s.key}</span><span>${s.optional ? "<small>Optional detour</small>" : ""}
          <strong>${escape(s.title)}</strong><span class="step-body" ${s.key === step || showAllSteps ? "" : "hidden"}>${escape(s.body)}</span>
        </span></button>${s.topic ? `<div class="step-topic" data-step-topic="${s.key}" ${s.key === step || showAllSteps ? "" : "hidden"}>
          ${articleLinks([s.topic],routePage.id)}</div>` : ""}</li>`).join("")}</ol>`;
  }
  function changeStep(n) {
    const steps = routeSteps();
    const target = steps.find(s=>s.key === n);
    if (!target) return;
    step = n;
    document.querySelectorAll("[data-action=step]").forEach(el => {
      const active = Number(el.dataset.number) === n;
      el.setAttribute("aria-pressed", String(active));
      const text = $(".step-body",el);
      if (text) text.hidden = !(active || showAllSteps);
    });
    for (const related of main.querySelectorAll("[data-step-topic]")) {
      related.hidden = !(Number(related.dataset.stepTopic) === n || showAllSteps);
    }
    const chooser = $("#choose-step",main);
    if (chooser) {
      chooser.value = String(n);
      $(".step-count",main).textContent = `${n} of ${steps.length}`;
      chooser.closest(".directions").dataset.expanded = String(showAllSteps);
      $("[data-action=previous-step]",main).disabled = n === steps[0].key;
      $("[data-action=next-step]",main).disabled = n === steps.at(-1).key;
    }
    if ($("#enlarged-direction")) $("#enlarged-direction").textContent = target.body;
    const next = new URLSearchParams(params);
    next.set("step",String(n));
    replaceReadingAddress(next);
    note(target.title);
  }
  function directionReader(label) {
    const steps = routeSteps();
    const long = !sheet && steps.length > 6;
    const expand = steps.length > 1 ? button("all-steps",showAllSteps ? "Show selected step" : "Read all steps","text-button",
      `aria-expanded="${showAllSteps}"`) : "";
    const travel = long ? `<nav class="step-travel" aria-label="Walkthrough steps">
      ${button("previous-step","←","step-arrow",`aria-label="Previous step" ${step === steps[0].key ? "disabled" : ""}`)}
      <label class="step-chooser"><span class="step-position" aria-hidden="true"><span class="step-prefix">Step </span><span class="step-count">${step} of ${steps.length}</span></span>
        <select id="choose-step" aria-label="Choose a step">${steps.map(s=>`<option value="${s.key}" ${s.key === step ? "selected" : ""}>${s.key}. ${escape(s.title)}</option>`).join("")}</select></label>
      ${button("next-step","→","step-arrow",`aria-label="Next step" ${step === steps.at(-1).key ? "disabled" : ""}`)}${expand}</nav>` : "";
    return `<section class="directions${long ? " long-route" : ""}" data-expanded="${showAllSteps}" aria-label="Directions">${label ? `<div class="directions-head"><h2 class="eyebrow">${escape(label)}</h2>
      ${button("enlarge","View map","quick-map",'aria-haspopup="dialog"')}</div>` : ""}
      ${travel}${stepList()}${long ? "" : expand}</section>`;
  }
  function routeNotes(stop,part) {
    const tip = part?.tip || stop.tip;
    const lore = !part || part.lore ? stop.lore : "";
    const hint = part?.hint || stop.hint;
    return (hint ? `<details data-panel="hint"><summary>Need a hint?</summary><p>${escape(hint)}</p></details>` : "") +
      (tip ? `<details data-panel="tip"><summary>Field note</summary><p>${escape(tip)}</p></details>` : "") +
      (lore ? `<details data-panel="lore"><summary>Local lore</summary><p>${escape(lore)}</p></details>` : "");
  }
  function landmarks(stop,part) {
    const chapterArea = stop.sectionsByArea?.find(a => a.id === stop.id) || stop.sectionsByArea?.[0];
    if (!stop.map || (part && part !== chapterArea)) return "";
    return `<details data-panel="landmarks"><summary>${escape(stop.map.title)} landmarks</summary><ul>
      ${stop.map.points.map(p=>`<li><strong>${escape(p.name)}</strong> ${escape(p.note)}</li>`).join("")}</ul></details>`;
  }
  function adjacent(stop) {
    const idx = book.route.indexOf(stop);
    const next = sheet?.nextSheet;
    const previousSheet = sheet && Object.values(book.fieldSheets).find(candidate => candidate.nextSheet === sheet.id);
    const previousStop = book.route[idx-1];
    const previous = previousSheet?.id || previousStop?.sectionsByArea?.at(-1)?.id || previousStop?.id;
    return `<nav class="page-ends" aria-label="Walkthrough pages">
      ${previous ? link(href(previous),"← " + titleOf(previous)) : link(href("walk"),"Walkthrough contents")}
      ${next ? link(href(next),sheet.unlock && !displayed(entries.get(next)) ? "Next stop →" : titleOf(next) + " →") : idx+1 < book.route.length ?
        link(href(book.route[idx+1].id),"Next stop →") : link(href("walk"),"Walkthrough contents")}</nav>`;
  }
  function readableFrom(targetStop,fromStop) {
    const boundary = Math.max(reader.through,book.route.findIndex(s=>s.id === fromStop));
    return reveals[game] || book.route.findIndex(s=>s.id === targetStop) <= boundary;
  }
  function articleLinks(ids,fromStop) {
    if (!ids?.length) return "";
    const rows = [...new Set(ids)].map(id=>entries.get(id)).filter(Boolean);
    const visible = rows.filter(r=>readableFrom(r.unlock || r.id,fromStop));
    if (!visible.length && !rows.length) return "";
    return `<div class="links">${visible.map(r=>link(href(r.id),titleOf(r.id))).join("")}
      ${visible.length < rows.length ? showReveal("Show later references") : ""}</div>`;
  }
  function relatedReading(ids,fromStop) {
    const links = articleLinks(ids,fromStop);
    return links ? `<nav class="related-reading" aria-label="Related pages"><h2>Related pages</h2>${links}</nav>` : "";
  }
  function workedRoute(stop) {
    const mapTitle = sheet.mapTitle || sheet.area;
    const early = sheet.opening?.steps || [];
    const panel = (part,title,group,lines) => lines.length ?
      `<details class="${part}" data-panel="${group}"><summary>${escape(title)}</summary>
        <ol>${lines.map(s=>`<li>${escape(typeof s === "string" ? s : s.body)}</li>`).join("")}</ol></details>` : "";
    const notes = sheet.after ? panel("after",sheet.after.title,"after",sheet.after.steps) : "";
    const directions = warning(sheet.warning,sheet.warningLabel || "Missable") + panel("arrival",sheet.opening?.title,"before",early) +
        `<div class="route-spread">${directionReader(sheet.entry)}<section class="route-map"><div class="row-head"><h2>${escape(mapTitle || sheet.area)}</h2>${button("enlarge","Enlarge map")}</div>
          <figure>${sheetMap(sheet)}<figcaption><span>${escape(sheet.mapKind)}</span><span>Landmarks · not to scale</span></figcaption></figure>
          <div class="map-tools"><details data-panel="key"><summary>Read the map</summary><p>${escape(sheet.mapAlt)}</p></details></div></section></div>`;
    return banner(sheet.title,sheet.objective,sheet.chapter,sheet.art) +
      `<div class="leaf reading-leaf">${placePanels(stop,directions,floors(stop,area),notes+routeNotes(stop,area)+bibliography(sheet.sources || stop.sources))}
        ${relatedReading([...(sheet.links || []),...(stop.links || [])],sheet.unlock || stop.id)}
        ${controls(page,sheet.unlock || stop.id)}${areaNavigation(stop)}${adjacent(stop)}</div>`;
  }
  function ordinaryRoute(stop) {
    if (stop.sectionsByArea && !area) {
      return banner(stop.title,"Choose your location.",stop.region,stop.art,true) +
        `<div class="leaf"><h2>Along the road</h2>${listed(stop.sectionsByArea.map(a=>({
          id:a.id,url:href(a.id),title:titleOf(a.id),description:a.lead
        })))}${controls(page,stop.id)}${adjacent(stop)}</div>`;
    }
    const name = area && area.id !== stop.id ? area.name : stop.title;
    const directions = warning(!area || area.warning ? stop.warning?.text : "",stop.warning?.label) + directionReader("");
    return banner(name,area?.lead || stop.lead,stop.region,stop.art,true) +
      `<div class="leaf reading-leaf">${placePanels(stop,directions,floors(stop,area)+landmarks(stop,area),routeNotes(stop,area)+bibliography(stop.sources))}
        ${relatedReading(stop.links,stop.id)}${controls(page,stop.id)}${areaNavigation(stop)}${adjacent(stop)}</div>`;
  }
  function pageTable(title,columns,rows) {
    if (!rows?.length) return "";
    const numeric = columns.map((_,i)=>rows.every(row=>/^[+−-]?\d+(?:[.,]\d+)?%?$/.test(row[i])));
    const cell = (val,i,heading=false) => {
      const tag = !heading && i > 0 ? "td" : "th";
      const scope = tag === "th" ? `scope="${heading ? "col" : "row"}"` : "";
      return `<${tag} ${scope} ${numeric[i] ? 'class="quantity"' : ""}>${escape(val)}</${tag}>`;
    };
    return `<section class="article-table"><h2>${escape(title)}</h2><div class="table-wrap"><table class="entries" aria-label="${escape(title)}">
      <thead><tr>${columns.map((val,i)=>cell(val,i,true)).join("")}</tr></thead>
      <tbody>${rows.map(row=>`<tr>${row.map((val,i)=>cell(val,i)).join("")}</tr>`).join("")}</tbody></table></div></section>`;
  }
  function contentSections(row) {
    return (row.sections || []).map(section=>`<section class="article-block"><h2>${escape(section.title)}</h2><p>${escape(section.text)}</p></section>`).join("") +
      (row.referenceTables || []).map(t=>pageTable(t.title,t.columns,t.rows)).join("");
  }
  function articleFloor(row) {
    const ref = row.floorRef;
    if (!ref) return "";
    const stop = book.route.find(s=>s.id === ref.stop);
    if (!stop) return "";
    const part = stop.sectionsByArea?.find(a=>a.floorIds.includes(ref.mapId));
    if (stop.sectionsByArea?.length && !part) return "";
    const local = (stop.floors || []).filter(f=>!part || part.floorIds.includes(f.mapId));
    const index = local.findIndex(f=>f.mapId === ref.mapId && f.section === ref.section);
    if (index < 0) return "";
    const id = part?.id || stop.id;
    const scope = book.fieldSheets[id]?.unlock || stop.id;
    const query = {view:"floors",floor:index,map:ref.mapId,section:ref.section};
    if (part) query.area = part.name;
    const reference = readableFrom(scope,row.unlock) ? link(href(id,query),"Floor landmarks · " + local[index].name) :
      showReveal("Show later floor");
    return `<div class="article-floor">${reference}</div>`;
  }
  function regularArticle(row) {
    const content = row.table ? recordTable(row.records,row.table,row.unlock) : contentSections(row);
    return banner(row.title,row.lead,row.category,row.art,true) + `<div class="leaf entry-leaf">${articleFloor(row)}
      <article class="reader-prose">${content}</article>${relatedReading(row.links,row.unlock)}
      ${bibliography(row.sources)}${controls()}</div>`;
  }
  function entityLeaf(row) {
    const at = params.get("at");
    const nearer = observation => observationAt(observation,at);
    const sighting = params.get("sighting");
    const rank = observation => nearer(observation) ? (observation.where === sighting ? 2 : 1) : 0;
    const permitted = row.observations.filter(canReadObservation).sort((a,b)=>rank(b)-rank(a));
    const first = permitted[0];
    const stop = first && entries.get(first.stop);
    const item = row.category === "Item ledger";
    const places = permitted.map(o => {
      const r = entries.get(o.stop);
      const local = r.sectionsByArea?.filter(a=>o.areaIds.includes(a.id)) || [];
      const destinations = local.length ? local.map(a=>link(href(a.id),a.name)) : [link(href(r.id),titleOf(r.id))];
      return `<section class="article-block"><h2>${escape(o.where)}</h2><p>${escape(o.detail)}</p><div class="links">${destinations.join("")}</div></section>`;
    });
    const illustration = (first && nearer(first) && book.fieldSheets[at]?.art) || stop?.art || volume.theme;
    const others = places.length > 1 ? `<details data-panel="sightings"><summary>Other locations (${places.length-1})</summary>${places.slice(1).join("")}</details>` : "";
    return banner(row.name,"",item ? "Item ledger" : "Bestiary",illustration,true) +
      `<div class="leaf entry-leaf"><article class="reader-prose">${places[0] || "<p>Its location is beyond your marked place.</p>"}${others}
      ${permitted.length < row.observations.length ? showReveal("Show later locations") : ""}
      ${bibliography(permitted.flatMap(o=>entries.get(o.stop).sources))}</article>${controls()}</div>`;
  }
  function recipeAnswer() {
    const ids = specimens.map(s=>s.id).filter(id=>selectedGenes.has(id));
    const recipe = books.extras.recipes[ids.join("+")];
    if (!recipe) return '<div><strong>Choose a gene</strong><p>The form and initial AP cost appear here.</p></div>';
    const chosen = specimens.filter(s=>selectedGenes.has(s.id)).map(s=>s.name).join(" + ");
    return `<div><div class="eyebrow">${escape(chosen)}</div><strong>${escape(recipe.form)}</strong></div>
      <p><span class="cost">${recipe.cost} initial AP</span><br>${escape(recipe.detail)}</p>`;
  }
  function genePage() {
    const tray = specimens.map(s => `<button type="button" class="specimen" data-action="gene" data-gene="${s.id}"
      aria-pressed="${selectedGenes.has(s.id)}" aria-label="${escape(s.name)}">
      <span class="picture" role="img" aria-label="${escape(s.shape)}" style="${scene(s.id)}"></span>
      <span class="spec-name">${escape(s.name)} <small>${s.ap} AP</small></span></button>`).join("");
    const combinations = Object.entries(books.extras.recipes).map(([key,r]) => [
      key.split("+").map(id=>specimens.find(s=>s.id === id).name).join(" + "),r.form,String(r.cost)
    ]);
    return `<header class="cabinet"><div class="eyebrow">Breath of Fire III · Accession</div><h1>Dragon genes</h1>
      <p>Choose up to three specimens to see what Ryu becomes.</p><div class="specimen-tray">${tray}</div>
      <div class="recipe"><div id="result" role="status" aria-live="polite" aria-atomic="true">${recipeAnswer()}</div>
        ${button("clear","Clear","quiet",selectedGenes.size ? "" : "hidden")}</div></header>
      <div class="leaf columns"><article><h2>In battle</h2>
      <p>Use Accession to transform. The initial AP is paid when Ryu changes form. Staying in that form costs AP on later turns.</p>
      <details data-panel="recipes"><summary>All seven combinations</summary>${pageTable("Elemental recipes",["Genes","Form","Initial AP"],combinations)}
        <p>The Windows app can read the full gene table from your imported game.</p></details>
      ${controls()}</article><aside class="sidebar"><h2>Specimen notes</h2>
      ${namedLinks(["flame","frost","thunder","accession-field","fusion-forms"])}</aside></div>`;
  }
  function specimenPage(s) {
    return banner(s.name,`${s.ap} initial AP`,"Dragon genes",s.id,true) +
      `<div class="leaf"><div class="action-row">${button("mix","Mix " + s.name,"primary",`data-gene="${s.id}"`)}
      ${link(href("genes"),"Open the specimen case",'class="text-button"')}</div>
      ${namedLinks(["accession-field","coastal-genes"])}${controls()}</div>`;
  }
  let selectedMaster = "teacher-rwolf", comparisonMaster = "";
  const growthStats = [["HP","HP"],["AP","AP"],["Power","power"],["Defence","defence"],["Agility","agility"],["Wisdom","wisdom"]];

  function masterPage() {
    const overview = page === "masters";
    const roster = book.teachers.filter(t=>displayed(t) || (!overview && t.id === "teacher-rwolf"));
    const teacher = roster.find(t=>t.id === (overview ? selectedMaster : "teacher-rwolf")) || roster[0];
    const baseline = roster.find(t=>t.id === comparisonMaster);
    const select = (id,title,current,none) => {
      const options = (none ? [{id:"",name:"Unaffiliated"},...roster] : roster).map(option =>
        `<option value="${escape(option.id)}" ${current === option.id ? "selected" : ""}>${escape(option.name)}</option>`);
      return `<label>${title}<select id="${id}">${options.join("")}</select></label>`;
    };
    let training;
    if (teacher) {
      const entry = entries.get(teacher.id);
      const modifiers = growthStats.map(([name,key]) => {
        const delta = teacher.growth[key] - (baseline ? baseline.growth[key] : 0);
        return `<div><dt>${name}</dt><dd>${delta > 0 ? "+" : ""}${delta}</dd></div>`;
      });
      const notes = entry.sections.filter(s=>!s.title.startsWith("Where to find "));
      const lessons = entry.referenceTables.filter(t=>t.title === "Lessons and rewards");
      training = `<section><h2>Growth per level</h2><div class="compare">
        ${overview ? select("apprentice","Apprentice under",teacher.id,false) : ""}
        ${select("compare-master","Compare with",baseline?.id || "",true)}</div>
        <p>${escape(teacher.name)}’s growth compared with ${escape(baseline?.name || "an unaffiliated apprentice")}.</p>
        <dl class="stat-grid" aria-label="Change per level">${modifiers.join("")}</dl></section>
        <section class="article-block"><h2>Studying under ${escape(teacher.name)}</h2>
        <p>${escape(teacher.where.replace(/[.]$/,""))}. ${escape(teacher.join)}</p></section>
        ${contentSections({sections:notes,referenceTables:lessons})}${bibliography(entry.sources)}`;
    } else {
      training = "<p>Your reading place comes before the first teacher. Show later masters to look ahead.</p>";
    }
    const title = overview ? "Master training" : "Rwolf";
    const lead = overview ? "Compare growth and find the skills each apprentice can learn." : "Find him on the ridge west of Chamba.";
    const links = teacher ? [teacher.id,...(teacher.id === "teacher-rwolf" ? ["kurok"] : []),...teacher.links] : ["apprentices"];
    return banner(title,lead,overview ? volume.title : "Master · South Desert","iv-training",true) +
      `<div class="leaf columns"><article>${training}${controls()}</article>
      <aside class="sidebar"><h2>Apprenticeship</h2>${showReveal("Show later masters")}
      ${articleLinks(links,teacher?.unlock)}
      ${overview && roster.length ? `<details data-panel="teachers"><summary>Master roster</summary>${listed(roster.map(t=>({id:t.id,title:t.name,description:t.where})))}</details>` : ""}</aside></div>`;
  }
  function searchPage() {
    return banner("Search the guide","",volume.title,volume.theme,true) +
      `<div class="leaf"><form class="find" id="search"><label for="query">Place, item, enemy or skill</label>
        <input id="query" type="search" maxlength="140" autocomplete="off" value="${escape((params.get("q") || "").slice(0,140))}">
        <div class="summary"><span class="meta" id="search-count" role="status"></span>${showReveal("Show later matches")}</div></form>
        <div id="matches" class="find"></div></div>`;
  }
  function searchable(row) {
    const details = [
      row.title,row.category,row.region,row.lead,row.objective,row.hint,row.tip,...(row.aliases || []),...(row.landmarks || []),...(row.steps || []),
      ...(row.sections || []).map(s=>s.title + " " + s.text),
      ...(row.referenceTables || []).map(t=>t.title+" "+t.rows.flat().join(" ")),
      ...(row.records || []).map(r=>r.name+" "+r.where+" "+r.detail),
      ...(row.observations || []).filter(canReadObservation).map(o=>o.where+" "+o.detail),
    ];
    const local = book.fieldSheets[row.id];
    if (local) details.push(local.area,...(local.aliases || []),local.objective,...local.steps.map(s=>s.title+" "+s.body),...(local.enemies || []).map(e=>e.detail));
    return normal(details.join(" "));
  }
  function updateSearch(query) {
    const term = normal(query.trim());
    const target = $("#matches");
    if (!term) {
      $("#search-count").textContent = "";
      target.innerHTML = "";
      return;
    }
    const matches = [];
    let hidden = 0;
    for (const row of entries.values()) {
      if (!searchable(row).includes(term)) continue;
      if (!displayed(row)) { hidden++; continue; }
      const local = book.fieldSheets[row.id];
      const aliases = (row.aliases || []).concat(local ? [local.area, ...(local.aliases || [])] : []);
      const rank = searchRank(term, local?.title || row.title, aliases);
      matches.push({rank,id:row.id,title:row.title,description:row.category || row.region || "Walkthrough"});
    }
    matches.sort((a,b)=>a.rank-b.rank || a.title.localeCompare(b.title));
    $("#search-count").textContent = matches.length ? `${matches.length} ${matches.length === 1 ? "match" : "matches"}` :
      hidden ? "No matches within your reading place." : "No matching pages. Try another name.";
    target.innerHTML = matches.length ? listed(matches) : "";
  }
  function bookmarkPage() {
    const stored = reader.pins.map(id=>entries.get(id)).filter(Boolean);
    return banner("Bookmarks","",volume.title,volume.theme,true) + `<div class="leaf">
      ${stored.length ? listed(stored.map(row=>({id:row.id,title:titleOf(row.id),description:row.category || row.region}))) :
        '<p>Choose <strong>Bookmark page</strong> on a route or wiki entry to keep it here.</p>'}</div>`;
  }
  function pageContent() {
    if (!page) return volumeCover();
    if (page === "walk") return routeIndex();
    if (page === "wiki") return wiki();
    if (page === "bookmarks") return bookmarkPage();
    if (page === "search") return searchPage();
    if (sheet) return workedRoute(routePage);
    if (routePage) return ordinaryRoute(routePage);
    const row = entries.get(page);
    if (!row) return banner("Page not found","Choose a page from this volume.",volume.title,volume.theme,true) +
      `<div class="leaf">${link(href(""),"Back to the volume",'class="primary"')}</div>`;
    if (row.entity) return entityLeaf(row);
    if (game === "bof3") {
      if (page === "genes") return genePage();
      const s = specimens.find(gene=>gene.id === page);
      if (s) return specimenPage(s);
    }
    if (game === "bof4" && ["masters","rwolf"].includes(page)) return masterPage();
    return regularArticle(row);
  }
  function render() {
    document.body.dataset.game = game;
    document.body.dataset.page = page || "cover";
    $("#imprint").href = href();
    $("#search-link").href = href("search");
    $("#spine").innerHTML = sidebar();
    main.classList.toggle("detail-reading",entries.has(page));
    main.innerHTML = detailTrail() + pageContent();
    const heading = $("h1",main)?.textContent;
    document.title = (page ? heading + " · " : "") + volume.title + " · BoF Atelier Field Guide";
    if (page === "search") updateSearch($("#query").value);
  }
  function openDialog(title,body,css,opener) {
    dialogOpener = opener;
    dialog.className = css;
    $("#dialog-title").textContent = title;
    $("#dialog-body").innerHTML = body;
    dialog.showModal();
  }
  function openMap(opener) {
    const active = sheet.steps.find(s=>s.key === step);
    const buttons = sheet.steps.map(s=>button("step",s.key + ". " + s.title,"chip",
      `data-number="${s.key}" aria-pressed="${s.key === step}"`));
    openDialog(sheet.title,`<div class="map-window" tabindex="0" aria-label="Map, scroll to pan">${sheetMap(sheet)}</div>
      <div class="action-row">${buttons.join("")}</div><p id="enlarged-direction" class="direction">${escape(active.body)}</p>`,
      "map-dialog",opener);
  }
  function updateGenes() {
    for (const el of main.querySelectorAll("[data-action=gene]")) {
      el.setAttribute("aria-pressed",String(selectedGenes.has(el.dataset.gene)));
    }
    $("#result").innerHTML = recipeAnswer();
    $("[data-action=clear]").hidden = !selectedGenes.size;
  }
  function changeBoundary(buttonEl) {
    const idx = book.route.findIndex(r=>r.id === buttonEl.dataset.stop);
    if (idx < 0) return;
    reader.through = idx;
    reader.spot = page;
    reveals[game] = false;
    savePreferences();
    const open = openPanels();
    render();
    restorePanels(open);
    $("[data-action=mark]")?.focus({preventScroll:true});
    note(storageAvailable ? "Reading place saved." : "Reading place set for this session.");
  }
  function toggleBookmark(el) {
    const pinned = reader.pins.includes(page);
    reader.pins = pinned ? reader.pins.filter(id=>id !== page) : [...reader.pins,page];
    savePreferences();
    el.textContent = pinned ? "Bookmark page" : "Bookmarked";
    el.setAttribute("aria-pressed",String(!pinned));
    note(storageAvailable ? (pinned ? "Bookmark removed." : "Page bookmarked.") : "Bookmarks last for this session.");
  }

  document.addEventListener("click",event=>{
    const el = event.target.closest("button[data-action]");
    if (!el) {
      const anchor = event.target.closest("a[href]");
      if (anchor && !event.defaultPrevented && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
        if (anchor.hasAttribute("data-reading-back") && origin) {
          event.preventDefault();
          rememberReading(true,anchor);
          history.back();
          return;
        }
        const target = anchor.getAttribute("href");
        if (target.startsWith("#bof") && target !== location.hash) {
          rememberReading(true,anchor);
          if (!anchor.closest(".detail-trail")) {
            nextOrigin = {slot,address:currentAddress || href(),title:$("h1",main)?.textContent || volume.title};
          }
        }
      }
      if (event.target.closest(".skip")) { event.preventDefault(); main.focus(); }
      if (dialog.open && anchor) dialog.close();
      return;
    }
    switch (el.dataset.action) {
      case "contents": openDialog("Contents",`<div class="drawer">${sidebar()}</div>`,"contents-dialog",el); break;
      case "close": dialog.close(); break;
      case "enlarge": openMap(el); break;
      case "view": switchSection(el.dataset.view); break;
      case "step": changeStep(Number(el.dataset.number)); break;
      case "previous-step": case "next-step":
        changeStep(step + (el.dataset.action === "next-step" ? 1 : -1));
        if (el.disabled) $("#choose-step",main).focus({preventScroll:true});
        break;
      case "all-steps":
        showAllSteps = !showAllSteps;
        el.textContent = showAllSteps ? "Show selected step" : "Read all steps";
        el.setAttribute("aria-expanded",String(showAllSteps));
        changeStep(step);
        break;
      case "pin": toggleBookmark(el); break;
      case "mark": changeBoundary(el); break;
      case "reveal": {
        const buttons = [...main.querySelectorAll("[data-action=reveal]")];
        const at = buttons.indexOf(el);
        const open = openPanels();
        reveals[game] = !reveals[game];
        render();
        restorePanels(open);
        const sightings = main.querySelector("[data-panel=sightings]");
        if (sightings && reveals[game]) sightings.open = true;
        main.querySelectorAll("[data-action=reveal]")[Math.max(0,at)]?.focus({preventScroll:true});
        break;
      }
      case "gene": {
        const id = el.dataset.gene;
        if (selectedGenes.has(id)) selectedGenes.delete(id); else selectedGenes.add(id);
        updateGenes(); break;
      }
      case "clear": selectedGenes.clear(); updateGenes(); $("[data-action=gene]").focus(); break;
      case "mix": selectedGenes.clear(); selectedGenes.add(el.dataset.gene); location.hash = href("genes"); break;
    }
  });
  dialog.addEventListener("close",()=>{
    if (dialogOpener?.isConnected) dialogOpener.focus({preventScroll:true});
    dialogOpener = null;
    $("#dialog-body").replaceChildren();
  });
  main.addEventListener("change",event=>{
    const control = event.target.id;
    if (control === "choose-step") {
      changeStep(Number(event.target.value));
      return;
    }
    if (control === "apprentice" || control === "compare-master") {
      if (control === "apprentice") selectedMaster = event.target.value; else comparisonMaster = event.target.value;
      render();
      $("#" + control).focus({preventScroll:true});
      note("Growth comparison updated.");
      return;
    }
    if (control !== "floor") return;
    const next = new URLSearchParams(params);
    next.set("floor",event.target.value);
    next.set("map",event.target.selectedOptions[0].dataset.map);
    next.set("section",event.target.selectedOptions[0].dataset.section);
    if (area) next.set("area",area.name);
    replaceReadingAddress(next);
    render();
    $("#floor").focus({preventScroll:true});
  });
  main.addEventListener("input",event=>{
    if (event.target.id !== "query") return;
    const value = event.target.value.slice(0,140);
    replaceReadingAddress(new URLSearchParams(value ? {q:value} : {}));
    updateSearch(value);
  });
  main.addEventListener("submit",event=>{
    if (event.target.id === "search") { event.preventDefault(); updateSearch($("#query").value); }
  });
  document.addEventListener("keydown",event=>{
    const tab = event.target.closest("[role=tab][data-view]");
    if (tab && ["ArrowRight","ArrowLeft","Home","End"].includes(event.key)) {
      event.preventDefault();
      const tabs = [...tab.parentElement.querySelectorAll("[role=tab]")];
      const position = tabs.indexOf(tab);
      const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs.at(-1) :
        tabs[(position + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
      switchSection(next.dataset.view);
      next.focus();
      return;
    }
    if (event.key === "/" && !event.ctrlKey && !event.altKey && !event.metaKey &&
        !event.target.closest("input,select,textarea,[contenteditable=true]")) {
      event.preventDefault();
      if (dialog.open) dialog.close();
      if (page === "search") $("#query").focus(); else location.hash = href("search");
    }
  });
  function focusIdentity(element) {
    if (!element) return "";
    return element.id || (element.matches("a[href]") ? element.getAttribute("href") :
      element.matches("summary") ? "summary:" + element.parentElement.dataset.panel :
      element.dataset.action ? [element.dataset.action,element.dataset.number,element.dataset.view,element.dataset.gene].join(":") :
      element.dataset.record ? "row:" + element.dataset.record : "");
  }
  function matchingFocus(key) {
    if (!key) return [];
    return [...main.querySelectorAll("a[href],button[data-action],summary,input,select,[data-record]")].filter(el=>focusIdentity(el) === key);
  }
  function openPanels() {
    return [...main.querySelectorAll("details[open][data-panel]")].map(el=>el.dataset.panel);
  }
  function restorePanels(open) {
    for (const el of main.querySelectorAll("details[data-panel]")) el.open = open.includes(el.dataset.panel);
  }
  function readingSnapshot(target = document.activeElement) {
    const key = focusIdentity(target);
    return {step,showAllSteps,section:readingSection,scroll:scrollY,
      focus:key,index:matchingFocus(key).indexOf(target),open:openPanels()};
  }
  function rememberReading(persist,target) {
    if (!slot) return;
    const view = readingSnapshot(target);
    readingHistory.set(slot,view);
    if (persist && currentAddress === location.hash)
      history.replaceState({atelierReading:{slot,address:currentAddress,origin,view}},"");
  }
  function replaceReadingAddress(next) {
    params = next;
    currentAddress = href(page,Object.fromEntries(next));
    const view = readingSnapshot();
    readingHistory.set(slot,view);
    history.replaceState({atelierReading:{slot,address:currentAddress,origin,view}},"",currentAddress);
  }
  function navigate(event) {
    if (event && !nextOrigin) rememberReading(false);
    const stored = history.state?.atelierReading;
    const entry = stored?.address === location.hash ? stored : null;
    slot = entry?.slot || historySession + "-" + (++slotCount);
    origin = entry ? entry.origin : nextOrigin;
    nextOrigin = null;
    readAddress();
    currentAddress = location.hash;
    const last = readingHistory.get(slot) || entry?.view;
    readingSection = last?.section || params.get("view") || (params.has("floor") ? "floors" : "");
    if (!readingSection && params.has("entry") && routePage) {
      const name = params.get("entry");
      readingSection = areaRecords(routePage,area,"items",sheet).some(item=>item.name === name) ? "items" : "enemies";
    }
    const requestedStep = Number(params.get("step"));
    const availableSteps = routeSteps();
    step = [last?.step,requestedStep,sheet?.id === "kurok" ? 2 : 1]
      .find(n=>availableSteps.some(s=>s.key === n)) || availableSteps[0]?.key;
    showAllSteps = last?.showAllSteps || false;
    if (dialog.open) dialog.close();
    render();
    if (last) restorePanels(last.open);
    const rows = params.has("entry") ? [...main.querySelectorAll("[data-record]")].filter(el=>el.dataset.record === params.get("entry") && !el.closest("[hidden]")) : [];
    const found = rows.find(el=>el.dataset.sighting === params.get("sighting")) || rows[0];
    if (found) found.dataset.found = "true";
    if (last) {
      const target = matchingFocus(last.focus)[last.index];
      (target || main).focus({preventScroll:true});
      window.scrollTo(0,last.scroll);
    } else if (found) {
      found.focus();
      found.scrollIntoView({block:"center"});
    } else if (page === "search") {
      $("#query").focus({preventScroll:true});
    } else if (event) {
      main.focus({preventScroll:true});
      window.scrollTo(0,0);
    }
    rememberReading(true);
  }
  window.addEventListener("pagehide",()=>rememberReading(true));
  window.addEventListener("hashchange",navigate);
  if ("scrollRestoration" in history) history.scrollRestoration = "manual";
  $("#download-guide").hidden = !["http:","https:"].includes(location.protocol);
  navigate();
})();
