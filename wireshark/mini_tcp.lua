-- Mini-TCP dissector for Wireshark
--
-- Teaches Wireshark to decode the 17-byte header of the Mini-TCP protocol
-- (protocol/segment.py) that rides inside UDP datagrams:
--
--   flags(1) seq(4) ack(4) window(2) length(2) crc32(4) | payload (0-1024 bytes)
--
-- It recognises our packets automatically (no port setup needed), checks the
-- CRC32 itself, and does a little connection analysis: duplicate ACKs, gaps in
-- the sequence numbers, and retransmissions that fill those gaps.
--
-- Load it with:  wireshark -X lua_script:wireshark/mini_tcp.lua  (see wireshark/README.md)

local mini_tcp = Proto("mini_tcp", "Mini-TCP (CN project)")

local HEADER_LEN  = 17
local MAX_PAYLOAD = 1024
local FLAG_SYN, FLAG_ACK, FLAG_FIN = 0x01, 0x02, 0x04

------------------------------------------------------------------------------
-- Fields (these are what you can filter on, e.g.  mini_tcp.seq == 5)
------------------------------------------------------------------------------
local f = mini_tcp.fields
f.flags    = ProtoField.uint8 ("mini_tcp.flags",   "Flags", base.HEX)
f.syn      = ProtoField.bool  ("mini_tcp.flags.syn", "SYN (open connection)", 8, nil, FLAG_SYN)
f.ack_flag = ProtoField.bool  ("mini_tcp.flags.ack", "ACK (ack field is valid)", 8, nil, FLAG_ACK)
f.fin      = ProtoField.bool  ("mini_tcp.flags.fin", "FIN (close connection)", 8, nil, FLAG_FIN)
f.seq      = ProtoField.uint32("mini_tcp.seq",     "Sequence number")
f.ack      = ProtoField.uint32("mini_tcp.ack",     "Acknowledgement number")
f.window   = ProtoField.uint16("mini_tcp.window",  "Advertised window (packets)")
f.length   = ProtoField.uint16("mini_tcp.length",  "Payload length")
f.crc      = ProtoField.uint32("mini_tcp.crc",     "CRC32", base.HEX)
f.crc_ok   = ProtoField.bool  ("mini_tcp.crc.good", "CRC32 correct")
f.payload  = ProtoField.bytes ("mini_tcp.payload", "Payload")
f.dup_ack  = ProtoField.bool  ("mini_tcp.dup_ack", "Duplicate ACK")
f.dup_cnt  = ProtoField.uint32("mini_tcp.dup_ack_count", "Duplicate ACK number")
f.gap      = ProtoField.uint32("mini_tcp.gap",     "Segments missing before this one")
f.fill     = ProtoField.bool  ("mini_tcp.gap_fill", "Arrived late: fills an earlier gap (retransmission or reordering)")
f.dup_data = ProtoField.bool  ("mini_tcp.dup_data", "Data delivered twice")

-- Expert info shows up in Analyze > Expert Information and colours the packet list.
local ei_bad_crc  = ProtoExpert.new("mini_tcp.bad_crc",  "CRC32 mismatch: packet was corrupted",
                                    expert.group.CHECKSUM, expert.severity.ERROR)
local ei_dup_ack  = ProtoExpert.new("mini_tcp.dup_ack_ei", "Duplicate ACK: receiver is missing a segment",
                                    expert.group.SEQUENCE, expert.severity.NOTE)
local ei_gap      = ProtoExpert.new("mini_tcp.gap_ei",  "Gap: earlier segment(s) did not arrive (lost or reordered)",
                                    expert.group.SEQUENCE, expert.severity.WARN)
local ei_fill     = ProtoExpert.new("mini_tcp.fill_ei", "Late segment fills a gap: a retransmission (or reordering)",
                                    expert.group.SEQUENCE, expert.severity.NOTE)
local ei_dup_data = ProtoExpert.new("mini_tcp.dup_data_ei", "Same sequence number delivered twice",
                                    expert.group.SEQUENCE, expert.severity.WARN)
mini_tcp.experts = { ei_bad_crc, ei_dup_ack, ei_gap, ei_fill, ei_dup_data }

mini_tcp.prefs.port = Pref.uint("Always decode this UDP port", 0,
    "Optional. Mini-TCP is normally recognised automatically; set a port here only to force it. 0 = off.")

