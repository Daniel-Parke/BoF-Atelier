"""Use the pinned PCSX-Redux Lua API in an isolated Windows reference session."""
from __future__ import annotations

from pathlib import Path
import re

from .checkpoints import Checkpoint
from .local_store import atomic_bytes

SCANCODES = {"F3": 60, "F4": 61, "F7": 64, "F9": 66}

# The emulator receives source-owned code and fixed private filenames only.
LUA = r"""
local quickKey, suspendKey = QUICK_KEY, SUSPEND_KEY
local bit = require('bit')
local uv = luv
local ready = false
local frames = 0
local held = {}
local awaitingLoad = false
local function writeWitness()
    local witness = assert(io.open('atelier-resumed', 'wb'))
    witness:close()
end
atelierCheckpointLoaded = PCSX.Events.createEventListener('ExecutionFlow::SaveStateLoaded', function()
    if awaitingLoad then
        awaitingLoad = false
        ready = true
        PCSX.nextTick(writeWitness)
    end
end)
local function save(kind)
    local pending = kind .. '.pending'
    local state = PCSX.createSaveState()
    local bytes = state.size
    assert(bytes > 0 and bytes <= 64 * 1024 * 1024, 'Unexpected checkpoint size')
    local file = Support.File.open(pending, 'TRUNCATE')
    file:writeMoveSlice(state)
    file:close()
    assert(assert(uv.fs_stat(pending)).size == bytes, 'Incomplete checkpoint write')
    assert(uv.fs_rename(pending, kind .. '.state'))
    print('Atelier checkpoint saved: ' .. kind)
end
atelierCheckpointReady = PCSX.Events.createEventListener('GPU::Vsync', function()
    frames = frames + 1
    if frames == 150 and awaitingLoad then
        print('Atelier checkpoint rejected: load was not acknowledged')
        PCSX.nextTick(function() PCSX.quit(2) end)
    end
    if frames ~= 25 then return end
    PCSX.nextTick(function()
        local ok, reason = pcall(function()
            if RESTORE_STATE then
                local file = Support.File.open('atelier-resume.state')
                awaitingLoad = true
                local accepted = PCSX.loadSaveState(file)
                file:close()
                assert(accepted ~= false, 'The emulator rejected the checkpoint')
            else
                ready = true
            end
        end)
        if not ok then
            print('Atelier checkpoint rejected: ' .. tostring(reason))
            PCSX.quit(2)
            return
        end
    end)
end)
atelierCheckpointKeys = PCSX.Events.createEventListener('Keyboard', function(event)
    local key = event.scancode
    if key ~= quickKey and key ~= suspendKey then return end
    if event.action == 1 then
        -- Ignore toggle locks. Shift/Ctrl/Alt/GUI combinations belong to the runtime.
        if bit.band(event.mods, 0x0FC3) == 0 then held[key] = true end
        return
    end
    if event.action ~= 0 then return end
    local pressed = held[key]
    held[key] = nil
    if not (pressed and ready) then return end
    PCSX.nextTick(function()
        local kind = key == suspendKey and 'suspend' or 'quick'
        local ok, reason = pcall(save, kind)
        if not ok then
            print('Atelier checkpoint failed: ' .. tostring(reason))
        elseif kind == 'suspend' then
            PCSX.quit(0)
        end
    end)
end)
"""


