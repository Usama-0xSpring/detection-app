import { useEffect, useState } from "react";

// Set VITE_API_URL at build time to point at a deployed backend later.
const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function App() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function onPick(e) {
    const f = e.target.files[0];
    if (!f) return;
    setFile(f);
    setResult(null);
    setError("");
  }

  async function onSubmit() {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_URL}/predict`, { method: "POST", body: form });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Server error (${res.status})`);
      }
      setResult(await res.json());
    } catch (err) {
      setError(err.message || "Could not reach the API");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="container">
      <h1>Objects Detection Demo</h1>
      <p className="hint">Upload an image to run the YOLOv8n model (pretrained on everyday objects; swap in a signature model later).</p>

      <div className="controls">
        <input type="file" accept="image/*" onChange={onPick} />
        <button onClick={onSubmit} disabled={!file || loading}>
          {loading ? "Detecting…" : "Detect"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      {preview && (
        <div className="image-wrap">
          <img src={preview} alt="uploaded" />
          {result?.detections.map((d, i) => {
            const [x1, y1, x2, y2] = d.box;
            return (
              <div
                key={i}
                className="box"
                style={{
                  left: `${(x1 / result.width) * 100}%`,
                  top: `${(y1 / result.height) * 100}%`,
                  width: `${((x2 - x1) / result.width) * 100}%`,
                  height: `${((y2 - y1) / result.height) * 100}%`,
                }}
              >
                <span>
                  {d.label} {(d.confidence * 100).toFixed(0)}%
                </span>
              </div>
            );
          })}
        </div>
      )}

      {result && (
        <section className="results">
          <h2>
            {result.detections.length} detection(s) · {result.inference_ms} ms
          </h2>
          <ul>
            {result.detections.map((d, i) => (
              <li key={i}>
                {d.label} — {(d.confidence * 100).toFixed(1)}% — [{d.box.join(", ")}]
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}
