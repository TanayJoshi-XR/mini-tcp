# Phase 5: a Wireshark dissector for Mini-TCP

Wireshark is the standard tool for looking at network traffic. By default it sees our packets
as anonymous UDP blobs. `mini_tcp.lua` teaches it our protocol, so every packet is decoded into
its fields (flags, sequence number, ACK number, window, length, CRC) and the capture can be
analysed like real TCP: handshakes, duplicate ACKs, gaps, corrupted packets.

```
Before:  UDP  59 51272 -> 44138 Len=17
After:   MINI-TCP  SYN,ACK  seq=0  ack=0  win=256
```

This guide assumes you have never used Wireshark.

## Contents

1. [Wireshark in five minutes](#1-wireshark-in-five-minutes)
2. [Install the dissector](#2-install-the-dissector)
3. [Open a sample capture](#3-open-a-sample-capture-no-capturing-needed)
4. [Capture your own transfer](#4-capture-your-own-transfer)
5. [What to look for](#5-what-to-look-for-in-the-congestion-sample)
6. [Useful display filters](#6-useful-display-filters)
7. [How the dissector works](#7-how-the-dissector-works)
8. [Limits and troubleshooting](#8-limits-and-troubleshooting)

## 1. Wireshark in five minutes

**Capturing** means recording every packet that passes through a network interface. Wireshark
saves them in a `.pcap` file and lets you read them. Our experiments run on one computer, so
the interface to watch is the **loopback** (`lo0` on a Mac), the computer talking to itself.

The window has three panes:

| Pane | Shows |
|---|---|
| **Packet list** (top) | One row per packet: number, time, source, destination, protocol, info |
| **Packet details** (middle) | The selected packet broken into layers: Frame, the link layer (Loopback or Ethernet), IP, UDP, then our Mini-TCP |
| **Packet bytes** (bottom) | The raw bytes, highlighted for whichever field you click |

Two kinds of filters, easy to confuse:

- A **capture filter** decides what is recorded in the first place (set before you start).
- A **display filter** hides packets from an already-recorded capture. It is the green bar at
  the top. Almost everything in this guide uses display filters, and a green bar means the
  filter is valid.

## 2. Install the dissector

A dissector is just a script that Wireshark loads. It is written in Lua, which Wireshark has
built in.

1. In Wireshark open **Help > About Wireshark > Folders** and look at the row
   **Personal Lua Plugins**. On a Mac it is normally `~/.config/wireshark/plugins`.
2. Copy the script there. From the project folder in a terminal:

   ```bash
   mkdir -p ~/.config/wireshark/plugins
   cp wireshark/mini_tcp.lua ~/.config/wireshark/plugins/
   ```

   (Use the path shown in the Folders row if it differs.)
3. Restart Wireshark, or press **Cmd+Shift+L** (Analyze > Reload Lua Plugins).
4. Check: **Help > About Wireshark > Plugins** should list `mini_tcp.lua`.

You do not need to set any port number. The dissector looks at every UDP packet and takes the
ones shaped like Mini-TCP.

## 3. Open a sample capture (no capturing needed)

Two ready-made captures are in `wireshark/samples/`:

| File | What it contains |
|---|---|
| `congestion.pcap` | A 300 kB Reno transfer through a 4 Mbit/s bottleneck with a 30-packet buffer. 592 packets |
| `lossy.pcap` | A 40 kB transfer over a channel with 10% loss and 5% corruption. 87 packets |

Use **File > Open**. The Protocol column should say `MINI-TCP`. If it still says `UDP`, see
the troubleshooting section.

## 4. Capture your own transfer

1. Open Wireshark and double-click **Loopback: lo0** in the list of interfaces. Capturing
   starts (the shark fin is blue). If you get a permission error, log out and back in (or restart),
   because Wireshark's installer sets up capture permissions that need a reboot.
2. In the display filter bar type `mini_tcp` and press Enter, so only our packets show.
3. In a terminal in the project folder run one of:

   ```bash
   python wireshark/demo_transfer.py            # congestion: Reno over a bottleneck
   python wireshark/demo_transfer.py lossy      # loss and corrupted packets
   ```
4. When it finishes, press the red square to stop. Save with **File > Save As**.

## 5. What to look for in the congestion sample

Open `congestion.pcap`. Frame numbers below are from this exact file.

| Frames | What you are seeing |
|---|---|
| 1 to 3 | **Three-way handshake.** `SYN`, then `SYN,ACK` (the receiver advertises a window of 256), then `ACK`. Click frame 2 and look at the Flags field in the details pane |
| 4 to 23 | **Slow start.** Data arrives in bursts that double: 2 packets, then 4, then 8. This is the congestion window growing |
| 189 | First **GAP** flag: `seq=98` arrived but `seq=97` did not. The bottleneck's buffer overflowed and dropped it |
| 208 to 212 | **Duplicate ACKs.** The receiver keeps saying `ack=97` ("I still need 97"). Dup ACK #3 at frame 212 is what triggers fast retransmit |
| 287 | `seq=97` finally arrives, marked `Late: fills earlier gap`. This is the retransmission. It comes about 80 ms after the third duplicate ACK because it had to queue behind packets in the emulated bottleneck |
| 590 to 592 | **Teardown.** `FIN`, `FIN,ACK`, `ACK` |

A consistency check worth knowing: the emulator reported 16 packets dropped by the bottleneck,
and the dissector finds exactly 16 gaps and 16 late fills.
(Try `Statistics > I/O Graph`, or the filter `mini_tcp.gap`, and count.)

In `lossy.pcap`:

- Frame 22 is a data packet marked **BAD CRC**. Click it and open the CRC32 line: the
  details pane shows the value in the packet and the value it should have been.
- Frames 10 and 11 show **reordering**: `seq=7` arrives before `seq=6`, even though nothing
  was lost. This is the effect that made Go-Back-N slow in the Phase 1b benchmark.
- Frames 51 and 68 stay plain `UDP`. In both, the corruption hit the header, so the packet no
  longer looks like Mini-TCP and the dissector does not claim it.

Also try **Analyze > Expert Information**: it lists every duplicate ACK, gap and bad CRC found.

## 6. Useful display filters

| Filter | Shows |
|---|---|
| `mini_tcp` | Only Mini-TCP packets |
| `mini_tcp.flags.syn == 1` | Connection setup |
| `mini_tcp.flags.fin == 1` | Connection teardown |
| `mini_tcp.length > 0` | Data packets only |
| `mini_tcp.length == 0` | ACKs and control packets |
| `mini_tcp.seq == 97` | Every packet with sequence number 97 |
| `mini_tcp.dup_ack` | Duplicate ACKs |
| `mini_tcp.dup_ack_count >= 3` | Duplicate ACKs that trigger fast retransmit |
| `mini_tcp.gap` | Data packets that arrived after a gap |
| `mini_tcp.gap_fill` | Late packets that fill an earlier gap |
| `mini_tcp.crc.good == 0` | Corrupted packets |
| `mini_tcp.window < 100` | ACKs where the receiver's window is shrinking |

## 7. How the dissector works

Everything is in one file, `mini_tcp.lua`.

1. **Recognition.** For each UDP packet it checks three things: at least 17 bytes, only the
   SYN/ACK/FIN bits set in the flags byte, and the `length` field equal to the actual payload
   size. Packets that pass are Mini-TCP. This avoids fixed ports, since our experiments pick
   random ones.
2. **Decoding.** It reads the 17-byte header (`flags(1) seq(4) ack(4) window(2) length(2)
   crc(4)`, big-endian, matching `protocol/segment.py`) and adds each field to the tree.
3. **CRC check.** It computes CRC32 in Lua over the header (with the CRC field zeroed) plus
   the payload, the same as `zlib.crc32` in the sender, and compares.
4. **Analysis.** It keeps a little state per direction. A sequence number higher than expected
   means a gap. A lower, never-seen one means a late arrival. A sequence number seen before is
   delivered twice. A repeated ACK number is a duplicate ACK. Corrupted packets are ignored
   by this logic, because the receiver would have thrown them away.

This analysis is the same idea Wireshark's built-in TCP analysis uses, in much-simplified form.

## 8. Limits and troubleshooting

**What the capture can and cannot see.**

- In our experiments the emulated bottleneck drops packets inside the Python program, before
  they reach the network socket. So Wireshark never sees a lost packet; it sees the *effects*:
  gaps, duplicate ACKs and late retransmissions.
- The capture point is effectively at the far end of the emulated link, so timestamps include
  the queueing delay. That is why a retransmission can seem slow.
- The payload is shown as raw bytes. It is file data, so there is nothing to decode.

**Problems.**

| Symptom | Fix |
|---|---|
| Protocol column says `UDP`, not `MINI-TCP` | The plugin is not loaded. Check the Folders path, put `mini_tcp.lua` there, press Cmd+Shift+L, and look for a Lua error under **Help > About Wireshark > Plugins** or in the terminal if you started Wireshark from there |
| A few packets stay `UDP` | Normal in `lossy.pcap`: corruption hit the header |
| `Permission denied` on the interface | Log out and back in (or restart) after installing Wireshark |
| Nothing is captured | Select **Loopback: lo0**, not Wi-Fi, since all traffic here stays on your own computer |
| Lua does nothing when run with `sudo` | Wireshark disables Lua scripts when run as root. Run it normally |
| Want it on a fixed port too | Preferences > Protocols > MINI_TCP, set "Always decode this UDP port" |

Tested with Wireshark/TShark 4.2 (Lua 5.2) against real captures of this project's transfers.