# The verified US IV executable and its AREAE005 overlay provide these fields.
# Read only the active leader, that leader's world-node row and the loaded story.
# The Lua host publishes a small session-local record. It never writes guest RAM.
VISIT_LUA = r"""
do
local token = 'VISIT_TOKEN'
local fresh, seed = NEW_CAMPAIGN, VISIT_SEED
local seen = {}
local frame, epoch, sequence, arrival = 0, 0, 0, 0
local started, trusted = false, false
local needsRetry, retryAt, retryDelay = false, 0, 1
local node, x, z, visit = -1, -1, -1, 'away'
local map, section, scenario, progress = -1, -1, -1, 0
local clockMinutes, candidate, candidateFrames = nil, nil, 0
local lastSignature = nil
local function noted(index)
    local byte = math.floor(index / 8) + 1
    return bit.band(seen[byte] or 0, 2 ^ (index % 8)) ~= 0
end
local function mark(index)
    local byte = math.floor(index / 8) + 1
    seen[byte] = bit.bor(seen[byte] or 0, 2 ^ (index % 8))
end
local function publish(force)
    local signature = table.concat({epoch, node, map, section, scenario, progress, visit,
                                   tostring(trusted)}, ':')
    local changed = signature ~= lastSignature
    if changed then
        -- Even if the disk is temporarily locked, A -> B -> A is a new visit.
        lastSignature, arrival = signature, frame
    end
    if not (changed or force or needsRetry) or (needsRetry and frame < retryAt) then return end
    local bits = {}
    for i = 1, 14 do bits[i] = string.format('%02x', seen[i] or 0) end
    sequence = sequence + 1
    local file = assert(io.open('guide-visits.pending', 'wb'))
    local ok = file:write(string.format(
        '{"version":1,"token":"%s","frame":%d,"epoch":%d,"sequence":%d,"arrival":%d,"node":%d,"tile":[%d,%d],"map":%d,"section":%d,"scenario":%d,"progress":%.0f,"visit":"%s","seen":"%s","trusted":%s}',
        token, frame, epoch, sequence, arrival, node, x, z, map, section, scenario, progress, visit,
        table.concat(bits), tostring(trusted)))
    local closed = file:close()
    assert(ok and closed and luv.fs_rename('guide-visits.pending', 'guide-visits.json'))
    if needsRetry and luv.fs_stat('guide-visits.blocked') then
        assert(luv.fs_unlink('guide-visits.blocked'))
    end
    needsRetry, retryDelay = false, 1
end
local function safelyPublish(force)
    if not pcall(publish, force) then
        if not needsRetry then print('Atelier Field Guide: waiting for visit history storage') end
        needsRetry, retryAt = true, frame + retryDelay
        retryDelay = math.min(120, retryDelay * 2)
        -- A Windows reader can briefly deny replacement. Even if it denies
        -- deletion as well, the Player rejects the old JSON while marked.
        local marker = io.open('guide-visits.blocked', 'wb')
        if marker then marker:close() end
        luv.fs_unlink('guide-visits.json')
    end
end
local function away()
    node, x, z, visit = -1, -1, -1, 'away'
end
local function discontinuity()
    fresh, seed, trusted = false, nil, false
    seen, clockMinutes, candidate, candidateFrames = {}, nil, nil, 0
    epoch = epoch + 1
    started = false
    map, section, scenario, progress = -1, -1, -1, 0
    away()
    safelyPublish(true)
end
local function observe()
    frame = frame + 1
    local mem = PCSX.getMemPtr()
    local function u8(a) return tonumber(mem[a]) end
    local function u16(a) return u8(a) + 256 * u8(a + 1) end
    local function u32(a) return u16(a) + 65536 * u16(a + 2) end
    local mode = u16(0x114850)
    local gameOverlay = u32(0x18d800)
    if started and (mode == 0 or gameOverlay ~= 0x0e) then
        discontinuity() -- title, new game, ordinary reload or game overlay replacement
        return
    end
    if gameOverlay ~= 0x0e then return end
    local minutes = 60 * u32(0x11ad90) + u8(0x11ad94)
    if clockMinutes and (minutes < clockMinutes or minutes > clockMinutes + 1) then
        discontinuity()
        return
    end
    if started then clockMinutes = minutes end
    -- Menus, battle and camera/Shift cursors do not themselves move the leader.
    if (mode ~= 2 and mode ~= 4) or u32(0x1cc800) ~= 0x0f then
        if started and frame % 120 == 0 then safelyPublish(true) end
        return
    end
    local location, room, stage = u16(0x11c944), u8(0x11c946), u8(0x11b7c0)
    if location < 0x0200 or location > 0x10ff or stage > 31 then return end
    local leader = u8(0x1172af)
    if leader > 2 then return end
    local actor = 0x116fb0 + 0xfc * leader
    local cellX, cellZ = u16(actor + 14), u16(actor + 22)
    local flags = u32(0x11b7d0 + 4 * stage)
    local world = location == 0x0805 and room == 0
    local index = -1
    if world then
        -- The Shift cursor and last field exit can each refer to a different town.
        local pointer = u32(0x11b728)
        local offset = pointer - 0x800fae9c
        if offset >= 0 and offset < 108 * 20 and offset % 20 == 0 then
            local row = 0x0fae9c + offset
            if u8(row) == cellX and u8(row + 1) == cellZ then index = offset / 20 end
        end
        -- Browsing a distant node on the map keeps the actor at the current one.
        if node >= 0 and cellX == x and cellZ == z then index = node end
    end
    -- Reject transient rows during a field or map load. A stationary visit
    -- keeps its starting frame so the Player can bracket an ordinary save.
    local key = location * 65536 + room * 256 + index + 1
    if key ~= candidate then candidate, candidateFrames = key, 1; return end
    candidateFrames = candidateFrames + 1
    if candidateFrames < 3 then return end
    if not started then
        -- While a world save loads, the pointer and actor arrive on different frames.
        if world and index < 0 then return end
        local match = seed and seed.map == location and seed.section == room and
                      seed.scenario == stage and seed.progress == flags and seed.node == index and
                      u8(0x11b7c1) == room and u16(0x11b7c2) == location and
                      u16(0x11b7c4) == seed.x and u16(0x11b7c6) == seed.z and
                      (not world or (seed.x == cellX and seed.z == cellZ))
        -- The first field of a blank US campaign is the sandflier introduction.
        -- A plausible early save loaded from some other card has no such provenance.
        trusted = match == true or (fresh and location == 0x081e and room == 0 and
                                     stage == 0 and flags == 0 and minutes <= 4)
        started, clockMinutes = true, minutes
        if match then
            for i=1,14 do seen[i] = tonumber(seed.seen:sub(2*i-1,2*i), 16) end
        end
        if world then
            node, x, z = index, cellX, cellZ
            if match then visit = seed.first and 'arrived' or 'returned'
            elseif trusted then visit = 'arrived'
            else visit = 'baseline' end
            mark(index)
        end
        seed, fresh = nil, false
    elseif index < 0 then
        away()
    elseif index ~= node then
        visit = noted(index) and 'returned' or 'arrived'
        node, x, z = index, cellX, cellZ
        mark(index)
    end
    map, section, scenario, progress = location, room, stage, flags
    safelyPublish(frame % 120 == 0)
end
atelierVisitFrames = PCSX.Events.createEventListener('GPU::Vsync', function()
    observe()
    if needsRetry and frame >= retryAt then safelyPublish(true) end
end)
atelierVisitRestore = PCSX.Events.createEventListener('ExecutionFlow::SaveStateLoaded', discontinuity)
atelierVisitReset = PCSX.Events.createEventListener('ExecutionFlow::Reset', function()
    if frame > 0 then discontinuity() end
end)
atelierVisitDisc = PCSX.Events.createEventListener('IsoMounted', function()
    if frame > 0 then discontinuity() end
end)
safelyPublish(true)
end
"""


