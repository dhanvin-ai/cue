import { Check, FileText } from "lucide-react";
import { AiTag, Brand, CueFace, Face, type PersonId } from "../kit";
import { camera, mix, prog } from "../lib";

const START = 414;
const END = 524;

const shots = [
  { f: 414, x: 960, y: 540, s: 1.06 },
  { f: 500, x: 960, y: 540, s: 1 },
  { f: 524, x: 960, y: 540, s: 1 },
];

const actions: { who: PersonId; text: string; due: string; at: number }[] = [
  { who: "arjun", text: "Fix the payment-webhook test", due: "Fri", at: 440 },
  { who: "sam", text: "Rotate the Stripe key", due: "Today", at: 445 },
  { who: "priya", text: "Confirm the Monday date with Dana", due: "Thu", at: 450 },
];

function Label({ children }: { children: string }) {
  return <p className="text-[14px] font-semibold uppercase tracking-[0.12em] text-faint">{children}</p>;
}

/** Fades and lifts a block in at frame `at`. */
const reveal = (f: number, at: number) => {
  const p = prog(f, at, 14);
  return { opacity: p, translate: `0 ${mix(14, 0, p)}px` };
};

function Sent({ f, at }: { f: number; at: number }) {
  const p = prog(f, at, 10);
  return (
    <span
      className="flex items-center gap-1.5 rounded-full bg-lime px-3 py-1 text-[14px] font-semibold text-ink"
      style={{ opacity: p, scale: `${mix(0.7, 1, p)}` }}
    >
      <Check className="size-4" strokeWidth={3} /> Sent
    </span>
  );
}

/** A delivery card flying out from behind the notes to its resting spot. */
const fly = (f: number, at: number, fromX: number, fromY: number) => {
  const p = prog(f, at, 26);
  return {
    opacity: prog(f, at, 10),
    translate: `${mix(fromX, 0, p)}px ${mix(fromY, 0, p)}px`,
    scale: `${mix(0.6, 1, p)}`,
    rotate: `${mix(fromX > 0 ? 6 : -6, 0, p)}deg`,
  };
};

