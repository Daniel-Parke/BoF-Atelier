/* Editorial sample, US PlayStation revisions. Evidence and media provenance are in
   FIELD-GUIDE-EXPERIENCE.md. No game assets, save addresses or disc tables are bundled. */
"use strict";
function searchText(value) {
  return String(value || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .toLowerCase().replace(/[’‘]/g, "'").replace(/[‐‑–-]/g, " ")
    .replace(/\b(?:mt\.?|mount)(?=\s)/g, "mount").replace(/\s+/g, " ").trim();
}
function searchRank(term, title, aliases) {
  const names = [title].concat(aliases || []).map(searchText);
  if (names.some(name => name === term)) return 0;
  if (names.some(name => name.startsWith(term + " "))) return 1;
  if (names.some(name => name.includes(term))) return 2;
  return 3;
}
const volumes = {
  iii: {
    title: "Breath of Fire III",
    number: "III",
    theme: "highlands",
    signature: "The dragon gene atlas",
    tool: "genes",
    toolTitle: "Dragon genes",
    toolNote: "Build a recipe and check its initial AP.",
    artAlt: "An illustrated copper-winged dragon above a green mountain valley",
    entries: [
      {
        id: "walk",
        title: "Walkthrough",
        detail: "Opening route, a nudge or the next step",
        terms: "story route hints opening mine movement what do I do next",
      },
      {
        id: "genes",
        title: "Dragon genes",
        detail: "Combine Flame, Frost and Thunder",
        terms:
          "dragon gene genes combination accession fusion frost thunder flame recipe chrysm AP cost transformation",
      },
      {
        id: "diary",
        title: "Using a diary",
        detail: "Write and reload an ordinary save",
        terms: "save point memory card load backup diary save game",
      },
    ],
    places: [
      {
        name: "The mine",
        chapter: "Opening",
        lead: "The opening mine is the first place you can move as the little dragon.",
        hint: "When the scene gives you control, look for something left behind by the workers.",
        step: "Approach the dropped blade and interact with it. Watch the Melted Blade event before continuing through the mine.",
        next: "The next guide stop covers your first ordinary diary save.",
      },
      {
        name: "Rei’s house",
        chapter: "First diary",
        lead: "Inside the house, the diary gives you an ordinary save you can load from the title screen.",
        hint: "Look beside Ryu for the diary.",
        step: "Face the diary and interact. Choose the first memory card, then an empty file. Wait for the game to return you to the room.",
        next: "To check the save, start the game again and choose Load Game. Select that file and confirm.",
      },
    ],
    article: {
      id: "diary",
      title: "Using a diary",
      intro: "A diary writes your adventure to a PlayStation memory card.",
      sections: [
        [
          "Write a new file",
          "Interact with the diary and choose a card. Use an empty file if you want to keep an older point.",
        ],
        [
          "Pick up your adventure",
          "Choose Continue in Atelier to open the game’s own load menu. Select the file you wrote. A compatible checkpoint has its own Resume action.",
        ],
      ],
    },
  },
  iv: {
    title: "Breath of Fire IV",
    number: "IV",
    theme: "sandsea",
    signature: "A traveller’s record",
    tool: "masters",
    toolTitle: "Master growth",
    toolNote: "Compare what changes at each level.",
    artAlt: "A sand dragon breaching above ochre dunes and a small caravan",
    entries: [
      {
        id: "walk",
        title: "Walkthrough",
        detail: "Opening route, a nudge or the next step",
        terms:
          "story route opening sandflier wreck crash hints awakening what do I do next",
      },
      {
        id: "masters",
        title: "Master growth",
        detail: "Compare six per-level modifiers",
        terms:
          "master apprentice unaffiliated rwolf comparison growth wisdom AP HP stats power",
      },
      {
        id: "dragons",
        title: "Dragons & evocation",
        detail: "Find the distinction between a form and a call",
        terms: "dragon forms evocations summon ryu transformation breath",
      },
    ],
    places: [
      {
        name: "The sandflier wreck",
        chapter: "Opening",
        lead: "Chapter I opens at the sandflier. The wreck is a field location you can return to from the world map.",
        hint: "If you are on the map, look for the location named Crash.",
        step: "Enter Crash and move away from the wreck. If you are resuming an ordinary save, check the location name on the load screen first.",
        next: "The next guide stop covers reloading on the world map.",
      },
      {
        name: "North Desert",
        chapter: "World map",
        lead: "An ordinary North Desert save returns you to the world map.",
        hint: "The starting scene after loading can differ from the field where you last walked.",
        step: "At the title screen choose Load Game, Memory Card Slot 1 and your North Desert file. Confirm, then enter Crash from the map.",
        next: "You can return to the guide to compare master growth without changing your character.",
      },
    ],
    article: {
      id: "dragons",
      title: "Dragons & evocation",
      intro:
        "IV has its own dragon system. Start with what you want to do in battle.",
      sections: [
        [
          "Change form",
          "Follow the transformation available to your current protagonist. Ryu and Fou-Lu have separate routes. This entry keeps later form names hidden.",
        ],
        [
          "Call a dragon",
          "Evocation is a separate reference topic. A stored skill record alone cannot tell you the AP a call will charge in battle. Check the battle menu before committing.",
        ],
      ],
    },
  },
};
const specimens = [
  {
    id: "flame",
    name: "Flame",
    ap: 5,
    shape: "A cluster of orange crystal points",
  },
  {
    id: "frost",
    name: "Frost",
    ap: 5,
    shape: "A fan of tall ice-blue crystal blades",
  },
  {
    id: "thunder",
    name: "Thunder",
    ap: 5,
    shape: "A forked gold mineral branching like lightning",
  },
];
const masterExamples = [
  { name: "Unaffiliated", stats: [0, 0, 0, 0, 0, 0] },
  { name: "Rwolf", stats: [0, 1, -1, 0, 0, 1] },
];
const statNames = ["HP", "AP", "Power", "Defence", "Agility", "Wisdom"];
const referenceLeaves = {
  iii: specimens.map((s) => ({
    id: s.id,
    title: s.name,
    detail: "Elemental gene · " + s.ap + " initial AP",
    terms: s.id + " elemental crystal initial ap",
  })),
  iv: [
    {
      id: "rwolf",
      title: "Rwolf",
      detail: "Master · AP, power and wisdom",
      terms: "rwolf wisdom apprenticeship master",
    },
  ],
};
