import React from "react";
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export type MotionTemplate =
  | "M_TITLE"
  | "M_COMPARE"
  | "M_LIST"
  | "M_TIMELINE"
  | "M_NUMBER"
  | "M_RANKING"
  | "M_PROCESS"
  | "M_GALLERY";

export type MotionShotProps = {
  duration: number;
  title: string;
  items: string[];
  images: string[];
  numbers: string[];
  highlight_index: number;
  aspect_ratio: "9:16" | "1:1" | "16:9";
};

const palette = {
  ink: "#18332d",
  paper: "#f8f6ed",
  green: "#9fbd73",
  amber: "#d8ad62",
  blue: "#79a9be",
  coral: "#cf8065",
  rose: "#ae7e9d",
};

const stageStyle = (ratio: MotionShotProps["aspect_ratio"]): React.CSSProperties => ({
  background: palette.paper,
  color: palette.ink,
  overflow: "hidden",
  fontFamily: "Microsoft YaHei, Segoe UI, sans-serif",
  padding: ratio === "9:16" ? "9% 8%" : ratio === "1:1" ? "7%" : "5% 7%",
});

const titleSize = (ratio: MotionShotProps["aspect_ratio"]) =>
  ratio === "9:16" ? 76 : ratio === "1:1" ? 68 : 72;

function Reveal({
  children,
  delay = 0,
  y = 28,
}: {
  children: React.ReactNode;
  delay?: number;
  y?: number;
}) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const progress = spring({
    frame: frame - delay,
    fps,
    config: { damping: 18, stiffness: 120 },
  });
  return (
    <div
      style={{
        opacity: progress,
        transform: `translateY(${interpolate(progress, [0, 1], [y, 0])}px)`,
      }}
    >
      {children}
    </div>
  );
}

function Header({ title, accent }: { title: string; accent: string }) {
  return (
    <div style={{ marginBottom: "5%" }}>
      <div
        style={{
          width: 92,
          height: 8,
          background: accent,
          marginBottom: 20,
          borderRadius: 4,
        }}
      />
      <div style={{ fontSize: 28, letterSpacing: 2, opacity: 0.68 }}>
        SCENEFLOW / VISUAL DIRECTOR
      </div>
      <h1 style={{ fontSize: 62, lineHeight: 1.18, margin: "18px 0 0" }}>{title}</h1>
    </div>
  );
}