export function RecapScene({ f }: { f: number }) {
  if (f < START || f > END) return null;

  const doc = prog(f, 418, 24);
  const exit = prog(f, 500, 22);
  const away = (lag: number) => {
    const p = prog(f, 500 + lag, 20);
    return { translate: `${-p * 360}px 0`, opacity: 1 - p };
  };

  return (
    <div className="absolute inset-0" style={camera(f, shots)}>
      <div className="absolute inset-0" style={{ filter: `blur(${exit * 4}px)` }}>
        {/* Meeting notes */}
        <div className="absolute left-[570px] top-[118px]" style={away(0)}>
          <div
            className="w-[780px] rounded-[30px] bg-white p-10 ring-1 ring-black/[0.06]"
            style={{
              opacity: doc,
              translate: `0 ${mix(90, 0, doc)}px`,
              scale: `${mix(0.94, 1, doc)}`,
              boxShadow: "0 2px 4px rgb(15 16 13 / 0.04), 0 40px 90px -30px rgb(15 16 13 / 0.35)",
            }}
          >
            <div className="flex items-center gap-4" style={reveal(f, 422)}>
              <CueFace size={56} round={false} />
              <div className="flex-1">
                <p className="text-[32px] font-semibold tracking-[-0.03em] text-ink">Release sync: notes</p>
                <p className="text-[17px] text-muted">Thu, Oct 29 · 24 min · Priya, Arjun, Sam</p>
              </div>
              <span className="flex items-center gap-2 rounded-full border border-line px-3.5 py-1.5 text-[15px] font-medium text-ink-soft">
                <Brand name="google-meet" size={20} /> Google Meet
              </span>
            </div>

            <div className="mt-8" style={reveal(f, 428)}>
              <Label>Summary</Label>
              <p className="mt-2 text-[21px] leading-[1.5] text-ink-soft">
                Billing v2 is ready on staging. The release is blocked by one failing webhook test and a pending Stripe key rotation.
              </p>
            </div>

            <div className="mt-7" style={reveal(f, 434)}>
              <Label>Decisions</Label>
              {["Ship billing v2 behind the billing_v2 flag, as agreed on Oct 23.", "Move the release to Monday if checks aren’t green by Friday."].map(
                (d) => (
                  <p key={d} className="mt-2.5 flex gap-3 text-[19px] leading-[1.45] text-ink">
                    <span className="mt-[11px] size-2 shrink-0 rounded-full bg-lime-ink" />
                    {d}
                  </p>
                ),
              )}
            </div>

            <div className="mt-7" style={reveal(f, 438)}>
              <Label>Action items</Label>
              <div className="mt-3 flex flex-col gap-2">
                {actions.map((a) => (
                  <div key={a.who} className="flex items-center gap-3.5 rounded-[14px] bg-paper px-4 py-3" style={reveal(f, a.at)}>
                    <Face id={a.who} size={34} />
                    <span className="flex-1 text-[18px] font-medium text-ink">{a.text}</span>
                    <span className="rounded-full bg-white px-3 py-1 text-[15px] font-medium text-muted ring-1 ring-line">{a.due}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Slack */}
        <div className="absolute left-[64px] top-[500px]" style={away(4)}>
          <div className="w-[520px] rounded-[26px] bg-white p-6 shadow-[0_30px_70px_-26px_rgb(15_16_13/0.45)] ring-1 ring-black/[0.05]" style={fly(f, 466, 520, -60)}>
            <div className="flex items-center gap-3">
              <Brand name="slack" size={30} />
              <span className="text-[18px] font-semibold text-ink">#launch-billing</span>
              <span className="ml-auto">
                <Sent f={f} at={488} />
              </span>
            </div>
            <div className="mt-4 flex gap-3.5">
              <CueFace size={46} round={false} />
              <div className="flex-1">
                <p className="flex items-center gap-2 text-[17px]">
                  <span className="font-semibold text-ink">Cue</span>
                  <AiTag size={11} />
                  <span className="text-muted">11:28 AM</span>
                </p>
                <p className="mt-1 text-[18px] leading-[1.45] text-ink-soft">
                  Notes from Release sync are up: 2 decisions, 3 action items.{" "}
                  <span className="rounded bg-[#e8f5fa] px-1 text-[#1264a3]">@Arjun</span>{" "}
                  <span className="rounded bg-[#e8f5fa] px-1 text-[#1264a3]">@Sam</span>{" "}
                  <span className="rounded bg-[#e8f5fa] px-1 text-[#1264a3]">@Priya</span> you each have one.
                </p>
                <span className="mt-3 flex items-center gap-2.5 rounded-[12px] border border-line px-3 py-2 text-[16px] font-medium text-ink-soft">
                  <FileText className="size-5 text-muted" /> Release sync: notes
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Email */}
        <div className="absolute left-[1326px] top-[214px]" style={away(8)}>
          <div className="w-[530px] rounded-[26px] bg-white p-6 shadow-[0_30px_70px_-26px_rgb(15_16_13/0.45)] ring-1 ring-black/[0.05]" style={fly(f, 472, -460, 160)}>
            <div className="flex items-center gap-3">
              <Brand name="gmail" size={30} />
              <span className="text-[18px] font-semibold text-ink">cue@yourteam.com</span>
              <span className="ml-auto">
                <Sent f={f} at={494} />
              </span>
            </div>
            <p className="mt-4 text-[16px] text-muted">To: Priya, Arjun, Sam</p>
            <p className="mt-1 text-[22px] font-semibold tracking-[-0.02em] text-ink">Release sync: notes and next steps</p>
            <p className="mt-2 text-[17px] leading-[1.5] text-muted">
              Hi all, here’s what we decided and who owns what. I’ll check in on the webhook test Friday morning.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
