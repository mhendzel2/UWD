import React, { useState } from "react";

type Props = {
  apiBase: string;
  sessionId: string;
  onSessionCreated: (id: string, date: string) => void;
  onUploaded: (msg: string) => void;
};

const sources = ["OI_DIFF", "BOT_EOD", "HOT_CHAINS", "DARKPOOL_EOD", "STOCK_SCREENER"];

const UploadDataset: React.FC<Props> = ({ apiBase, sessionId, onSessionCreated, onUploaded }) => {
  const [source, setSource] = useState<string>(sources[0]);
  const [file, setFile] = useState<File | null>(null);

  const extractDate = (filename: string): string | null => {
    const match = filename.match(/(\d{4}-\d{2}-\d{2})/);
    return match ? match[1] : null;
  };

  const ensureSession = async (dateStr: string): Promise<string | null> => {
    const form = new FormData();
    form.append("session_date", dateStr);
    form.append("strategy_mode", "INDEX_EOD");
    try {
      const res = await fetch(`${apiBase}/sessions/ensure`, { method: "POST", body: form });
      if (res.ok) {
        const data = await res.json();
        onSessionCreated(data.session_id, data.date);
        return data.session_id;
      }
    } catch (e) {
      console.error(e);
    }
    return null;
  };

  const submit = async () => {
    if (!file) {
      alert("Pick a CSV file");
      return;
    }

    let currentSessionId = sessionId;

    if (!currentSessionId) {
      const dateStr = extractDate(file.name);
      if (dateStr) {
        const newId = await ensureSession(dateStr);
        if (newId) {
          currentSessionId = newId;
        } else {
          alert("Failed to create session from filename date");
          return;
        }
      } else {
        alert("No session active and could not extract date from filename");
        return;
      }
    }

    const form = new FormData();
    form.append("session_id", currentSessionId);
    form.append("file", file);
    const res = await fetch(`${apiBase}/import/${source}`, { method: "POST", body: form });
    if (res.ok) {
      const data = await res.json();
      onUploaded(`Imported ${file.name} (${data.rows} rows)`);
    } else {
      onUploaded("Import failed");
    }
  };

  return (
    <section style={{ border: "1px solid #ccc", padding: 12 }}>
      <h3>Upload Dataset</h3>
      <label>
        Source
        <select value={source} onChange={(e) => setSource(e.target.value)}>
          {sources.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>
      <input type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] || null)} />
      <button onClick={submit}>Upload</button>
    </section>
  );
};

export default UploadDataset;
