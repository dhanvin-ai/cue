import { Disc, MessageCircle, Mic, MicOff, MonitorUp, ShieldCheck, SmilePlus, Users, VideoOff } from "lucide-react";
import { AiTag, Brand, CueFace, Waveform, Window, people, type PersonId } from "../kit";
import { camera, mix, prog, wordsShown } from "../lib";

const START = 498;

const shots = [
  { f: 498, x: 960, y: 519, s: 1 },
  { f: 530, x: 980, y: 530, s: 1.04 },
  { f: 564, x: 1080, y: 560, s: 1.1 },
  { f: 590, x: 960, y: 600, s: 0.74 },
  { f: 600, x: 960, y: 600, s: 0.74 },
];

const SPEECH = { text: "Hi Dana, I'm Cue, Priya's AI teammate. I'll send notes to both teams after the call.", start: 538, per: 2.5 };
const ZOOM_GREEN = "#3ccf6b";

const W = 1520;
const H = 590;
const GAP = 8;
const tile = { w: (W - GAP) / 2, h: (H - GAP) / 2 };
const slots: { id: PersonId | "cue"; x: number; y: number }[] = [
  { id: "dana", x: 0, y: 0 },
  { id: "marcus", x: tile.w + GAP, y: 0 },
  { id: "priya", x: 0, y: tile.h + GAP },
  { id: "cue", x: tile.w + GAP, y: tile.h + GAP },
];

function speaking(f: number) {
  const words = SPEECH.text.split(" ").length;
  return prog(f, SPEECH.start - 4, 6) * (1 - prog(f, SPEECH.start + words * SPEECH.per, 8));
}

function ZoomTile({ id, x, y, f }: { id: PersonId | "cue"; x: number; y: number; f: number }) {
  const cue = id === "cue";
  const join = cue ? prog(f, 520, 18) : 1;
  const level = cue ? speaking(f) : 0;
  const name = cue ? "Cue" : people[id].name;
  return (
    <div
      className="absolute grid place-items-center overflow-hidden rounded-[14px] bg-[#242424]"
      style={{
        left: x,
        top: y,
        width: tile.w,
        height: tile.h,
        opacity: join,
        scale: `${mix(0.88, 1, join)}`,
        boxShadow: `inset 0 0 0 ${4 * level}px ${ZOOM_GREEN}`,
      }}
    >
      {cue ? (
        <div className="flex flex-col items-center gap-4">
          <CueFace size={104} ring={level * (0.75 + 0.25 * Math.sin(f / 4))} />
          <Waveform f={f} level={level} bars={9} height={28} width={6} gap={5} color={level > 0.05 ? "#d9f25c" : "#5c5c5c"} />
        </div>
      ) : (
        <span className="text-[46px] font-semibold tracking-[-0.02em] text-white">{name}</span>
      )}
      <span className="absolute bottom-3 left-3 flex items-center gap-2 rounded-[8px] bg-black/60 px-2.5 py-1.5 text-[17px] text-white">
        {cue ? (level > 0.05 ? <Mic className="size-4 text-white" /> : <Mic className="size-4 text-white/80" />) : <MicOff className="size-4 text-[#ff5c5c]" />}
        {name}
        {cue && <AiTag size={11} />}
      </span>
    </div>
  );
}

function Toolbar() {
  const item = (Icon: typeof Mic, label: string, accent?: string) => (
    <span className="flex w-[104px] flex-col items-center gap-1.5 text-[14px] text-white/80">
      <span className={accent ? "grid size-9 place-items-center rounded-[10px]" : ""} style={{ background: accent }}>
        <Icon className="size-7" />
      </span>
      {label}
    </span>
  );
  return (
    <div className="absolute inset-x-0 bottom-0 flex h-[96px] items-center bg-[#1a1a1a] px-6">
      <div className="flex">
        {item(Mic, "Mute")}
        {item(VideoOff, "Start Video")}
      </div>
      <div className="flex flex-1 justify-center">
        {item(ShieldCheck, "Security")}
        {item(Users, "Participants")}
        {item(MessageCircle, "Chat")}
        {item(MonitorUp, "Share", ZOOM_GREEN)}
        {item(Disc, "Record")}
        {item(SmilePlus, "Reactions")}
      </div>
      <span className="rounded-[10px] bg-[#e5372f] px-6 py-2.5 text-[17px] font-semibold text-white">End</span>
    </div>
  );
}

export function ZoomScene({ f }: { f: number }) {
  if (f < START) return null;

  const enter = prog(f, 498, 28);
  const toast = prog(f, 522, 12) * (1 - prog(f, 556, 12));
  const shown = SPEECH.text.split(" ").slice(0, wordsShown(f, SPEECH.start, SPEECH.text, SPEECH.per)).join(" ");
  const captionIn = prog(f, SPEECH.start, 6);
  const finale = prog(f, 570, 18);

  return (
    <>
      <div className="absolute inset-0" style={camera(f, shots)}>
        <Window
          dark
          style={{ opacity: enter, translate: `${mix(420, 0, enter)}px 0`, scale: `${mix(0.94, 1, enter)}`, background: "#111" }}
          bar={
            <>
              <span className="flex items-center gap-3 text-[20px] font-medium">
                <Brand name="zoom" size={26} />
                Fieldstone × Your team · Weekly
              </span>
              <span className="ml-auto flex items-center gap-2 text-[17px] text-white/45">
                <ShieldCheck className="size-5" style={{ color: ZOOM_GREEN }} />
                Zoom Meeting
              </span>
            </>
          }
        >
          <div className="absolute left-5 top-4" style={{ width: W, height: H }}>
            {slots.map((s) => (
              <ZoomTile key={s.id} {...s} f={f} />
            ))}
            <span
              className="absolute left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-[12px] bg-[#2d2d2d] py-2 pl-2 pr-5 text-[18px] text-white shadow-lg ring-1 ring-white/10"
              style={{ opacity: toast, top: mix(2, 14, toast) }}
            >
              <CueFace size={34} round={false} />
              <span>
                <span className="font-semibold">Cue (AI teammate)</span> joined the meeting
              </span>
            </span>
          </div>
          {f >= SPEECH.start && (
            <div
              className="absolute left-1/2 top-[620px] w-[980px] -translate-x-1/2 rounded-[10px] bg-black/75 px-6 py-3 text-center text-[26px] leading-[38px] text-white"
              style={{ opacity: captionIn }}
            >
              <span className="font-semibold text-white/60">Cue: </span>
              {shown}
            </div>
          )}
          <Toolbar />
        </Window>
      </div>

      {/* Closing line */}
      <div
        className="absolute inset-x-0 top-[842px] flex flex-col items-center gap-4"
        style={{ opacity: finale, translate: `0 ${mix(26, 0, finale)}px` }}
      >
        <p className="text-[58px] font-semibold leading-none tracking-[-0.05em] text-ink">
          Same teammate.{" "}
          <span className="relative inline-block">
            <span
              className="absolute -inset-x-[0.12em] bottom-[-0.04em] top-[0.12em] -z-10 origin-left rounded-[0.25em] bg-lime-soft"
              style={{ scale: `${prog(f, 580, 14)} 1` }}
            />
            Every meeting.
          </span>
        </p>
        <p className="flex items-center gap-5 text-[22px] font-medium text-ink-soft">
          <span className="flex items-center gap-2.5">
            <Brand name="google-meet" size={28} /> Google Meet
          </span>
          <span className="text-faint">·</span>
          <span className="flex items-center gap-2.5">
            <Brand name="zoom" size={28} /> Zoom
          </span>
        </p>
      </div>
    </>
  );
}