function M_TITLE(props: MotionShotProps) {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const scale = interpolate(
    frame,
    [0, Math.max(1, durationInFrames - 1)],
    [1, 1.035],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return (
    <AbsoluteFill style={{ ...stageStyle(props.aspect_ratio), justifyContent: "center" }}>
      <div style={{ transform: `scale(${scale})`, transformOrigin: "left center" }}>
        <Reveal>
          <h1 style={{ fontSize: titleSize(props.aspect_ratio), lineHeight: 1.12, margin: 0 }}>
            {props.title}
          </h1>
        </Reveal>
        <Reveal delay={8}>
          <div
            style={{
              width: "42%",
              height: 12,
              marginTop: 34,
              borderRadius: 6,
              background: palette.green,
            }}
          />
        </Reveal>
      </div>
    </AbsoluteFill>
  );
}

function M_COMPARE(props: MotionShotProps) {
  const items = [...props.items, "A", "B"].slice(0, 2);
  return (
    <AbsoluteFill style={stageStyle(props.aspect_ratio)}>
      <Header title={props.title} accent={palette.blue} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4%" }}>
        {items.map((item, index) => (
          <Reveal key={item} delay={index * 10}>
            <div
              style={{
                minHeight: 260,
                padding: "9%",
                borderRadius: 18,
                background: index === props.highlight_index ? "#dce9ef" : "#efe9d9",
                border: `4px solid ${index === props.highlight_index ? palette.blue : palette.amber}`,
              }}
            >
              <div style={{ opacity: 0.55, fontSize: 28 }}>0{index + 1}</div>
              <div style={{ marginTop: 32, fontSize: 48, lineHeight: 1.3 }}>{item}</div>
            </div>
          </Reveal>
        ))}
      </div>
    </AbsoluteFill>
  );
}

function M_LIST(props: MotionShotProps) {
  const items = (props.items.length ? props.items : props.numbers).slice(0, 5);
  return (
    <AbsoluteFill style={stageStyle(props.aspect_ratio)}>
      <Header title={props.title} accent={palette.green} />
      <div style={{ display: "grid", gap: 18 }}>
        {items.map((item, index) => (
          <Reveal key={`${item}-${index}`} delay={index * 7}>
            <div style={{ display: "flex", alignItems: "flex-start", gap: 22, fontSize: 44 }}>
              <span style={{ color: palette.green, fontWeight: 700 }}>{index + 1}</span>
              <span>{item}</span>
            </div>
          </Reveal>
        ))}
      </div>
    </AbsoluteFill>
  );
}

function M_TIMELINE(props: MotionShotProps) {
  const items = props.items.slice(0, 4);
  return (
    <AbsoluteFill style={stageStyle(props.aspect_ratio)}>
      <Header title={props.title} accent={palette.amber} />
      <div style={{ position: "relative", marginTop: "5%" }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 28, height: 6, background: "#d7ceb8" }} />
        <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.max(items.length, 1)}, 1fr)` }}>
          {items.map((item, index) => (
            <Reveal key={`${item}-${index}`} delay={index * 8}>
              <div style={{ paddingRight: 12 }}>
                <div style={{ width: 58, height: 58, borderRadius: "50%", background: palette.amber }} />
                <div style={{ marginTop: 26, fontSize: 38 }}>{item}</div>
              </div>
            </Reveal>
          ))}
        </div>
      </div>
    </AbsoluteFill>
  );
}

function M_NUMBER(props: MotionShotProps) {
  const value = props.numbers[0] || props.items[0] || props.title;
  const frame = useCurrentFrame();
  const pulse = 1 + Math.sin(frame / 7) * 0.015;
  return (
    <AbsoluteFill
      style={{
        ...stageStyle(props.aspect_ratio),
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
      }}
    >
      <Reveal>
        <div style={{ fontSize: 34, opacity: 0.68 }}>{props.title}</div>
        <div
          style={{
            marginTop: 22,
            fontSize: props.aspect_ratio === "9:16" ? 150 : 128,
            fontWeight: 800,
            color: palette.coral,
            transform: `scale(${pulse})`,
          }}
        >
          {value}
        </div>
      </Reveal>
    </AbsoluteFill>
  );
}

function M_RANKING(props: MotionShotProps) {
  const rows = props.items.length ? props.items : props.numbers;
  return (
    <AbsoluteFill style={stageStyle(props.aspect_ratio)}>
      <Header title={props.title} accent={palette.coral} />
      <div style={{ display: "grid", gap: 14 }}>
        {rows.slice(0, 5).map((item, index) => (
          <Reveal key={`${item}-${index}`} delay={index * 6}>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "72px 1fr auto",
                alignItems: "center",
                gap: 18,
                padding: "18px 24px",
                background: index === props.highlight_index ? "#f1d8cf" : "#eee9da",
                borderRadius: 12,
              }}
            >
              <strong style={{ color: palette.coral, fontSize: 42 }}>{index + 1}</strong>
              <span style={{ fontSize: 40 }}>{item}</span>
              <span style={{ fontSize: 34, opacity: 0.48 }}>{props.numbers[index] || ""}</span>
            </div>
          </Reveal>
        ))}
      </div>
    </AbsoluteFill>
  );
}

function M_PROCESS(props: MotionShotProps) {
  const items = [...props.items];
  if (items.length < 3 && props.numbers.length) items.push(...props.numbers);
  const stages = items.slice(0, 3);
  return (
    <AbsoluteFill style={stageStyle(props.aspect_ratio)}>
      <Header title={props.title} accent={palette.blue} />
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        {stages.map((item, index) => (
          <React.Fragment key={`${item}-${index}`}>
            <Reveal delay={index * 9}>
              <div
                style={{
                  width: props.aspect_ratio === "9:16" ? 230 : 300,
                  minHeight: 170,
                  display: "grid",
                  placeItems: "center",
                  padding: 20,
                  borderRadius: 16,
                  background: "#dfeaf0",
                  fontSize: 38,
                  textAlign: "center",
                }}
              >
                {item}
              </div>
            </Reveal>
            {index < stages.length - 1 ? (
              <Reveal delay={index * 9 + 4}>
                <div style={{ color: palette.blue, fontSize: 64 }}>→</div>
              </Reveal>
            ) : null}
          </React.Fragment>
        ))}
      </div>
    </AbsoluteFill>
  );
}

function M_GALLERY(props: MotionShotProps) {
  const items = props.items.length ? props.items : props.images;
  return (
    <AbsoluteFill style={stageStyle(props.aspect_ratio)}>
      <Header title={props.title} accent={palette.rose} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: props.aspect_ratio === "9:16" ? "1fr" : "repeat(3, 1fr)",
          gap: 18,
        }}
      >
        {items.slice(0, 6).map((item, index) => (
          <Reveal key={`${item}-${index}`} delay={index * 5}>
            <div
              style={{
                minHeight: 150,
                display: "grid",
                placeItems: "center",
                padding: 18,
                borderRadius: 14,
                background: index % 3 === 0 ? "#ece1ed" : index % 3 === 1 ? "#e4ece0" : "#f0e7d4",
                fontSize: 34,
                textAlign: "center",
              }}
            >
              {item}
            </div>
          </Reveal>
        ))}
      </div>
    </AbsoluteFill>
  );
}

export const MOTION_COMPONENTS: Record<MotionTemplate, React.FC<MotionShotProps>> = {
  M_TITLE,
  M_COMPARE,
  M_LIST,
  M_TIMELINE,
  M_NUMBER,
  M_RANKING,
  M_PROCESS,
  M_GALLERY,
};

export const MotionShot: React.FC<
  MotionShotProps & { template: MotionTemplate }
> = ({ template, ...props }) => {
  const Component = MOTION_COMPONENTS[template] || M_TITLE;
  return <Component {...props} />;
};
