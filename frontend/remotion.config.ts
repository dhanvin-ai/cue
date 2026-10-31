import path from "node:path";
import { Config } from "@remotion/cli/config";
import { enableTailwind } from "@remotion/tailwind-v4";

// Remotion renders the landing-page demo video from ./video. Assets come from ./public.
Config.setEntryPoint("video/index.ts");
Config.setVideoImageFormat("jpeg");
Config.overrideWebpackConfig((config) => {
  const withTailwind = enableTailwind(config);
  return {
    ...withTailwind,
    resolve: {
      ...withTailwind.resolve,
      alias: { ...withTailwind.resolve?.alias, "@": path.join(process.cwd(), "src") },
    },
  };
});
