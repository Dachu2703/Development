import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Clapperboard,
  Download,
  FileVideo,
  Film,
  FolderOpen,
  Gauge,
  ImagePlus,
  LayoutDashboard,
  Layers3,
  Play,
  Plus,
  RotateCcw,
  Save,
  Settings,
  Sparkles,
  Type,
  Upload,
  WandSparkles,
  X,
} from "lucide-react";
import "./styles.css";

const navItems = [
  ["Dashboard", LayoutDashboard],
  ["Video Upload", Upload],
  ["Segments", Layers3],
  ["Layout Designer", WandSparkles],
  ["Preview", Play],
  ["Rendering", Gauge],
  ["Generated Videos", FolderOpen],
  ["Templates", Clapperboard],
  ["Settings", Settings],
];

const initialElements = [
  {
    id: "video",
    label: "Video frame",
    kind: "video",
    x: 8,
    y: 10,
    w: 84,
    h: 58,
    z: 1,
  },
  {
    id: "title",
    label: "Title",
    kind: "title",
    x: 10,
    y: 73,
    w: 80,
    h: 8,
    z: 3,
  },
  {
    id: "guest",
    label: "Guest details",
    kind: "guest",
    x: 12,
    y: 53,
    w: 52,
    h: 10,
    z: 4,
  },
  { id: "logo", label: "Logo", kind: "logo", x: 76, y: 4, w: 16, h: 8, z: 5 },
];