def _lua_seed(seed: dict | None) -> str:
    """Render fixed keys and bounded numeric literals from a verified card receipt."""
    if not isinstance(seed, dict):
        return "nil"
    bits = seed.get("seen")
    if not isinstance(bits, str) or not re.fullmatch(r"[0-9a-f]{26}0[0-9a-f]", bits):
        return "nil"
    tile = seed.get("tile")
    if not isinstance(tile, (list, tuple)) or len(tile) != 2 or type(seed.get("first")) is not bool:
        return "nil"
    values = {key: seed.get(key) for key in ("node", "map", "section", "scenario", "progress")}
    values.update(x=tile[0], z=tile[1])
    bounds = {"node": (-1, 107), "map": (0, 65535), "section": (0, 255), "scenario": (0, 31),
              "progress": (0, 0xffffffff), "x": (0, 65535), "z": (0, 65535)}
    if any(type(n) is not int or not bounds[key][0] <= n <= bounds[key][1] for key, n in values.items()):
        return "nil"
    index = values["node"]
    if index >= 0 and not bytes.fromhex(bits)[index // 8] & (1 << (index % 8)):
        return "nil"
    fields = [f"{key}={value}" for key, value in values.items()]
    return "{" + ",".join(fields + [f"seen='{bits}'", "first=" + str(seed['first']).lower()]) + "}"


def prepare(directory: Path, keys: dict[str, str] | None, checkpoint: Checkpoint | None, *,
            visit_token: str | None = None, new_campaign: bool = False, visit_seed: dict | None = None) -> Path:
    if checkpoint is not None:
        if keys is None:
            raise ValueError("Checkpoint restore requires the managed controls.")
        atomic_bytes(directory / "atelier-resume.state", checkpoint.state)
    source = ""
    if keys is not None:
        source = LUA.replace("QUICK_KEY", str(SCANCODES[keys["quick"]])).replace(
            "SUSPEND_KEY", str(SCANCODES[keys["suspend"]])
        ).replace("RESTORE_STATE", "true" if checkpoint is not None else "false")
    if visit_token is not None:
        if not isinstance(visit_token, str) or not re.fullmatch(r"[0-9a-f]{32}", visit_token):
            raise ValueError("Invalid session visit token.")
        observer = VISIT_LUA.replace("VISIT_TOKEN", visit_token).replace(
            "NEW_CAMPAIGN", str(new_campaign is True and checkpoint is None and visit_seed is None).lower()
        ).replace("VISIT_SEED", _lua_seed(visit_seed if checkpoint is None else None))
        source += "\nlocal bit = require('bit')\n" + observer
    script = directory / "atelier-checkpoints.lua"
    atomic_bytes(script, source.encode("ascii"))
    return script
