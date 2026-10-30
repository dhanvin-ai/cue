import { loadFont } from "@remotion/google-fonts/Geist";
import { loadFont as loadMono } from "@remotion/google-fonts/GeistMono";
import { Composition } from "remotion";
import { CueMeetingDemo } from "./cue-meeting-demo";
import { DURATION, FPS, HEIGHT, WIDTH } from "./lib";
import "./video.css";

const sans = loadFont("normal", { weights: ["400", "500", "600", "700"], subsets: ["latin"] });
const mono = loadMono("normal", { weights: ["500"], subsets: ["latin"] });

export function RemotionRoot() {
  return (
    <Composition
      id="CueMeetingDemo"
      component={CueMeetingDemo}
      durationInFrames={DURATION}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      defaultProps={{ sans: sans.fontFamily, mono: mono.fontFamily }}
    />
  );
}