function App() {
  const [active, setActive] = useState("Dashboard");
  const [source, setSource] = useState(null);
  const [videoDuration, setVideoDuration] = useState(null);
  const [segments, setSegments] = useState([
    { id: 1, start: 0, end: 45, maxSeconds: 180, selected: true },
  ]);
  const [elements, setElements] = useState(initialElements);
  const [selected, setSelected] = useState("video");
  const [resolution, setResolution] = useState("1080x1920");
  const [guest, setGuest] = useState({
    name: "Guest name",
    contact: "Guest contact",
  });
  const [title, setTitle] = useState("Your short video title");
  const [status, setStatus] = useState("Ready to design");
  const [renderProgress, setRenderProgress] = useState(null);
  const [renderMessage, setRenderMessage] = useState("");
  const [outputs, setOutputs] = useState([]);
  const [dragging, setDragging] = useState(null);
  const canvasRef = useRef(null);
  const sessionOutputPaths = useRef(
    new Set(JSON.parse(sessionStorage.getItem("auto-shorts-session-outputs") || "[]")),
  );

  useEffect(() => {
    fetch("/api/videos")
      .then((response) => (response.ok ? response.json() : []))
      .then((videos) =>
        setOutputs(
          videos.filter((video) => sessionOutputPaths.current.has(video.path)),
        ),
      )
      .catch(() => setOutputs([]));
  }, []);

  const selectedElement =
    elements.find((element) => element.id === selected) || elements[0];
  const selectedCount = segments.filter((segment) => segment.selected).length;
  const selectedLabel = selectedElement?.label || "Element";

  const updateElement = (key, value) => {
    setElements((items) =>
      items.map((item) =>
        item.id === selected ? { ...item, [key]: Number(value) } : item,
      ),
    );
  };

  const addSegment = () => {
    const last = segments.at(-1);
    const start = last ? last.end + 5 : 0;
    setSegments((items) => [
      ...items,
      {
        id: Date.now(),
        start,
        end: start + 45,
        maxSeconds: 180,
        selected: true,
      },
    ]);
  };

  const updateSegment = (id, key, value) => {
    setSegments((items) =>
      items.map((item) => {
        if (item.id !== id) return item;
        const number = Math.max(0, Number(value) || 0);
        if (key === "maxSeconds") {
          return {
            ...item,
            maxSeconds: Math.max(1, Math.min(180, number)),
          };
        }
        if (key === "end")
          return { ...item, end: number };
        if (key === "start")
          return { ...item, start: number };
        return { ...item, [key]: number };
      }),
    );
  };

  const normalizeEnd = (id) => {
    setSegments((items) =>
      items.map((item) =>
        item.id === id
          ? { ...item, end: Math.max(item.start + 1, item.end) }
          : item,
      ),
    );
  };

  const segmentErrors = segments.map((segment, index) => {
    const previous = segments[index - 1];
    if (segment.end <= segment.start) return "End must be greater than Start.";
    if (previous && segment.start <= previous.end)
      return `Start must be greater than Segment ${String(index).padStart(2, "0")} End.`;
    if (videoDuration !== null && segment.end > videoDuration)
      return `End cannot exceed the video duration (${videoDuration.toFixed(1)} seconds).`;
    return "";
  });
  const hasSegmentErrors = segmentErrors.some(Boolean);

  const handleSourceChange = (file) => {
    setSource(file);
    setVideoDuration(null);
    if (!file) return;
    const video = document.createElement("video");
    video.preload = "metadata";
    video.onloadedmetadata = () => {
      setVideoDuration(Number.isFinite(video.duration) ? video.duration : null);
      URL.revokeObjectURL(video.src);
    };
    video.src = URL.createObjectURL(file);
  };

  const moveElement = (event) => {
    if (!dragging || !canvasRef.current) return;
    const bounds = canvasRef.current.getBoundingClientRect();
    const x = Math.max(
      0,
      Math.min(
        100 - dragging.w,
        ((event.clientX - bounds.left) / bounds.width) * 100,
      ),
    );
    const y = Math.max(
      0,
      Math.min(
        100 - dragging.h,
        ((event.clientY - bounds.top) / bounds.height) * 100,
      ),
    );
    setElements((items) =>
      items.map((item) => (item.id === dragging.id ? { ...item, x, y } : item)),
    );
  };

  const previewStyle = useMemo(() => {
    const [width, height] = resolution.split("x").map(Number);
    return { aspectRatio: `${width} / ${height}` };
  }, [resolution]);

  const renderProject = async () => {
    setRenderProgress(0);
    setRenderMessage("Uploading source video...");
    setStatus("Rendering selected segments...");
    try {
      if (!source) throw new Error("Choose a source video first");
      if (hasSegmentErrors) throw new Error("Fix the segment validation errors first");
      const upload = new FormData();
      upload.append("file", source);
      const uploadResponse = await fetch("/api/upload", {
        method: "POST",
        body: upload,
      });
      if (!uploadResponse.ok) throw new Error("Upload failed");
      const uploaded = await uploadResponse.json();
      const payload = {
        source: uploaded.source,
        resolution,
        title,
        guest,
        segments: segments
          .filter((item) => item.selected)
          .map(({ id, maxSeconds, ...item }) => ({
            ...item,
            max_seconds: maxSeconds,
          })),
        elements,
      };
      const response = await fetch("/api/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error("API unavailable");
      const result = await response.json();
      setStatus(`Render queued: ${result.job_id}`);
      setRenderProgress(result.progress ?? 0);
      setRenderMessage(result.message || "Waiting to start");
      let job = result;
      while (job.status === "queued" || job.status === "running") {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const jobResponse = await fetch(`/api/render/${result.job_id}`);
        if (!jobResponse.ok) throw new Error("Render status unavailable");
        job = await jobResponse.json();
        setRenderProgress(job.progress ?? 0);
        setRenderMessage(job.message || "Rendering...");
      }
      if (job.status !== "completed")
        throw new Error(job.detail || "Render failed");
      const videosResponse = await fetch("/api/videos");
      if (!videosResponse.ok) throw new Error("Generated videos unavailable");
      const videos = await videosResponse.json();
      const currentSessionVideos = videos.filter((video) => {
        if (sessionOutputPaths.current.has(video.path)) return true;
        sessionOutputPaths.current.add(video.path);
        return true;
      });
      sessionStorage.setItem(
        "auto-shorts-session-outputs",
        JSON.stringify([...sessionOutputPaths.current]),
      );
      setOutputs(currentSessionVideos);
      setRenderProgress(100);
      setRenderMessage("Render complete");
      setStatus("Render complete");
    } catch (error) {
      setRenderProgress(null);
      setRenderMessage("");
      setStatus(error instanceof Error ? error.message : "Render failed");
    }
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Film size={18} />
          </div>
          <span>auto-shorts</span>
          <small>STUDIO</small>
        </div>
        <div className="workspace-label">WORKSPACE</div>
        <nav>
          {navItems.map(([label, Icon]) => (
            <button
              className={active === label ? "nav-item active" : "nav-item"}
              onClick={() => setActive(label)}
              key={label}
            >
              <Icon size={17} />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="status-dot" /> <span>Local workspace</span>
          <Settings size={15} />
        </div>
      </aside>
      <main className="main-area">
        <header className="topbar">
          <div>
            <div className="eyebrow">PROJECT / EPISODE 01</div>
            <h1>{active}</h1>
          </div>
          <div className="top-actions">
            <span className="save-state">
              <span className="status-dot" /> {status}
            </span>
            <button
              className="icon-button"
              title="Reset layout"
              onClick={() => setElements(initialElements)}
            >
              <RotateCcw size={17} />
            </button>
            <button
              className="button secondary"
              onClick={() => setStatus("Project saved locally")}
            >
              <Save size={16} /> Save project
            </button>
            <button className="avatar">NS</button>
          </div>
        </header>
        <div className="content-grid">
          <section className="primary-column">
            <div className="hero-row">
              <div>
                <h2>Build your next short</h2>
                <p className="muted">
                  Compose, preview, and render platform-ready clips from one
                  workspace.
                </p>
              </div>
              <div className="resolution-control">
                <span>OUTPUT</span>
                <select
                  value={resolution}
                  onChange={(event) => setResolution(event.target.value)}
                >
                  <option>1080x1920</option>
                  <option>1920x1080</option>
                  <option>1080x1080</option>
                  <option>720x1280</option>
                </select>
              </div>
            </div>
            <div className="panel upload-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">01 / SOURCE</span>
                  <h3>Long video input</h3>
                </div>
                <FileVideo size={20} />
              </div>
              <label className="drop-zone">
                <Upload size={22} />
                <strong>
                  {source ? source.name : "Drop a video here or browse"}
                </strong>
                <span>MP4, MOV, MKV up to 4 GB</span>
                <input
                  type="file"
                  accept="video/*"
                  onChange={(event) =>
                    handleSourceChange(event.target.files?.[0] || null)
                  }
                />
              </label>
              {videoDuration !== null && (
                <p className="muted video-duration">
                  Video duration: {videoDuration.toFixed(1)} seconds
                </p>
              )}
            </div>
            <div className="panel">
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">02 / SEGMENTS</span>
                  <h3>Choose your moments</h3>
                  <p className="muted segment-help">
                    Start and End define the analysis range. Max seconds limits the
                    final Short. Example: 5-300 seconds with Max seconds 60.
                  </p>
                </div>
                <button className="button small secondary" onClick={addSegment}>
                  <Plus size={15} /> Add segment
                </button>
              </div>
              <div className="timeline">
                <div className="timeline-track">
                  <div className="timeline-wave" />
                  {segments.map((segment) => (
                    <div
                      key={segment.id}
                      className={
                        segment.selected ? "segment selected" : "segment"
                      }
                      style={{
                        left: `${Math.min(segment.start / 3, 94)}%`,
                        width: `${Math.max(5, Math.min((segment.end - segment.start) / 3, 94))}%`,
                      }}
                      onClick={() =>
                        setSegments((items) =>
                          items.map((item) =>
                            item.id === segment.id
                              ? { ...item, selected: !item.selected }
                              : item,
                          ),
                        )
                      }
                    >
                      <span>{segment.end - segment.start}s</span>
                    </div>
                  ))}
                </div>
                <div className="time-axis">
                  <span>00:00</span>
                  <span>01:00</span>
                  <span>02:00</span>
                  <span>03:00</span>
                  <span>04:00</span>
                </div>
              </div>
              <div className="segment-list">
                {segments.map((segment, index) => (
                  <div className="segment-row" key={segment.id}>
                    <input
                      type="checkbox"
                      checked={segment.selected}
                      onChange={() =>
                        setSegments((items) =>
                          items.map((item) =>
                            item.id === segment.id
                              ? { ...item, selected: !item.selected }
                              : item,
                          ),
                        )
                      }
                    />
                    <b>Segment {String(index + 1).padStart(2, "0")}</b>
                    <label>
                      Start{" "}
                      <input
                        type="number"
                        value={segment.start}
                        onChange={(event) =>
                          updateSegment(segment.id, "start", event.target.value)
                        }
                      />
                    </label>
                    <label>
                      End{" "}
                      <input
                        type="number"
                        min={segment.start + 1}
                        max={videoDuration ?? undefined}
                        value={segment.end}
                        onChange={(event) =>
                          updateSegment(segment.id, "end", event.target.value)
                        }
                        onBlur={() => normalizeEnd(segment.id)}
                      />
                    </label>
                    {segmentErrors[index] && (
                      <span className="field-error">{segmentErrors[index]}</span>
                    )}
                    <label>
                      Max seconds{" "}
                      <input
                        type="number"
                        min="1"
                        max="180"
                        value={segment.maxSeconds}
                        onChange={(event) =>
                          updateSegment(
                            segment.id,
                            "maxSeconds",
                            event.target.value,
                          )
                        }
                      />
                    </label>
                    <button
                      className="icon-button"
                      onClick={() =>
                        setSegments((items) =>
                          items.filter((item) => item.id !== segment.id),
                        )
                      }
                    >
                      <X size={15} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <div className="panel designer-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">03 / LAYOUT DESIGNER</span>
                  <h3>Arrange every layer</h3>
                </div>
                <span className="chip">
                  <Sparkles size={13} /> Drag to position
                </span>
              </div>
              <div className="designer-grid">
                <div className="canvas-wrap">
                  <div
                    ref={canvasRef}
                    className="canvas"
                    style={previewStyle}
                    onPointerMove={moveElement}
                    onPointerUp={() => setDragging(null)}
                  >
                    {elements
                      .sort((a, b) => a.z - b.z)
                      .map((element) => (
                        <div
                          key={element.id}
                          className={`canvas-element ${element.kind} ${selected === element.id ? "selected" : ""}`}
                          style={{
                            left: `${element.x}%`,
                            top: `${element.y}%`,
                            width: `${element.w}%`,
                            height: `${element.h}%`,
                            zIndex: element.z,
                          }}
                          onPointerDown={(event) => {
                            event.stopPropagation();
                            setSelected(element.id);
                            setDragging(element);
                          }}
                        >
                          <span>
                            {element.kind === "video"
                              ? "VIDEO"
                              : element.kind === "logo"
                                ? "LOGO"
                                : element.kind === "title"
                                  ? title
                                  : `${guest.name} · ${guest.contact}`}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
                <div className="inspector">
                  <div className="inspector-title">
                    <Layers3 size={16} /> {selectedLabel}
                  </div>
                  <label>
                    X position
                    <input
                      type="range"
                      min="0"
                      max="90"
                      value={selectedElement.x}
                      onChange={(event) =>
                        updateElement("x", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    Y position
                    <input
                      type="range"
                      min="0"
                      max="90"
                      value={selectedElement.y}
                      onChange={(event) =>
                        updateElement("y", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    Width
                    <input
                      type="range"
                      min="5"
                      max="100"
                      value={selectedElement.w}
                      onChange={(event) =>
                        updateElement("w", event.target.value)
                      }
                    />
                  </label>
                  <label>
                    Height
                    <input
                      type="range"
                      min="4"
                      max="100"
                      value={selectedElement.h}
                      onChange={(event) =>
                        updateElement("h", event.target.value)
                      }
                    />
                  </label>
                  {selected === "title" && (
                    <label>
                      Title text
                      <input
                        value={title}
                        onChange={(event) => setTitle(event.target.value)}
                      />
                    </label>
                  )}
                  {selected === "guest" && (
                    <>
                      <label>
                        Guest name
                        <input
                          value={guest.name}
                          onChange={(event) =>
                            setGuest({ ...guest, name: event.target.value })
                          }
                        />
                      </label>
                      <label>
                        Guest contact
                        <input
                          value={guest.contact}
                          onChange={(event) =>
                            setGuest({ ...guest, contact: event.target.value })
                          }
                        />
                      </label>
                    </>
                  )}
                </div>
              </div>
            </div>
            <div className="panel preview-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">04 / PREVIEW</span>
                  <h3>Final composition</h3>
                </div>
                <button className="button secondary">
                  <Play size={15} /> Preview
                </button>
              </div>
              <div className="preview-stage">
                <div className="phone-preview" style={previewStyle}>
                  {elements
                    .sort((a, b) => a.z - b.z)
                    .map((element) => (
                      <div
                        key={`preview-${element.id}`}
                        className={`canvas-element ${element.kind}`}
                        style={{
                          left: `${element.x}%`,
                          top: `${element.y}%`,
                          width: `${element.w}%`,
                          height: `${element.h}%`,
                          zIndex: element.z,
                        }}
                      >
                        <span>
                          {element.kind === "title"
                            ? title
                            : element.kind === "guest"
                              ? `${guest.name}\n${guest.contact}`
                              : element.kind.toUpperCase()}
                        </span>
                      </div>
                    ))}
                </div>
              </div>
            </div>
          </section>
          <aside className="right-column">
            <div className="summary-card">
              <div className="summary-icon">
                <Gauge size={18} />
              </div>
              <span className="section-kicker">RENDER QUEUE</span>
              <strong>{selectedCount} selected segments</strong>
              <p>{resolution} · MP4 · H.264 + AAC</p>
              {renderProgress !== null && (
                <div className="render-progress" aria-live="polite">
                  <div className="render-progress-label">
                    <span>{renderMessage}</span>
                    <b>{renderProgress}%</b>
                  </div>
                  <div
                    className="render-progress-track"
                    role="progressbar"
                    aria-valuenow={renderProgress}
                    aria-valuemin="0"
                    aria-valuemax="100"
                  >
                    <div
                      className="render-progress-bar"
                      style={{ width: `${renderProgress}%` }}
                    />
                  </div>
                </div>
              )}
              <button
                className="button primary full"
                onClick={renderProject}
                disabled={!source || videoDuration === null || hasSegmentErrors}
              >
                <Clapperboard size={16} /> Render selected clips
              </button>
            </div>
            <div className="side-panel">
              <div className="panel-heading">
                <h3>Branding</h3>
                <ImagePlus size={17} />
              </div>
              <label>
                Logo position
                <select defaultValue="Top right">
                  <option>Top right</option>
                  <option>Top left</option>
                  <option>Bottom right</option>
                  <option>Bottom left</option>
                </select>
              </label>
              <label>
                Watermark
                <input placeholder="Your channel name" />
              </label>
              <label>
                Accent color
                <input type="color" defaultValue="#ef8354" />
              </label>
            </div>
            <div className="side-panel">
              <div className="panel-heading">
                <h3>Generated videos</h3>
                <FolderOpen size={17} />
              </div>
              {outputs.length === 0 ? (
                <p className="muted">
                  Rendered clips will appear here with download links.
                </p>
              ) : (
                outputs.map((output, index) => (
                  <a
                    className="output-row"
                    href={output.url}
                    target="_blank"
                    rel="noreferrer"
                    download={output.name || `clip_${index + 1}.mp4`}
                    key={output.path || index}
                    title="Open or download video"
                  >
                    <FileVideo size={16} />
                    <span>{output.name || `clip_${index + 1}.mp4`}</span>
                    <Download size={15} />
                  </a>
                ))
              )}
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
}

export default App;

createRoot(document.getElementById("root")).render(<App />);