------------------------------------------------------------------------------
-- CRC32 (same algorithm as Python's zlib.crc32)
------------------------------------------------------------------------------
local bxor, band, rshift
if bit32 then
    bxor, band, rshift = bit32.bxor, bit32.band, bit32.rshift
elseif bit then
    bxor, band, rshift = bit.bxor, bit.band, bit.rshift
else
    local ok, chunk = pcall(load, "return function(a,b) return a ~ b end, " ..
                                  "function(a,b) return a & b end, " ..
                                  "function(a,n) return a >> n end")
    if ok and chunk then bxor, band, rshift = chunk() end
end

local crc_table = {}
if bxor then
    for i = 0, 255 do
        local c = i
        for _ = 1, 8 do
            if band(c, 1) == 1 then
                c = bxor(0xEDB88320, rshift(c, 1))
            else
                c = rshift(c, 1)
            end
        end
        crc_table[i] = c % 4294967296
    end
end

local function crc32(bytes)
    local crc = 0xFFFFFFFF
    for i = 1, #bytes do
        crc = bxor(crc_table[band(bxor(crc, bytes:byte(i)), 0xFF)], rshift(crc, 8)) % 4294967296
    end
    return bxor(crc, 0xFFFFFFFF) % 4294967296
end

-- The sender computes the CRC with the crc field set to zero, so we do the same.
local function packet_crc(buf)
    local raw = buf:raw(0, buf:len())
    return crc32(raw:sub(1, 13) .. "\0\0\0\0" .. raw:sub(18))
end

------------------------------------------------------------------------------
-- Tiny per-direction connection analysis (reset every time a file is opened)
------------------------------------------------------------------------------
local flows, analysis_cache

local function reset_state()
    flows, analysis_cache = {}, {}
end
reset_state()

-- Wireshark calls this each time a capture file is opened, so old results never leak
function mini_tcp.init()
    reset_state()
end

local function analyse(pinfo, flags, seq, ack, length)
    local key = tostring(pinfo.src) .. ":" .. pinfo.src_port .. ">" ..
                tostring(pinfo.dst) .. ":" .. pinfo.dst_port
    local fl = flows[key]
    if not fl then
        fl = { max_seq = -1, seen = {}, last_ack = nil, dups = 0 }
        flows[key] = fl
    end
    local an = {}

    if length > 0 then                               -- a data segment
        if fl.seen[seq] then
            an.dup_data = true
        else
            if seq > fl.max_seq + 1 then
                an.gap = seq - fl.max_seq - 1
            elseif seq < fl.max_seq then
                an.fill = true
            end
            fl.seen[seq] = true
            if seq > fl.max_seq then fl.max_seq = seq end
        end
    elseif flags == FLAG_ACK then                    -- a pure ACK
        if fl.last_ack == ack then
            fl.dups = fl.dups + 1
            an.dup_ack = fl.dups
        else
            fl.last_ack, fl.dups = ack, 0
        end
    end
    return an
end

------------------------------------------------------------------------------
-- The dissector itself
------------------------------------------------------------------------------
-- Is this flag bit set? (plain arithmetic, so it works on every Lua version)
local function has(flags, bit)
    return math.floor(flags / bit) % 2 == 1
end

local function flag_names(flags)
    local t = {}
    if has(flags, FLAG_SYN) then t[#t + 1] = "SYN" end
    if has(flags, FLAG_FIN) then t[#t + 1] = "FIN" end
    if has(flags, FLAG_ACK) then t[#t + 1] = "ACK" end
    return t
end

function mini_tcp.dissector(buf, pinfo, tree)
    if buf:len() < HEADER_LEN then return 0 end

    local flags  = buf(0, 1):uint()
    local seq    = buf(1, 4):uint()
    local ack    = buf(5, 4):uint()
    local window = buf(9, 2):uint()
    local length = buf(11, 2):uint()
    local crc    = buf(13, 4):uint()

    local names = flag_names(flags)
    local crc_good = true                      -- assume fine if we cannot compute a CRC
    if bxor then crc_good = (packet_crc(buf) == crc) end

    -- A corrupted packet is thrown away by the receiver, so it must not count as "seen"
    -- (otherwise its good retransmission would look like a duplicate).
    local an = analysis_cache[pinfo.number]
    if not an then
        if crc_good then
            an = analyse(pinfo, flags, seq, ack, length)
        else
            an = {}
        end
        analysis_cache[pinfo.number] = an
    end

    -- Columns in the packet list
    local info
    if length > 0 then
        info = string.format("DATA  seq=%d len=%d", seq, length)
    else
        local label = (#names > 0) and table.concat(names, ",") or "EMPTY"
        info = string.format("%s", label)
        if has(flags, FLAG_SYN) or has(flags, FLAG_FIN) then info = info .. string.format("  seq=%d", seq) end
        if has(flags, FLAG_ACK) then info = info .. string.format("  ack=%d", ack) end
        if window > 0 or flags == FLAG_ACK then info = info .. string.format("  win=%d", window) end
    end
    if an.dup_ack  then info = info .. string.format("  [Dup ACK #%d]", an.dup_ack) end
    if an.gap      then info = info .. string.format("  [GAP: %d missing before]", an.gap) end
    if an.fill     then info = info .. "  [Late: fills earlier gap]" end
    if an.dup_data then info = info .. "  [Delivered twice]" end
    if not crc_good then info = info .. "  [BAD CRC]" end

    pinfo.cols.protocol:set("MINI-TCP")
    pinfo.cols.info:set(info)

    -- The tree in the details pane
    local title = "Mini-TCP"
    if #names > 0 then title = title .. ", " .. table.concat(names, "+") end
    title = title .. string.format(", Seq: %d, Ack: %d, Win: %d, Len: %d", seq, ack, window, length)
    local t = tree:add(mini_tcp, buf(0, math.min(buf:len(), HEADER_LEN + length)), title)

    local ft = t:add(f.flags, buf(0, 1))
    ft:append_text((#names > 0) and (" (" .. table.concat(names, ", ") .. ")") or " (none: a data segment)")
    ft:add(f.syn,      buf(0, 1))
    ft:add(f.ack_flag, buf(0, 1))
    ft:add(f.fin,      buf(0, 1))
    t:add(f.seq,    buf(1, 4))
    t:add(f.ack,    buf(5, 4))
    t:add(f.window, buf(9, 2))
    t:add(f.length, buf(11, 2))
    local ct = t:add(f.crc, buf(13, 4))
    if bxor then
        local ok_item = ct:add(f.crc_ok, buf(13, 4), crc_good)
        ok_item:set_generated()
        if crc_good then
            ct:append_text(" [correct]")
        else
            ct:append_text(string.format(" [INCORRECT, expected 0x%08x]", packet_crc(buf)))
            ct:add_proto_expert_info(ei_bad_crc)
        end
    end

    if length > 0 and buf:len() >= HEADER_LEN + length then
        t:add(f.payload, buf(HEADER_LEN, length))
    end

    -- Analysis (generated by this script, not in the packet itself)
    if an.dup_ack then
        local d = t:add(f.dup_ack, buf(0, 0), true); d:set_generated()
        t:add(f.dup_cnt, buf(0, 0), an.dup_ack):set_generated()
        d:add_proto_expert_info(ei_dup_ack)
    end
    if an.gap then
        local g = t:add(f.gap, buf(0, 0), an.gap); g:set_generated()
        g:add_proto_expert_info(ei_gap)
    end
    if an.fill then
        local g = t:add(f.fill, buf(0, 0), true); g:set_generated()
        g:add_proto_expert_info(ei_fill)
    end
    if an.dup_data then
        local g = t:add(f.dup_data, buf(0, 0), true); g:set_generated()
        g:add_proto_expert_info(ei_dup_data)
    end

    return buf:len()
end

------------------------------------------------------------------------------
-- How Wireshark finds our packets: look at every UDP datagram and accept the
-- ones that fit the Mini-TCP shape. Cheap, and avoids fixed port numbers
-- (our experiments use random ports).
------------------------------------------------------------------------------
local function looks_like_mini_tcp(buf)
    if buf:len() < HEADER_LEN then return false end
    if buf(0, 1):uint() > 7 then return false end            -- only SYN/ACK/FIN bits may be set
    local length = buf(11, 2):uint()
    return length <= MAX_PAYLOAD and length == buf:len() - HEADER_LEN
end

local function heuristic(buf, pinfo, tree)
    if not looks_like_mini_tcp(buf) then return false end
    mini_tcp.dissector(buf, pinfo, tree)
    return true
end
mini_tcp:register_heuristic("udp", heuristic)

-- Optional manual port (Preferences > Protocols > MINI_TCP)
local udp_table = DissectorTable.get("udp.port")
local forced_port = 0
function mini_tcp.prefs_changed()
    if forced_port ~= 0 then udp_table:remove(forced_port, mini_tcp) end
    forced_port = mini_tcp.prefs.port
    if forced_port ~= 0 then udp_table:add(forced_port, mini_tcp) end
end
