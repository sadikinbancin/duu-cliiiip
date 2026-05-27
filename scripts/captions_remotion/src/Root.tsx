import React from "react";
import {
  Composition,
  Series,
  staticFile,
} from "remotion";
import { CaptionsComposition } from "./CaptionsComposition";

// Default style configs
export const STYLES = {
  default: {
    clean: {
      fontFamily: "Arial, sans-serif",
      fontSize: 52,
      color: "#FFFFFF",
      outlineColor: "#000000",
      outlineWidth: 3.5,
      shadowColor: "rgba(0,0,0,0.5)",
      shadowBlur: 1.5,
      alignment: "center" as const,
      position: "bottom" as const,
      marginV: 500,
      marginL: 135,
      marginR: 135,
    },
    bold: {
      fontFamily: "Arial Black, Arial, sans-serif",
      fontSize: 60,
      color: "#FFFFFF",
      activeColor: "#FFD700",
      outlineColor: "#000000",
      outlineWidth: 4,
      alignment: "center" as const,
      position: "bottom" as const,
      marginV: 480,
      marginL: 100,
      marginR: 100,
      uppercase: true,
    },
    bounce: {
      fontFamily: "Impact, sans-serif",
      fontSize: 72,
      color: "#FFFFFF",
      outlineColor: "#000000",
      outlineWidth: 5,
      alignment: "center" as const,
      position: "bottom" as const,
      marginV: 450,
      marginL: 80,
      marginR: 80,
    },
  },
};

// Default style
export const DEFAULT_STYLE = STYLES.default;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="CaptionsComp"
        component={CaptionsComposition}
        durationInFrames={900}
        fps={30}
        width={1080}
        height={1920}
      />
    </>
  );
};
